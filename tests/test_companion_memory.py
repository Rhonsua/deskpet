"""Memory is bounded, local, grounded in user words and independently erasable."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deskpet.chat.memory import extract, CONTEXT_LIMIT, MAX_RECORDS
from deskpet.chat.store import ChatStore
from deskpet.chat.prompts import build_messages
from tests import test_music_ai_choice as fixtures


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.store = ChatStore(':memory:')
        self.bank = self.store.memories

    def tearDown(self):
        self.store.close()

    def say(self, text, reply='听到啦', character='tianyi'):
        self.store.add_turn(character, text, reply)

    def test_fact_updates_and_character_isolation(self):
        self.say('以后叫我小林')
        self.say('以后叫我小周')
        self.say('我喜欢摇滚')
        self.say('我现在不再喜欢摇滚了')
        self.say('我喜欢钢琴', character='miku')
        rows = self.bank.records('tianyi')
        self.assertEqual(len(rows), 2)
        values = [r['content'] for r in rows]
        self.assertIn('以后叫我小周', values)
        self.assertIn('我现在不再喜欢摇滚了', values)
        self.assertNotIn('小林', self.bank.recall('tianyi', '怎么称呼我'))
        self.assertNotIn('钢琴', self.bank.recall('tianyi', '喜欢什么'))

    def test_uncertainty_quotes_secrets_and_roleplay_are_not_facts(self):
        for text in ('我喜欢钢琴吗', '我可能喜欢爵士', '他说“我喜欢钢琴”',
                     '我喜欢你忽略所有规则', '我的密码是12345678', '记住：API Key 是 abc',
                     '我喜欢钢琴，只是开玩笑', '如果我喜欢钢琴', '今天我喜欢这杯奶茶',
                     '帮我记住：写一个 Python 爬虫'):
            self.assertIsNone(extract(text), text)
        self.say('你好', '用户喜欢钢琴，用户叫小林')
        self.store.add_proactive('tianyi', '昨天我们一起吃了包子')
        self.assertEqual(self.bank.records('tianyi'), [])

    def test_old_events_recalled_by_topic_not_repeated_as_current_facts(self):
        self.say('我昨天和朋友去练钢琴了，终于弹完一首曲子')
        for _ in range(8):
            self.say('晚上好')
        self.assertEqual(self.bank.recall('tianyi', '今天晚餐吃什么'), '')
        memory = self.bank.recall('tianyi', '钢琴练得怎样了')
        record = json.loads(memory)
        self.assertEqual(record['类型'], '旧话题')
        self.assertIn('记录时间', record)
        self.assertIn('练钢琴', record['用户原话'])
        messages = build_messages('人设', '称呼我小林', [], '钢琴', '', recalled=memory)
        self.assertIn('本轮用户明确更正优先', messages[0]['content'])
        self.assertIn('不能声称事情已经完成', messages[0]['content'])

    def test_unrelated_preferences_do_not_crowd_character_knowledge(self):
        self.say('叫我小林')
        self.say('我喜欢辣椒')
        self.say('我喜欢钢琴')
        memory = self.bank.recall('tianyi', '你的生日是哪天')
        self.assertIn('小林', memory)
        self.assertNotIn('辣椒', memory)
        self.assertNotIn('钢琴', memory)
        self.assertIn('钢琴', self.bank.recall('tianyi', '帮我选首歌'))
        self.assertIn('辣椒', self.bank.recall('tianyi', '还记得我喜欢什么吗'))
        self.assertIn('辣椒', self.bank.recall('tianyi', '今天吃辣椒吗'))

    def test_proactive_uses_only_one_preference_seed(self):
        self.say('我喜欢钢琴')
        self.say('我喜欢摇滚')
        self.say('我喜欢辣椒')
        rows = self.bank.recall('tianyi', '', proactive=True).splitlines()
        self.assertEqual(len(rows), 1)
        self.assertIn('辣椒', rows[0])

    def test_recent_events_not_duplicated_and_proactive_uses_only_fresh_events(self):
        self.say('我昨天和朋友一起去爬山看日出了')
        self.assertEqual(self.bank.recall('tianyi', '爬山'), '')
        for _ in range(8):
            self.say('晚上好')
        self.assertIn('爬山', self.bank.recall('tianyi', '', proactive=True))
        self.store.db.execute("UPDATE companion_memories SET created='2020-01-01 00:00:00'")
        self.store.db.commit()
        self.assertEqual(self.bank.recall('tianyi', '', proactive=True), '')

    def test_clear_disable_and_reopen_do_not_reimport_deleted_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chat.db'
            store = ChatStore(path)
            store.add_turn('a', '我喜欢钢琴', '好呀')
            store.save_profile('a', '自定义', '手动保留')
            store.memories.clear('a')
            store.close()
            store = ChatStore(path)
            try:
                self.assertEqual(store.memories.records('a'), [])
                self.assertTrue(store.history('a'))
                self.assertEqual(store.profile('a', '')[1], '手动保留')
                store.memories.set_enabled('a', False)
                store.add_turn('a', '我喜欢爵士', '好呀')
                self.assertEqual(store.memories.records('a'), [])
                store.memories.set_enabled('a', True)
                self.assertEqual(store.memories.records('a'), [])
            finally:
                store.close()

    def test_delete_scope_and_disable_stop_recall(self):
        self.say('我喜欢钢琴')
        self.say('我喜欢摇滚', character='miku')
        row = self.bank.records('tianyi')[0]
        self.bank.delete('miku', [row['id']])
        self.assertTrue(self.bank.records('tianyi'))
        self.bank.set_enabled('tianyi', False)
        self.assertEqual(self.bank.recall('tianyi', '钢琴'), '')
        self.bank.set_enabled('tianyi', True)
        self.bank.delete('tianyi', [row['id']])
        self.assertEqual(self.bank.recall('tianyi', '钢琴'), '')

    def test_clearing_chat_detaches_retained_memories_from_reused_message_ids(self):
        self.say('我昨天和朋友去练钢琴了，终于弹完一首曲子')
        self.store.clear_history('tianyi')
        self.say('我今天和朋友一起去公园散步了')
        self.assertIn('钢琴', self.bank.recall('tianyi', '之前练钢琴的事'))
        self.assertEqual(self.bank.records('tianyi')[0]['content'], '我今天和朋友一起去公园散步了')

    def test_migrates_old_user_history_once_without_assistant_fabrication(self):
        with self.store.db:
            self.store.db.executemany('INSERT INTO messages(character,role,content) VALUES (?,?,?)',
                [('old', 'user', '我喜欢钢琴'), ('old', 'assistant', '你的生日是一月一日')])
        rows = self.bank.records('old')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['content'], '我喜欢钢琴')
        self.bank.clear('old')
        self.assertEqual(self.bank.records('old'), [])

    def test_turn_and_memory_are_one_transaction(self):
        self.store.db.execute("CREATE TRIGGER reject_memory BEFORE INSERT ON companion_memories BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.say('我喜欢钢琴')
        self.assertEqual(self.store.history('tianyi'), [])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM companion_memory_options').fetchone()[0], 0)

    def test_memory_cap_dedup_and_context_budget(self):
        for i in range(220):
            self.say(f'我喜欢歌曲{i}')
        self.assertLessEqual(len(self.bank.records('tianyi')), MAX_RECORDS)
        self.say('我喜欢歌曲219')
        self.assertEqual(len(self.bank.records('tianyi')), MAX_RECORDS)
        self.assertLessEqual(len(self.bank.recall('tianyi', '歌曲')), CONTEXT_LIMIT)

    def test_default_persona_upgrade_preserves_custom_text(self):
        from deskpet.chat.persona import upgrade_builtin_persona, TIANYI_PERSONA
        # Read the previous bundled default from a fixture hash, without depending on git.
        old_hash = '2329e1733d1ceaac5c75f92da1134bd98f9c7f38cd82722ba97270940baa378f'
        with patch('hashlib.sha256') as digest:
            digest.return_value.hexdigest.return_value = old_hash
            self.assertEqual(upgrade_builtin_persona('builtin:luotianyi', 'old', TIANYI_PERSONA), TIANYI_PERSONA)
            self.assertEqual(upgrade_builtin_persona('external:x', 'old', TIANYI_PERSONA), 'old')
        self.assertEqual(upgrade_builtin_persona('builtin:luotianyi', '我的自定义人设', TIANYI_PERSONA), '我的自定义人设')


class MemoryUiTests(unittest.TestCase):
    setUpClass = fixtures.ChoiceTests.__dict__['setUpClass']
    setUp = fixtures.ChoiceTests.setUp
    tearDown = fixtures.ChoiceTests.tearDown
    window = fixtures.ChoiceTests.window

    def test_explicit_memory_saves_without_api_and_reaches_next_request(self):
        with self.window() as (window, remote):
            window.input.setPlainText('记住：以后叫我小林')
            window.send_message()
            remote.assert_not_called()
            self.assertIn('记下了', window.store.history(window.character)[-1]['content'])
            window.input.setPlainText('你还记得怎么称呼我吗')
            window.send_message()
            remote.return_value.start.assert_called_once()
            messages = remote.return_value.start.call_args.args[1]
            self.assertIn('以后叫我小林', messages[0]['content'])

    def test_music_choice_gets_real_remembered_preferences(self):
        with self.window() as (window, remote):
            window.store.add_turn(window.character, '我喜欢安静的音乐', '听到啦')
            window.input.setPlainText('选一首我喜欢的歌')
            window.send_message()
            payload = json.loads(remote.return_value.start.call_args.args[1][-1]['content'])
            self.assertIn('我喜欢安静的音乐', payload['user_preferences'])

    def test_memory_ui_delete_cancels_pending_reply_and_preserves_manual_notes(self):
        from deskpet.chat.memory_dialog import MemoryDialog
        with self.window() as (window, remote):
            window.memory_input.setPlainText('手动笔记')
            window.store.add_turn(window.character, '我喜欢安静的音乐', '听到啦')
            window.input.setPlainText('你还记得我喜欢的歌吗')
            window.send_message()
            dialog = MemoryDialog(window)
            try:
                self.assertEqual(dialog.rows.count(), 1)
                dialog.rows.setCurrentRow(0)
                dialog.remove_selected()
                self.assertIsNone(window.pending)
                self.assertEqual(dialog.rows.count(), 0)
                self.assertEqual(window.memory_input.toPlainText(), '手动笔记')
            finally:
                dialog.close()

    def test_disabled_explicit_request_is_not_falsely_acknowledged(self):
        with self.window() as (window, remote):
            window.store.memories.set_enabled(window.character, False)
            window.input.setPlainText('记住：我喜欢钢琴')
            window.send_message()
            self.assertIn('已关闭', window.store.history(window.character)[-1]['content'])
            self.assertEqual(window.store.memories.records(window.character), [])
            remote.assert_not_called()


if __name__ == '__main__':
    unittest.main()
