"""Delegated music requests select real candidates and execute exactly once."""
import json
from pathlib import Path
import unittest

from tests import test_music_ai_choice as fixtures
from deskpet.chat.action_protocol import parameters, split_reply
from deskpet.chat.music_requests import delegated_music
from deskpet.chat.music_actions import MusicChoice, perform, selection_candidates


class RequestsTests(unittest.TestCase):
    def test_casual_requests_are_executable_without_treating_them_as_titles(self):
        for value in ('随便唱首歌听听', '放歌啊', '天依，你挑一首吧', '随机放一首',
                      '给我唱一首歌听听', '帮我选首歌', '随机播放本地一首歌', 'B站随机放一首'):
            self.assertEqual(delegated_music(value)[0], 'music_random', value)
        self.assertEqual(delegated_music('B站随机放一首')[1], {'source': 'web'})
        self.assertEqual(delegated_music('随机播放本地一首歌')[1], {'source': 'local'})
        self.assertEqual(delegated_music('帮我挑一首适合放松的歌')[0], 'music_pick')

    def test_negation_quotes_discussion_and_named_songs_are_not_delegation(self):
        for value in ('不要随便唱首歌', '如果你随便唱首歌会怎么样', '昨天你说随便放一首',
                      '他说“放歌啊”', '随便放一首是什么意思', '你会随机放歌吗',
                      '播放反乌托邦', '播放《随便》', '拿麦唱歌', '唱一下', '唱歌'):
            self.assertIsNone(delegated_music(value), value)

    def test_selection_parameters_are_bounded_and_separate_from_regex(self):
        value = '[动作:music_pick {"preference":"轻松一点","source":"local"}]这就选。'
        self.assertEqual(parameters(value)['preference'], '轻松一点')
        self.assertEqual(split_reply(value)[1], 'music_pick')
        for value in ('[动作:music_pick {"source":"https://example.com"}]好',
                      '[动作:music_pick {"path":"C:/secret.mp3"}]好',
                      '[动作:music_random {"preference":"放松"}]好',
                      '[动作:music_pick {"pattern":".*"}]好',
                      '[动作:music_pick {"source":"web","playlist":"我的歌单"}]好',
                      '[动作:music_pick {"preference":42}]好'):
            self.assertIsNotNone(split_reply(value)[2], value)


