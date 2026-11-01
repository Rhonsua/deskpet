"""Optional, isolated NetEase metadata, lyrics and collection browser."""

def __getattr__(name):
    if name == 'NeteaseWidget':
        from .widget import NeteaseWidget
        return NeteaseWidget
    raise AttributeError(name)

__all__ = ['NeteaseWidget']
