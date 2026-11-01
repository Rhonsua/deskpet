"""Bounded, pure-text lyric timelines. Positive LRC offsets advance lyrics."""
from bisect import bisect_right
from dataclasses import dataclass
import re

MAX_TEXT = 512_000
_STAMP = re.compile(r'\[(\d{1,4}):(\d{2})(?:[.:](\d{1,3}))?\]')
_SRT = re.compile(r'(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*'
                  r'(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})')
_META = re.compile(r'^\[(?:ar|al|ti|au|by|re|ve|length|offset):[^\]]*\]\s*$', re.I)


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int | None
    text: str


@dataclass(frozen=True)
class Lyrics:
    cues: tuple[Cue, ...]
    starts: tuple[int, ...]
    plain_text: str

    @property
    def timed(self):
        return bool(self.cues)

    def at(self, position_ms):
        index = bisect_right(self.starts, position_ms) - 1
        if index < 0:
            return ''
        cue = self.cues[index]
        if cue.end_ms is not None and position_ms >= cue.end_ms:
            return ''
        return cue.text


def _validated(text):
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise ValueError('歌词文本最多 512000 字符。')
    return text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n').replace('\x00', '')


def parse_lrc(text):
    text = _validated(text)
    offsets = re.findall(r'\[offset:\s*([+-]?\d+)\s*\]', text, re.I)
    offset = int(offsets[-1]) if offsets else 0
    if abs(offset) > 24 * 3600 * 1000:
        raise ValueError('LRC offset 超过 24 小时。')
    grouped = {}
    plain = []
    for line in text.splitlines():
        # Only leading timestamps are line tags; inline markup remains plain text.
        rest = line.strip()
        stamps = []
        while (match := _STAMP.match(rest)):
            minute, second, fraction = match.groups()
            if int(second) >= 60:
                break
            stamps.append((int(minute) * 60 + int(second)) * 1000
                          + int((fraction or '0').ljust(3, '0')) - offset)
            rest = rest[match.end():]
        content = rest.strip()
        if stamps:
            for stamp in stamps:
                lines = grouped.setdefault(stamp, {})
                if content:
                    lines.setdefault(content, None)
        elif content and not _META.fullmatch(content):
            plain.append(content)
    cues = tuple(Cue(start, None, '\n'.join(lines)) for start, lines in sorted(grouped.items()))
    return Lyrics(cues, tuple(cue.start_ms for cue in cues), '\n'.join(plain) if not cues else '\n'.join(cue.text for cue in cues))


def parse_srt(text):
    text = _validated(text)
    cues = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines.pop(0)
        if not lines:
            continue
        match = _SRT.fullmatch(lines[0].strip())
        if not match:
            continue
        values = list(map(int, match.groups()))
        if any(values[index] >= 60 for index in (1, 2, 5, 6)):
            continue
        start = ((values[0] * 60 + values[1]) * 60 + values[2]) * 1000 + values[3]
        end = ((values[4] * 60 + values[5]) * 60 + values[6]) * 1000 + values[7]
        if end <= start:
            continue
        cues.append(Cue(start, end, '\n'.join(lines[1:]).strip()))
    cues = tuple(sorted(set(cues), key=lambda cue: (cue.start_ms, cue.end_ms, cue.text)))
    if not cues and text.strip():
        raise ValueError('SRT 没有可用的时间轴，请检查时间格式。')
    return Lyrics(cues, tuple(cue.start_ms for cue in cues), '\n'.join(cue.text for cue in cues))


def parse(text, format='lrc'):
    return parse_srt(text) if format.lower() == 'srt' else parse_lrc(text)
