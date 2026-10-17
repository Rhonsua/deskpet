"""第一阶段：透明桌宠窗口与本地 MP3 播放验证。"""
import math
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, QUrl, QStandardPaths, QLockFile
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMenu,
    QMessageBox, QPushButton, QSlider, QStyle, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)


def clock(ms):
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02}:{seconds % 60:02}"


from pet_store import PetStore, FOODS
from visual_style import build, update_cover, sprite_bounds


class MusicPanel(QWidget):
    def __init__(self, pet, data_dir=None):
        super().__init__()
        self.pet = pet
        self.settings = QSettings("TianyiPet", "Prototype")
        data_dir = Path(data_dir) if data_dir else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        data_dir.mkdir(parents=True, exist_ok=True)
        self.store = PetStore(data_dir / "pet.db")
        self.last_tick = time.monotonic()
        self.last_position = None
        self.last_source = None
        self.setWindowTitle("天依音乐 · 第一阶段原型")
        self.resize(460, 440)
        self.paths = []
        self.audio = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        build(self)
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.sample)
        self.progress_timer.start(1000)
        self.player.durationChanged.connect(lambda n: self.seek.setRange(0, n))
        self.player.positionChanged.connect(self.position_changed)
        self.player.playbackStateChanged.connect(self.state_changed)
        self.player.mediaStatusChanged.connect(self.media_changed)
        self.player.errorOccurred.connect(lambda *_: self.status.setText("播放失败：" + self.player.errorString()))
        self.list.itemDoubleClicked.connect(lambda _: self.play_row(self.list.currentRow()))
        self.setAcceptDrops(True)
        saved = self.settings.value("paths", [])
        self.import_paths(saved if isinstance(saved, list) else [saved])
        self.refresh_growth()

    def seek_to(self):
        self.last_position = None
        self.player.setPosition(self.seek.value())

    def refresh_growth(self):
        pet = self.store.pet()
        stats = self.store.stats()
        self.growth.setText(
            f"等级 {pet['level']} · 经验 {pet['xp']} · 音符 {pet['notes']}\n"
            f"饱食度 {pet['hunger']}/100 · 心情 {pet['mood']}/100\n"
            f"听歌：今日 {clock(int(stats['today'] * 1000))} / "
            f"本周 {clock(int(stats['week'] * 1000))} / 累计 {clock(int(stats['total'] * 1000))}"
        )
        self.experience.setRange(0, 50 + 20 * (pet['level'] - 1))
        self.experience.setValue(pet['xp'])

    def feed(self, food):
        success, message = self.store.feed(food)
        self.status.setText(message)
        self.refresh_growth()

    def sample(self):
        now = time.monotonic()
        elapsed = now - self.last_tick
        self.last_tick = now
        position = self.player.position()
        source = self.player.source().toLocalFile()
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if 0 < elapsed <= 3:
            self.store.tick_running(elapsed)
            if (playing and source and source == self.last_source and self.last_position is not None
                    and not self.seek.isSliderDown()):
                advance = (position - self.last_position) / 1000
                if 0 < advance <= elapsed + 0.5:
                    self.store.record(source, min(elapsed, advance),
                                      self.audio.volume() > 0 and not self.audio.isMuted())
        self.last_position = position if playing else None
        self.last_source = source
        self.refresh_growth()

    def import_paths(self, paths):
        for item in paths:
            path = str(Path(item).resolve())
            if Path(path).suffix.lower() == ".mp3" and path not in self.paths:
                self.paths.append(path)
                self.list.addItem(Path(path).stem)
                self.list.item(self.list.count() - 1).setToolTip(path)
        self.list_stack.setCurrentIndex(1 if self.paths else 0)
        self.queue_label.setText(f"我的歌单 · {len(self.paths)} 首" if self.paths else "我的歌单")

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 MP3", "", "MP3 音频 (*.mp3)")
        self.import_paths(paths)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def play_row(self, row):
        if not 0 <= row < len(self.paths):
            return
        path = self.paths[row]
        if not Path(path).is_file():
            self.status.setText("文件不存在，请重新添加：" + Path(path).name)
            return
        self.list.setCurrentRow(row)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self.song_title.setText(Path(path).stem)
        self.song_meta.setText('本地 MP3 · 顺序播放')
        self.status.setText("正在播放：" + Path(path).stem)

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self.player.source().isEmpty():
            self.play_row(max(0, self.list.currentRow()))
        else:
            self.player.play()

    def step(self, direction):
        if self.paths:
            self.play_row((self.list.currentRow() + direction) % len(self.paths))

    def position_changed(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        self.time.setText(f"{clock(position)} / {clock(self.player.duration())}")

    def state_changed(self, state):
        self.last_position = None
        self.pet.playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText('暂停' if self.pet.playing else '播放')

    def media_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            row = self.list.currentRow() + 1
            if row < len(self.paths):
                self.play_row(row)

    def save(self):
        self.settings.setValue("paths", self.paths)
        self.settings.setValue("volume", self.volume.value())
        self.settings.sync()

    def closeEvent(self, event):
        self.save()
        event.accept()


class Pet(QWidget):
    def __init__(self, data_dir=None):
        super().__init__()
        self.setWindowTitle("天依桌宠")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(240, 290)
        self.playing = False
        self.sprite = QPixmap()
        self.phase = 0
        self.drag_offset = None
        self.panel = MusicPanel(self, data_dir)
        self.variant = self.panel.settings.value('visual_variant', 'refined')
        if self.panel.settings.value('appearance_revision', '') != 'refined-smooth-v1':
            self.variant = 'refined'
            self.panel.settings.setValue('appearance_revision', 'refined-smooth-v1')
        self.set_variant(self.variant)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(33)
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        menu.addAction("显示桌宠", self.restore)
        menu.addAction("音乐面板", self.panel.show)
        menu.addAction("播放 / 暂停", self.panel.toggle)
        menu.addAction("退出", QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("天依桌宠 · 右键打开菜单")
        self.tray.show()
        self.restore()

    def restore(self):
        screen = QApplication.primaryScreen().availableGeometry()
        saved = self.panel.settings.value("position")
        point = saved if isinstance(saved, QPoint) else QPoint(screen.right() - 280, screen.bottom() - 330)
        if not any(s.availableGeometry().contains(point) for s in QApplication.screens()):
            point = screen.topLeft() + QPoint(80, 80)
        self.move(point)
        self.show()

    def animate(self):
        self.phase += 0.05
        self.update()

    def set_variant(self, variant):
        self.variant = variant
        directory = Path(__file__).resolve().parent / 'assets' / 'character'
        filename = directory / ('tianyi-simple-v3-costume.png' if variant == 'simple' else 'tianyi-refined-v3-smooth.png')
        if not filename.exists():
            filename = directory / 'tianyi-master-v1.png'
        self.sprite = QPixmap(str(filename))
        if not self.sprite.isNull():
            bounds = sprite_bounds(self.sprite)
            if not bounds.isEmpty():
                self.sprite = self.sprite.copy(bounds)
        update_cover(self.panel, filename)
        self.panel.settings.setValue('visual_variant', variant)
        self.panel.appearance.blockSignals(True)
        self.panel.appearance.setCurrentIndex(0 if variant == 'simple' else 1)
        self.panel.appearance.blockSignals(False)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.sprite.isNull():
            sway = math.sin(self.phase) * (3 if self.playing else 0.6)
            bob = math.sin(self.phase * 2) * (3 if self.playing else 1)
            image = self.sprite.scaled(206, 244, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            p.translate(120, 246)
            p.rotate(sway)
            p.drawPixmap(-image.width() // 2, -image.height() + int(bob), image)
            p.resetTransform()
            return
        p.translate(math.sin(self.phase) * (4 if self.playing else 1), math.sin(self.phase * 2) * 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 24))
        p.drawEllipse(60, 247, 120, 16)
        # Temporary geometric mascot; replace with approved character frames later.
        p.setBrush(QColor("#627d94"))
        p.drawEllipse(37, 42, 65, 148)
        p.drawEllipse(138, 42, 65, 148)
        p.setBrush(QColor("#225c83"))
        p.drawRoundedRect(86, 216, 25, 38, 10, 10)
        p.drawRoundedRect(130, 216, 25, 38, 10, 10)
        p.setBrush(QColor("#69cbe2"))
        p.drawRoundedRect(67, 147, 106, 81, 26, 26)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(94, 148, 52, 61, 10, 10)
        p.setBrush(QColor("#ffe5d5"))
        p.drawEllipse(57, 53, 126, 109)
        p.setBrush(QColor("#8196a8"))
        p.drawPie(52, 27, 138, 106, 0, 180 * 16)
        p.drawEllipse(52, 58, 33, 52)
        p.drawEllipse(153, 58, 33, 52)
        p.setBrush(QColor("#5dcacb"))
        p.drawEllipse(48, 46, 28, 20)
        p.drawEllipse(165, 46, 28, 20)
        p.setPen(QPen(QColor("#34796a"), 5))
        blink = int(self.phase * 10) % 48 < 2
        for x in (96, 145):
            if blink:
                p.drawLine(x - 6, 111, x + 6, 111)
            else:
                p.drawEllipse(x - 3, 103, 6, 13)
        p.setPen(QPen(QColor("#c1757c"), 2))
        p.drawArc(110, 121, 22, 15, 180 * 16, 180 * 16)
        p.setPen(QColor("#356477"))
        p.drawText(20, 269, 200, 20, Qt.AlignmentFlag.AlignCenter, "♫ 一起听歌吧" if self.playing else "双击打开音乐面板")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None:
            point = event.globalPosition().toPoint() - self.drag_offset
            screen = QApplication.screenAt(event.globalPosition().toPoint()) or QApplication.primaryScreen()
            r = screen.availableGeometry()
            self.move(max(r.left(), min(point.x(), r.right() - self.width() + 1)),
                      max(r.top(), min(point.y(), r.bottom() - self.height() + 1)))

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        self.panel.settings.setValue("position", self.pos())

    def mouseDoubleClickEvent(self, event):
        self.panel.show()
        self.panel.raise_()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        appearance = menu.addMenu('角色外观')
        appearance.addAction('圆润 Q 版 · V3公式服', lambda: self.set_variant('simple'))
        appearance.addAction('精致 Q 版 · V3公式服', lambda: self.set_variant('refined'))
        menu.addAction("音乐面板", self.panel.show)
        menu.addAction("播放 / 暂停", self.panel.toggle)
        menu.addAction("隐藏桌宠（托盘恢复）", self.hide)
        menu.addAction("退出", QApplication.instance().quit)
        menu.exec(event.globalPos())


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setApplicationName("TianyiPet")
    app.setOrganizationName("TianyiPet")
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(data_dir / "instance.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "天依桌宠", "桌宠已经在运行，请从系统托盘打开。")
        return 0
    app.setQuitOnLastWindowClosed(False)
    pet = Pet()
    app.aboutToQuit.connect(pet.panel.save)
    app.aboutToQuit.connect(pet.panel.store.close)
    pet.panel.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
