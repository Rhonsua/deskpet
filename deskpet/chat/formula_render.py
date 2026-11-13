"""Render a work-chat formula with the bundled math font, entirely offline."""
import base64
from functools import lru_cache
from html import escape
from math import ceil, isfinite
import re


# Chat formulas need symbols and layout, not macro expansion, external content
# or arbitrary font sizes. Bound the work before handing it to the typesetter.
_UNSUPPORTED = re.compile(
    r'\\(?:[egx]?def|(?:re)?new(?:command|environment)|providecommand|DeclareMathOperator'
    r'|input|include(?:graphics)?|href|url|require|style|class|cssId|mathchoice'
    r'|rule|fontsize|genfrac|hspace|vspace|kern|mkern|mspace|skew|above|abovewithdelims)\b'
)
_DIMENSION = re.compile(r'(?<![\w.])(\d+(?:\.\d+)?)(?:em|ex|pt|px|mu|cm|mm|in)\b')


def _eligible(source):
    if not source or len(source) > 1536 or source.count('\\') > 150 or _UNSUPPORTED.search(source):
        return False
    if 'url(' in source.lower() or any(float(n) > 64 for n in _DIMENSION.findall(source)):
        return False
    depth = 0
    for token in re.findall(r'\\.|[{}]', source):
        if token == '{':
            depth += 1
        elif token == '}':
            depth -= 1
        if not 0 <= depth <= 24:
            return False
    return depth == 0


@lru_cache(maxsize=192)
def _render(source, display):
    # Neither fonts nor the Qt SVG plugin are needed at startup or for prose.
    import ziamath
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    ziamath.config.svg2 = False  # use standalone paths compatible with Qt SVG
    equation = ziamath.Latex(source, size=19 if display else 16, inline=not display,
                             color='#243541')
    size = equation.getsize()
    if not all(isfinite(n) and 0 < n < limit for n, limit in zip(size, (1600, 360))):
        return ''
    svg = equation.svg().encode('utf-8')
    if len(svg) > 1500000:
        return ''
    renderer = QSvgRenderer(QByteArray(svg))
    if not renderer.isValid():
        return ''
    bounds = renderer.viewBoxF()  # includes the typesetter's antialiasing margin
    width, height = ceil(bounds.width()), ceil(bounds.height())
    if not 0 < width <= 1610 or not 0 < height <= 370:
        return ''
    image = QImage(2 * width, 2 * height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    output = QBuffer()
    output.open(QIODevice.WriteOnly)
    if not image.save(output, 'PNG'):
        return ''
    data = base64.b64encode(bytes(output.data())).decode('ascii')
    return (f'<img alt="{escape(source, quote=True)}" width="{width}" height="{height}" '
            f'style="vertical-align: middle" src="data:image/png;base64,{data}">')


def render_formula(source: str, display: bool) -> str:
    """Return a Qt-rich-text image, or preserve the original TeX as literal text."""
    if _eligible(source):
        try:
            image = _render(source, display)
            if image:
                return image
        except Exception:
            # Syntax errors and missing packaged resources must not hide a reply.
            pass
    return '<code>' + escape(source) + '</code>'
