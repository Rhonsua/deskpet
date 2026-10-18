"""Check opaque leg interiors under motion, scale and outer body rotation.

The former four-pixel strip renderer produces alpha as low as 192 at these
interior samples. This checks rendered pixels, not the chosen implementation.
"""
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import QApplication
from singing_motion import SingingRig, leg_offset


app = QApplication([])
output = Path(__file__).resolve().parents[1] / 'preview'
output.mkdir(exist_ok=True)
samples = 0
for scale in (.75, 1, 1.5):
    source = QImage(round(120 * scale), round(200 * scale), QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(Qt.GlobalColor.transparent)
    painter = QPainter(source)
    painter.scale(scale, scale)
    painter.fillRect(10, 10, 100, 118, QColor('#61b7d4'))
    painter.fillRect(22, 120, 20, 76, QColor('#facfbd'))
    painter.fillRect(78, 120, 20, 76, QColor('#425275'))
    painter.end()
    pixmap = QPixmap.fromImage(source)
    rig = SingingRig(pixmap, QRegion(pixmap.mask()))
    for moment in (.12, .3, .65, .95):
        for angle in (0, -1.4, 1.4):
            frame = QImage(source.width() + 60, source.height() + 60, source.format())
            frame.fill(Qt.GlobalColor.transparent)
            painter = QPainter(frame)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            transform = QTransform().translate(30, 20).rotate(angle)
            painter.setTransform(transform)
            mask = rig.draw(painter, moment, scale)
            painter.end()
            for y in range(rig.hem + 2, round(188 * scale)):
                fraction = (y - rig.hem) / (source.height() - rig.hem)
                for side, center in enumerate((32, 88)):
                    dx, dy = leg_offset(moment, fraction, side, scale)
                    local = QPointF(center * scale + dx, y + dy)
                    point = transform.map(local).toPoint()
                    alpha = frame.pixelColor(point).alpha()
                    assert alpha >= 250, (scale, moment, angle, y, side, alpha)
                    assert mask.contains(local.toPoint()), 'visible leg interior must remain interactive'
                    samples += 1
            if scale == 1 and moment == .3 and angle == 0:
                frame.save(str(output / 'singing-seam-regression.png'))
    still = QImage(source.size(), source.format())
    moved = QImage(source.size(), source.format())
    for image, moment in ((still, 0), (moved, .3)):
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        rig.draw(painter, moment, scale)
        painter.end()
    assert still.copy(0, 0, source.width(), rig.hem) == moved.copy(0, 0, source.width(), rig.hem)
    assert still != moved, 'the legs must keep moving'
print(f'PASS: {samples} opaque leg samples; three scales, four phases, body rotation, hit areas and stable upper body')
