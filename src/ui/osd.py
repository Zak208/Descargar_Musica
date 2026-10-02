"""Aviso flotante (OSD) para lo que se hace con el teclado: volumen, saltos de ±5 s, silencio. Un solo widget
reutilizable: aparece con un fundido breve, se queda un segundo y se va."""
from PySide6.QtCore import Qt, QRectF, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor

from PySide6.QtWidgets import QWidget

from ui import motion
from ui.icons import icon
from ui.styles import accent


class Osd(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._icon = None
        self._text = ""
        self._value = None            # 0..1 para dibujar una barra (volumen)
        self._k = 0.0
        self._target = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_value)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._fade(0.0, 300))
        self.setFixedSize(220, 70)
        self.hide()

    def show_osd(self, icon_name: str, text: str, value: float = None):
        parent = self.parentWidget()
        if parent is None:
            return
        self._icon = icon(icon_name, "#FFFFFF").pixmap(26, 26)
        self._text = text
        self._value = value
        self.move((parent.width() - self.width()) // 2, 86)
        self.show()
        self.raise_()
        self._fade(1.0, 110)
        self._timer.start(1000)
        self.update()

    def _fade(self, target: float, duration: int):
        self._target = target
        if not motion.enabled():
            self._k = target
            self.setVisible(target > 0)
            self.update()
            return
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setStartValue(self._k)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_value(self, v):
        self._k = float(v)
        if self._k <= 0.001 and self._target == 0.0:
            self.hide()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._k)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(24, 24, 24, 235))
        p.drawRoundedRect(QRectF(self.rect()), 16, 16)
        if self._icon is not None:
            p.drawPixmap(18, (self.height() - 26) // 2 - (7 if self._value is not None else 0), self._icon)
        p.setPen(QColor("#FFFFFF"))
        font = self.font()
        font.setBold(True)
        font.setPointSize(11)
        p.setFont(font)
        top = 0 if self._value is None else -14
        p.drawText(QRectF(54, top, self.width() - 66, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._text)
        if self._value is not None:
            bar = QRectF(54, self.height() - 24, self.width() - 72, 5)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#4A4A4A"))
            p.drawRoundedRect(bar, 2.5, 2.5)
            p.setBrush(QColor(accent()))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, self._value)), 5), 2.5, 2.5)
