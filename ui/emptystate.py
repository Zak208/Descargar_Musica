"""Estado vacío con vida: una ilustración sencilla con un único movimiento lento, el mensaje y un consejo útil que
cambia cada 8 segundos con un cruce. Solo se mueve en el nivel «Completas» y mientras se ve."""
import math
import random

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui import motion
from ui.anim_clock import clock
from ui.icons import icon
from ui.textfx import SwapLabel

TIPS = (
    "Arrastra una canción hasta una lista de la barra lateral para guardarla.",
    "Pulsa Espacio para pausar y reanudar la música.",
    "Con Ctrl + clic marcas varias canciones a la vez.",
    "Sin internet puedes seguir escuchando tu música descargada.",
    "Ctrl + Z deshace lo último que quitaste.",
    "Pega un enlace de YouTube o Spotify en el buscador para descargarlo.",
    "Las flechas ← → saltan 5 segundos dentro de la canción.",
)


class Illustration(QWidget):
    """Una nota musical en un círculo suave que sube y baja unos píxeles (muy despacio)."""

    def __init__(self, icon_name: str = "music.svg", parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 120)
        self._icon_name = icon_name
        self._phase = 0.0
        self._token = None

    def showEvent(self, event):
        if self._token is None and motion.full():
            self._token = clock().subscribe(self._tick, 8)
        super().showEvent(event)

    def hideEvent(self, event):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
        super().hideEvent(event)

    def _tick(self, dt):
        self._phase = (self._phase + dt / 4000.0) % 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bob = 3 * math.sin(self._phase * 2 * math.pi) if self._token is not None else 0.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 16))
        p.drawEllipse(10, 10 + bob, 100, 100)
        p.setBrush(QColor(255, 255, 255, 10))
        p.drawEllipse(24, 24 + bob, 72, 72)
        pix = icon(self._icon_name, "#7A7A7A", 64).pixmap(48, 48)
        p.drawPixmap(36, int(36 + bob), pix)


class EmptyState(QWidget):
    """Ilustración + mensaje + consejo. Tiene `setText` y `setVisible` como un QLabel para sustituirlo sin más."""

    def __init__(self, icon_name: str = "music.svg", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 20, 0, 20)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignHCenter)
        self.art = Illustration(icon_name)
        lay.addWidget(self.art, alignment=Qt.AlignHCenter)
        self.message = QLabel("")
        self.message.setObjectName("SectionSubtitle")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setStyleSheet("font-size: 14px; background: transparent;")
        lay.addWidget(self.message)
        self.tip = SwapLabel("")
        self.tip.setObjectName("SectionSubtitle")
        self.tip.setAlignment(Qt.AlignCenter)
        self.tip.setStyleSheet("font-size: 12px; color: #8A8A8A; background: transparent;")
        lay.addWidget(self.tip)
        self._order = list(range(len(TIPS)))
        random.shuffle(self._order)
        self._i = 0
        self.tip.setText("Consejo: " + TIPS[self._order[0]])
        self._timer = QTimer(self)
        self._timer.setInterval(8000)
        self._timer.timeout.connect(self._next_tip)

    def setText(self, text: str):
        self.message.setText(text)

    def text(self) -> str:
        return self.message.text()

    def _next_tip(self):
        self._i = (self._i + 1) % len(self._order)
        self.tip.setText("Consejo: " + TIPS[self._order[self._i]])

    def showEvent(self, event):
        if motion.full():
            self._timer.start()             # solo en «Completas» cambia el consejo; mientras se ve
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)
