"""Offscreen playback-clock subtitle and binding checks with synthetic text only."""
import argparse
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox
from music_lyrics import LyricsController


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    app = QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    app.setFont(QFont(families[0] if families else 'Microsoft YaHei UI', 9))
    with tempfile.TemporaryDirectory(prefix='lyrics-qt-') as temp:
        root = Path(temp)
        pet = QWidget()
        pet.setGeometry(200, 100, 180, 240)
        pet.show()
        app.processEvents()
        controller = LyricsController(pet, root)
        widget = controller.create_widget()
        widget.resize(520, 730)
        widget.show()
        try:
            bindings = []
            controller.bound.connect(lambda song_id, source: bindings.append((song_id, source)))
            controller.cache_online('123', '合成人工样本', '[00:01]第一句\n[00:02]第二句\n[00:03]\n[00:04]<img src="file:///do-not-load">')
            assert controller.source_key == '' and controller.overlay is None
            assert len(controller.get_cached()) == 1
            assert controller.get_cached()[0]['source'] == 'netease'
            source = 'bilibili:BV1synthetic:2'
            controller.update(source, 1000, True)
            assert controller.document is None
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                widget.bind_button.click()
            assert bindings == [('123', source)]
            assert controller.overlay.text == '第一句' and controller.overlay.isVisible()
            assert controller.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            assert controller.overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
            assert controller.overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
            # Repaint onto the same transparent surface: shorter text must erase old glyphs.
            overlay = controller.overlay
            menu = overlay.make_menu()
            colors = menu.actions()[0].menu()
            colors.actions()[1].trigger()
            assert controller.settings['color'] == '#66ccff' and overlay.text_color == '#66ccff'
            assert '#66ccff' in widget.color_button.text()
            toggle = next(action for action in menu.actions() if action.text().startswith('左键穿透'))
            toggle.trigger()
            assert not controller.settings['left_passthrough'] and not widget.passthrough.isChecked()
            assert not overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
            toggle.trigger()
            assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
            next(action for action in menu.actions() if action.text() == '隐藏歌词').trigger()
            assert not overlay.isVisible() and not widget.enabled.isChecked()
            widget.enabled.setChecked(True)
            assert overlay.isVisible()
            menu.deleteLater()
            overlay.set_content('这是一句很长的合成歌词，用于验证缩短后没有残影', 18, 580)
            frame = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
            frame.fill(Qt.GlobalColor.transparent)
            overlay.render(frame)
            overlay.set_content('短句', 18, 580)
            overlay.render(frame)
            reference = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
            reference.fill(Qt.GlobalColor.transparent)
            overlay.render(reference)
            assert frame == reference, 'shorter lyric retained pixels from previous line'
            with patch.object(controller.store, 'binding', side_effect=AssertionError('same-source update queried database')):
                for position, playing, expected in ((2000, True, '第二句'), (2000, False, '第二句'),
                                                    (1000, True, '第一句'), (4000, True, '<img')):
                    controller.update(source, position, playing)
                    assert expected in controller.overlay.text
            assert '<img' in controller.overlay.text  # Painter text, never HTML or a loaded resource.
            controller.update(source, 3000, True)
            assert not controller.overlay.isVisible() and controller.overlay.text == ''
            controller.update(source, 1000, True, valid=False)
            assert controller.source_key == source and not controller.overlay.isVisible()
            controller.update(source, 1000, True, valid=True)
            assert controller.overlay.text == '第一句'
            controller.set_offset(1000)
            assert controller.overlay.text == '第二句'
            assert controller.store.binding(source)['offset_ms'] == 1000
            widget.offset_input.setValue(777)
            with patch.object(controller.store, 'offset', side_effect=sqlite3.OperationalError('test disk full')):
                widget.offset_button.click()
            assert widget.offset_input.value() == 777 and '未保存' in widget.status.text()
            widget.offset_input.setValue(0)
            widget.offset_button.click()
            controller.update(source, 1000, True)
            pet.move(-1000, -1000)
            controller.configure(x_offset=-2000, y_offset=-2000)
            assert controller.overlay.x() == pet.frameGeometry().center().x() - controller.overlay.width() // 2 - 2000
            assert controller.overlay.y() == pet.frameGeometry().bottom() + 1 - 2000
            controller.configure(enabled=False)
            assert not controller.overlay.isVisible()
            controller.configure(enabled=True, font_size=22, x_offset=0, y_offset=8)
            pet.setGeometry(250, 180, 180, 240)
            controller.update(source, 1000, True)
            old = controller.overlay.pos()
            pet.move(280, 180)
            controller.update(source, 1000, True)
            assert controller.overlay.pos() != old
            pet.hide()
            assert not controller.overlay.isVisible()  # Hide event clears immediately, without another tick.
            controller.update(source, 1000, False)
            assert not controller.overlay.isVisible()
            pet.show()
            controller.update(source, 1000, False)
            assert controller.overlay.text == '第一句'
            controller.update(source, 5000, False, duration_ms=5000)
            assert not controller.overlay.isVisible()
            controller.update('bilibili:BV1synthetic:1', 1000, True)
            assert controller.binding is None and not controller.overlay.isVisible()
            controller.update('bilibili:av12345:10000', 1000, False)
            controller.import_online('123', '合成人工样本', '[00:01]av 分P歌词', controller.source_key)
            assert controller.overlay.text == 'av 分P歌词'
            assert 'B站：av12345 第 10000 P' in widget.source_label.text()
            controller.update('', 0, False)
            assert not controller.overlay.isVisible() and controller.overlay.text == ''
            # Only exact MP3 basename matching is automatic, and only on a source transition.
            audio = root / '短样本.mp3'
            audio.write_bytes(b'not played by this test')
            audio.with_suffix('.lrc').write_text('[00:00]同名歌词\n[00:01]第二句', encoding='utf-8')
            local = 'local:' + str(audio.resolve())
            controller.update(local, 0, True)
            assert controller.overlay.text == '同名歌词'
            srt = root / '手动.srt'
            srt.write_text('1\n00:00:01,000 --> 00:00:02,000\nSRT 第一行\nSRT 第二行', encoding='utf-8')
            controller.import_file(srt)
            assert widget.cache_combo.currentData() == controller.binding['id']
            assert '本地文件：' in widget.source_label.text() and 'local:' not in widget.source_label.text()
            controller.update(local, 1000, False)
            assert controller.overlay.text == 'SRT 第一行\nSRT 第二行'
            controller.update(local, 2000, False)
            assert not controller.overlay.isVisible()
            plain = root / '无时间轴.lrc'
            plain.write_text('只有纯文本，不冒充时间同步。', encoding='utf-8')
            controller.import_file(plain)
            controller.update(local, 1000, True)
            assert not controller.overlay.isVisible() and '纯文本' in controller.status
            assert '只有纯文本' in widget.preview.toPlainText()
            # Bind the timed source again for screenshot and persisted offset checks.
            controller.update(source, 1000, False)
            assert widget.cache_combo.currentData() == controller.binding['id']
            assert 'B站：BV1synthetic 第 2 P' in widget.source_label.text()
            # A manually chosen candidate stays selected while the current binding is unchanged.
            candidate = next(index for index in range(widget.cache_combo.count())
                             if widget.cache_combo.itemData(index) != controller.binding['id'])
            widget.cache_combo.setCurrentIndex(candidate)
            chosen = widget.cache_combo.currentData()
            widget.refresh()
            controller.update(source, 1100, False)
            assert widget.cache_combo.currentData() == chosen
            controller.import_online('123', '合成人工样本', '[00:01]第一句\n[00:02]第二句', source)
            assert widget.cache_combo.currentData() == controller.binding['id']
            controller.set_offset(250)
            widget.font_input.setValue(21)
            widget.position_input.setCurrentIndex(1)
            widget.x_input.setValue(17)
            widget.y_input.setValue(9)
            widget.settings_button.click()
            app.processEvents()
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                assert widget.grab().save(str(args.screenshot))
            controller.shutdown()
            assert not controller.overlay.isVisible()
            restored = LyricsController(pet, root)
            try:
                restored.update(source, 1000, False)
                assert restored.binding['offset_ms'] == 250
                assert restored.settings['font_size'] == 21 and restored.settings['position'] == 'above'
                assert restored.settings['color'] == '#66ccff' and restored.settings['left_passthrough']
                assert (restored.settings['x_offset'], restored.settings['y_offset']) == (17, 9)
                assert restored.overlay.text == '第一句'
            finally:
                restored.shutdown()
            print('PASS: exact cache binding, seek/pause/loop, no per-tick DB reads, valid-position gate, '
                  'offset persistence, pet-anchored edge-following overlay, local LRC/SRT, plain text, failures')
        finally:
            controller.shutdown()
            widget.close()
            pet.close()


if __name__ == '__main__':
    main()
