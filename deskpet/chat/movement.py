"""Explicit vertical repositioning, separate from passive smoke teleportation."""
from PySide6.QtCore import QPropertyAnimation, QPoint, QEasingCurve
from deskpet.pet.behavior import Action
from deskpet.animation.activity_area import roaming_bounds, roaming_allowed


def stop_move(pet):
    animation=getattr(pet,'chat_move_animation',None)
    if animation is not None:
        animation.stop();animation.deleteLater();pet.chat_move_animation=None
        pet.behavior.layers=[a for a in pet.behavior.layers if a.name!='move']
        pet.save_position();pet.update()


def move_vertical(pet,direction):
    if (pet.behavior.mode not in ('idle','listen') or pet.playing or pet.dock_edge
            or pet.behavior.layers):return False
    bounds=roaming_bounds(pet)
    if not roaming_allowed(pet,bounds):return False
    bottom=max(bounds.top(),bounds.bottom()+1-pet.height())
    target=max(bounds.top(),min(bottom,pet.y()+round(direction*80*pet.scale)))
    if target==pet.y():return False
    animation=QPropertyAnimation(pet,b'pos',pet)
    animation.setDuration(650);animation.setStartValue(pet.pos())
    animation.setEndValue(QPoint(pet.x(),target))
    animation.setEasingCurve(QEasingCurve.Type.InOutSine)
    pet.behavior.layers.append(Action('move',None))
    pet.chat_move_animation=animation
    animation.finished.connect(lambda:stop_move(pet))
    animation.start();return True
