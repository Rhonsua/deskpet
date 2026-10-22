"""Metadata-only discovery and isolated lazy execution in temporary packages."""
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pet_mods import ModContext, ModManager, ModManifest
from pet_mods.loader import discover


ENTRY = '''from .helper import VALUE
from pet_mods.api import ModContext
class Example:
    def __init__(self, context):
        assert isinstance(context, ModContext)
        self.context = context
    def start(self):
        (self.context.data_dir / "started.txt").write_text(VALUE)
    def tick(self, now):
        pass
    def stop(self):
        pass
    def create_widget(self, parent=None):
        return (VALUE, parent)
factory = Example
'''


class ModLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'packages'
        self.root.mkdir()
        self.manager = ModManager(Path(self.temp.name) / 'data', lambda text: True,
                                  lambda: datetime(2026, 10, 21, 12))
        self.addCleanup(self.manager.shutdown)

    def package(self, folder='example', mod_id='example', **changes):
        directory = self.root / folder
        directory.mkdir()
        meta = dict(id=mod_id, name='测试包', version='1.0.0', description='test', api_version=1)
        meta.update(changes)
        (directory / 'mod.json').write_text(json.dumps(meta), encoding='utf-8')
        (directory / 'entry.py').write_text(ENTRY, encoding='utf-8')
        (directory / 'helper.py').write_text('VALUE = "relative"', encoding='utf-8')
        return directory

    def namespaces(self):
        return {key for key in sys.modules if key.startswith('_desktop_pet_package_')}

    def test_discovery_is_metadata_only_and_relative_imports_are_lazy(self):
        directory = self.package()
        marker = Path(self.temp.name) / 'executed'
        with (directory / 'entry.py').open('a', encoding='utf-8') as output:
            output.write('\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("yes")\n')
        (directory / '__init__.py').write_text('raise RuntimeError("must not run")', encoding='utf-8')
        before_modules = self.namespaces()
        before_path = list(sys.path)
        found, warnings = discover(self.root)
        self.assertFalse(warnings)
        self.assertEqual(len(found), 1)
        self.assertFalse(marker.exists())
        self.assertEqual(self.namespaces(), before_modules)
        manifest, factory = found[0]
        self.manager.register(manifest, factory)
        self.assertFalse(marker.exists())
        self.assertTrue(self.manager.set_enabled(manifest.id, True))
        self.assertTrue(marker.exists())
        self.assertEqual(self.manager.create_widget(manifest.id, 'parent'), ('relative', 'parent'))
        self.assertEqual((self.manager.data_dir / manifest.id / 'started.txt').read_text(), 'relative')
        self.assertTrue(self.namespaces() - before_modules)
        self.assertTrue(self.manager.set_enabled(manifest.id, False))
        self.assertEqual(self.namespaces(), before_modules)
        self.assertTrue(self.manager.set_enabled(manifest.id, True))
        self.assertEqual(sys.path, before_path)

    def test_duplicate_and_reserved_ids_are_rejected(self):
        self.package('one', 'same')
        self.package('two', 'same')
        self.package('reserved', 'builtin-goals')
        found, warnings = discover(self.root)
        self.assertEqual(found, [])
        self.assertEqual(len(warnings), 2)

    def test_registered_host_id_cannot_be_overridden(self):
        self.package()
        found, warnings = discover(self.root)
        manifest, factory = found[0]
        self.manager.register(ModManifest('example', 'host', '1.0'), factory)
        with self.assertRaises(ValueError):
            self.manager.register(manifest, factory)
        self.assertFalse(self.manager.is_enabled('example'))

    def test_invalid_metadata_and_entry_paths(self):
        bad = [dict(id='../outside'), dict(api_version=True), dict(api_version=2),
               dict(name=3), dict(name=' '), dict(version='bad'), dict(description=[]),
               dict(entry='../other.py')]
        for index, changes in enumerate(bad):
            self.package(str(index), 'example' + str(index), **changes)
        directory = self.package('missing', 'missing')
        (directory / 'entry.py').unlink()
        malformed = self.package('malformed', 'malformed')
        (malformed / 'mod.json').write_text('{"id":"a","id":"b"}', encoding='utf-8')
        found, warnings = discover(self.root)
        self.assertEqual(found, [])
        self.assertEqual(len(warnings), len(bad) + 2)

    def test_missing_root_empty_folder_and_nonpackages_are_ignored(self):
        self.assertEqual(discover(self.root / 'absent'), ([], []))
        (self.root / 'empty').mkdir()
        (self.root / 'readme.txt').write_text('not a package')
        self.assertEqual(discover(self.root), ([], []))

    def test_file_and_package_budgets_are_checked(self):
        self.package()
        with patch('pet_mods.loader._MAX_FILE_BYTES', 10):
            self.assertTrue(discover(self.root)[1])
        with patch('pet_mods.loader._MAX_PACKAGE_BYTES', 10):
            self.assertTrue(discover(self.root)[1])
        with patch('pet_mods.loader._MAX_ENTRIES', 1):
            self.assertTrue(discover(self.root)[1])

    def test_outside_link_is_rejected_without_opening(self):
        self.package()
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            if path.name == 'helper.py':
                return Path(self.temp.name) / 'outside.py'
            return original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve):
            found, warnings = discover(self.root)
        self.assertEqual(found, [])
        self.assertTrue(warnings)

    def test_changes_after_discovery_are_rechecked_before_execution(self):
        directory = self.package()
        manifest, factory = discover(self.root)[0][0]
        (directory / 'mod.json').write_text('{}')
        self.manager.register(manifest, factory)
        before = self.namespaces()
        self.assertFalse(self.manager.set_enabled(manifest.id, True))
        self.assertEqual(self.namespaces(), before)
        self.assertTrue(self.manager.error(manifest.id))

    def test_failed_import_and_lifecycle_do_not_unload_another_package(self):
        self.package('healthy', 'healthy')
        bad = self.package('broken', 'broken')
        (bad / 'entry.py').write_text('from .helper import VALUE\nraise SystemExit("no")')
        found, warnings = discover(self.root)
        for manifest, factory in found:
            self.manager.register(manifest, factory)
        self.assertTrue(self.manager.set_enabled('healthy', True))
        before = self.namespaces()
        self.assertFalse(self.manager.set_enabled('broken', True))
        self.assertEqual(self.namespaces(), before)
        self.assertEqual(self.manager.create_widget('healthy'), ('relative', None))
        self.manager.tick()
        self.assertTrue(self.manager.is_enabled('healthy'))

    def test_bad_factory_contract_is_disabled(self):
        directory = self.package()
        (directory / 'entry.py').write_text('factory = lambda context: object()')
        manifest, factory = discover(self.root)[0][0]
        self.manager.register(manifest, factory)
        before = self.namespaces()
        self.assertFalse(self.manager.set_enabled(manifest.id, True))
        self.assertEqual(self.namespaces(), before)


if __name__ == '__main__':
    unittest.main()
