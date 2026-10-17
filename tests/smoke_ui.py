"""Headless widget initialization and rendering check; uses disposable settings."""
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout
from main import Pet


class TestStartup:
    supported = True
    active = False
    fail = False

    def enabled(self):
        return self.active

    def set_enabled(self, enabled):
        if self.fail:
            raise OSError('测试：写入失败')
        self.active = enabled


def dispose(pet):
    pet.timer.stop()
    pet.panel.progress_timer.stop()
    pet.panel.audio_router.poll.stop()
    pet.panel.player.stop()
    pet.tray.hide()
    pet.toolbar.hide()
    pet.bubble.hide()
    pet.panel.store.close()
    pet.panel.hide()
    pet.hide()

with tempfile.TemporaryDirectory() as scratch, ExitStack() as cleanup:
    os.environ['LOCALAPPDATA'] = scratch
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, scratch)
    app = QApplication([])
    font_id = QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    families = QFontDatabase.applicationFontFamilies(font_id)
    app.setFont(QFont(families[0] if families else 'Microsoft YaHei UI', 9))
    app.setApplicationName('TianyiPetSmoke')
    for filename in ('tianyi-simple-v3-costume.png', 'tianyi-refined-v3-smooth.png'):
        source = QImage(str(Path(__file__).resolve().parents[1] / 'assets' / 'character' / filename))
        assert not source.isNull(), filename
        assert source.hasAlphaChannel(), filename
        assert source.pixelColor(0, 0).alpha() == 0, filename
    startup = TestStartup()
    pet = Pet(data_dir=Path(scratch) / 'data', startup=startup,
              settings=QSettings(str(Path(scratch) / 'settings.ini'), QSettings.Format.IniFormat))
    cleanup.callback(dispose, pet)
    assert pet.variant == 'refined'
    assert not pet.panel.isVisible()
    assert set(('idle', 'blink', 'happy', 'eat', 'lift', 'sleep', 'phone')).issubset(pet.frames)
    pet.panel.show()
    app.processEvents()
    assert pet.panel.list.count() == 0
    assert '等级 1' in pet.panel.growth.text()
    pet.panel.feed('小包子')
    assert pet.panel.store.pet()['notes'] == 12
    assert pet.panel.store.pet()['hunger'] == 85
    output = Path(__file__).resolve().parents[1] / 'preview'
    output.mkdir(exist_ok=True)
    assert pet.grab().save(str(output / 'pet.png'))
    assert pet.panel.grab().save(str(output / 'panel.png'))
    pet.panel.tabs.setCurrentIndex(1)
    app.processEvents()
    assert pet.panel.grab().save(str(output / 'companion.png'))
    pet.panel.tabs.setCurrentIndex(2)
    app.processEvents()
    assert pet.panel.grab().save(str(output / 'settings.png'))
    pet.toolbar.page('home')
    pet.toolbar.show()
    app.processEvents()
    assert pet.toolbar.grab().save(str(output / 'toolbar.png'))
    pet.toolbar.hide()
    pet.panel.startup_toggle.setChecked(True)
    assert startup.active
    pet.panel.startup_toggle.setChecked(False)
    assert not startup.active
    startup.fail = True
    pet.panel.startup_toggle.setChecked(True)
    assert not pet.panel.startup_toggle.isChecked()
    startup.fail = False
    pet.set_variant('simple')
    app.processEvents()
    assert pet.grab().save(str(output / 'pet-simple.png'))
    pet.set_variant('refined')
    app.processEvents()
    assert pet.grab().save(str(output / 'pet-refined.png'))
    comparison = QWidget()
    comparison.setStyleSheet('QWidget { background: #F2F6FA; color: #294C66; font-size: 14px; }')
    comparison_layout = QHBoxLayout(comparison)
    comparison_layout.setContentsMargins(24, 20, 24, 20)
    comparison_layout.setSpacing(20)
    for variant, caption in [('simple', 'A · 圆润 Q 版 / V3公式服'), ('refined', 'B · 精致 Q 版 / V3公式服')]:
        pet.set_variant(variant)
        app.processEvents()
        column = QVBoxLayout()
        heading = QLabel(caption)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(heading)
        image = QLabel()
        image.setPixmap(pet.grab())
        column.addWidget(image)
        comparison_layout.addLayout(column)
    comparison.show()
    app.processEvents()
    assert comparison.grab().save(str(output / 'styles-comparison.png'))
    comparison.hide()
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint
    pet.set_variant('refined')
    # A feeding action deliberately cannot be interrupted by a head pat.
    for _ in range(70):
        if pet.action != 'eat':
            break
        QTest.qWait(50)
    QTest.mouseClick(pet, Qt.MouseButton.LeftButton, pos=QPoint(pet.width() // 2, 90))
    QTest.qWait(350)
    assert pet.action == 'happy'
    QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=QPoint(pet.width() // 2, 90))
    QTest.qWait(330)
    assert pet.dragging
    QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=QPoint(pet.width() // 2, 90))
    assert pet.action == 'land' and not pet.dragging
    pet.toggle_sleep()
    assert pet.sleeping
    app.processEvents()
    assert pet.grab().save(str(output / 'pet-sleep.png'))
    sleep_region = pet.hit_region.boundingRect()
    assert sleep_region.width() > sleep_region.height()
    pet.panel.state_changed(pet.panel.player.PlaybackState.PlayingState)
    assert pet.sleeping, 'music must not wake the sleeping pet'
    pet.toggle_phone()
    assert pet.using_phone and not pet.sleeping
    app.processEvents()
    assert pet.grab().save(str(output / 'pet-phone.png'))
    pet.toggle_sleep()
    assert pet.sleeping and not pet.using_phone
    pet.touch()
    assert not pet.sleeping and not pet.using_phone
    pet.timer.stop()
    pet.panel.progress_timer.stop()
    pet.panel.player.stop()
    pet.tray.hide()
    pet.toolbar.hide()
    pet.bubble.hide()
    pet.panel.store.close()
    pet.panel.hide()
    pet.hide()
    print('PASS: widget initialization, feeding, transparent pet and panel rendering')
