"""Capture the real pet and foreground windows into a repeatable demo GIF."""
import io
import random
import time

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QPainter
from teleport_controller import TeleportController


def export(pet, output):
    pet.stop_roaming()
    pet.set_mode('idle')
    pet.panel.hide()
    pet.toolbar.hide()
    pet.bubble.hide()
    bounds = pet.screen_bounds()
    upper = bounds.top() + 45
    lower = min(upper + 290, bounds.bottom() + 1 - pet.height() - 45)
    assert lower > upper + 100
    x = bounds.left() + (bounds.width() - pet.width()) // 2
    pet.move(x, upper)
    pet.grab()
    origin_x = x + pet.width()/2 - 230
    origin_y = upper - 60
    width, height = 460, lower-upper+pet.height()+120
    frames = []

    def capture():
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor('#33434b'))
        painter = QPainter(image)
        painter.drawPixmap(round(pet.x()-origin_x), round(pet.y()-origin_y), pet.grab())
        if pet.effects.teleporting:
            painter.drawPixmap(round(pet.effects.x()-origin_x), round(pet.effects.y()-origin_y),
                               pet.effects.grab())
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, 'PNG')
        frames.append(Image.open(io.BytesIO(bytes(buffer.data()))).convert('RGB'))

    for destination in (lower, upper):
        for _ in range(16):
            pet.behavior.tick(.04)
            pet.phase += .04
            capture()
        # Preview only: fixed destinations and shortened wait between two demos.
        # Playback uses the actual controller, renderer, timing and movement.
        pet.teleport_controller = TeleportController(rng=random.Random(4))
        pet.last_interaction = time.monotonic()-20
        assert pet._start_teleport()
        pet.teleport_controller.destination = destination
        for _ in range(54):
            pet.tick_teleport(.04)
            pet.behavior.tick(.04)
            pet.phase += .04
            capture()
    for _ in range(16):
        pet.behavior.tick(.04)
        pet.phase += .04
        capture()
    path = output / 'teleport-live2d.gif'
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=40,
                   loop=0, optimize=False, disposal=2)
    print(f'GIF: {path} ({len(frames)} frames, 25 fps)')
