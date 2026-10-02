"""Animar con «fotos»: se captura una vez el aspecto de una pantalla y solo se anima el dibujo de esa foto en una capa
transparente (posición, opacidad, tamaño). Animar los widgets de verdad obligaría a recolocar y repintar todo su
contenido en cada fotograma; con una foto son unos pocos `drawPixmap`."""
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

from ui import motion


def grab(widget, rect: QRect = None) -> QPixmap:
    """Foto del widget tal como se ve ahora (con la nitidez de la pantalla)."""
    try:
        pix = widget.grab(rect) if rect is not None else widget.grab()
    except RuntimeError:
        return QPixmap()
    return pix


class Layer(QWidget):
    """Capa transparente sobre un widget que dibuja una foto con opacidad, desplazamiento y tamaño animables."""

    def __init__(self, host, pixmap: QPixmap, rect: QRect = None):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.pix = pixmap
        self.opacity = 1.0
        self.dx = 0.0
        self.dy = 0.0
        self.zoom = 1.0
        self._anim = None
        self.setGeometry(rect if rect is not None else host.rect())
        self.show()
        self.raise_()

    def paintEvent(self, _event):
        if self.pix is None or self.pix.isNull() or self.opacity <= 0.003:
            return
        p = QPainter(self)
        p.setOpacity(max(0.0, min(1.0, self.opacity)))
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        p.translate(w / 2 + self.dx, h / 2 + self.dy)
        if abs(self.zoom - 1.0) > 0.001:
            p.scale(self.zoom, self.zoom)
        p.drawPixmap(QRectF(-w / 2, -h / 2, w, h), self.pix, QRectF(self.pix.rect()))

    def animate(self, duration: int, step, easing=QEasingCurve.OutCubic, on_done=None):
        """`step(t)` con t de 0 a 1 ajusta las propiedades de la capa en cada fotograma; al final se borra."""
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(max(1, duration))
        anim.setEasingCurve(easing)

        def on_value(v):
            step(float(v))
            self.update()

        def done():
            if on_done is not None:
                on_done()
            self.hide()
            self.deleteLater()

        anim.valueChanged.connect(on_value)
        anim.finished.connect(done)
        self._anim = anim
        anim.start()


def crossfade(host, old: QPixmap, duration: int = motion.DUR_BASE, dx: float = 0.0, dy: float = 0.0,
              rect: QRect = None, on_done=None):
    """La foto de lo que había se desvanece (y se desplaza un poco) sobre lo nuevo, que ya está debajo."""
    if not motion.enabled() or old is None or old.isNull() or not motion.visible_ok(host):
        if on_done:
            on_done()
        return None
    layer = Layer(host, old, rect)

    def step(t):
        layer.opacity = 1.0 - t
        layer.dx = dx * t
        layer.dy = dy * t

    layer.animate(duration, step, QEasingCurve.OutCubic, on_done)
    return layer


def scale_fade_in(host, pix: QPixmap, rect: QRect, duration: int = motion.DUR_BASE, start_zoom: float = 0.96):
    """Una foto que aparece creciendo un poco (ventanas internas, menús)."""
    if not motion.enabled() or pix is None or pix.isNull():
        return None
    layer = Layer(host, pix, rect)
    layer.opacity = 0.0
    layer.zoom = start_zoom

    def step(t):
        layer.opacity = t
        layer.zoom = start_zoom + (1.0 - start_zoom) * t

    layer.animate(duration, step, QEasingCurve.OutCubic)
    return layer


class _Flyer(QWidget):
    def __init__(self, host, pixmap: QPixmap, size: int):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.pix = pixmap
        self.setFixedSize(size, size)
        self.scale_f = 1.0
        self.alpha = 1.0

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.alpha)
        w = self.width() * self.scale_f
        r = QRectF((self.width() - w) / 2, (self.height() - w) / 2, w, w)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.setClipPath(path)
        p.drawPixmap(r, self.pix, QRectF(self.pix.rect()))


def fly(window, pixmap: QPixmap, start_global, end_global, size: int = 34, duration: int = 300, on_done=None):
    """Una miniatura vuela de un sitio a otro (curva suave) y al llegar avisa: así se ve adónde ha ido algo
    (una canción que sueltas en una lista, una descarga que se pone en cola…). Los puntos son globales."""
    if not motion.enabled() or pixmap is None or pixmap.isNull() or not window.isVisible():
        if on_done:
            on_done()
        return None
    a = window.mapFromGlobal(start_global)
    b = window.mapFromGlobal(end_global)
    flyer = _Flyer(window, pixmap, size)
    flyer.show()
    flyer.raise_()
    mid = QPointF((a.x() + b.x()) / 2, min(a.y(), b.y()) - 40)
    anim = QVariantAnimation(flyer)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(max(1, motion.ms(duration)))
    anim.setEasingCurve(QEasingCurve.InOutCubic)

    def on_value(v):
        t = float(v)
        x = (1 - t) ** 2 * a.x() + 2 * (1 - t) * t * mid.x() + t * t * b.x()
        y = (1 - t) ** 2 * a.y() + 2 * (1 - t) * t * mid.y() + t * t * b.y()
        flyer.move(int(x - size / 2), int(y - size / 2))
        flyer.scale_f = 1.0 - 0.45 * t
        flyer.alpha = 1.0 - 0.5 * max(0.0, t - 0.7) / 0.3
        flyer.update()

    def done():
        flyer.hide()
        flyer.deleteLater()
        if on_done:
            on_done()

    anim.valueChanged.connect(on_value)
    anim.finished.connect(done)
    flyer._anim = anim
    on_value(0.0)
    anim.start()
    return flyer


class _Traveler(QWidget):
    def __init__(self, host, pixmap: QPixmap, radius: int):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.pix = pixmap
        self.radius = radius

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        p.setClipPath(path)
        p.drawPixmap(QRectF(self.rect()), self.pix, QRectF(self.pix.rect()))


def travel(window, pixmap: QPixmap, from_rect: QRect, to_rect_fn, duration: int = 280, radius: int = 8, on_done=None):
    """Elemento compartido: una portada pasa del hueco donde estaba al hueco que tiene en la página de destino.
    `from_rect` y lo que devuelve `to_rect_fn()` están en coordenadas de `window`."""
    if not motion.enabled() or pixmap is None or pixmap.isNull() or not window.isVisible():
        if on_done:
            on_done()
        return None
    walker = _Traveler(window, pixmap, radius)
    walker.setGeometry(from_rect)
    walker.show()
    walker.raise_()
    anim = QVariantAnimation(walker)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(max(1, duration))
    anim.setEasingCurve(QEasingCurve.OutCubic)
    state = {"to": None}

    def on_value(v):
        t = float(v)
        if state["to"] is None:
            state["to"] = to_rect_fn() or from_rect
        a, b = from_rect, state["to"]
        lerp = lambda p, q: int(p + (q - p) * t)
        walker.setGeometry(lerp(a.x(), b.x()), lerp(a.y(), b.y()), max(8, lerp(a.width(), b.width())),
                           max(8, lerp(a.height(), b.height())))

    def done():
        walker.hide()
        walker.deleteLater()
        if on_done:
            on_done()

    anim.valueChanged.connect(on_value)
    anim.finished.connect(done)
    walker._anim = anim
    anim.start()
    return walker
