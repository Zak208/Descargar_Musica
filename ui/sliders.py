"""Deslizador propio, pintado a mano: el tirador aparece al acercar el ratón, el tramo recorrido toma el color del tema,
una burbuja muestra el momento al que saltarías y puede marcar el tramo A–B que se está repitiendo."""
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve, QEvent
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QSlider, QWidget

from ui import motion
from ui.styles import accent


class TimeBubble(QWidget):
    """Burbuja pequeña con un texto («01:37») que sigue al cursor sobre el deslizador."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.text = ""
        self.k = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(80)
        self._anim.valueChanged.connect(self._on_value)
        self.hide()

    def _on_value(self, v):
        self.k = float(v)
        self.update()
        if self.k <= 0.001 and self._target == 0.0:
            self.hide()

    _target = 0.0

    def show_text(self, text: str, center_x: int, bottom_y: int):
        fm = self.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 18, fm.height() + 10
        self.text = text
        self.setGeometry(int(center_x - w / 2), int(bottom_y - h), w, h)
        if not self.isVisible():
            self.show()
            self.raise_()
        self._fade(1.0)

    def hide_bubble(self):
        self._fade(0.0)

    def _fade(self, target: float):
        if self._target == target:
            self.update()
            return
        self._target = target
        if not motion.enabled():
            self.k = target
            if target == 0.0:
                self.hide()
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self.k)
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.k)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        p.setPen(QColor("#000000"))
        font = self.font()
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, self.text)


class SmoothSlider(QSlider):
    """Barra de tiempo / volumen. Al hacer clic salta a ese punto; el tirador solo se ve con el ratón encima."""
    PAD = 7

    def __init__(self, orientation=Qt.Horizontal, parent=None, bubble_text=None):
        super().__init__(orientation, parent)
        self._hover_t = 0.0
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(motion.DUR_FAST)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover)
        self._marks = (None, None)          # tramo A–B, en las mismas unidades del deslizador
        self._bubble_text = bubble_text     # función valor → texto, o None
        self._bubble = None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)

    # -- tramo A–B
    def set_marks(self, a, b):
        if (a, b) != self._marks:
            self._marks = (a, b)
            self.update()

    # -- geometría
    def _ratio(self) -> float:
        span = self.maximum() - self.minimum()
        return 0.0 if span <= 0 else (self.value() - self.minimum()) / span

    def _value_at(self, x: float) -> int:
        width = max(1.0, self.width() - 2 * self.PAD)
        ratio = max(0.0, min(1.0, (x - self.PAD) / width))
        return int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def _x_of(self, value: float) -> float:
        span = self.maximum() - self.minimum()
        ratio = 0.0 if span <= 0 else (value - self.minimum()) / span
        return self.PAD + ratio * (self.width() - 2 * self.PAD)

    # -- eventos
    def _on_hover(self, v):
        self._hover_t = float(v)
        self.update()

    def _go_hover(self, target: float):
        if not motion.enabled():
            self._hover_t = target
            self.update()
            return
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, event):
        self._go_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.isSliderDown():
            self._go_hover(0.0)
        if self._bubble is not None:
            self._bubble.hide_bubble()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.width() > 0:
            self.setSliderDown(True)
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self.isSliderDown():
            self.setValue(self._value_at(x))
        self._show_bubble(x)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
            if not self.underMouse():
                self._go_hover(0.0)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _show_bubble(self, x: float):
        if self._bubble_text is None or self.maximum() <= 0:
            return
        parent = self.parentWidget()
        if parent is None:
            return
        if self._bubble is None:
            self._bubble = TimeBubble(self.window())
        top_left = self.mapTo(self.window(), self.rect().topLeft())
        x = max(self.PAD, min(self.width() - self.PAD, x))
        self._bubble.show_text(self._bubble_text(self._value_at(x)), int(top_left.x() + x), int(top_left.y()) - 2)

    # -- dibujo
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        cy = h / 2
        left, right = float(self.PAD), float(self.width() - self.PAD)
        groove = QRectF(left, cy - 2, right - left, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3E3E3E"))
        p.drawRoundedRect(groove, 2, 2)
        a, b = self._marks
        if a is not None and b is not None and self.maximum() > 0:
            band = QColor(accent())
            band.setAlphaF(0.55)
            p.setBrush(band)
            p.drawRoundedRect(QRectF(self._x_of(a), cy - 3, max(2.0, self._x_of(b) - self._x_of(a)), 6), 3, 3)
        elif a is not None and self.maximum() > 0:
            p.setBrush(QColor(accent()))
            p.drawRoundedRect(QRectF(self._x_of(a) - 1, cy - 5, 2, 10), 1, 1)
        x = self._x_of(self.value())
        fill = QColor(accent()) if self._hover_t > 0.5 else QColor("#FFFFFF")
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(left, cy - 2, max(0.0, x - left), 4), 2, 2)
        r = 6.0 * self._hover_t
        if r > 0.5 or self.isSliderDown():
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(x, cy), max(r, 5.0 if self.isSliderDown() else 0.0), max(r, 5.0 if self.isSliderDown() else 0.0))

    def event(self, ev):
        if ev.type() == QEvent.Hide and self._bubble is not None:
            self._bubble.hide()
        return super().event(ev)
