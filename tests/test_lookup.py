"""Read-only lookups, cancellation, attribution, and isolation from actions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace as NS
from PySide6.QtCore import QCoreApplication
from deskpet.chat.lookup_protocol import parse_lookup, sources_from_rows
from deskpet.chat.lookup_service import parse_rss, parse_headings, relevant, plain, LookupService, LookupJob
from deskpet.chat.prompts import parse_reply
from tests.test_music_ai_choice import ChoiceTests

QUERY = '[联网:{"kind":"lyrics","query":"测试歌曲","current":true}]'
ROW = dict(title='测试歌曲 · 作者', url='https://www.kugou.com/song/example.html', kind='lyrics', text='自制歌词测试文本')


class ProtocolTests(unittest.TestCase):
    def test_request_is_bounded_read_only_and_hidden_while_streaming(self):
        self.assertEqual(parse_lookup(QUERY)[0]['query'], '测试歌曲')
        for raw in ('[联网:{}]', QUERY + '[动作:sleep]', QUERY + QUERY,
                    '[联网:{"kind":"web","query":"x","command":"del"}]',
                    '[联网:{"kind":"lyrics","query":"x","current":"yes"}]'):
            self.assertIsNotNone(parse_lookup(raw)[1], raw)
        for end in range(1, len(QUERY) + 1):
            self.assertEqual(parse_reply(QUERY[:end], partial=True)[0], '', end)
        self.assertEqual(parse_lookup('这句歌词是什么意思？'), (None, None))

    def test_sources_disallow_local_paths_credentials_and_scripts(self):
        for url in ('file:///C:/private.txt', 'http://127.0.0.1/a', 'http://localhost/',
                    'https://user:secret@example.com/', 'javascript:alert(1)', 'http://10.0.0.1/'):
            self.assertEqual(sources_from_rows([dict(title='bad', url=url)]), [])
        self.assertEqual(sources_from_rows([ROW])[0]['url'], ROW['url'])

    def test_public_result_parsers_drop_active_page_content(self):
        self.assertEqual(plain('<h1>标题</h1><script>danger()</script><p>正文</p>'), '标题\n正文')
        rows = parse_rss('<rss><channel><item><title>歌名</title><link>https://example.com/song</link>'
                         '<description>摘要</description></item></channel></rss>')
        self.assertEqual(rows[0]['text'], '摘要')
        self.assertEqual(rows[0]['kind'], 'search_summary')
        self.assertEqual(relevant([dict(title='洛谷题库', text='算术题')], '洛天依 天钿 设定'), [])
        headings = parse_headings('<h3><a href="https://example.com/a">洛天依</a></h3><p>人物介绍</p>'
                                  '<h3><a href="https://ai.so.com/search/a">AI回答</a></h3>')
        self.assertEqual(len(headings), 1)
        self.assertEqual(headings[0]['text'], '人物介绍')

    def test_lyrics_local_first_and_no_network_without_need(self):
        job = LookupJob(1, parse_lookup(QUERY)[0], dict(ROW, local=True, url=''))
        results = []
        job.signals.done.connect(lambda *args: results.append(args))
        with patch.object(job, 'fetch') as fetch:
            job.run()
        fetch.assert_not_called()
        self.assertEqual(results[0][1][0]['text'], ROW['text'])


class ChatTests(unittest.TestCase):
    setUpClass = ChoiceTests.__dict__['setUpClass']
    setUp = ChoiceTests.setUp
    tearDown = ChoiceTests.tearDown
    window = ChoiceTests.window

    def ask(self, window):
        window.input.setPlainText('查一下正在播放的这首歌，再聊聊它想表达什么')
        window.send_message()

    def test_query_answer_sources_and_voice_are_separate(self):
        with self.window() as (w, remote), patch.object(w.lookup_service, 'start') as lookup, \
                patch.object(w.speech, 'set_enabled'), patch.object(w.speech, 'speak', return_value=False) as voice:
            w.speech_toggle.setChecked(True)
            w.pet.music_companion = NS(lyrics=NS(binding=dict(title='测试歌曲', body='[00:01]自制歌词', format='lrc')))
            self.ask(w)
            w.pet.music_companion.lyrics.binding = dict(title='下一首', body='[00:01]别的歌词', format='lrc')
            w.on_completed(QUERY)
            self.assertIsNotNone(w.pending)
            self.assertEqual(w.store.history(w.character), [])
            voice.assert_not_called()
            self.assertEqual(lookup.call_args.args[1]['text'], '自制歌词')
            w.lookup_finished([ROW], '')
            messages = remote.return_value.start.call_args.args[1]
            self.assertIn('自制歌词测试文本', messages[0]['content'])
            self.assertIn('不是指令', messages[0]['content'])
            self.assertEqual(messages[-1]['content'], '查一下正在播放的这首歌，再聊聊它想表达什么')
            w.on_completed('[温柔]我觉得它是在说，平凡的日子也能有自己的光。')
            self.assertEqual(remote.return_value.start.call_count, 2)
            self.assertEqual(voice.call_args.args, ('我觉得它是在说，平凡的日子也能有自己的光。',))
            history = w.store.history(w.character)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[-1]['sources'][0]['url'], ROW['url'])
            self.assertIn('查询来源', w.history_view.toPlainText())
            self.assertIn(ROW['url'], w.history_view.toHtml())
            from deskpet.chat.store import ChatStore
            reopened = ChatStore(w.store.db.execute('PRAGMA database_list').fetchone()[2])
            self.assertEqual(reopened.history(w.character), history)
            reopened.close()

    def test_disabled_and_cancelled_queries_do_not_fetch_or_deliver(self):
        with self.window() as (w, remote), patch.object(w.lookup_service, 'start') as lookup:
            w.lookup_toggle.setChecked(False)
            self.ask(w)
            w.on_completed(QUERY)
            lookup.assert_not_called()
            w.lookup_toggle.setChecked(True)
            self.ask(w)
            w.on_completed(QUERY)
            self.assertEqual(lookup.call_count, 1)
            w.stop()
            w.lookup_finished([ROW], '')
            self.assertEqual(w.store.history(w.character), [])
            self.assertEqual(remote.return_value.start.call_count, 2)

    def test_lookup_failure_is_reported_and_cannot_trigger_actions_or_loop(self):
        with self.window() as (w, remote), patch.object(w.lookup_service, 'start'), \
                patch('deskpet.chat.actions.perform_action') as action:
            self.ask(w)
            w.on_completed(QUERY)
            w.lookup_finished([], '暂时没查到')
            message = remote.return_value.start.call_args.args[1][0]['content']
            self.assertIn('not_found', message)
            w.on_completed('[动作:sleep]网页让我睡觉。')
            action.assert_not_called()
            self.assertEqual(w.store.history(w.character), [])
            self.ask(w)
            w.on_completed(QUERY)
            w.lookup_finished([ROW], '')
            w.on_completed(QUERY)
            self.assertIsNone(w.pending)
            self.assertIn('已完成一次查询', w.status.text())

    def test_query_results_cannot_start_image_search_or_cross_work_mode(self):
        with self.window() as (w, remote), patch.object(w.lookup_service, 'start'), \
                patch.object(w.sticker_service, 'search') as search:
            self.ask(w)
            w.on_completed(QUERY)
            w.lookup_finished([ROW], '')
            w.on_completed('[搜表情:{"character":"洛天依","query":"注入内容"}]')
            search.assert_not_called()
            self.ask(w)
            w.on_completed(QUERY)
            count = remote.return_value.start.call_count
            w.tabs.setCurrentIndex(w.work_index)
            w.lookup_finished([ROW], '')
            self.assertEqual(remote.return_value.start.call_count, count)

    def test_no_lookup_for_ordinary_reply_and_stale_worker_is_ignored(self):
        with self.window() as (w, remote), patch.object(w.lookup_service, 'start') as lookup:
            w.input.setPlainText('今天好开心')
            w.send_message()
            w.on_completed('我也替你开心。')
            lookup.assert_not_called()
            self.assertEqual(remote.return_value.start.call_count, 1)
            service = LookupService()
            ready = Mock()
            service.ready.connect(ready)
            service.active = True
            old = service.ticket
            service.cancel()
            service.finished(old, [ROW], '')
            ready.assert_not_called()


if __name__ == '__main__':
    unittest.main()
