"""Avisos flotantes breves (en lugar de ventanas emergentes que obligan a pulsar 'Aceptar')."""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect


class Toast(QLabel):
    """Aviso centrado en la parte inferior de la ventana que se desvanece solo."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            "background-color: #FFFFFF; color: #000000; font-size: 14px; font-weight: bold;"
            "border-radius: 20px; padding: 12px 22px;"
        )
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.finished.connect(self._on_anim_finished)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(260)
        self._slide.setEasingCurve(QEasingCurve.OutBack)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, msec: int = 2800, bottom_margin: int = 120):
        parent = self.parentWidget()
        if parent is None:
            return
        self.setText(text)
        width = min(560, max(240, parent.width() - 80))
        self.setFixedWidth(width)
        self.adjustSize()
        target = QPoint((parent.width() - self.width()) // 2, parent.height() - self.height() - bottom_margin)
        self.move(target.x(), target.y() + 24)
        self.raise_()
        self.show()
        self._slide.stop()
        self._slide.setStartValue(QPoint(target.x(), target.y() + 24))
        self._slide.setEndValue(target)
        self._slide.start()
        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(msec)

    def _fade_out(self):
        self._anim.stop()
        self._anim.setDuration(350)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_finished(self):
        if self._effect.opacity() <= 0.01:
            self.hide()
