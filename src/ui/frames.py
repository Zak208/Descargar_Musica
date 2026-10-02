"""Tiras de fotogramas pre-dibujadas: se pintan una vez y animar es solo `drawPixmap` (sin antialiasing por fotograma).
Se regeneran al cambiar de tema porque dependen del color."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QPixmap, QTransform

_cache: dict = {}


def clear() -> None:
    _cache.clear()


def _canvas(size: int, dpr: float) -> QPixmap:
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    return pix


def spinner_frames(size: int, color: str, steps: int = 12, dpr: float = 2.0) -> list:
    """Arco que gira, en `steps` posiciones (un giro completo)."""
    key = ("spinner", size, color, steps, dpr)
    frames = _cache.get(key)
    if frames is not None:
        return frames
    frames = []
    width = max(2.0, size / 10)
    rect = QRectF(width, width, size - 2 * width, size - 2 * width)
    for i in range(steps):
        pix = _canvas(size, dpr)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 30), width))
        p.drawEllipse(rect)
        arc = QPen(QColor(color), width)
        arc.setCapStyle(Qt.RoundCap)
        p.setPen(arc)
        p.drawArc(rect, int(-i * (360 / steps) * 16), 100 * 16)
        p.end()
        frames.append(pix)
    _cache[key] = frames
    return frames


def rotated_frames(source: QPixmap, steps: int = 12, tag: str = "") -> list:
    """El mismo dibujo girado en `steps` pasos (por ejemplo el icono de «actualizar»)."""
    key = ("rot", tag or source.cacheKey(), steps)
    frames = _cache.get(key)
    if frames is not None:
        return frames
    frames = []
    w, h = source.width(), source.height()
    for i in range(steps):
        t = QTransform().translate(w / 2, h / 2).rotate(i * 360 / steps).translate(-w / 2, -h / 2)
        rotated = source.transformed(t, Qt.SmoothTransformation)
        x, y = (rotated.width() - w) // 2, (rotated.height() - h) // 2
        frame = rotated.copy(x, y, w, h)
        frame.setDevicePixelRatio(source.devicePixelRatio())
        frames.append(frame)
    _cache[key] = frames
    return frames


def ring_frames(size: int, color: str, steps: int = 8, dpr: float = 2.0) -> list:
    """Anillo que se expande y se desvanece (el «latido» de guardar, el aviso de descarga terminada)."""
    key = ("ring", size, color, steps, dpr)
    frames = _cache.get(key)
    if frames is not None:
        return frames
    frames = []
    for i in range(steps):
        t = (i + 1) / steps
        pix = _canvas(size, dpr)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(color)
        c.setAlphaF(max(0.0, 0.85 * (1 - t)))
        p.setPen(QPen(c, max(1.5, size / 16 * (1 - t * 0.5))))
        r = size / 2 * (0.55 + 0.45 * t) - 1
        p.drawEllipse(QRectF(size / 2 - r, size / 2 - r, 2 * r, 2 * r))
        p.end()
        frames.append(pix)
    _cache[key] = frames
    return frames
