"""Tirador para cambiar el ancho del panel «En reproducción» arrastrando con el ratón (como en Spotify): una franja fina entre
el contenido y el panel; al pasar el ratón se marca y el cursor cambia a flechas laterales."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ui.styles import accent

GRIP_WIDTH = 10
PANEL_MIN = 270
PANEL_MAX = 620
PANEL_DEFAULT = 330


def clamp_width(width: int, window_width: int, other_width: int) -> int:
    """El panel no puede ser más estrecho que PANEL_MIN ni más ancho que PANEL_MAX, ni quitarle al contenido el sitio que
    necesita (`other_width` = lo que ocupa todo lo demás de la ventana)."""
    available = window_width - other_width
    return max(PANEL_MIN, min(PANEL_MAX, width, max(PANEL_MIN, available)))


class PanelGrip(QWidget):
    resizing = Signal(int)       # nuevo ancho mientras se arrastra
    finished = Signal(int)       # ancho final al soltar

    def __init__(self, panel: QWidget, window: QWidget, others, parent=None):
        """`others()` devuelve el ancho que ocupa el resto de la ventana (barra lateral, contenido mínimo, márgenes)."""
        super().__init__(parent)
        self.panel, self.window_ref, self._others = panel, window, others
        self.setFixedWidth(GRIP_WIDTH)
        self.setCursor(Qt.SizeHorCursor)
        self.setMouseTracking(True)
        self.setToolTip("Arrastra para cambiar el ancho del panel")
        self._start_x = 0
        self._start_w = 0
        self._hover = False
        self._drag = False

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = True
            self._start_x = event.globalPosition().x()
            self._start_w = self.panel.width()
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag:
            wanted = int(self._start_w + (self._start_x - event.globalPosition().x()))
            width = clamp_width(wanted, self.window_ref.width(), self._others())
            if width != self.panel.width():
                self.panel.setFixedWidth(width)
                self.resizing.emit(width)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag and event.button() == Qt.LeftButton:
            self._drag = False
            self.update()
            self.finished.emit(self.panel.width())
            event.accept()

    def mouseDoubleClickEvent(self, event):
        """Doble clic: vuelve al ancho de siempre."""
        self.panel.setFixedWidth(PANEL_DEFAULT)
        self.resizing.emit(PANEL_DEFAULT)
        self.finished.emit(PANEL_DEFAULT)

    def paintEvent(self, _event):
        if not (self._hover or self._drag):
            return
        p = QPainter(self)
        color = QColor(accent())
        color.setAlpha(200 if self._drag else 120)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(self.width() // 2 - 1, 8, 3, max(0, self.height() - 16), 1.5, 1.5)
