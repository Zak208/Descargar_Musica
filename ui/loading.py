"""Indicador de carga propio de la aplicación (círculo giratorio con el color del tema)."""
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui.perf import eco
from ui.styles import accent


class Spinner(QWidget):
    """Arco que gira. El temporizador solo funciona mientras se ve (no gasta CPU oculto)."""

    def __init__(self, size: int = 40, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event):
        self._timer.start(70 if eco() else 40)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._angle = (self._angle - 18) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = 4
        rect = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        track = QPen(QColor(255, 255, 255, 30), w)
        p.setPen(track)
        p.drawEllipse(rect)
        arc = QPen(QColor(accent()), w)
        arc.setCapStyle(Qt.RoundCap)
        p.setPen(arc)
        p.drawArc(rect, self._angle * 16, 100 * 16)


class LoadingBlock(QWidget):
    """Círculo giratorio con un texto debajo."""

    def __init__(self, text: str = "Cargando...", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 36, 0, 36)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignCenter)
        self.spinner = Spinner(40)
        lay.addWidget(self.spinner, alignment=Qt.AlignCenter)
        self.label = QLabel(text)
        self.label.setObjectName("SectionSubtitle")
        self.label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.label)

    def set_text(self, text: str):
        self.label.setText(text)
