"""«¿Se ve bien?»: tras un cambio que podría dejar la pantalla ilegible (el alto contraste), la aplicación pregunta y, si
nadie responde en 10 segundos, lo deshace sola (como hace Windows con la resolución de pantalla)."""
from PySide6.QtCore import Qt, QRectF, QTimer, QVariantAnimation
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from ui.overlay import InlineDialog
from ui.styles import accent


class _Countdown(QWidget):
    def __init__(self, seconds: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.seconds = seconds
        self.left = float(seconds)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(float(seconds))
        self._anim.setEndValue(0.0)
        self._anim.setDuration(seconds * 1000)
        self._anim.valueChanged.connect(self._on_value)

    def start(self):
        self._anim.start()

    def stop(self):
        self._anim.stop()

    def _on_value(self, v):
        self.left = float(v)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(5, 5, -5, -5)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40), 5))
        p.drawEllipse(r)
        pen = QPen(QColor(accent()), 5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 90 * 16, int(-360 * 16 * (self.left / self.seconds)))
        p.setPen(QColor("#FFFFFF"))
        font = self.font()
        font.setBold(True)
        font.setPointSize(14)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, str(int(self.left) + 1 if self.left > 0 else 0))


class KeepChangeDialog(InlineDialog):
    def __init__(self, window, text: str, seconds: int = 10):
        super().__init__(window, closable=False)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(14)
        title = QLabel("¿Se ve bien?")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.ring = _Countdown(seconds)
        row.addWidget(self.ring)
        body = QLabel(text + f"\n\nSi no respondes, se deshará solo en {seconds} segundos.")
        body.setWordWrap(True)
        body.setObjectName("SectionSubtitle")
        row.addWidget(body, stretch=1)
        lay.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addStretch()
        revert = QPushButton("Deshacer")
        revert.setCursor(Qt.PointingHandCursor)
        revert.clicked.connect(self.reject)
        buttons.addWidget(revert)
        keep = QPushButton("Mantener")
        keep.setObjectName("GiantActionBtn")
        keep.setDefault(True)
        keep.setCursor(Qt.PointingHandCursor)
        keep.clicked.connect(self.accept)
        buttons.addWidget(keep)
        lay.addLayout(buttons)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(seconds * 1000)
        self._timer.timeout.connect(self.reject)

    def showEvent(self, event):
        self.ring.start()
        self._timer.start()
        super().showEvent(event)

    def done(self, result: int):
        self._timer.stop()
        self.ring.stop()
        super().done(result)


def ask_keep_change(window, text: str, seconds: int = 10) -> bool:
    """True si se mantiene el cambio; False si se pulsa «Deshacer» o se acaba el tiempo."""
    return KeepChangeDialog(window, text, seconds).exec() == 1
