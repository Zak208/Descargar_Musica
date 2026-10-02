"""Desplazamiento: rueda del ratón con inercia suave, barras finas que se agrandan al acercar el ratón y se ocultan al
reposar, y un botón «volver arriba» que aparece cuando te alejas del principio."""
from PySide6.QtCore import (
    Qt, QObject, QEvent, QPropertyAnimation, QEasingCurve, QTimer, QVariantAnimation, QRectF, QPoint, QSize
)
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QScrollBar, QScrollArea, QPushButton

from ui import motion
from ui.animations import reveal_widget
from ui.icons import icon


class SmoothWheel(QObject):
    """La rueda del ratón desplaza con una animación corta (acumula si sigues girando). Los gestos del panel táctil,
    que ya son suaves, no se tocan."""

    def __init__(self, area: QScrollArea, step: int = 100, duration: int = 190):
        super().__init__(area)
        self.area = area
        self.step = step
        self.anim = QPropertyAnimation(area.verticalScrollBar(), b"value", self)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.duration = duration
        self._target = None
        area.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel or not motion.enabled():
            return False
        if not event.pixelDelta().isNull() or event.modifiers() != Qt.NoModifier:
            return False
        bar = self.area.verticalScrollBar()
        if bar.maximum() <= bar.minimum():
            return False
        delta = event.angleDelta().y()
        if delta == 0:
            return False
        base = self._target if (self.anim.state() == QPropertyAnimation.Running and self._target is not None) else bar.value()
        target = int(max(bar.minimum(), min(bar.maximum(), base - delta / 120.0 * self.step)))
        self._target = target
        self.anim.stop()
        self.anim.setDuration(self.duration)
        self.anim.setStartValue(bar.value())
        self.anim.setEndValue(target)
        self.anim.start()
        event.accept()
        return True


class ThinScrollBar(QScrollBar):
    """Barra de desplazamiento fina: se ve solo mientras te desplazas o la tocas, y se hace un poco más ancha al
    acercar el ratón. En reposo no pinta nada (el temporizador de ocultarla es de un solo disparo)."""

    def __init__(self, orientation=Qt.Vertical, parent=None):
        super().__init__(orientation, parent)
        self.setFixedWidth(12)
        self._k = 0.0                   # visibilidad (0 a 1)
        self._thick = 0.0               # grosor extra al acercar el ratón
        self._drag = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(900)
        self._hide_timer.timeout.connect(lambda: self._fade(0.0))
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(200)
        self._anim.valueChanged.connect(self._on_fade)
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(motion.DUR_FAST)
        self._hover_anim.valueChanged.connect(self._on_thick)
        self.setAttribute(Qt.WA_Hover, True)
        self.valueChanged.connect(self._poke)
        self.setStyleSheet("QScrollBar { background: transparent; border: none; }")

    # -- visibilidad
    def _poke(self, *_):
        self._fade(1.0)
        self._hide_timer.start()

    def _fade(self, target: float):
        if not motion.enabled():
            self._k = target
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._k)
        self._anim.setEndValue(float(target))
        self._anim.start()

    def _on_fade(self, v):
        self._k = float(v)
        self.update()

    def _on_thick(self, v):
        self._thick = float(v)
        self.update()

    def enterEvent(self, event):
        self._fade(1.0)
        self._hide_timer.stop()
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._thick)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hide_timer.start()
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._thick)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    # -- geometría de la barrita
    def _handle(self) -> QRectF:
        span = self.maximum() - self.minimum()
        h = float(self.height())
        if span <= 0:
            return QRectF()
        page = float(self.pageStep())
        size = max(36.0, h * page / (span + page))
        pos = (self.value() - self.minimum()) / span * (h - size)
        w = 5.0 + 4.0 * self._thick
        return QRectF(self.width() - w - 2, pos, w, size)

    def paintEvent(self, _event):
        if self._k <= 0.01 and not self._drag:
            return
        rect = self._handle()
        if rect.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(255, 255, 255)
        c.setAlphaF(0.30 + 0.30 * self._thick if self._drag is None else 0.65)
        c.setAlphaF(c.alphaF() * max(self._k, 1.0 if self._drag else 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(rect, rect.width() / 2, rect.width() / 2)

    # -- ratón (la barrita pintada es la que se arrastra)
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        handle = self._handle()
        y = event.position().y()
        if handle.contains(event.position()):
            self._drag = y - handle.top()
        else:
            self.setValue(self.value() + (self.pageStep() if y > handle.bottom() else -self.pageStep()))
        self._poke()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            span = self.maximum() - self.minimum()
            handle = self._handle()
            room = max(1.0, self.height() - handle.height())
            ratio = (event.position().y() - self._drag) / room
            self.setValue(int(self.minimum() + max(0.0, min(1.0, ratio)) * span))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        self._hide_timer.start()
        event.accept()


class BackToTop(QPushButton):
    """Botón redondo que aparece (sube y se funde) cuando te has alejado más de una pantalla y lleva arriba de golpe."""

    def __init__(self, area: QScrollArea, parent=None):
        super().__init__("", parent or area.parentWidget())
        self.area = area
        self.setObjectName("BackToTop")
        self.setIcon(icon("arrow_up.svg", "#000000"))
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(40, 40)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Volver arriba")
        self.setStyleSheet("QPushButton#BackToTop { background-color: #FFFFFF; border-radius: 20px; border: none; }"
                           "QPushButton#BackToTop:hover { background-color: #E5E5E5; }")
        self.clicked.connect(self._go_top)
        self._shown = False
        self.hide()
        area.verticalScrollBar().valueChanged.connect(self._check)
        area.installEventFilter(self)
        self._anim = QPropertyAnimation(area.verticalScrollBar(), b"value", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def _place(self):
        host = self.parentWidget()
        if host is None:
            return
        pos = self.area.mapTo(host, QPoint(self.area.width() - self.width() - 26, self.area.height() - self.height() - 18))
        self._base = pos
        self.move(pos)

    def eventFilter(self, obj, event):
        if obj is self.area and event.type() in (QEvent.Resize, QEvent.Show):
            if self._shown:
                self._place()
        return False

    def _check(self, value: int):
        far = value > self.area.viewport().height() * 1.5
        if far != self._shown:
            self._shown = far
            self._place()
            self.raise_()
            if far:
                self.setProperty("_revealBase", self._base)
            reveal_widget(self, far, dy=10, duration=150)

    def _go_top(self):
        bar = self.area.verticalScrollBar()
        if not motion.enabled():
            bar.setValue(0)
            return
        self._anim.stop()
        self._anim.setDuration(380)
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(0)
        self._anim.start()


def polish_scroll_area(area: QScrollArea, thin: bool = True, smooth: bool = True) -> QScrollArea:
    """Rueda con inercia suave y barra fina para una zona con desplazamiento."""
    if thin and not isinstance(area.verticalScrollBar(), ThinScrollBar):
        area.setVerticalScrollBar(ThinScrollBar(Qt.Vertical))
    if smooth and not hasattr(area, "_smooth_wheel"):
        area._smooth_wheel = SmoothWheel(area)
    return area
