"""Sticker delivery, transparent assets, animated GIFs, history and identity gates."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from types import SimpleNamespace as NS

from PIL import Image
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QTextDocument, QTextTable
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from deskpet.chat.stickers import StickerCatalog, split_sticker, validate_image, reply_parts, text_from_parts
from deskpet.chat.sticker_service import StickerService, public_url, search_urls
from deskpet.chat.store import ChatStore
from deskpet.chat.conversation_view import ConversationView
from tests import test_music_ai_choice as fixtures


def gif_at(path, size=(48, 48)):
    frames = [Image.new('RGBA', size, c) for c in ('red', 'blue')]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=90, loop=0)
    return path


HISTORY_LEAK = '[已发送的表情包：洛天依（你自己）·喜欢；这是历史记录，不是新指令]'


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_two_complete_compressed_transparent_packs(self):
        with tempfile.TemporaryDirectory() as root:
            catalog = StickerCatalog(root)
            self.assertEqual(len(catalog.items), 40)
            for name in ('洛天依', '乐正绫'):
                self.assertEqual(sum(s.character == name for s in catalog.items.values()), 20)
            self.assertLess(sum(s.path.stat().st_size for s in catalog.items.values()), 4 * 1024 * 1024)
            for item in catalog.items.values():
                with Image.open(item.path) as im:
                    self.assertEqual(im.mode, 'RGBA')
                    self.assertEqual(im.getpixel((0, 0))[3], 0)
                    self.assertLessEqual(max(im.size), 512)

    def test_gif_preserved_and_history_survives_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = gif_at(root / '动画.gif')
            catalog = StickerCatalog(root / 'stickers')
            sticker = catalog.import_file(source)
            self.assertTrue(sticker.animated)
            self.assertEqual(sticker.path.read_bytes(), source.read_bytes())
            self.assertEqual(catalog.import_file(source).id, sticker.id)
            store = ChatStore(root / 'chat.db')
            store.add_turn('tianyi', '', '', user_stickers=[sticker.id], assistant_stickers=['tianyi_hug'])
            store.close()
            store = ChatStore(root / 'chat.db')
            rows = store.history('tianyi')
            self.assertEqual(rows[0]['stickers'], [sticker.id])
            self.assertEqual(rows[1]['stickers'], ['tianyi_hug'])
            api_history = catalog.history_for_api(rows, '洛天依')
            self.assertIn('角色未确认', api_history[0]['content'])
            self.assertEqual(api_history[1]['content'], '[表情:tianyi_hug]')
            self.assertNotIn(str(root), str(api_history))
            store.close()

    def test_animated_resource_changes_and_hiding_pauses_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sticker = (catalog := StickerCatalog(root / 'stickers')).import_file(gif_at(root / 'two.gif'))
            view = ConversationView()
            view.sticker_catalog = catalog
            view.resize(400, 350)
            view.show()
            view.set_messages([dict(role='user', content='动画', stickers=[sticker.id])])
            movie = view.sticker_movies[sticker.id]
            seen = []
            movie.frameChanged.connect(seen.append)
            QTest.qWait(330)
            self.assertGreaterEqual(len(set(seen)), 2)
            pixmap = view.document().resource(QTextDocument.ImageResource, QUrl('sticker:' + sticker.id))
            self.assertFalse(pixmap.isNull())
            view.hide()
            self.assertEqual(movie.state(), movie.MovieState.Paused)
            view.set_messages([])
            self.assertEqual(view.sticker_movies, {})
            view.deleteLater()

    def test_protocol_rejects_fabricated_search_and_hides_partial_tags(self):
        text = '[表情:tianyi_hug]抱抱你'
        for pos in range(1, text.index(']')+1):
            self.assertEqual(split_sticker(text[:pos], True)[0], '')
        self.assertEqual(split_sticker(text)[1], 'tianyi_hug')
        self.assertIsNone(split_sticker('[表情:tianyi_hug][表情:aling_hug]')[3])
        self.assertTrue(split_sticker('[表情:tianyi_hug]' * 5)[3])
        self.assertTrue(split_sticker('[搜表情:{"character":"别人","query":"hello"}]')[3])
        self.assertTrue(split_sticker('[表情:../../secret]')[3])
        rows = search_urls('<a m="{&quot;murl&quot;:&quot;https://example.com/a.gif&quot;}"></a>')
        self.assertEqual(rows, ['https://example.com/a.gif'])
        with patch('socket.getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                public_url('https://example.com/a.gif')

    def test_chat_stickers_are_compact_without_enlarging_small_gifs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = StickerCatalog(root / 'stickers')
            large = catalog.import_file(gif_at(root / 'wide.gif', (320, 160)), character='洛天依', verified=True)
            small = catalog.import_file(gif_at(root / 'small.gif'), character='洛天依', verified=True)
            view = ConversationView()
            view.sticker_catalog = catalog
            view.set_messages([
                dict(role='user', content='一起发', stickers=['tianyi_happy']),
                dict(role='assistant', content='', stickers=['aling_hug', large.id, small.id]),
            ])
            for key in ('tianyi_happy', 'aling_hug'):
                size = view.sticker_frames[key].size()
                self.assertEqual(max(size.width(), size.height()), 96)
            for item, expected in ((large, (96, 48)), (small, (48, 48))):
                size = view.sticker_movies[item.id].scaledSize()
                self.assertEqual((size.width(), size.height()), expected)
            view.set_messages([])
            view.deleteLater()

    def test_chat_opens_at_latest_after_layout_without_fighting_history_reading(self):
        view = ConversationView()
        try:
            view.set_messages([dict(role='user', content=('历史消息 ' + str(i) + ' ') * 12)
                               for i in range(30)], live=('天依', '回复中'))
            view.resize(380, 220)
            view.show()
            QTest.qWait(30)
            bar = view.verticalScrollBar()
            self.assertGreater(bar.maximum(), 0)
            self.assertEqual(bar.value(), bar.maximum())
            view.resize(300, 180)
            QTest.qWait(30)
            self.assertEqual(bar.value(), bar.maximum())
            # A user's navigation cancels any queued automatic scroll, and
            # streaming updates keep the reader's position in old messages.
            view.latest_scroll.start(0)
            QTest.keyClick(view, Qt.Key_PageUp)
            QTest.qWait(30)
            reading_position = bar.value()
            self.assertLess(reading_position, bar.maximum() - 30)
            view.update_live('这一条正在继续输出。' * 20)
            QTest.qWait(30)
            self.assertEqual(bar.value(), reading_position)
            view.hide()
            view.show()
            QTest.qWait(30)
            self.assertEqual(bar.value(), bar.maximum())
        finally:
            view.close()
            view.deleteLater()

    def test_wrong_or_uncertain_identity_is_not_imported_or_sent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = StickerCatalog(root / 'stickers')
            service = StickerService(catalog, lambda: None)
            source = gif_at(root / 'test.gif')
            ready, failed = [], []
            service.ready.connect(ready.append)
            service.failed.connect(failed.append)
            for char, confidence in [('乐正绫', .99), ('洛天依', .6), ('不确定', .99)]:
                service.active = True; service.expected = '洛天依'
                service.candidates = [dict(path=source, source='https://example.com/a.gif')]
                service._identified(json.dumps(dict(index=0, character=char, confidence=confidence, suitable=True, title='开心')))
            self.assertFalse(ready)
            self.assertEqual(len(failed), 3)
            self.assertEqual(len(catalog.custom), 0)
            service.active = True; service.expected = '洛天依'
            service.candidates = [dict(path=source, source='https://example.com/a.gif')]
            service._identified(json.dumps(dict(index=0, character='洛天依', confidence=.98, suitable=True, title='开心')))
            self.assertEqual(len(ready), 1)
            self.assertTrue(catalog.get(ready[0]).animated)
            service.shutdown()

    def test_multi_message_protocol_legacy_ids_and_streaming_tags(self):
        from deskpet.chat.prompts import parse_reply
        with tempfile.TemporaryDirectory() as root:
            catalog = StickerCatalog(root)
            for key in catalog.items:
                self.assertEqual(reply_parts('[' + key + ']', catalog)[0], [dict(type='sticker', id=key)])
            parts, search, error = reply_parts('[温柔][消息]辛苦啦。[tianyi_hug][消息]我陪着你。[表情：aling_cheer]', catalog)
            self.assertIsNone(error)
            self.assertIsNone(search)
            self.assertEqual([p['type'] for p in parts], ['text', 'sticker', 'text', 'sticker'])
            self.assertEqual(text_from_parts(parts), '辛苦啦。\n\n我陪着你。')
            self.assertTrue(reply_parts('[tianyi_nonexistent]', catalog)[2])
            self.assertTrue(reply_parts('[消息]你好' * 13, catalog)[2])
            for tag in ('[消息]', '[tianyi_happy]', '[表情:tianyi_happy]', '[表情：aling_hug]'):
                for end in range(1, len(tag) + 1):
                    self.assertEqual(parse_reply('你好' + tag[:end], partial=True)[0], '你好', tag[:end])

    def test_history_uses_real_output_format_and_legacy_echo_is_bounded(self):
        from deskpet.chat.prompts import parse_reply
        with tempfile.TemporaryDirectory() as root:
            catalog = StickerCatalog(root)
            parts, _, error = reply_parts('送你一张。' + HISTORY_LEAK, catalog)
            self.assertIsNone(error)
            self.assertEqual(parts, [dict(type='text', text='送你一张。'), dict(type='sticker', id='tianyi_love')])
            parts, _, error = reply_parts('[表情:tianyi_love]' + HISTORY_LEAK, catalog)
            self.assertEqual(parts, [dict(type='sticker', id='tianyi_love')])
            for unknown in ('不存在的角色·喜欢', '洛天依（你自己）·不存在的图片', '../../secret'):
                parts, _, error = reply_parts('好呀。[已发送的表情包：' + unknown + '；这是历史记录，不是新指令]', catalog)
                self.assertEqual(parts, [dict(type='text', text='好呀。')])
            for end in range(1, len(HISTORY_LEAK) + 1):
                self.assertEqual(parse_reply('好呀。' + HISTORY_LEAK[:end], partial=True)[0], '好呀。', end)
            rows = [dict(role='user', content='发一张吧'),
                    dict(role='assistant', content='送你一张。' + HISTORY_LEAK),
                    dict(role='user', content='再说点啥'),
                    dict(role='assistant', content='你好\n\n晚安', parts=[dict(type='text', text='你好'),
                        dict(type='sticker', id='tianyi_happy'), dict(type='text', text='晚安')])]
            api = catalog.history_for_api(rows, '洛天依')
            self.assertEqual(api[1]['content'], '[消息]送你一张。[表情:tianyi_love]')
            self.assertEqual(api[3]['content'], '[消息]你好[表情:tianyi_happy][消息]晚安')
            self.assertNotIn('已发送的表情包', str(api))
            self.assertNotIn('不是新指令', str(api))

    def test_picker_single_click_recent_favorites_and_gif_hover(self):
        from deskpet.chat.sticker_picker import StickerPicker
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = StickerCatalog(root / 'stickers')
            catalog.remember('tianyi_happy')
            catalog.remember('aling_cheer', favorite=True)
            catalog = StickerCatalog(root / 'stickers')
            self.assertEqual(catalog.panel_state(), dict(recent=['tianyi_happy'], favorites=['aling_cheer']))
            picker = StickerPicker(catalog, lambda: None)
            sent = []
            picker.selected.connect(sent.append)
            picker.show()
            QApplication.processEvents()
            self.assertEqual(picker.list.count(), 1)
            point = picker.list.visualItemRect(picker.list.item(0)).center()
            QTest.mouseClick(picker.list.viewport(), Qt.LeftButton, pos=point)
            self.assertEqual(sent, ['tianyi_happy'])
            self.assertFalse(picker.isVisible())
            gif = catalog.import_file(gif_at(root / 'hover.gif'))
            picker.show()
            picker.imported(gif.id)
            QApplication.processEvents()
            QTest.mouseMove(picker.list.viewport(), picker.list.visualItemRect(picker.list.item(0)).center())
            QTest.qWait(400)
            self.assertIsNotNone(picker.movie)
            picker.close()
            self.assertIsNone(picker.movie)
            picker.deleteLater()


class DeliveryTests(unittest.TestCase):
    setUpClass = fixtures.ChoiceTests.__dict__['setUpClass']
    setUp = fixtures.ChoiceTests.setUp
    tearDown = fixtures.ChoiceTests.tearDown
    window = fixtures.ChoiceTests.window

    def test_reported_history_note_becomes_image_and_is_never_spoken(self):
        with self.window() as (w, remote), patch.object(w.speech, 'set_enabled'), patch.object(w.speech, 'speak', return_value=False) as speech:
            w.speech_toggle.setChecked(True)
            w.input.setPlainText('你找点表情包发发')
            w.send_message()
            caption = '好啦，那我挑一张送给你。'
            w.on_completed(caption + '\n' + HISTORY_LEAK)
            self.assertIsNone(w.pending)
            self.assertEqual(speech.call_args.args, (caption,))
            self.assertIn('tianyi_love', w.history_view.sticker_frames)
            row = w.store.history(w.character)[-1]
            self.assertEqual(row['content'], caption)
            self.assertEqual(row['parts'], [dict(type='text', text=caption), dict(type='sticker', id='tianyi_love')])
            self.assertNotIn('已发送', w.history_view.toPlainText())
            w.input.setPlainText('这张好可爱')
            w.send_message()
            messages = remote.return_value.start.call_args.args[1]
            previous = [m['content'] for m in messages if m['role'] == 'assistant']
            self.assertEqual(previous, ['[消息]' + caption + '[表情:tianyi_love]'])
            self.assertNotIn('不是新指令', str(previous))
            w.stop()

    def test_old_note_is_repaired_on_read_without_erasing_history(self):
        with self.window() as (w, _):
            for stored_parts in ([], [dict(type='text', text='送你一张。' + HISTORY_LEAK)]):
                w.store.add_turn(w.character, '来张表情', '送你一张。' + HISTORY_LEAK, assistant_parts=stored_parts)
            w.render_history()
            self.assertIn('tianyi_love', w.history_view.sticker_frames)
            self.assertNotIn('已发送的表情包', w.history_view.toPlainText())
            self.assertEqual(len(w.store.history(w.character)), 4)
            self.assertIn(HISTORY_LEAK, w.store.history(w.character)[-1]['content'])

    def test_text_and_stickers_are_separate_and_only_text_synthesizes(self):
        with self.window() as (w, remote), patch.object(w.speech, 'set_enabled'), patch.object(w.speech, 'speak', return_value=False) as speech:
            w.speech_toggle.setChecked(True)
            w.pet.bubble.say_sticker = Mock()
            for response in ('[表情:tianyi_hug]', '[表情:aling_cheer]一起加油！'):
                w.input.setPlainText('给我发表情嘛')
                w.send_message()
                w.on_completed(response)
                self.assertIsNone(w.pending)
                self.assertIn('stickers', w.store.history(w.character)[-1])
            speech.assert_called_once()
            self.assertEqual(speech.call_args.args, ('一起加油！',))
            self.assertEqual(w.pet.bubble.say_sticker.call_count, 2)
            self.assertNotIn('[表情:', w.history_view.toPlainText())

    def test_multiple_messages_wait_for_voice_persist_and_render_in_order(self):
        with self.window() as (w, remote), patch.object(w.speech, 'set_enabled'), patch.object(w.speech, 'speak', return_value=True) as speech:
            w.speech_toggle.setChecked(True)
            w.input.setPlainText('陪我一会嘛')
            w.send_message()
            w.on_completed('[消息]今天辛苦啦。[tianyi_hug][消息]我陪着你！[表情:aling_cheer]')
            self.assertEqual(remote.return_value.start.call_count, 1)
            speech.assert_called_once()
            self.assertEqual(speech.call_args.args, ('今天辛苦啦。\n\n我陪着你！',))
            self.assertEqual(w.store.history(w.character), [])
            delivery = speech.call_args.kwargs['deliver']
            self.assertTrue(delivery())
            self.assertFalse(delivery())
            history = w.store.history(w.character)
            self.assertEqual(len(history), 2)
            self.assertEqual([p['type'] for p in history[-1]['parts']], ['text', 'sticker', 'text', 'sticker'])
            path = w.store.db.execute('PRAGMA database_list').fetchone()[2]
            reopened = ChatStore(path)
            self.assertEqual(reopened.history(w.character), history)
            reopened.close()
            self.assertEqual(len([f for f in w.history_view.document().rootFrame().childFrames() if isinstance(f, QTextTable)]), 5)
            html = w.history_view.toHtml()
            self.assertLess(html.index('今天辛苦啦'), html.index('sticker:tianyi_hug'))
            self.assertLess(html.index('sticker:tianyi_hug'), html.index('我陪着你'))
            self.assertLess(html.index('我陪着你'), html.index('sticker:aling_cheer'))
            self.assertNotIn('[消息]', w.history_view.toPlainText())
            api = w.stickers.history_for_api(history, w.name)
            self.assertEqual([r['role'] for r in api], ['user', 'assistant'])
            self.assertNotIn('parts', api[-1])
            self.assertIn('[表情:tianyi_hug]', api[-1]['content'])

    def test_explicit_standalone_sticker_preserves_draft_on_failure(self):
        with self.window() as (w, remote):
            w.input.setPlainText('还没写完的草稿')
            w.attach_sticker('aling_shy')
            w.send_sticker('tianyi_happy')
            self.assertEqual(w.pending_user_stickers, ['tianyi_happy'])
            self.assertEqual(w.input.toPlainText(), '还没写完的草稿')
            self.assertEqual(w.selected_stickers, ['aling_shy'])
            self.assertEqual(w.stickers.panel_state()['recent'], ['tianyi_happy'])
            w.send_sticker('tianyi_cry')
            self.assertEqual(w.pending_user_stickers, ['tianyi_happy'])
            w.on_failed('网络错误')
            self.assertEqual(w.input.toPlainText(), '还没写完的草稿')
            self.assertEqual(w.selected_stickers, ['aling_shy'])

    def test_picker_click_attaches_then_send_combines_text_and_image(self):
        with self.window() as (w, remote):
            w.resize(760, 900)
            w.show()
            w.input.setPlainText('阿绫也在努力呢')
            w.sticker_button.click()
            picker = w.sticker_picker
            picker.tabs.setCurrentIndex(3)
            picker.query.setText('努力中')
            QApplication.processEvents()
            self.assertEqual(picker.list.count(), 1)
            point = picker.list.visualItemRect(picker.list.item(0)).center()
            QTest.mouseClick(picker.list.viewport(), Qt.LeftButton, pos=point)
            QApplication.processEvents()
            remote.assert_not_called()
            self.assertIsNone(w.pending)
            self.assertEqual(w.input.toPlainText(), '阿绫也在努力呢')
            self.assertEqual(w.selected_stickers, ['aling_work'])
            self.assertFalse(w.sticker_thumbnail.isHidden())
            self.assertFalse(w.sticker_thumbnail.pixmap().isNull())
            self.assertFalse(picker.isVisible())
            self.assertEqual(w.stickers.panel_state()['recent'], [])
            w.send_button.click()
            self.assertEqual(remote.return_value.start.call_count, 1)
            sent = remote.return_value.start.call_args.args[1][-1]
            self.assertEqual(sent['content'], '阿绫也在努力呢\n[用户发送的表情包：乐正绫·努力中]')
            self.assertEqual(w.input.toPlainText(), '')
            self.assertTrue(w.sticker_thumbnail.isHidden())
            self.assertEqual(w.stickers.panel_state()['recent'], ['aling_work'])
            w.on_completed('一起加油呀。')
            history = w.store.history(w.character)
            self.assertEqual(history[0]['content'], '阿绫也在努力呢')
            self.assertEqual(history[0]['stickers'], ['aling_work'])
            tables = [f for f in w.history_view.document().rootFrame().childFrames() if isinstance(f, QTextTable)]
            self.assertEqual(len(tables), 2)
            self.assertIn('sticker:aling_work', w.history_view.toHtml())

    def test_sticker_first_enter_send_failure_and_remove_preserve_caption(self):
        with self.window() as (w, remote):
            w.choose_sticker()
            w.sticker_picker.choose('tianyi_hug')
            w.input.setPlainText('今天抱抱你')
            QTest.keyClick(w.input, Qt.Key_Return)
            self.assertEqual(remote.return_value.start.call_count, 1)
            self.assertEqual(w.pending_user_stickers, ['tianyi_hug'])
            w.on_failed('网络错误')
            self.assertEqual(w.input.toPlainText(), '今天抱抱你')
            self.assertEqual(w.selected_stickers, ['tianyi_hug'])
            self.assertFalse(w.sticker_thumbnail.isHidden())
            w.sticker_remove.click()
            self.assertEqual(w.input.toPlainText(), '今天抱抱你')
            self.assertEqual(w.selected_stickers, [])
            self.assertTrue(w.sticker_thumbnail.isHidden())
            w.input.clear()
            w.attach_sticker('tianyi_happy')
            w.send_message()
            w.on_failed('网络错误')
            self.assertEqual(w.input.toPlainText(), '')
            self.assertEqual(w.selected_stickers, ['tianyi_happy'])

    def test_cancel_mixed_reply_discards_voice_and_all_messages(self):
        with self.window() as (w, remote), patch.object(w.speech, 'set_enabled'), patch.object(w.speech, 'speak', return_value=True) as speech:
            w.speech_toggle.setChecked(True)
            w.input.setPlainText('给我抱抱')
            w.send_message()
            w.on_completed('抱抱。[tianyi_hug][消息]一起加油！')
            delivery = speech.call_args.kwargs['deliver']
            w.stop()
            self.assertFalse(delivery())
            self.assertEqual(w.store.history(w.character), [])

    def test_assistant_gif_is_independent_of_spoken_message(self):
        with self.window() as (w, remote), patch.object(w.speech, 'set_enabled'), patch.object(w.speech, 'speak', return_value=False) as speech:
            item = w.stickers.import_file(gif_at(Path(self.temp.name) / 'reply.gif'), character='洛天依', verified=True)
            w.speech_toggle.setChecked(True)
            w.input.setPlainText('发个动图吧')
            w.send_message()
            w.on_completed('来啦。[' + item.id + ']')
            self.assertEqual(speech.call_args.args, ('来啦。',))
            self.assertIn(item.id, w.history_view.sticker_movies)
            self.assertEqual([p['type'] for p in w.store.history(w.character)[-1]['parts']], ['text', 'sticker'])

    def test_existing_bare_id_history_renders_as_image(self):
        with self.window() as (w, remote):
            w.store.add_turn(w.character, '你开心吗', '[tianyi_happy]今天挺开心的。')
            w.render_history()
            self.assertNotIn('[tianyi_happy]', w.history_view.toPlainText())
            self.assertIn('tianyi_happy', w.history_view.sticker_frames)
            history = w.stickers.history_for_api(w.store.history(w.character), w.name)
            self.assertNotIn('[tianyi_happy]', history[-1]['content'])
            self.assertIn('今天挺开心的', history[-1]['content'])

    def test_known_sticker_works_with_text_only_model_and_ordinary_reply_voice(self):
        with self.window() as (w, remote):
            w.attach_sticker('tianyi_cry')
            w.send_message()
            messages = remote.return_value.start.call_args.args[1]
            self.assertIsInstance(messages[-1]['content'], str)
            self.assertEqual(messages[-1]['content'], '[用户发送的表情包：洛天依（你自己）·委屈]')
            self.assertIn('洛天依（你自己）·委屈', messages[0]['content'])
            w.on_completed('怎么啦，想和我说说吗？')
            self.assertEqual(w.store.history(w.character)[-2]['stickers'], ['tianyi_cry'])

    def test_all_builtin_clicks_put_identity_on_current_user_message(self):
        from deskpet.chat.protocol import request_payload
        with self.window() as (w, remote):
            # A text-only model must receive meaningful content even when the
            # user clicks a sticker without typing a caption.
            for item in w.stickers.items.values():
                w.send_sticker(item.id)
                config, messages = remote.return_value.start.call_args.args[:2]
                current = messages[-1]
                self.assertEqual(current['role'], 'user')
                self.assertIn(item.character, current['content'], item.id)
                self.assertIn(item.title, current['content'], item.id)
                self.assertNotIn('（发送了表情包）', current['content'], item.id)
                self.assertNotIn('image_url', str(current), item.id)
                wire = request_payload(config.validate(), config.model, messages, False, False)
                self.assertEqual(wire['messages'][-1], current)
                self.assertNotIn(str(item.path), str(wire))
                w.stop()

    def test_caption_and_attachment_stay_together_and_history_matches(self):
        with self.window() as (w, remote):
            w.input.setPlainText('阿绫也在努力呢')
            w.attach_sticker('aling_work')
            w.send_message()
            sent = remote.return_value.start.call_args.args[1][-1]
            self.assertEqual(sent['content'], '阿绫也在努力呢\n[用户发送的表情包：乐正绫·努力中]')
            w.on_completed('一起加油呀。')
            history = w.stickers.history_for_api(w.store.history(w.character), w.name)
            self.assertEqual(history[0], sent)

    def test_unknown_image_uses_vision_and_failure_restores_attachment(self):
        with self.window() as (w, remote):
            entry = w.stickers.import_file(gif_at(Path(self.temp.name) / 'new.gif'))
            w.attach_sticker(entry.id)
            w.vision_model_input.setText('test-vision')
            w.input.setPlainText('图里面是你吗？')
            w.send_message()
            config, messages = remote.return_value.start.call_args.args[:2]
            self.assertEqual(config.model, 'test-vision')
            self.assertIn('图里面是你吗', messages[-1]['content'][0]['text'])
            self.assertIn('角色未确认', messages[-1]['content'][0]['text'])
            self.assertTrue(messages[-1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,'))
            w.on_failed('服务不支持图片')
            self.assertEqual(w.selected_stickers, [entry.id])
            self.assertEqual(w.input.toPlainText(), '图里面是你吗？')

    def test_fabricated_sticker_and_mixed_action_do_not_execute(self):
        with self.window() as (w, remote), patch('deskpet.chat.actions.perform_action') as action:
            for reply in ('[表情:nonexistent]', '[动作:sleep][表情:tianyi_sleepy]'):
                w.input.setPlainText('发张表情给我')
                w.send_message();w.on_completed(reply)
                self.assertIsNone(w.pending)
                self.assertEqual(w.store.history(w.character), [])
            action.assert_not_called()

    def test_network_cancel_does_not_send_late_sticker(self):
        with self.window() as (w, remote), patch.object(w.sticker_service, 'search') as search:
            w.input.setPlainText('网上找张你开心的表情包')
            w.send_message()
            w.on_completed('[搜表情:{"character":"洛天依","query":"开心"}]')
            search.assert_called_once_with('洛天依', '开心')
            w.stop()
            w.sticker_found('tianyi_happy')
            self.assertEqual(w.store.history(w.character), [])

    def test_proactive_sticker_does_not_request_voice(self):
        from tests.test_chat_speech_delivery import ProactiveVoiceTests
        with self.window() as (w, _):
            runtime, callbacks = ProactiveVoiceTests().runtime()
            runtime.window.stickers = w.stickers
            runtime.window.name = '洛天依'
            runtime.window.show_sticker_bubble = Mock()
            runtime._completed('[表情:tianyi_cheer]')
            self.assertEqual(callbacks, [])
            runtime.window.show_sticker_bubble.assert_called_once()
            self.assertFalse(runtime.busy)

    def test_proactive_mixed_reply_speaks_only_text(self):
        from tests.test_chat_speech_delivery import ProactiveVoiceTests
        with self.window() as (w, _):
            runtime, callbacks = ProactiveVoiceTests().runtime()
            runtime.window.stickers = w.stickers
            runtime.window.name = '洛天依'
            runtime.window.show_sticker_bubble = Mock()
            runtime.window.speech.speak = Mock(return_value=True)
            runtime._completed('休息一下吧。[tianyi_happy][消息]我陪你。')
            self.assertEqual(runtime.window.speech.speak.call_args.args, ('休息一下吧。\n\n我陪你。',))
            runtime.window.show_sticker_bubble.assert_not_called()
            self.assertTrue(runtime.window.speech.speak.call_args.kwargs['deliver']())
            runtime.window.show_sticker_bubble.assert_called_once()


if __name__ == '__main__':
    unittest.main()
