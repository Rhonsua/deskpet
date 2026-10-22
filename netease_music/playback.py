"""Opt-in cloud queue using the existing isolated audio device/player."""
from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer

from music_tools.library import PlaybackQueue, MODES
from netease_music.client import Client
from netease_music.links import music_id


def clean_tracks(tracks):
    result, seen = [], set()
    for track in list(tracks)[:20000]:
        item_id = music_id(track.get('id'))
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(dict(id=item_id, title=str(track.get('title', item_id))[:1000],
                           artists=str(track.get('artists', ''))[:1000]))
    return result


class NeteasePlayback(QObject):
    def __init__(self, companion, cloud):
        super().__init__(companion)
        self.companion, self.cloud = companion, cloud
        self.panel = companion.pet.panel
        self.queue = PlaybackQueue(self.panel.queue.mode)
        self.tracks = []
        self.current = None
        self.loading = self.media_ready = self.want_play = False
        self.trial = False
        self.trial_offset = 0
        self.failures = set()
        self.generation = 0
        self.client = Client(self)
        self.lyric_client = Client(self)
        self.client.completed.connect(self._resolved)
        self.client.failed.connect(self._failed)
        self.lyric_client.completed.connect(self._lyrics)
        self.lyric_client.failed.connect(self._lyric_failed)
        self.advance_timer = QTimer(self)
        self.advance_timer.setSingleShot(True)
        self.advance_timer.timeout.connect(self._skip_failed)
        cloud.sessionChanged.connect(self.deactivate)

    @property
    def active(self):
        return self.panel.playback_source == 'netease'

    def status(self, message):
        self.cloud.set_playback_status(message)
        if self.active:
            self.panel.status.setText(message)

    def play(self, tracks, index=0):
        try:
            prepared = clean_tracks(tracks)
        except (ValueError, AttributeError, TypeError):
            self.status('歌曲列表无效，请重新读取歌单。')
            return
        if not prepared:
            self.status('请先选择歌曲或打开歌单。')
            return
        self.deactivate()
        if self.panel.bilibili.active:
            self.panel.bilibili.stop()
        self.panel._restore_request = None
        self.panel.playback_source = 'netease'
        self.panel.last_position = self.panel.last_source = None
        self.tracks = prepared
        self.queue.mode = self.panel.queue.mode
        self.queue.reset([item['id'] for item in prepared], max(0, min(index, len(prepared)-1)))
        self.failures.clear()
        self.want_play = True
        self._load()

    def _load(self):
        self.generation += 1
        self.companion.preparation.cancel()
        self.advance_timer.stop()
        self.client.cancel()
        self.lyric_client.cancel()
        if not self.active or not 0 <= self.queue.index < len(self.tracks):
            return
        self.current = self.tracks[self.queue.index]
        self.loading, self.media_ready = True, False
        self.trial, self.trial_offset = False, 0
        self.panel.autoplay_requested = False
        self.panel.pending_seek = None
        self.panel.last_position = self.panel.last_source = None
        self.panel.ensure_audio()
        self.panel.player.stop()
        self.panel.player.setSource(QUrl())
        self.panel.pet.playing = False
        self.panel.set_song_title(self.current['title'])
        self.panel.song_meta.setText('网易云 · ' + MODES[self.queue.mode])
        self.status('正在获取音源：' + self.current['title'])
        self.client.run('media', self.cloud._service().media(self.current['id']))

    def _resolved(self, kind, result):
        if not self.active or not self.current or result.get('id') != self.current['id']:
            return
        if result.get('unavailable') or not result.get('url'):
            self._failed(kind, result.get('reason') or '当前账号无法播放这首歌曲。', False)
            return
        from netease_music.media import validate_media_url
        try:
            url = validate_media_url(result['url'])
        except ValueError:
            self._failed(kind, '音源地址不兼容，已跳过。', False)
            return
        self.trial = bool(result.get('trial'))
        self.trial_offset = max(0, int(result.get('trial_start_ms', 0))) if self.trial else 0
        self.panel.song_meta.setText('网易云 · ' + ('试听片段 · ' if self.trial else '') + MODES[self.queue.mode])
        self.lyric_client.run('lyrics', self.cloud._service().song(self.current['id']))
        generation = self.generation
        def ready():
            if not self.active or generation != self.generation:
                return
            self.loading, self.media_ready = False, True
            self.panel.player.setSource(QUrl(url))
            if self.want_play:
                self.panel.player.play()
            self.status(('仅提供试听：' if self.trial else '音源已就绪：') + self.current['title'])
        self.companion.preparation.online(self.current, result, ready)

    def _lyrics(self, kind, result):
        if not self.active or not self.current or result.get('id') != self.current['id']:
            return
        if result.get('lrc'):
            try:
                self.companion.lyrics.import_online(result['id'], result['title'], result['lrc'],
                                                     'netease:' + result['id'])
                self.companion.tick()
            except Exception:
                self.status('歌曲可继续播放，但歌词暂时无法保存。')
        else:
            self.status(('试听中；' if self.trial else '') + result.get('lrc_status', '此曲暂无逐句歌词。'))

    def _lyric_failed(self, kind, message, expired):
        if expired:
            self.cloud._failed(kind, message, True)
        elif self.active:
            self.status('音乐继续播放；歌词获取失败，可稍后重试。')

    def _failed(self, kind, message, expired):
        if not self.active:
            return
        if expired:
            self.cloud._failed(kind, message, True)
            return
        self.loading = self.media_ready = False
        if self.current:
            self.failures.add(self.current['id'])
        self.panel.player.stop()
        self.panel.pet.playing = False
        self.status(message)
        if len(self.failures) >= min(10, len(self.tracks)):
            self.want_play = False
            self.status('多首歌曲不可播放，已停止自动尝试。请检查登录或选择其他歌曲。')
        elif self.want_play:
            self.advance_timer.start(350)

    def _skip_failed(self):
        if self.active and self.want_play:
            self.step(1, automatic=True, failed=True)

    def step(self, direction=1, automatic=False, failed=False):
        if not self.active or not self.tracks:
            return
        if not automatic:
            self.failures.clear()
        for _ in self.tracks:
            index = self.queue.advance(direction, ended=automatic and not failed)
            if index is None:
                self.want_play = False
                self.status('这个网易云歌单听完啦。')
                return
            if self.tracks[index]['id'] not in self.failures:
                self.want_play = True
                self._load()
                return
        self.want_play = False
        self.status('列表中暂时没有可播放的歌曲。')

    def toggle(self):
        if not self.active:
            return
        if self.loading:
            self.want_play = not self.want_play
            self.status('音源就绪后播放。' if self.want_play else '已暂停，音源就绪后也不会自动播放。')
        elif self.panel.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.want_play = False
            self.panel.player.pause()
        elif not self.media_ready:
            self.want_play = True
            self.failures.clear()
            self._load()
        else:
            self.want_play = True
            self.panel.player.play()

    def media_changed(self, status):
        if self.active and self.media_ready and status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.want_play:
                self.step(automatic=True)

    def audio_error(self):
        if self.active and self.media_ready:
            self._failed('audio', '网易云音频加载失败或链接已过期，正在尝试下一首。', False)

    def set_mode(self, mode):
        self.queue.mode, self.queue.bag = mode, []
        if self.active:
            self.panel.song_meta.setText('网易云 · ' + ('试听片段 · ' if self.trial else '') + MODES[mode])

    def deactivate(self):
        self.generation += 1
        if self.active:
            self.companion.preparation.cancel()
        self.advance_timer.stop()
        self.client.cancel()
        self.lyric_client.cancel()
        self.want_play = self.loading = self.media_ready = False
        self.current = None
        if self.active:
            self.panel.playback_source = 'local'
            if self.panel._player is not None:
                self.panel.player.stop()
                self.panel.player.setSource(QUrl())
            self.panel.pet.playing = False
            self.panel.last_position = self.panel.last_source = None
            self.panel.set_song_title('网易云播放已停止')
