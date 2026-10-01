"""Microanimaciones: aparición suave, 'pop' de iconos y pulsación de botones."""
from PySide6.QtCore import QObject, QEvent, QPropertyAnimation, QEasingCurve, QSize, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QPushButton

from ui.perf import eco


def fade_in(widget, duration: int = 240, delay: int = 0):
    """Hace aparecer el widget con un fundido (y retira el efecto al terminar para no gastar recursos).
    En modo ahorro no se anima nada."""
    if eco():
        return
    def start():
        try:
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


def _clear_effect(widget):
    try:
        widget.setGraphicsEffect(None)
    except RuntimeError:
        pass


def pop_icon(button: QPushButton, grow: float = 1.4, duration: int = 260):
    """El icono del botón 'late': crece y vuelve a su tamaño (por ejemplo al dar me gusta)."""
    base = button.iconSize()
    if base.width() <= 0 or eco():
        return
    big = QSize(int(base.width() * grow), int(base.height() * grow))
    anim = QPropertyAnimation(button, b"iconSize", button)
    anim.setDuration(duration)
    anim.setKeyValueAt(0.0, base)
    anim.setKeyValueAt(0.4, big)
    anim.setKeyValueAt(1.0, base)
    anim.setEasingCurve(QEasingCurve.OutBack)
    button._pop_anim = anim
    anim.start()


class PressFeedback(QObject):
    """Los botones circulares y de iconos se encogen un instante al pulsarlos. Se instala solo en esos botones
    (con `press_feedback(boton)`), no en toda la aplicación, para no gastar CPU."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and isinstance(obj, QPushButton) and not eco():
            base = obj.property("_baseIconSize")
            if base is None:
                base = obj.iconSize()
                obj.setProperty("_baseIconSize", base)
            if base.width() > 0:
                small = QSize(int(base.width() * 0.8), int(base.height() * 0.8))
                anim = QPropertyAnimation(obj, b"iconSize", obj)
                anim.setDuration(200)
                anim.setKeyValueAt(0.0, base)
                anim.setKeyValueAt(0.35, small)
                anim.setKeyValueAt(1.0, base)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                obj._press_anim = anim
                anim.start()
        return False


_PRESS = PressFeedback()


def press_feedback(button: QPushButton) -> QPushButton:
    """Activa el efecto de pulsación en un botón."""
    button.installEventFilter(_PRESS)
    return button
