import tempfile
import unittest
from pathlib import Path

from deskpet.music.tools.library import MusicLibrary, PlaybackQueue


class LibraryTests(unittest.TestCase):
    def test_legacy_import_deduplicates_and_preserves_missing_paths(self):
        library = MusicLibrary('', ['歌曲.mp3', '歌曲.mp3', '不是音乐.txt'])
        self.assertEqual(library.paths, [str(Path('歌曲.mp3').resolve())])
        restored = MusicLibrary(library.dumps())
        self.assertEqual(restored.paths, library.paths)
        self.assertEqual(restored.active_id, library.active_id)

    def test_playlist_switch_and_roundtrip(self):
        library = MusicLibrary()
        original = library.active_id
        library.add(['第一首.mp3'])
        library.create('睡前音乐')
        library.add(['第二首.mp3'])
        library.rename('晚安')
        restored = MusicLibrary(library.dumps())
        self.assertEqual(restored.active['name'], '晚安')
        restored.active_id = original
        self.assertEqual(Path(restored.paths[0]).name, '第一首.mp3')
        restored.delete()
        self.assertEqual(len(restored.playlists), 1)
        with self.assertRaises(ValueError):
            restored.delete()

    def test_removing_song_keeps_disk_file(self):
        with tempfile.TemporaryDirectory() as scratch:
            song = Path(scratch) / '歌曲.mp3'
            song.write_bytes(b'test')
            library = MusicLibrary()
            library.add([str(song)])
            library.remove([0])
            self.assertEqual(library.paths, [])
            self.assertTrue(song.exists())

    def test_corrupt_state_falls_back_to_legacy(self):
        library = MusicLibrary('{bad json', ['音乐.mp3'])
        self.assertEqual(len(library.paths), 1)


class QueueTests(unittest.TestCase):
    def test_reverse_order_stops_at_front_and_manual_next_wraps(self):
        queue = PlaybackQueue('order')
        queue.reverse = True
        queue.reset(['a', 'b', 'c'], 2)
        self.assertEqual(queue.advance(ended=True), 1)
        self.assertEqual(queue.advance(ended=True), 0)
        self.assertIsNone(queue.advance(ended=True))
        self.assertEqual(queue.advance(), 2)
        self.assertEqual(queue.advance(-1), 0)

    def test_reverse_loop_single_and_unselected_start(self):
        queue = PlaybackQueue('loop')
        queue.reverse = True
        queue.reset(['a', 'b', 'c'], -1)
        self.assertEqual(queue.advance(), 2)
        queue.index = 0
        self.assertEqual(queue.advance(ended=True), 2)
        queue.mode = 'single'
        self.assertEqual(queue.advance(ended=True), 2)
        self.assertEqual(queue.advance(), 1)

    def test_reordering_preserves_current_and_shuffle_identities(self):
        queue = PlaybackQueue('shuffle')
        queue.reset(['a', 'b', 'c', 'd'], 1)
        queue.bag, queue.history = [2, 3], [0]
        queue.reorder(['d', 'c', 'a', 'b'])
        self.assertEqual(queue.paths[queue.index], 'b')
        self.assertEqual([queue.paths[i] for i in queue.bag], ['c', 'd'])
        self.assertEqual(queue.paths[queue.advance(-1)], 'a')

    def test_reverse_empty_single_song_and_shuffle(self):
        queue = PlaybackQueue('order')
        queue.reverse = True
        self.assertIsNone(queue.advance(ended=True))
        queue.reset(['a'], 0)
        self.assertIsNone(queue.advance(ended=True))
        queue.mode = 'loop'
        self.assertEqual(queue.advance(ended=True), 0)
        queue.mode = 'shuffle'
        queue.reset(['a', 'b', 'c'], 0)
        self.assertEqual(set([0, queue.advance(), queue.advance()]), {0, 1, 2})

    def test_order_stops_at_end_but_manual_next_wraps(self):
        queue = PlaybackQueue('order')
        queue.reset(['a', 'b'], 1)
        self.assertIsNone(queue.advance(ended=True))
        self.assertEqual(queue.advance(), 0)

    def test_loop_and_single_have_distinct_end_behavior(self):
        queue = PlaybackQueue('loop')
        queue.reset(['a', 'b'], 1)
        self.assertEqual(queue.advance(ended=True), 0)
        queue.mode = 'single'
        self.assertEqual(queue.advance(ended=True), 0)
        self.assertEqual(queue.advance(), 1)

    def test_shuffle_finishes_cycle_without_repeating_and_can_go_back(self):
        queue = PlaybackQueue('shuffle')
        queue.reset(['a', 'b', 'c', 'd'], 0)
        visited = [0] + [queue.advance() for _ in range(3)]
        self.assertEqual(set(visited), {0, 1, 2, 3})
        self.assertEqual(queue.advance(-1), visited[-2])


if __name__ == '__main__':
    unittest.main()
