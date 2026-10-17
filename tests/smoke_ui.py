"""Headless widget initialization and rendering check; uses disposable settings."""
import os
import sys
import tempfile
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QFontDatabase, QImage
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout
from main import Pet

with tempfile.TemporaryDirectory() as scratch:
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
    pet = Pet(data_dir=Path(scratch) / 'data')
    assert pet.variant == 'refined'
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
    pet.timer.stop()
    pet.panel.progress_timer.stop()
    pet.panel.player.stop()
    pet.tray.hide()
    pet.panel.store.close()
    pet.panel.hide()
    pet.hide()
    print('PASS: widget initialization, feeding, transparent pet and panel rendering')
