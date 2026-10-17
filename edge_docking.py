"""Screen-relative docking geometry; coordinates support negative monitor origins."""
from PySide6.QtCore import QPoint


EDGES = ('left', 'right', 'top', 'bottom')


def clamp_position(point, size, bounds):
    return QPoint(max(bounds.left(), min(point.x(), bounds.right() + 1 - size.width())),
                  max(bounds.top(), min(point.y(), bounds.bottom() + 1 - size.height())))


def dock_position(point, size, bounds, edge):
    point = clamp_position(point, size, bounds)
    if edge == 'left':
        point.setX(bounds.left())
    elif edge == 'right':
        point.setX(bounds.right() + 1 - size.width())
    elif edge == 'top':
        point.setY(bounds.top())
    elif edge == 'bottom':
        point.setY(bounds.bottom() + 1 - size.height())
    return point


def nearest_edge(point, size, bounds, threshold=32):
    gaps = (abs(point.x() - bounds.left()),
            abs(bounds.right() + 1 - point.x() - size.width()),
            abs(point.y() - bounds.top()),
            abs(bounds.bottom() + 1 - point.y() - size.height()))
    index = min(range(4), key=gaps.__getitem__)
    return EDGES[index] if gaps[index] <= threshold else ''
