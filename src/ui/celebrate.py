"""Celebración puntual: unas 40 piezas de confeti caen durante poco más de un segundo cuando pasa algo que merece la pena
(una copia de seguridad terminada, una lista entera descargada, llegar a un múltiplo de 100 canciones).

Solo en el nivel de animación «Completas»; en los otros, un simple destello. Es una capa transparente que se crea al
celebrar y se destruye al terminar: el resto del tiempo no existe."""
import math
import random

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget

from ui import motion
from ui.anim_clock import clock
from ui.styles import accent

DURATION_MS = 1500
COLORS = ("#1ED760", "#FFD166", "#FF6B8B", "#4FC3F7", "#BB86FC", "#FF8A3D")


class Confetti(QWidget):
    def __init__(self, host: QWidget, count: int = 40):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(host.rect())
        w = self.width()
        palette = [accent()] + list(COLORS)
        self.pieces = []
        for _ in range(count):
            self.pieces.append({
                "x": w * (0.2 + 0.6 * random.random()), "y": -10.0 - random.random() * 60,
                "vx": random.uniform(-90, 90), "vy": random.uniform(80, 260),
                "size": random.uniform(5, 10), "rot": random.uniform(0, 360), "vrot": random.uniform(-420, 420),
                "color": QColor(random.choice(palette)),
            })
        self.age = 0.0
        self._token = clock().subscribe(self._tick, 30)
        self.show()
        self.raise_()

    def _tick(self, dt):
        self.age += dt
        step = dt / 1000.0
        for p in self.pieces:
            p["vy"] += 420 * step
            p["x"] += p["vx"] * step
            p["y"] += p["vy"] * step
            p["rot"] += p["vrot"] * step
        if self.age >= DURATION_MS:
            clock().unsubscribe(self._token)
            self.hide()
            self.deleteLater()
            return
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        fade = 1.0 if self.age < DURATION_MS * 0.7 else max(0.0, 1.0 - (self.age - DURATION_MS * 0.7) / (DURATION_MS * 0.3))
        for piece in self.pieces:
            c = QColor(piece["color"])
            c.setAlphaF(fade)
            p.setBrush(c)
            p.save()
            p.translate(piece["x"], piece["y"])
            p.rotate(piece["rot"])
            s = piece["size"]
            p.drawRect(QRectF(-s / 2, -s / 4 * (1 + abs(math.sin(piece["rot"] / 40))), s, s / 2))
            p.restore()


def celebrate(window: QWidget, fallback=None):
    """Confeti si el movimiento es «Completas»; si no, se llama a `fallback()` (por ejemplo un destello)."""
    if motion.full() and window.isVisible():
        Confetti(window)
    elif fallback is not None:
        fallback()