class DelegationTests(unittest.TestCase):
    setUpClass = fixtures.ChoiceTests.__dict__['setUpClass']
    setUp = fixtures.ChoiceTests.setUp
    tearDown = fixtures.ChoiceTests.tearDown
    window = fixtures.ChoiceTests.window

    def test_screenshot_requests_play_immediately_even_without_api(self):
        with self.window() as (window, remote):
            window.config.model = ''
            for value in ('随便唱首歌听听', '放歌啊', '你挑一首吧'):
                window.input.setPlainText(value)
                window.send_message()
            remote.assert_not_called()
            self.assertEqual(self.p.start_track.call_count, 3)
            self.assertEqual(len({c.args[0] for c in self.p.start_track.call_args_list}), 3)
            self.assertIn('正在准备播放本地的《', window.store.history(window.character)[-1]['content'])

    def test_preference_selects_actual_id_and_hides_internal_json(self):
        with self.window() as (window, remote):
            window.input.setPlainText('帮我挑一首适合放松的歌')
            window.send_message()
            messages = remote.return_value.start.call_args.args[1]
            payload = json.loads(messages[-1]['content'])
            self.assertIn('放松', payload['preference'])
            self.assertNotIn(self.temp.name, json.dumps(messages))
            self.assertNotIn('https://', json.dumps(messages))
            index = next(str(i) for i,m in enumerate(window.music_choice) if m['key'] == self.local[2])
            window.on_partial('{"id":')
            self.assertNotIn('{"id":', window.partial_text)
            self.p.start_track.assert_not_called()
            window.on_completed(json.dumps({'id': index}))
            self.p.start_track.assert_called_once_with(2)
            window.on_completed(json.dumps({'id': index}))
            self.p.start_track.assert_called_once_with(2)

    def test_api_can_delegate_with_preference_and_source(self):
        with self.window() as (window, remote):
            window.input.setPlainText('今天有点累，挑点音乐陪我歇一会儿')
            window.send_message()
            window.on_completed('[动作:music_pick {"preference":"适合休息","source":"web"}]这就挑。')
            self.assertTrue(all(m['source'] == 'web' for m in window.music_choice))
            window.on_completed('{"id":"0"}')
            self.assertEqual(self.p.playback_source, 'web')
            self.assertEqual(self.p.bilibili.current_url, self.p.bilibili.tracks[0]['url'])

    def test_cancel_stale_reply_and_invalid_selection_never_start(self):
        with self.window() as (window, _):
            for event in ('cancel', 'changed', 'invalid'):
                window.input.setPlainText('选一首适合现在的歌')
                window.send_message()
                self.assertIsNotNone(window.music_choice)
                if event == 'cancel':
                    window.stop()
                    window.on_completed('{"id":"0"}')
                elif event == 'changed':
                    self.p.playback_source = 'web'
                    window.on_completed('{"id":"0"}')
                else:
                    window.on_completed('{"id":"999"}')
                self.assertIsNone(window.pending)
            self.p.start_track.assert_not_called()
            self.p.bilibili.start_process.assert_not_called()

    def test_random_skips_missing_and_current_without_changing_mode(self):
        self.p.current_path.return_value = self.local[0]
        Path(self.local[1]).unlink()
        mode = self.p.queue.mode
        result = perform(self.pet, 'music_random', {'source': 'local'})
        self.assertTrue(result.executed)
        self.p.start_track.assert_called_once_with(2)
        self.assertEqual(self.p.queue.mode, mode)

    def test_empty_and_single_candidate_have_honest_results(self):
        for path in self.local:
            Path(path).unlink()
        self.assertFalse(perform(self.pet, 'music_random', {'source': 'local'}).executed)
        self.p.bilibili.tracks = self.p.bilibili.tracks[:1]
        with self.assertRaises(MusicChoice):
            perform(self.pet, 'music_pick', {'source': 'web', 'preference': '只能是纯音乐'})
        self.p.bilibili.start_process.assert_not_called()
        result = perform(self.pet, 'music_random', {'source': 'web'})
        self.assertTrue(result.executed)
        self.assertEqual(self.p.playback_source, 'web')
        self.p.bilibili.tracks = []
        self.assertFalse(perform(self.pet, 'music_random').executed)

    def test_playlist_and_bilibili_scope_are_honored(self):
        self.p.library.create('睡前')
        self.p.library.add([self.local[2]])
        result = perform(self.pet, 'music_random', {'playlist': '睡前'})
        self.assertTrue(result.executed)
        self.p.start_track.assert_called_once_with(0)
        self.assertFalse(perform(self.pet, 'music_random', {'playlist': '不存在'}).executed)
        with self.assertRaises(MusicChoice) as caught:
            perform(self.pet, 'music_pick', {'source': 'web', 'preference': '开心'})
        self.assertTrue(all(m['source'] == 'web' for m in caught.exception.matches))

    def test_large_catalogue_is_bounded_and_uses_valid_candidate_keys(self):
        self.p.bilibili.tracks = [dict(url=f'https://www.bilibili.com/video/av{i}/', title=f'曲目{i}')
                                 for i in range(1, 101)]
        matches = selection_candidates(self.p, source='web')
        self.assertEqual(len(matches), 60)
        self.assertEqual(len({m['key'] for m in matches}), 60)
        self.assertTrue(all(m['key'] in {t['url'] for t in self.p.bilibili.tracks} for m in matches))


if __name__ == '__main__':
    unittest.main()
