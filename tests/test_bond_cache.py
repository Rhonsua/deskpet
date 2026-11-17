"""Small offline regressions for store read caches and deferred book layout."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from deskpet.mods.bond import album
from deskpet.mods.bond.album import MemoryBook
from deskpet.mods.bond.store import BondStore


class BondCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.store = BondStore(':memory:')
        self.addCleanup(self.store.close)

    def book(self, *, defer=False):
        book = MemoryBook(self.store, defer=defer)
        self.addCleanup(book.close)
        return book

    def add_chart(self, key, source='local-song', *, db=None):
        connection = self.store.db if db is None else db
        connection.execute('INSERT INTO charts VALUES(?,?,1,?)',
                           (key, json.dumps(dict(source=source, difficulty='normal')), '2026-11-17'))

    def test_unchanged_memories_and_chart_summaries_read_rows_once(self):
        with self.store.db:
            self.add_chart('one')
        queries = []
        self.store.db.set_trace_callback(queries.append)
        for _ in range(5):
            self.store.memories()
            self.store.favorite_chart_summaries()
        reads = [sql.lower() for sql in queries if sql.lower().startswith('select')]
        self.assertEqual(sum('from collection order by' in sql for sql in reads), 1)
        self.assertEqual(sum('from charts where favorite=1' in sql for sql in reads), 1)

    def test_returned_containers_and_dicts_do_not_mutate_caches(self):
        with self.store.db:
            self.add_chart('one')
        memories = self.store.memories()
        expected = [dict(row) for row in memories]
        memories[0]['title'] = 'modified by caller'
        memories.clear()
        self.assertEqual(self.store.memories(), expected)
        summaries = self.store.favorite_chart_summaries()
        summaries[0][1]['source'] = 'modified by caller'
        summaries.clear()
        self.assertEqual(self.store.favorite_chart_summaries(),
                         [('one', dict(source='local-song', difficulty='normal'))])

    def test_collection_and_chart_insert_update_delete_invalidate(self):
        self.store.memories()
        self.store.favorite_chart_summaries()
        with self.store.db:
            self.store.card('diary:one', 'new memory', 'body')
            self.add_chart('one')
        self.assertIn('diary:one', {r['id'] for r in self.store.memories()})
        self.assertEqual(len(self.store.favorite_chart_summaries()), 1)
        with self.store.db:
            self.store.db.execute('UPDATE charts SET body=? WHERE id=?',
                                  (json.dumps(dict(source='changed', difficulty='hard')), 'one'))
        self.assertEqual(self.store.favorite_chart_summaries(),
                         [('one', dict(source='changed', difficulty='hard'))])
        with self.store.db:
            self.store.db.execute("UPDATE collection SET title='updated' WHERE id='diary:one'")
            self.store.db.execute("UPDATE charts SET favorite=0 WHERE id='one'")
        self.assertEqual(next(r['title'] for r in self.store.memories() if r['id']=='diary:one'), 'updated')
        self.assertEqual(self.store.favorite_chart_summaries(), [])
        with self.store.db:
            self.add_chart('two')
        self.assertEqual([key for key, _ in self.store.favorite_chart_summaries()], ['two'])
        with self.store.db:
            self.store.db.execute("DELETE FROM collection WHERE id='diary:one'")
            self.store.db.execute('DELETE FROM charts')
        self.assertNotIn('diary:one', {r['id'] for r in self.store.memories()})
        self.assertEqual(self.store.favorite_chart_summaries(), [])

    def test_deferred_hidden_book_does_not_read_or_paginate_until_opened(self):
        with patch.object(self.store, 'memories', wraps=self.store.memories) as memories, \
                patch.object(album, 'text_pages', wraps=album.text_pages) as paginate:
            book = self.book(defer=True)
            self.assertTrue(book.isHidden())
            memories.assert_not_called()
            paginate.assert_not_called()
            book.set_section('days')
            memories.assert_called_once()
            self.assertGreater(paginate.call_count, 0)

    def test_repeated_reload_skips_memories_and_pagination(self):
        book = self.book()
        pages = book.pages
        with patch.object(self.store, 'memories', wraps=self.store.memories) as memories, \
                patch.object(album, 'text_pages', wraps=album.text_pages) as paginate:
            for _ in range(5):
                book.reload()
            memories.assert_not_called()
            paginate.assert_not_called()
        self.assertIs(book.pages, pages)

    def test_new_collection_reloads_book_and_reuses_existing_record_pages(self):
        with self.store.db:
            self.store.card('diary:old', 'old memory', 'body')
        book = self.book()
        old_page = next(p for p in book.pages['days'] if p.key == 'diary:old')
        with self.store.db:
            self.store.card('diary:new', 'new memory', 'new body')
        with patch.object(album, 'make_pages', wraps=album.make_pages) as make_pages:
            book.reload()
        self.assertTrue(any(p.key == 'diary:new' for p in book.pages['days']))
        self.assertIs(next(p for p in book.pages['days'] if p.key == 'diary:old'), old_page)
        self.assertNotIn('diary:old', [call.args[0] for call in make_pages.call_args_list])

    def test_rollback_discards_cached_uncommitted_rows(self):
        before = self.store.memories()
        self.store.card('diary:temporary', 'temporary', 'rolled back')
        self.add_chart('temporary')
        self.assertIn('diary:temporary', {r['id'] for r in self.store.memories()})
        self.assertEqual(len(self.store.favorite_chart_summaries()), 1)
        self.store.db.rollback()
        self.assertEqual(self.store.memories(), before)
        self.assertEqual(self.store.favorite_chart_summaries(), [])

    def test_rollback_then_same_number_of_writes_cannot_reuse_aborted_cache(self):
        self.store.card('diary:temporary', 'temporary', 'rolled back')
        self.add_chart('temporary')
        self.store.memories()
        self.store.favorite_chart_summaries()
        book = self.book()
        self.store.db.rollback()
        # No intervening read after rollback: table revision counters may repeat.
        with self.store.db:
            self.store.card('diary:committed', 'committed', 'kept')
            self.add_chart('committed')
        ids = {r['id'] for r in self.store.memories()}
        with self.subTest(cache='memories'):
            self.assertIn('diary:committed', ids)
            self.assertNotIn('diary:temporary', ids)
        with self.subTest(cache='chart summaries'):
            self.assertEqual([key for key, _ in self.store.favorite_chart_summaries()], ['committed'])
        with self.subTest(cache='book pages'):
            book.reload()
            self.assertTrue(any(p.key == 'diary:committed' for p in book.pages['days']))
            self.assertFalse(any(p.key == 'diary:temporary' for p in book.pages['days']))

    def test_external_connection_writes_invalidate_store_and_book(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BondStore(Path(directory) / 'cache.db')
            try:
                book = MemoryBook(store)
                store.memories()
                store.favorite_chart_summaries()
                external = sqlite3.connect(store.path)
                try:
                    with external:
                        external.execute('INSERT INTO collection VALUES(?,?,?,?)',
                                         ('diary:external', 'external memory', '2026-11-17', 'body'))
                        self.add_chart('external', db=external)
                finally:
                    external.close()
                self.assertIn('diary:external', {r['id'] for r in store.memories()})
                self.assertEqual([key for key, _ in store.favorite_chart_summaries()], ['external'])
                book.reload()
                self.assertTrue(any(p.key == 'diary:external' for p in book.pages['days']))
                book.close()
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
