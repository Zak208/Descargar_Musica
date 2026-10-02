"""Carga de iconos SVG con recoloreado dinámico (para seguir el color de acento del tema)."""
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

from config import BASE_DIR

ICONS_DIR = BASE_DIR / "assets" / "icons"
_CACHE: dict = {}


def icon(name: str, color: str | None = None, size: int = 64) -> QIcon:
    """Devuelve un QIcon del SVG `name`. Si se indica `color`, sustituye el blanco (#FFFFFF) por ese color."""
    key = (name, color, size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    path = ICONS_DIR / name
    if not color:
        result = QIcon(str(path))
    else:
        try:
            svg = path.read_text(encoding="utf-8").replace("#FFFFFF", color).replace("#ffffff", color)
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            pix = QPixmap(size, size)
            pix.fill(Qt.transparent)
            painter = QPainter(pix)
            renderer.render(painter)
            painter.end()
            result = QIcon(pix)
        except Exception:
            result = QIcon(str(path))

    _CACHE[key] = result
    return result
