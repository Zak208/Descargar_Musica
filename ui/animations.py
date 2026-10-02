"""Microanimaciones: aparición suave, «pop» de iconos, pulsación y ondas en botones, sacudida y destello.
Todas respetan el nivel de movimiento (`ui.motion`) y los efectos gráficos son temporales: se retiran al terminar."""
from PySide6.QtCore import (
    QObject, QEvent, QPropertyAnimation, QVariantAnimation, QEasingCurve, QSize, QTimer, QPoint, QPointF, QRectF, Qt
)
from PySide6.QtGui import QPainter, QColor, QPainterPath
from PySide6.QtWidgets import QGraphicsOpacityEffect, QPushButton, QWidget

from ui import motion


def fade_in(widget, duration: int = 240, delay: int = 0):
    """Hace aparecer el widget con un fundido (y retira el efecto al terminar para no gastar recursos).
    Solo se anima lo que se ve en pantalla."""
    if not motion.enabled():
        return

    def start():
        try:
            if not motion.visible_ok(widget):
                return
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(duration)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda: _clear_effect(widget))
            widget._fade_anim = anim
            anim.start()
        except RuntimeError:
            pass

    if delay > 0:
        QTimer.singleShot(delay, start)
    else:
        start()


def slide_fade_in(widget, dy: int = 12, duration: int = 240, delay: int = 0):
    """Aparece subiendo unos píxeles con un fundido (estantes, cabeceras)."""
    if not motion.enabled():
        return

    def start():
        try:
            if not motion.visible_ok(widget):
                return
            origin = widget.pos()
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", widget)
            fade.setDuration(duration)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.OutCubic)
            slide = QPropertyAnimation(widget, b"pos", widget)
            slide.setDuration(duration)
            slide.setStartValue(origin + QPoint(0, dy))
            slide.setEndValue(origin)
            slide.setEasingCurve(QEasingCurve.OutCubic)

            def done():
                _clear_effect(widget)
                try:
                    widget.move(origin)
                except RuntimeError:
                    pass

            fade.finished.connect(done)
            widget._fade_anim = fade
            widget._slide_anim = slide
            fade.start()
            slide.start()
        except RuntimeError:
            pass

    if delay > 0:
        QTimer.singleShot(delay, start)
    else:
        start()


def _clear_effect(widget):
    try:
        widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


