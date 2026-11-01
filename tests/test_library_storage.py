import json
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import QSettings
from deskpet.music.tools.library import MusicLibrary
from deskpet.music.tools.library_storage import LibraryStorage


class LibraryStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.settings=QSettings(str(self.root/'settings.ini'),QSettings.IniFormat)
        self.library=MusicLibrary();self.library.add([str(self.root/'song.mp3')])
    def tearDown(self):self.temp.cleanup()

    def test_invalid_existing_payload_is_not_replaced_with_empty_defaults(self):
        payload=self.library.dumps()
        broken=json.loads(payload);broken['playlists'].append({'id':'bad','name':'broken','paths':None})
        raw=json.dumps(broken);self.settings.setValue('library_v1',raw)
        storage=LibraryStorage(self.settings,self.root);fallback=storage.load()
        self.assertTrue(storage.blocked)
        with self.assertRaises(ValueError):storage.save(fallback)
        self.assertEqual(self.settings.value('library_v1'),raw)

    def test_backup_restores_corrupt_registry_without_losing_songs(self):
        self.settings.setValue('library_v1',self.library.dumps())
        original=LibraryStorage(self.settings,self.root);original.load()
        self.settings.setValue('library_v1','{bad json')
        restored=LibraryStorage(self.settings,self.root);library=restored.load()
        self.assertEqual(library.paths,self.library.paths)
        restored.save(library)
        self.assertEqual(MusicLibrary(self.settings.value('library_v1')).paths,self.library.paths)

    def test_empty_clear_does_not_erase_last_nonempty_backup(self):
        self.settings.setValue('library_v1',self.library.dumps())
        storage=LibraryStorage(self.settings,self.root);library=storage.load()
        library.remove([0]);storage.save(library)
        self.assertEqual(MusicLibrary(storage.path.read_text('utf8')).paths,[])
        self.assertEqual(MusicLibrary(storage.backup.read_text('utf8')).paths,self.library.paths)
        # A deliberate valid empty library must stay empty on reopen.
        self.assertEqual(LibraryStorage(self.settings,self.root).load().paths,[])

    def test_non_utf8_snapshot_falls_back_to_backup(self):
        self.settings.setValue('library_v1',self.library.dumps())
        storage=LibraryStorage(self.settings,self.root);storage.load()
        storage.path.write_bytes(b'\xff\xfe\x00')
        self.settings.setValue('library_v1','{broken')
        restored=LibraryStorage(self.settings,self.root);library=restored.load()
        self.assertEqual(library.paths,self.library.paths)
        restored.save(library)
        self.assertEqual(MusicLibrary(storage.path.read_text('utf8')).paths,self.library.paths)

    def test_old_instance_cannot_overwrite_new_import(self):
        self.settings.setValue('library_v1',self.library.dumps())
        old=LibraryStorage(self.settings,self.root);stale=old.load()
        self.library.add([str(self.root/'new.mp3')])
        self.settings.setValue('library_v1',self.library.dumps());self.settings.sync()
        stale.remove([0])
        with self.assertRaises(ValueError):old.save(stale)
        self.assertEqual(self.settings.value('library_v1'),self.library.dumps())

    def test_backup_write_failure_does_not_overwrite_registry(self):
        from unittest.mock import patch
        self.settings.setValue('library_v1',self.library.dumps())
        storage=LibraryStorage(self.settings,self.root);library=storage.load();library.remove([0])
        with patch('deskpet.music.tools.library_storage.write_atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):storage.save(library)
        self.assertEqual(self.settings.value('library_v1'),self.library.dumps())
