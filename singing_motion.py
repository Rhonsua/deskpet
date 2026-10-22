"""Three directional singing poses with independent, continuous leg deformation."""
import math
from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QBitmap, QImage, QPainter, QRegion


def singing_pose(seconds):
    yaw = math.sin(seconds * math.tau / 4.8)
    if yaw < -0.45:
        return 'sing-left', yaw + 0.7
    if yaw > 0.45:
        return 'sing-right', yaw - 0.7
    return 'sing-front', yaw


def leg_offset(seconds, fraction, side, scale):
    phase = seconds * 5 + side * math.pi
    weight = fraction * fraction * (3 - 2 * fraction)
    return (math.sin(phase) * 3.2 * scale * weight,
            -max(0, math.sin(phase)) * 2.4 * scale * weight)


class SingingRig:
    def __init__(self, pixmap, mask):
        self.pixmap = pixmap
        self.mask = mask
        self.hem = round(pixmap.height() * 0.64)
        self.upper = QRect(0, 0, pixmap.width(), self.hem)
        self.splits = []
        middle = pixmap.width() // 2
        image = pixmap.toImage()
        for y in range(self.hem, pixmap.height(), 4):
            height = min(4, pixmap.height() - y)
            runs, start = [], None
            for x in range(pixmap.width() + 1):
                solid = x < pixmap.width() and any(image.pixelColor(x, row).alpha() >= 128
                                                  for row in range(y, y + height))
                if solid and start is None:
                    start = x
                elif not solid and start is not None:
                    if x - start >= 3:
                        runs.append((start, x))
                    start = None
            gaps = [(a[1] + b[0]) // 2 for a, b in zip(runs, runs[1:])]
            if gaps:
                middle = min(gaps, key=lambda x: abs(x - middle))
            self.splits.extend([middle] * height)
        self.padding = 8
        self.surface = QImage(pixmap.width() + self.padding * 2,
                              pixmap.height() + self.padding * 2,
                              QImage.Format.Format_ARGB32_Premultiplied)

    def draw(self, painter, seconds, scale, beat=None):
        # Rasterize continuous source sampling into complete destination rows.
        # Transforming/clipping many antialiased bands separately makes their
        # fractional edges partially transparent, even inside an opaque leg.
        # Compose in local pixel space first, then transform the finished image
        # once with the outer body transform.
        self.surface.fill(Qt.GlobalColor.transparent)
        local = QPainter(self.surface)
        local.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pad = self.padding
        local.drawPixmap(QPoint(pad, pad), self.pixmap, self.upper)
        span = max(1, self.pixmap.height() - self.hem)
        for side in (0, 1):
            phase = seconds * 5 + side * math.pi
            horizontal = math.sin(phase) * 3.2 * scale
            lift = max(0, math.sin(phase)) * 2.4 * scale
            from music_tools.clock import beat_values
            synced = beat_values(beat)
            if synced is not None:
                index, beat_phase = synced
                pulse = math.sin(math.pi * beat_phase) ** 2 if index % 2 == side else 0
                horizontal, lift = (1 if side else -1) * pulse * 2.2 * scale, pulse * 3 * scale
            for y in range(self.hem, self.pixmap.height()):
                destination = y + 0.5 - self.hem
                source = destination
                # Invert y = source - lift*smoothstep(source/span).
                # The derivative stays positive for the supported pet scales.
                for _ in range(3):
                    fraction = max(0, min(1, source / span))
                    weight = fraction * fraction * (3 - 2 * fraction)
                    derivative = 1 - lift * 6 * fraction * (1 - fraction) / span
                    source -= (source - lift * weight - destination) / derivative
                if source >= span:
                    continue
                fraction = source / span
                dx = horizontal * fraction * fraction * (3 - 2 * fraction)
                split = self.splits[min(len(self.splits) - 1, int(source))]
                left, width = (0, split) if side == 0 else (split, self.pixmap.width() - split)
                local.drawPixmap(QRectF(pad + left + dx, pad + y, width, 1), self.pixmap,
                                 QRectF(left, self.hem + source - .5, width, 1))
        local.end()
        painter.drawImage(QPoint(-pad, -pad), self.surface)
        # Derive hit testing from the same completed pixels rather than a union
        # of rounded strip transforms, so it follows the displayed feet.
        mask = QBitmap.fromImage(self.surface.createAlphaMask())
        return QRegion(mask).translated(-pad, -pad)
