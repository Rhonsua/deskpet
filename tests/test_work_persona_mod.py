"""Regression tests for project edits and real API-1 package loading."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from extensions.tianyi_work_persona import instructions as work


class ProjectPersonaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / work.FILENAME

    def test_apply_update_remove_preserves_existing_bytes(self):
        for original in (b'', b'project instructions', '项目要求\r\n'.encode(), b'\xef\xbb\xbf# rules\n'):
            with self.subTest(original=original):
                self.target.write_bytes(original)
                work.apply_persona(self.root, '天依工作人设')
                work.apply_persona(self.root, '更新后的工作人设')
                self.assertEqual(self.target.read_bytes().count(work.BEGIN), 1)
                self.assertEqual(work.current_persona(self.root), '更新后的工作人设')
                self.assertTrue(work.remove_persona(self.root))
                self.assertEqual(self.target.read_bytes(), original)
                self.assertFalse(work.remove_persona(self.root))

    def test_external_additions_survive_removal(self):
        work.apply_persona(self.root, '天依')
        data = self.target.read_bytes()
        self.target.write_bytes(b'# before\n' + data + b'\n# after\n')
        work.remove_persona(self.root)
        self.assertEqual(self.target.read_bytes(), b'# before\n\n# after\n')

    def test_malformed_and_duplicate_markers_are_not_overwritten(self):
        for raw in (work.BEGIN, work.END, work.END + b'\n' + work.BEGIN,
                    work.BEGIN + b'\n' + work.BEGIN + b'\n' + work.END):
            self.target.write_bytes(raw)
            with self.assertRaises(ValueError):
                work.apply_persona(self.root, '天依')
            with self.assertRaises(ValueError):
                work.remove_persona(self.root)
            self.assertEqual(self.target.read_bytes(), raw)

    def test_invalid_encoding_and_oversized_file_survive(self):
        for raw in (b'\xffbad', b'a' * (work.MAX_FILE + 1)):
            self.target.write_bytes(raw)
            with self.assertRaises(ValueError):
                work.apply_persona(self.root, '天依')
            self.assertEqual(self.target.read_bytes(), raw)

    def test_failed_replace_leaves_original_and_cleans_temporary(self):
        self.target.write_bytes(b'original')
        with patch.object(work.os, 'replace', side_effect=PermissionError('file busy')):
            with self.assertRaises(PermissionError):
                work.apply_persona(self.root, '天依')
        self.assertEqual(self.target.read_bytes(), b'original')
        self.assertEqual(list(self.root.glob('.tianyi-persona-*')), [])

    def test_detects_intervening_edit(self):
        self.target.write_bytes(b'original')
        with self.assertRaises(ValueError):
            work.replace_file(self.target, b'old contents', b'replacement')
        self.assertEqual(self.target.read_bytes(), b'original')

    def test_empty_project_and_invalid_persona_are_rejected(self):
        with self.assertRaises(ValueError):
            work.apply_persona('', '天依')
        for text in ('', 'x'*48001, work.BEGIN.decode(), 'a\x00b'):
            with self.assertRaises(ValueError):
                work.apply_persona(self.root, text)
        self.assertFalse(self.target.exists())


class PackageTests(unittest.TestCase):
    def test_zip_loads_through_host_and_ui_applies_and_removes(self):
        from PySide6.QtWidgets import QApplication
        from deskpet.mods.api import ModContext
        from deskpet.mods.loader import discover
        import importlib.util
        builder_path = Path(__file__).resolve().parents[1] / 'packaging/build_work_persona_mod.py'
        spec = importlib.util.spec_from_file_location('work_persona_builder', builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = builder.build(root / 'persona.zip')
            packages = root / 'packages'
            with zipfile.ZipFile(output) as bundle:
                self.assertIsNone(bundle.testzip())
                bundle.extractall(packages)
            found, warnings = discover(packages)
            self.assertEqual(warnings, [])
            self.assertEqual(len(found), 1)
            manifest, factory = found[0]
            self.assertEqual(manifest.id, 'tianyi-work-persona')
            mod = factory(ModContext(root / 'mod-data', lambda _: False))
            mod.start()
            page = mod.create_widget()
            project = root / 'project'
            project.mkdir()
            try:
                self.assertFalse(page.apply_button.isEnabled())
                page.select_project(str(project))
                page.apply_button.click()
                self.assertIn('工作能力', work.current_persona(project))
                page.remove_button.click()
                self.assertIsNone(work.current_persona(project))
                mod.stop()
            finally:
                page.close()
                page.deleteLater()
                mod.stop()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
