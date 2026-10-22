"""Offscreen page smoke using synthetic results; does not contact NetEase."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont, QFontDatabase
from netease_music import NeteaseWidget
from netease_music.widget import login_pixmap
from netease_music.service import ApiError
from compact_ui import COMPACT_STYLE


def main():
    app = QApplication.instance() or QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    app.setFont(QFont(families[0] if families else 'Microsoft YaHei UI', 9))
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        widget = NeteaseWidget(Path(directory))
        widget.setStyleSheet(COMPACT_STYLE)
        widget.resize(760, 780)
        widget.show()
        app.processEvents()
        assert widget.selected_song() is None
        assert widget.tabs.currentIndex() == 2 and not widget.tabs.isTabVisible(3)
        assert widget.remember.isChecked()
        assert not widget.account_buttons['刷新歌单'].isEnabled()
        transport, modes = [], []
        widget.transportRequested.connect(transport.append)
        widget.modeRequested.connect(modes.append)
        for action in ('previous', 'toggle', 'next'):
            widget.transport_buttons[action].click()
        assert transport == ['previous', 'toggle', 'next']
        for index in range(1, 4): widget.play_mode.setCurrentIndex(index)
        assert modes == ['loop', 'single', 'shuffle']
        widget.play_mode.setCurrentIndex(0)
        session_changes = []
        widget.sessionChanged.connect(lambda: session_changes.append(True))
        # The normal account path needs no API configuration or network fixture.
        requests = []
        def record(kind, operation):
            requests.append((kind, next(operation)))
            operation.close()
        with patch.object(widget.client, 'run', side_effect=record):
            widget.begin_qr()
            assert requests[-1][0] == 'qr'
            fake_qr = dict(key='synthetic-key', url='https://music.163.com/login?codekey=synthetic-key')
            widget._completed('qr', fake_qr)
            assert not widget.qr_image.pixmap().isNull() and widget.qr_timer.isActive()
            # A non-null pixmap alone missed the original zero-height layout bug.
            for code in (801, 802):
                widget._poll_qr()
                widget._completed('qr_check', dict(code=code))
                app.processEvents()
                assert widget.qr_image.isVisible()
                assert widget.qr_image.width() >= widget.qr_image.pixmap().width()
                assert widget.qr_image.height() >= widget.qr_image.pixmap().height()
                assert widget.qr_image.parentWidget().rect().contains(widget.qr_image.geometry())
            preview = Path(__file__).resolve().parents[1] / 'preview'
            preview.mkdir(exist_ok=True)
            assert widget.grab().save(str(preview / 'netease-qr-visible.png'))
            widget._completed('qr_check', dict(code=800))
            assert widget.qr_image.isHidden() and not widget._qr_key
            widget.begin_qr()
            widget._completed('qr', fake_qr)
            widget._failed('qr_check', '确认扫码登录被网易云安全验证拦截（8821）。', False)
            assert not widget.qr_timer.isActive() and not widget._qr_key
            assert widget.qr_image.isHidden() and widget.session is None
            assert '8821' in widget.status.text() and '快照' not in widget.status.text()
            widget.begin_qr()
            widget._completed('qr', fake_qr)
            app.processEvents()
            assert widget.qr_image.isVisible() and widget.qr_image.height() == 240
            widget.qr_timer.stop()
            try:
                login_pixmap(dict(fake_qr, url='https://example.test/login?codekey=synthetic-key'))
                raise AssertionError('foreign QR origin accepted')
            except ApiError:
                pass
            fake_session = dict(api='', uid='77', nickname='测试账号', cookie='MUSIC_U=synthetic-only')
            # A disk error must not block an otherwise valid in-memory login.
            with patch.object(widget.cache, 'save_session', side_effect=OSError('synthetic disk failure')):
                before = len(session_changes)
                widget._completed('qr_check', dict(code=803, session=fake_session))
                assert len(session_changes) == before + 1
                assert widget.qr_image.isHidden()
            assert requests[-1][0] == 'collections'
            assert widget.account_buttons['刷新歌单'].isEnabled()
            assert widget.account_buttons['扫码登录网易云'].isHidden()
            assert '下次需重新登录' in widget._session_warning
            widget._completed('collections', dict(created=[dict(id='456', title='我的测试歌单')],
                                                  collected=[], warnings=[], complete=True))
            assert widget.collections.topLevelItemCount() == 1
            assert '下次需重新登录' in widget.status.text()
            widget.collections.setCurrentItem(widget.collections.topLevelItem(0))
            widget.open_collection()
            assert requests[-1][0] == 'playlist'
            before = len(session_changes)
            widget.hide()
            assert not widget.qr_timer.isActive() and not widget._qr_key
            widget.show()
            assert len(session_changes) == before  # Hiding the browser must not stop playback/downloads.
            widget.logout()
            assert len(session_changes) == before + 1
            assert widget.collections.topLevelItemCount() == 0
            assert widget.account_buttons['扫码登录网易云'].isVisible()
            from netease_music.browser_login import BrowserLogin, STATUS
            with patch.object(BrowserLogin, 'start') as start, patch.object(BrowserLogin,'request_check') as check:
                widget.remember.setChecked(False)
                widget.account_buttons['扫码登录网易云'].click()
                start.assert_called_once()
                assert widget._browser_pending and widget.browser_recheck.isVisible()
                assert '尚未收到' in widget.browser_status.text()
                for stage,text in STATUS.items():
                    widget.browser_login.status.emit(text)
                    assert widget.browser_status.text()==text and widget.status.text()==text
                    assert widget.session is None, 'a progress stage was mistaken for login success'
                widget.browser_login.status.emit(STATUS['expired'])
                widget.cancel();widget.begin_browser_login()
                assert STATUS['expired'] not in widget.browser_status.text()
                widget.browser_recheck.click();check.assert_called_once()
                assert '重新检测' in widget.status.text()
                widget._browser_completed(fake_session)
                assert widget.session == fake_session and requests[-1][0] == 'collections'
                assert not widget._browser_pending and widget.browser_recheck.isHidden()
                accepted=widget.status.text();widget.browser_login.status.emit('迟到状态');widget._browser_failed('迟到失败')
                assert widget.status.text()==accepted
                widget.logout()
                widget.begin_browser_login()
                widget.cancel()
                widget._browser_completed(fake_session)
                assert widget.session is None, 'cancelled browser result restored account'
                cancelled=widget.status.text();widget.browser_login.status.emit('迟到状态');widget._browser_failed('迟到失败')
                assert widget.status.text()==cancelled and widget.browser_recheck.isHidden()
                widget.begin_browser_login();widget.hide();widget._browser_completed(fake_session)
                assert widget.session is None and not widget._browser_pending
                widget.show()
                widget.begin_browser_login()
                widget.sessionChanged.emit()
                widget._browser_completed(fake_session)
                assert widget.session is None, 'old browser result crossed session boundary'
                widget.cancel()
                widget.begin_browser_login();widget._browser_failed('网页登录验证未通过')
                assert '重试' in widget.browser_status.text() and widget.browser_recheck.isHidden()
                widget.remember.setChecked(True)
                widget.begin_browser_login()
                with patch.object(widget.cache,'save_session') as save:
                    widget._browser_completed(fake_session)
                    save.assert_called_once_with(fake_session)
                widget._failed('collections','歌单读取403（合成）',True)
                assert requests[-1][0]=='session_recheck' and widget.session==fake_session
                widget._completed('session_recheck',dict(uid='77'))
                assert widget.session==fake_session and '验证仍有效' in widget.status.text()
                widget._failed('likes','喜欢列表读取失败（合成）',True)
                widget._failed('session_recheck','网络断开（合成）',False)
                assert widget.session==fake_session and '无法核实' in widget.status.text()
                widget._failed('collections','旧账号读取失败（合成）',True)
                widget.sessionChanged.emit()
                widget._failed('session_recheck','旧验证迟到（合成）',True)
                assert widget.session==fake_session, 'stale session recheck logged out current account'
                widget._failed('collections','已取消的验证（合成）',True)
                widget.cancel();widget._failed('session_recheck','取消后迟到（合成）',True)
                assert widget.session==fake_session and widget._session_recheck is None
                widget._failed('collections','被新请求取代的验证（合成）',True)
                widget._run('song',widget._service().song('123'))
                assert widget._session_recheck is None and widget._busy
                widget._completed('session_recheck',dict(uid='77'))
                widget._failed('session_recheck','旧请求迟到（合成）',True)
                assert widget.session==fake_session and widget._busy
                widget._failed('collections','账号可能过期（合成）',True)
                widget._failed('session_recheck','登录确实过期（合成）',True)
                assert widget.session is None and '已失效' in widget.status.text()
        bindings, plays = [], []
        widget.lyricsReady.connect(lambda *values: bindings.append(values))
        widget.playBoundRequested.connect(plays.append)
        playback, downloads = [], []
        widget.playRequested.connect(lambda tracks, start: playback.append((tracks, start)))
        widget.downloadRequested.connect(lambda tracks, only: downloads.append((tracks, only)))
        data = dict(id='123', title='测试歌曲', artists='测试歌手', unavailable=False,
                    lrc='[00:01.00]测试', lrc_status='逐句LRC可用')
        widget._completed('song', data)
        assert widget.selected_song() == dict(id='123', title='测试歌曲')
        assert bindings == []
        widget.bind_selected()
        widget.play_bound()
        assert bindings == [('123', '测试歌曲', '[00:01.00]测试')]
        assert plays == ['123']
        second = dict(id='124', title='第二首合成歌曲', artists='另一歌手', duration=123000,
                      cookie='must-not-cross-signal', url='https://example.test/private', unavailable=False)
        widget._fill_songs([dict(data, duration=120000), second])
        widget.songs.setCurrentItem(widget.songs.topLevelItem(1))
        widget.song_buttons['播放歌曲'].click()
        assert [track['id'] for track in playback[-1][0]] == ['124'] and playback[-1][1] == 0
        assert set(playback[-1][0][0]) == {'id', 'title', 'artists', 'duration', 'unavailable'}
        widget.song_buttons['播放歌单'].click()
        assert [track['id'] for track in playback[-1][0]] == ['123', '124'] and playback[-1][1] == 1
        widget.songs.itemDoubleClicked.emit(widget.songs.topLevelItem(1), 0)
        assert len(playback[-1][0]) == 1 and playback[-1][0][0]['id'] == '124'
        widget.songs.topLevelItem(0).setSelected(True)
        widget.songs.topLevelItem(1).setSelected(True)
        widget.song_buttons['下载歌曲＋LRC'].click()
        assert [track['id'] for track in downloads[-1][0]] == ['123', '124'] and downloads[-1][1] is False
        widget.song_buttons['只保存LRC'].click()
        assert downloads[-1][1] is True
        assert all('cookie' not in track and 'url' not in track for track in downloads[-1][0])
        many = [dict(id=str(1000+i), title=f'合成歌曲{i}', artists='', duration=1000) for i in range(101)]
        widget._fill_songs(many)
        widget.songs.selectAll()
        before_downloads = len(downloads)
        widget.download_songs()
        assert len(downloads) == before_downloads and '100' in widget.status.text()
        widget._fill_songs(many[:21]);widget.songs.selectAll()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            widget.download_songs()
        assert len(downloads) == before_downloads
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            widget.download_songs(True)
        assert len(downloads[-1][0]) == 21 and downloads[-1][1] is True
        before_downloads = len(downloads)
        def changed_while_confirming(*args, **kwargs):
            widget.sessionChanged.emit()
            return QMessageBox.StandardButton.Yes
        with patch.object(QMessageBox, 'question', side_effect=changed_while_confirming):
            widget.download_songs(False)
        assert len(downloads) == before_downloads and '账号或连接已变化' in widget.status.text()
        widget.set_playback_status('当前音源：试听 30 秒')
        assert '试听' in widget.status.text()
        widget._completed('playlist', dict(id='456', title='测试歌单', tracks=[data], total=2,
                                           count=1, complete=False, warnings=['缺少1首']))
        assert '部分结果' in widget.status.text()
        playlist_downloads = []
        widget.playlistDownloadRequested.connect(playlist_downloads.append)
        widget.download_playlist_button.click()
        assert playlist_downloads == ['456']
        widget._current_playlist['download_source'] = 'likes'
        widget.download_playlist_button.click()
        assert playlist_downloads[-1] == 'likes', 'liked user ID was mistaken for a playlist ID'
        widget._current_playlist.pop('download_source')
        assert widget.snapshot_list.count() == 1
        app.processEvents()
        assert widget.width() <= 760, 'song action rows made the page wider than its host'
        preview = Path(__file__).resolve().parents[1] / 'preview'
        preview.mkdir(exist_ok=True)
        assert widget.grab().save(str(preview / 'netease-playback-page.png'))
        with patch.object(widget.client, 'cancel') as cancel:
            widget.snapshot_list.setCurrentRow(0)
            widget.open_snapshot()
            cancel.assert_called_once()
        widget.base = 'https://api.example.test'
        widget.trust.setChecked(True)
        with patch.object(widget.cache, 'clear_private', side_effect=OSError('isolated')), \
             patch.object(widget.client, 'run') as run:
            widget.begin_qr()
            run.assert_not_called()
            assert '停止扫码' in widget.status.text()
            widget.logout()
            widget.begin_qr()
            run.assert_not_called()
        widget.logout()
        assert widget.selected_song() is None
        widget.api_input.setText('')
        before = len(session_changes)
        widget.save_api()
        assert widget.base == '' and len(session_changes) >= before + 1
        widget.shutdown()
        widget.shutdown()
        widget.close()
        app.processEvents()
    print('NetEase offscreen smoke OK: playback/playlist/download signals, bounded multi-select, metadata-only, '
          'session changes, hide preserves playback, direct QR, automatic playlists, exact binding, cleanup')


if __name__ == '__main__':
    main()