def heart_ring(button: QPushButton, size: int = 46):
    """Un aro del color del tema se expande desde el botón y se desvanece (el «latido» de guardar una canción)."""
    parent = button.parentWidget()
    if parent is None or not motion.enabled() or not button.isVisible():
        return
    from PySide6.QtWidgets import QLabel
    from ui import frames
    from ui.styles import accent
    strip = frames.ring_frames(size, accent())
    label = QLabel(parent)
    label.setAttribute(Qt.WA_TransparentForMouseEvents)
    label.setStyleSheet("background: transparent;")
    label.setFixedSize(size, size)
    center = button.geometry().center()
    label.move(center.x() - size // 2, center.y() - size // 2)
    label.setPixmap(strip[0])
    label.show()
    label.raise_()
    anim = QVariantAnimation(label)
    anim.setStartValue(0)
    anim.setEndValue(len(strip) - 1)
    anim.setDuration(260)
    anim.valueChanged.connect(lambda v: label.setPixmap(strip[max(0, min(len(strip) - 1, int(v)))]))

    def done():
        label.hide()
        label.deleteLater()

    anim.finished.connect(done)
    label._anim = anim
    anim.start()


def pop_icon(button: QPushButton, grow: float = 1.4, duration: int = 260, ring: bool = False):
    """El icono del botón 'late': crece y vuelve a su tamaño (por ejemplo al dar me gusta)."""
    base = button.iconSize()
    if base.width() <= 0 or not motion.enabled():
        return
    if ring:
        heart_ring(button)
    big = QSize(int(base.width() * grow), int(base.height() * grow))
    anim = QPropertyAnimation(button, b"iconSize", button)
    anim.setDuration(duration)
    anim.setKeyValueAt(0.0, base)
    anim.setKeyValueAt(0.4, big)
    anim.setKeyValueAt(1.0, base)
    anim.setEasingCurve(QEasingCurve.OutBack)
    button._pop_anim = anim
    anim.start()


def press_pulse(button: QPushButton, duration: int = motion.DUR_TAP):
    """La misma pulsación que al hacer clic (un atajo de teclado la reutiliza para que se vea qué botón actúa)."""
    if not motion.enabled():
        return
    base = button.property("_baseIconSize") or button.iconSize()
    button.setProperty("_baseIconSize", base)
    if base.width() <= 0:
        return
    small = QSize(int(base.width() * 0.8), int(base.height() * 0.8))
    anim = QPropertyAnimation(button, b"iconSize", button)
    anim.setDuration(duration * 2)
    anim.setKeyValueAt(0.0, base)
    anim.setKeyValueAt(0.35, small)
    anim.setKeyValueAt(1.0, base)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    button._press_anim = anim
    anim.start()


class PressFeedback(QObject):
    """Los botones circulares y de iconos se encogen un instante al pulsarlos. Se instala solo en esos botones
    (con `press_feedback(boton)`), no en toda la aplicación, para no gastar CPU."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and isinstance(obj, QPushButton) and motion.enabled():
            press_pulse(obj)
        return False


_PRESS = PressFeedback()


def press_feedback(button: QPushButton) -> QPushButton:
    """Activa el efecto de pulsación en un botón."""
    button.installEventFilter(_PRESS)
    return button


# --------------------------------------------------------------- ondas (ripple)
class _Ripple(QWidget):
    def __init__(self, host: QWidget, origin: QPoint, radius: float, color: QColor, corner: float):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.origin = QPointF(origin)
        self.max_r = radius
        self.color = color
        self.corner = corner
        self.t = 0.0
        self.setGeometry(host.rect())
        self.show()
        self.raise_()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self.corner, self.corner)
        p.setClipPath(clip)
        c = QColor(self.color)
        c.setAlphaF(max(0.0, self.color.alphaF() * (1.0 - self.t)))
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        r = self.max_r * self.t
        p.drawEllipse(self.origin, r, r)


class RippleFilter(QObject):
    """Onda circular que sale del punto pulsado (solo en botones principales)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and isinstance(obj, QWidget) and motion.enabled() \
                and event.button() == Qt.LeftButton:
            ripple(obj, event.position().toPoint())
        return False


_RIPPLE = RippleFilter()


def ripple(widget: QWidget, point: QPoint, color: str = "#FFFFFF", alpha: float = 0.28, duration: int = 320):
    if not motion.enabled() or not widget.isVisible() or widget.width() < 8:
        return
    w, h = widget.width(), widget.height()
    radius = max(((w - point.x()) ** 2 + (h - point.y()) ** 2) ** 0.5, (point.x() ** 2 + point.y() ** 2) ** 0.5,
                 ((w - point.x()) ** 2 + point.y() ** 2) ** 0.5, (point.x() ** 2 + (h - point.y()) ** 2) ** 0.5)
    c = QColor(color)
    c.setAlphaF(alpha)
    layer = _Ripple(widget, point, radius, c, min(h / 2, 18.0))
    anim = QVariantAnimation(layer)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def on_value(v):
        layer.t = float(v)
        layer.update()

    def done():
        layer.hide()
        layer.deleteLater()

    anim.valueChanged.connect(on_value)
    anim.finished.connect(done)
    layer._anim = anim
    anim.start()


def ripple_feedback(widget: QWidget) -> QWidget:
    """Activa la onda en un botón principal (Descargar, Reproducir grande, Crear lista…)."""
    widget.installEventFilter(_RIPPLE)
    return widget


# ------------------------------------------------------------ sacudida y destello
def shake(widget: QWidget, amplitude: int = 6, duration: int = 240):
    """El widget tiembla de lado a lado (3 oscilaciones): «aquí no se puede» sin ventanas ni textos."""
    if not motion.enabled() or not widget.isVisible():
        return
    old = getattr(widget, "_shake_anim", None)
    if old is not None and old.state() == QVariantAnimation.Running:
        return
    origin = widget.pos()
    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration)
    import math

    def on_value(v):
        try:
            widget.move(origin.x() + int(amplitude * math.sin(float(v) * math.pi * 6) * (1 - float(v))), origin.y())
        except RuntimeError:
            pass

    def done():
        try:
            widget.move(origin)
        except RuntimeError:
            pass

    anim.valueChanged.connect(on_value)
    anim.finished.connect(done)
    widget._shake_anim = anim
    anim.start()


class _Flash(QWidget):
    def __init__(self, host: QWidget, color: QColor, corner: float):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.color = color
        self.corner = corner
        self.k = 1.0
        self.setGeometry(host.rect())
        self.show()
        self.raise_()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.color)
        c.setAlphaF(self.color.alphaF() * self.k)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(self.rect()), self.corner, self.corner)


def flash(widget: QWidget, color: str = "#1ED760", alpha: float = 0.25, duration: int = 600, corner: float = 8.0):
    """Destello suave del color indicado sobre el widget (una descarga que termina, una letra que se guarda)."""
    if not motion.enabled() or not motion.visible_ok(widget):
        return
    c = QColor(color)
    c.setAlphaF(alpha)
    layer = _Flash(widget, c, corner)
    anim = QVariantAnimation(layer)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def on_value(v):
        layer.k = float(v)
        layer.update()

    def done():
        layer.hide()
        layer.deleteLater()

    anim.valueChanged.connect(on_value)
    anim.finished.connect(done)
    layer._anim = anim
    anim.start()


