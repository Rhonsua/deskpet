"""One read-only playback snapshot; never starts a player or invents progress."""
from dataclasses import dataclass
import math
from pathlib import Path
import time
from urllib.parse import urlsplit, parse_qs
from deskpet.music.players.bilibili_links import video_url


@dataclass(frozen=True)
class PlaybackSnapshot:
    source_key: str = ''
    title: str = ''
    position_ms: int = 0
    duration_ms: int = 0
    playing: bool = False
    rate: float = 1.0
    valid: bool = False


def number(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def bilibili_key(url):
    parsed = urlsplit(video_url(url))
    return 'bilibili:' + parsed.path.rstrip('/').split('/')[-1] + ':' + parse_qs(parsed.query).get('p', ['1'])[0]


def playback_snapshot(panel, now=None):
    now = time.monotonic() if now is None else now
    if panel.playback_source in ('netease', 'kugou'):
        cloud = panel.cloud_player
        if cloud is None or not cloud.current:
            return PlaybackSnapshot()
        key, title = panel.playback_source + ':' + cloud.current['id'], cloud.current['title']
        player, engine = panel._player, panel.engine
        if player is None:
            return PlaybackSnapshot(key, title)
        values = player.values
        valid = bool(cloud.media_ready and engine and engine.ready and 0 <= now - engine.last_report <= 3
                     and not values.get('error') and values.get('status') in (2, 3, 4, 5, 6))
        return PlaybackSnapshot(key, title,
            max(0, round(number(values.get('position'))) + cloud.trial_offset),
            max(0, round(number(values.get('duration'))) + cloud.trial_offset),
            valid and values.get('state') == 1, max(.1, min(8, number(values.get('playback_rate'), 1))), valid)
    if panel.playback_source == 'web':
        web = panel.bilibili
        if not web.active or not web.current_url:
            return PlaybackSnapshot()
        try:
            key = bilibili_key(web.current_url)
        except ValueError:
            return PlaybackSnapshot()
        metrics = web.metrics
        valid = bool(metrics and 0 <= now - web.last_report <= 3 and not metrics.get('error')
                     and not metrics.get('seeking') and number(metrics.get('ready_state'), 2) >= 2)
        return PlaybackSnapshot(key, web.title.text(), max(0, round(number(metrics.get('position')) * 1000)),
            max(0, round(number(metrics.get('duration')) * 1000)), bool(web.playing and valid),
            max(.1, min(8, number(metrics.get('playback_rate'), 1))), valid)
    if panel.playback_source != 'local':
        return PlaybackSnapshot()
    path = panel.current_path()
    if not path:
        return PlaybackSnapshot()
    key = 'local:' + str(Path(path).absolute())
    player = panel._player
    if player is None:
        return PlaybackSnapshot(key, Path(path).name)
    values = player.values
    engine = panel.engine
    valid = bool(engine and engine.ready and 0 <= now - engine.last_report <= 3
                 and not values.get('error') and values.get('status') in (2, 3, 4, 5, 6))
    return PlaybackSnapshot(key, Path(path).name, max(0, round(number(values.get('position')))),
        max(0, round(number(values.get('duration')))), valid and values.get('state') == 1,
        max(.1, min(8, number(values.get('playback_rate'), 1))), valid)


def beat_values(beat):
    if beat is None:
        return None
    get = beat.get if isinstance(beat, dict) else lambda key, default=None: getattr(beat, key, default)
    if not get('available', False):
        return None
    phase = number(get('phase'), -1)
    index = number(get('beat_index'), -1)
    if index < 0 or not 0 <= phase < 1:
        return None
    return int(index), phase


def singing_beat_time(seconds, beat):
    """Map eight music beats to one authored 4.8-second turn, without a free clock."""
    values = beat_values(beat)
    return ((values[0] % 8) + values[1]) * .6 if values else seconds


def apply_music_beat(parameters, beat):
    """One playback phase drives feet, head, torso and the free singing arm.

    Keep the microphone arm, facial animation and pose visibility untouched.
    Head/body yaw is selected by the caller using singing_beat_time.
    """
    values = beat_values(beat)
    if values is None:
        return dict(parameters)
    index, phase = values
    lift = math.sin(math.pi * phase) ** 2
    side = index % 2
    result = dict(parameters)
    result['ParamLegLSwing'] = 22 * lift if side == 0 else 0
    result['ParamLegRSwing'] = 22 * lift if side == 1 else 0
    weight = (-1 if side == 0 else 1) * lift
    result['ParamBodyAngleZ'] = max(-10, min(10,
        4 * weight - parameters.get('ParamBodyAngleX', 0) * 2 / 3))
    sway = math.sin(math.pi * (side + phase))
    # Dip on each beat, recover between beats. Two beats form one gentle sway.
    nod = .5 + .5 * math.cos(math.tau * phase)
    result['ParamAngleY'] = -5 * nod
    result['ParamAngleZ'] = 5 * sway
    result['ParamSingArm'] = 18 * sway
    return result
