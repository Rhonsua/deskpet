"""Verify grounded song recall reaches both real request paths without network."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from deskpet.chat.knowledge import (catalog, CATALOG_PATH, CONTEXT_LIMIT, knowledge_context,
                                    relevant_entries, matches)
from deskpet.chat.persona import TIANYI_PERSONA, TIANYI_SCOPE, TIANYI_EXAMPLES, upgrade_builtin_persona
from deskpet.chat.prompts import build_messages
from deskpet.chat.store import ChatStore
from tests import test_music_ai_choice as fixtures

TIANYI = 'builtin:luotianyi'


class KnowledgeTests(unittest.TestCase):
    def ids(self, query, history=(), current_song=''):
        return [e.id for e in relevant_entries(query, history, current_song)]

    def test_bundled_catalog_and_persona_are_valid(self):
        from deskpet.chat.personality import load_personality
        entries = catalog()
        self.assertEqual(len(entries), 28)
        self.assertEqual(sum(e.song for e in entries), 19)
        self.assertTrue(all(e.sources for e in entries))
        personality, warning = load_personality(TIANYI, '洛天依')
        self.assertFalse(warning)
        self.assertEqual(personality.persona, TIANYI_PERSONA)
        data = json.loads(CATALOG_PATH.parent.parent.joinpath('personas/luotianyi.json').read_text(encoding='utf-8'))
        self.assertEqual(data['scope'], TIANYI_SCOPE)
        self.assertEqual(data['examples'], TIANYI_EXAMPLES)

    def test_core_and_repertoire_always_present(self):
        context = knowledge_context(TIANYI, '晚上好')
        for value in ('天钿', '7月12日', '156cm', '阿绫', '《普通DISCO》', '《反乌托邦Pt.2》'):
            self.assertIn(value, context)
        self.assertIn('未收录不能断言', context)
        self.assertIn('也不表示本地歌单里已经有这些歌', context)
        self.assertEqual(self.ids('晚上好'), [])

    def test_title_alias_and_credit_selection(self):
        for title, expected in [('普通 disco 是谁唱的', 'disco'), ('普通迪斯科', 'disco'),
                                ('LIGHT ME UP', 'light'), ('hello & bye, days', 'hello'),
                                ('权御天下', 'quan'), ('天钿是什么', None)]:
            with self.subTest(title=title):
                if expected:
                    self.assertEqual(self.ids(title)[0], expected)
        text = knowledge_context(TIANYI, '普通DISCO是谁唱的')
        self.assertIn('洛天依与言和演唱', text)
        self.assertIn('ilem', text)
        self.assertIn('https://www.bilibili.com/video/BV1zs411S7sz/', text)
        self.assertFalse(matches('ST', 'just a question'))
        self.assertFalse(matches('COP', 'copyright'))
        self.assertNotIn('hello', self.ids('hello'))

    def test_versions_and_other_singer_not_confused(self):
        self.assertIn('utopia2', self.ids('反乌托邦'))
        self.assertIn('utopia-solo', self.ids('反乌托邦'))
        self.assertIn('utopia-origin', self.ids('反乌托邦'))
        self.assertEqual(self.ids('反乌托邦Pt.2（洛天依Solo Ver.）')[0], 'utopia-solo')
        context = knowledge_context(TIANYI, '世末歌者原唱是不是你')
        self.assertIn('《世末歌者》原唱为乐正绫', context)
        self.assertIn('翻调、翻唱或演出改编', context)

    def test_followup_uses_last_user_topic_not_assistant_invention(self):
        history = [dict(role='user', content='聊聊霜雪千年'),
                   dict(role='assistant', content='我还会普通DISCO')]
        ids = self.ids('这首歌的词曲是谁写的', history)
        self.assertEqual(ids[0], 'snow')
        self.assertNotIn('disco', ids)
        self.assertEqual(self.ids('今晚吃什么', history), [])
        self.assertEqual(self.ids('流光是谁写的', history)[0], 'light')
        self.assertNotIn('snow', self.ids('《一首没有收录的新歌》的歌词是什么意思', history))

    def test_current_song_context_for_demonstrative(self):
        history = [dict(role='user', content='普通DISCO')]
        self.assertEqual(self.ids('正在听的这首谁写的', history, '流光 (Light Me Up)_洛天依Official.mp3')[0], 'light')
        self.assertEqual(self.ids('普通DISCO谁写的', history, '流光 (Light Me Up)')[0], 'disco')
        self.assertNotIn('light', self.ids('晚上好', history, '流光 (Light Me Up)'))

    def test_character_isolation_even_when_persona_has_same_name(self):
        for character in ('', 'miku', 'external:luotianyi'):
            self.assertEqual(knowledge_context(character, '普通DISCO'), '')
            messages = build_messages('你是洛天依', '', [], '普通DISCO', '', character=character)
            self.assertNotIn('已核对的演唱作品', messages[0]['content'])

    def test_independent_of_user_memory_and_clear(self):
        store = ChatStore(':memory:')
        try:
            store.add_turn(TIANYI, '我喜欢爵士', '好呀')
            store.memories.clear(TIANYI)
            store.memories.set_enabled(TIANYI, False)
            messages = build_messages(TIANYI_PERSONA, '', [], '勾指起誓的作者', '',
                                      character=TIANYI, recalled=store.memories.recall(TIANYI, '歌曲'))
            self.assertIn('《勾指起誓》是ilem发布', messages[0]['content'])
            self.assertNotIn('我喜欢爵士', messages[0]['content'])
        finally:
            store.close()

    def test_context_bounded_with_all_titles_and_whole_entries(self):
        query = ' '.join(t for e in catalog() for t in e.terms)
        context = knowledge_context(TIANYI, query)
        self.assertLessEqual(len(context), CONTEXT_LIMIT)
        self.assertEqual(context, knowledge_context(TIANYI, query))
        self.assertTrue(context.rsplit('\n', 1)[-1].startswith('来源：https://'))

    def test_missing_or_malformed_catalog_does_not_break_chat(self):
        catalog.cache_clear()
        try:
            with patch.object(Path, 'read_text', return_value='{}'):
                self.assertEqual(catalog(), ())
                self.assertIn('内置资料暂不可用', knowledge_context(TIANYI, '你好'))
        finally:
            catalog.cache_clear()
        self.assertTrue(catalog())

    def test_new_default_migrates_but_customizations_survive(self):
        with patch('hashlib.sha256') as digest:
            digest.return_value.hexdigest.return_value = '6fdb254866295b2dcbe6616a3c64faaaec84660b457517e15ffe164342b2e8ec'
            self.assertEqual(upgrade_builtin_persona(TIANYI, 'old', TIANYI_PERSONA), TIANYI_PERSONA)
            self.assertEqual(upgrade_builtin_persona('external:x', 'old', TIANYI_PERSONA), 'old')
        self.assertEqual(upgrade_builtin_persona(TIANYI, '用户改过的内容', TIANYI_PERSONA), '用户改过的内容')


class KnowledgeRequestTests(unittest.TestCase):
    setUpClass = fixtures.ChoiceTests.__dict__['setUpClass']
    setUp = fixtures.ChoiceTests.setUp
    tearDown = fixtures.ChoiceTests.tearDown
    window = fixtures.ChoiceTests.window

    def test_actual_companion_request_includes_knowledge_not_false_playback(self):
        with self.window() as (window, remote):
            window.input.setPlainText('普通DISCO是你和谁唱的')
            self.assertTrue(window.send_message())
            messages = remote.return_value.start.call_args.args[1]
            self.assertIn('洛天依与言和演唱', messages[0]['content'])
            self.assertIsNone(window.music_choice)
            self.p.start_track.assert_not_called()

    def test_actual_proactive_request_includes_core_and_repertoire(self):
        from deskpet.chat.companion import CompanionState
        from deskpet.chat.companion_runtime import CompanionRuntime
        with self.window() as (window, remote):
            runtime = CompanionRuntime(window)
            runtime.timer.stop()
            window.companion_runtime = runtime
            runtime.client.start = Mock()
            runtime.state = lambda: CompanionState(idle_seconds=100)
            window.proactive_toggle.setChecked(True)
            runtime.tick()
            runtime.client.start.assert_called_once()
            system = runtime.client.start.call_args.args[1][0]['content']
            self.assertIn('已核对的演唱作品', system)
            self.assertIn('天钿', system)


if __name__ == '__main__':
    unittest.main()