def reveal_widget(widget: QWidget, show: bool, dy: int = 8, duration: int = 140):
    """Muestra u oculta un widget pequeño con un fundido y un desplazamiento corto (el botón ▶ de una tarjeta, por
    ejemplo). Sin animación (nivel «Ninguna») cambia al instante. El efecto de opacidad se retira al terminar."""
    base = widget.property("_revealBase")
    if base is None:
        base = widget.pos()
        widget.setProperty("_revealBase", base)
    if not motion.enabled() or not widget.parentWidget() or not widget.parentWidget().isVisible():
        widget.move(base)
        widget.setVisible(show)
        return
    old = getattr(widget, "_reveal_anim", None)
    if old is not None:
        old.stop()
    if show:
        widget.move(base + QPoint(0, dy))
        widget.show()
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0 if show else 1.0)
        widget.setGraphicsEffect(effect)
    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration if show else 90)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    start_op = effect.opacity()
    start_pos = widget.pos()
    end_op = 1.0 if show else 0.0
    end_pos = base if show else base + QPoint(0, dy)

    def on_value(v):
        t = float(v)
        try:
            effect.setOpacity(start_op + (end_op - start_op) * t)
            widget.move(start_pos + (end_pos - start_pos) * t)
        except RuntimeError:
            pass

    def done():
        try:
            widget.move(end_pos)
            if show:
                widget.setGraphicsEffect(None)
            else:
                widget.hide()
                widget.setGraphicsEffect(None)
                widget.move(base)
        except RuntimeError:
            pass

    anim.valueChanged.connect(on_value)
    anim.finished.connect(done)
    widget._reveal_anim = anim
    anim.start()


def expand_widget(widget: QWidget, show: bool, duration: int = 160):
    """Un panel (la barra de selección) se despliega o se pliega en altura en vez de aparecer de golpe."""
    if show == widget.isVisible() and not getattr(widget, "_expand_anim", None):
        return
    if not motion.enabled() or not widget.parentWidget() or not widget.parentWidget().isVisible():
        widget.setMaximumHeight(16777215)
        widget.setVisible(show)
        return
    old = getattr(widget, "_expand_anim", None)
    if old is not None:
        old.stop()
    full = max(widget.sizeHint().height(), 30)
    start = widget.height() if widget.isVisible() else 0
    if show:
        widget.setMaximumHeight(max(0, start))
        widget.show()
    anim = QVariantAnimation(widget)
    anim.setStartValue(float(start))
    anim.setEndValue(float(full if show else 0))
    anim.setDuration(duration if show else 110)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    def on_value(v):
        try:
            widget.setMaximumHeight(int(float(v)))
        except RuntimeError:
            pass

    def done():
        try:
            widget.setMaximumHeight(16777215)
            if not show:
                widget.hide()
            widget._expand_anim = None
        except RuntimeError:
            pass

    anim.valueChanged.connect(on_value)
    anim.finished.connect(done)
    widget._expand_anim = anim
    anim.start()


RIPPLE_NAMES = {"GiantActionBtn", "BigPlayBtn", "DownloadBtn", "BatchDownloadBtn", "RoundPlayBtn", "TilePlayBtn"}


def install_ripples(root: QWidget):
    """Onda al pulsar en los botones principales que hay dentro de `root` (se llama al crear pantallas y ventanas)."""
    for btn in root.findChildren(QPushButton):
        if btn.objectName() in RIPPLE_NAMES and not btn.property("_ripple"):
            btn.setProperty("_ripple", True)
            ripple_feedback(btn)


def fade_out_hide(widget: QWidget, duration: int = 200, delay: int = 0):
    """El widget se desvanece y se oculta (con un retraso opcional, para hacer cascadas)."""
    if not motion.enabled() or not widget.isVisible():
        widget.hide()
        return

    def start():
        try:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(1.0)
            widget.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(duration)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def done():
                try:
                    widget.hide()
                    widget.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            anim.finished.connect(done)
            widget._fade_anim = anim
            anim.start()
        except RuntimeError:
            pass

    if delay > 0:
        QTimer.singleShot(delay, start)
    else:
        start()


def show_fading(widget: QWidget, duration: int = 220, delay: int = 0):
    """Muestra el widget con un fundido, empezando tras `delay` (para cascadas)."""
    widget.hide()

    def start():
        try:
            widget.show()
            fade_in(widget, duration)
        except RuntimeError:
            pass

    if not motion.enabled():
        widget.show()
    elif delay > 0:
        QTimer.singleShot(delay, start)
    else:
        start()
