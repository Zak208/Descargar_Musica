"""Indicadores de carga: círculo giratorio barato (fotogramas pre-dibujados) y esqueletos que anticipan la forma de la
pantalla. Los dos usan el reloj compartido y solo funcionan mientras se ven."""
import math

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui import frames, motion
from ui.anim_clock import clock
from ui.styles import accent


class Spinner(QWidget):
    """Arco que gira. Son 12 posiciones ya dibujadas que se cambian a 12 por segundo: se ve igual de fluido que
    redibujar un arco 25 veces por segundo y gasta una cuarta parte. Oculto, no gasta nada."""

    def __init__(self, size: int = 40, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._i = 0
        self._token = None

    def showEvent(self, event):
        if self._token is None:
            self._token = clock().subscribe(self._tick, 12 if motion.enabled() else 6)
        super().showEvent(event)

    def hideEvent(self, event):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
        super().hideEvent(event)

    def _tick(self, _dt):
        self._i = (self._i + 1) % 12
        self.update()

    def paintEvent(self, event):
        strip = frames.spinner_frames(self.width(), accent())
        p = QPainter(self)
        p.drawPixmap(0, 0, strip[self._i % len(strip)])


class SkeletonRows(QWidget):
    """Esqueleto de una lista: filas grises con la forma de una canción (portada y dos líneas) que laten despacio.
    Un único valor de brillo compartido por todas las filas, a 8 repintados por segundo."""

    def __init__(self, rows: int = 6, parent=None):
        super().__init__(parent)
        self._rows = rows
        self._phase = 0.0
        self._token = None
        self.setFixedHeight(rows * 68 + 8)

    def showEvent(self, event):
        if self._token is None and motion.enabled():
            self._token = clock().subscribe(self._tick, 8)
        super().showEvent(event)

    def hideEvent(self, event):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
        super().hideEvent(event)

    def _tick(self, dt):
        self._phase = (self._phase + dt / 1400.0) % 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pulse = 0.5 + 0.5 * math.sin(self._phase * 2 * math.pi) if motion.enabled() else 0.4
        base = QColor(255, 255, 255)
        base.setAlphaF(0.05 + 0.05 * pulse)
        p.setPen(Qt.NoPen)
        p.setBrush(base)
        w = self.width()
        for i in range(self._rows):
            y = 4 + i * 68
            p.drawRoundedRect(QRectF(12, y + 6, 52, 52), 6, 6)
            p.drawRoundedRect(QRectF(80, y + 14, min(w * 0.38, 280) * (0.8 + 0.2 * ((i * 7) % 3) / 2), 12), 6, 6)
            p.drawRoundedRect(QRectF(80, y + 36, min(w * 0.22, 170) * (0.8 + 0.2 * ((i * 5) % 3) / 2), 10), 5, 5)


class LoadingBlock(QWidget):
    """Círculo giratorio con un texto debajo; con `skeleton=True`, un esqueleto de lista en su lugar."""

    def __init__(self, text: str = "Cargando...", parent=None, skeleton: bool = False):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8 if skeleton else 36, 0, 8 if skeleton else 36)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignCenter if not skeleton else Qt.AlignTop)
        self.skeleton = SkeletonRows(6) if skeleton else None
        if skeleton:
            lay.addWidget(self.skeleton)
        self.spinner = Spinner(40)
        self.spinner.setVisible(not skeleton)
        lay.addWidget(self.spinner, alignment=Qt.AlignCenter)
        self.label = QLabel(text)
        self.label.setObjectName("SectionSubtitle")
        self.label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.label)

    def set_text(self, text: str):
        self.label.setText(text)
