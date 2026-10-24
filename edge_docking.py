"""Screen-relative docking geometry; coordinates support negative monitor origins."""
from PySide6.QtCore import QPoint


EDGES = ('left', 'right', 'top', 'bottom')


def dock_ease(reveal):
    """Smooth endpoints without overshoot or changing transition duration."""
    value = max(0.0, min(1.0, 1.0 - reveal))
    return value * value * (3.0 - 2.0 * value)


def keep_drag_docked(point, size, bounds, edge, pointer_bounds, scale=1):
    """Stay latched until a deliberate inward pull; entering another screen wins."""
    return (bounds == pointer_bounds and
            edge_gap(point, size, bounds, edge) < round(36 * scale))


def edge_gap(point, size, bounds, edge):
    """Signed room inside an edge; negative means the requested window crossed it."""
    return {'left': point.x() - bounds.left(),
            'right': bounds.right() + 1 - point.x() - size.width(),
            'top': point.y() - bounds.top(),
            'bottom': bounds.bottom() + 1 - point.y() - size.height()}[edge]


def pushed_edge(point, size, bounds, threshold=24):
    edge = min(EDGES, key=lambda value: edge_gap(point, size, bounds, value))
    return edge if edge_gap(point, size, bounds, edge) <= -threshold else ''


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
