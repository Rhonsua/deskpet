"""Illustrations and attributed reading links for the offline keepsake book."""
from dataclasses import dataclass
from functools import lru_cache, partial
from hashlib import blake2s
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap


class ActivityImages(QObject):
    ready = Signal()
    decoded = Signal(str, QImage)

    def __init__(self):
        super().__init__()
        self.pixmaps = {}
        self.decoded.connect(self._store, Qt.QueuedConnection)

    def get(self, path):
        key = str(path)
        if key not in self.pixmaps:
            self.pixmaps[key] = QPixmap()
            QThreadPool.globalInstance().start(QRunnable.create(partial(self._read, key)))
        return self.pixmaps[key]

    def _read(self, path):
        self.decoded.emit(path, QImage(path))

    @Slot(str, QImage)
    def _store(self, path, image):
        self.pixmaps[path] = QPixmap.fromImage(image)
        self.ready.emit()


@lru_cache(maxsize=1)
def activity_images():
    return ActivityImages()


_DAY_STICKERS = Path(__file__).with_name('assets') / 'album-tianyi-days.webp'


@lru_cache(maxsize=512)
def page_sticker(started, key, part):
    """Keep a page's surprise even when new memories change its page number."""
    seed = f'{started}\0{key}\0{part}'.encode('utf-8')
    chance, pose, side = blake2s(seed, digest_size=3).digest()
    if key not in ('title', 'first-meeting') and chance >= 154:
        return None
    return pose % 8, bool(side & 1)


def draw_page_sticker(painter, pose, target):
    sheet = activity_images().get(_DAY_STICKERS)
    if sheet.isNull():
        return
    w, h = sheet.width() / 4, sheet.height() / 2
    row, col = divmod(pose, 4)
    painter.drawPixmap(target, sheet, QRectF(col*w, row*h, w, h))


@dataclass(frozen=True)
class PaperLink:
    title: str
    detail: str
    target: str
    stamp: str = ''


# Titles and credits follow the original publishers. Only an explicit click
# opens a URL. Remote illustrations are never fetched by the reader.
ART_FOLIO = {
    'official': (
        PaperLink('共鸣心翼', '洛天依官方 · 十三周年生日海报',
                  'https://www.bilibili.com/opus/1078300459391778817'),
        PaperLink('茉莉花', 'Haku白 设计 · T爹TID 绘制',
                  'https://www.bilibili.com/opus/337579305572229364'),
        PaperLink('洛天依纪念插画集 Vol.1', 'VSINGER 著 · 电子工业出版社',
                  'https://wap.phei.com.cn/module/goods/wssd_content.jsp?bookid=69782'),
    ),
    'fan': (
        PaperLink('向着宇宙明亮那边', '曲绘 巫烨 · 十周年同人生日会',
                  'https://www.bilibili.com/video/av598194441/'),
        PaperLink('夏忆', '曲绘 雪荷 · 百泽工作室生贺作品',
                  'https://www.bilibili.com/video/BV14D4y1S7cF/'),
        PaperLink('洛天依 Q 版表情包 2025', '星尘幻梦发布 · Q 版约稿与同人画',
                  'https://re.xcdream.com/article/635.html'),
    ),
}

_CELLS = {'bao': (0, 0), 'cassette': (1, 0), 'ticket': (0, 1), 'letter': (1, 1)}
_POSES = {
    'headpat': 'shy', 'gentle': 'shy', 'happy': 'happy', 'gaze': 'hello',
    'mouse_wave': 'hello', 'turn': 'cheer', 'level_up': 'cheer', 'sway': 'puzzled',
    'dream': 'sleepy', 'sleep': 'sleepy', 'quiet': 'sleepy', 'chat': 'hello',
}

_FIRST_ACTION = {
    'action:headpat': '这天，你第一次摸了摸天依的头。',
    'action:feed': '这天，你第一次给天依投喂了食物。',
    'action:eat': '第一次看到天依吃点心，记在这一天。',
    'action:sing': '这天，纪念集第一次记下天依拿起麦克风。',
    'action:sleep': '第一次记下天依睡觉的模样。',
    'action:mouse_wave': '第一次把天依挥手的样子收进了这本书。',
    'action:turn': '天依转了个身，纪念集第一次记下这个动作。',
    'action:happy': '第一次收下天依开心的样子。',
    'action:level_up': '第一次把天依庆祝的样子留在这页。',
}


def record_body(key, original):
    if original in ('亲自触发后收录', '亲自触发后收录。'):
        return _FIRST_ACTION.get(key, original)
    return original


def keepsake(key):
    family, _, event = key.partition(':')
    if family in ('action', 'combo', 'need'):
        if event in ('eat', 'feed', 'snack'):
            return 'bao'
        if event in ('listen', 'sing'):
            return 'cassette' if event == 'listen' else 'wings'
        return _POSES.get(event, 'letter')
    if family == 'song' or family == 'quiz' or key == 'first-quiz':
        return 'cassette'
    if key in ('first-rhythm', 'first-performance'):
        return 'wings'
    if family == 'show':
        return 'ticket'
    return 'letter'


class ScrapbookArt:
    """Decode only a visible illustration, once per book, including missing art."""
    def __init__(self, loader=None):
        self.images = {}
        self.loader = loader

    def draw(self, painter, name, target):
        sheet = name in _CELLS
        cache_key = 'stationery' if sheet else name
        if cache_key not in self.images:
            if sheet:
                path = Path(__file__).with_name('assets') / 'album-stationery.webp'
            elif name in ('jasmine','wings'):
                path = Path(__file__).with_name('assets') / ('album-' + name + '.webp')
            elif name in _POSES.values():
                from deskpet.paths import RESOURCE_ROOT
                path = RESOURCE_ROOT / 'assets/stickers/tianyi' / (name + '.webp')
            else:
                return False
            if self.loader is None:
                self.images[cache_key] = QPixmap(str(path))
            else:
                image = self.loader.get(path)
                if image.isNull():
                    return False
                self.images[cache_key] = image
        image = self.images[cache_key]
        if image.isNull():
            return False
        source = QRectF(image.rect())
        if sheet:
            col, row = _CELLS[name]
            w, h = source.width() / 2, source.height() / 2
            source = QRectF(col * w, row * h, w, h)
        scale = min(target.width() / source.width(), target.height() / source.height())
        w, h = source.width() * scale, source.height() * scale
        destination = QRectF(target.center().x() - w/2, target.center().y() - h/2, w, h)
        painter.drawPixmap(destination, image, source)
        return True
