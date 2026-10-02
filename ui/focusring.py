"""Anillo de foco para quien usa el teclado: al moverse con Tab (o Mayús+Tab) se dibuja un contorno del color del tema
alrededor del control que tiene el foco, y se desliza al siguiente. Con el ratón no aparece. Es una capa transparente
que solo se pinta cuando cambia el foco: en reposo no hace nada."""
from PySide6.QtCore import Qt, QObject, QEvent, QRect, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QLineEdit, QComboBox, QCheckBox, QSlider

from ui import motion
from ui.styles import accent

KEYBOARD_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
FOCUSABLE = (QPushButton, QLineEdit, QComboBox, QCheckBox, QSlider)


class _Ring(QWidget):
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.rect_now = QRect()
        self.hide()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(accent()), 2.2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.drawRoundedRect(r, min(14.0, r.height() / 2), min(14.0, r.height() / 2))


class FocusRingFilter(QObject):
    def __init__(self, window: QWidget):
        super().__init__(window)
        self.window = window
        self.ring = _Ring(window)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(motion.DUR_FAST)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._from = self._to = QRect()
        self._target = None

    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t == QEvent.FocusIn:
                if isinstance(obj, FOCUSABLE) and event.reason() in KEYBOARD_REASONS:
                    self._follow(obj)
            elif t in (QEvent.MouseButtonPress, QEvent.FocusOut, QEvent.Hide) and self._target is not None:
                if t == QEvent.MouseButtonPress or obj is self._target:
                    self.ring.hide()
                    self._target = None
        except RuntimeError:                       # la ventana ya se está cerrando
            return False
        return False

    def _follow(self, widget: QWidget):
        if widget.window() is not self.window:
            return
        top_left = widget.mapTo(self.window, widget.rect().topLeft())
        target = QRect(top_left, widget.size()).adjusted(-3, -3, 3, 3)
        self._target = widget
        self.ring.raise_()
        if not self.ring.isVisible() or not motion.enabled():
            self._anim.stop()
            self.ring.setGeometry(target)
            self.ring.show()
            self.ring.raise_()
            return
        self._anim.stop()
        self._from, self._to = self.ring.geometry(), target
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_value(self, v):
        t = float(v)
        a, b = self._from, self._to
        lerp = lambda p, q: int(p + (q - p) * t)
        self.ring.setGeometry(lerp(a.x(), b.x()), lerp(a.y(), b.y()), lerp(a.width(), b.width()), lerp(a.height(), b.height()))


def install(window: QWidget) -> FocusRingFilter:
    f = FocusRingFilter(window)
    QApplication.instance().installEventFilter(f)
    return f


def uninstall(f: FocusRingFilter) -> None:
    try:
        QApplication.instance().removeEventFilter(f)
    except RuntimeError:
        pass
