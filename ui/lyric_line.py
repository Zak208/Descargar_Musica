"""Una línea de letra: se oscurece al terminar de leerla, se subraya al pasar el ratón y al pulsarla salta a ese momento."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy

COLORS = {
    "past": "rgba(255, 255, 255, 0.34)",     # ya leída: apagada
    "idle": "#D2D2D2",                        # todavía no ha sonado
    "active": "#FFFFFF",                      # la que suena ahora
}


class LyricLine(QLabel):
    def __init__(self, ms: int, text: str, on_seek=None, size: int = 19, pad: str = "0px", parent=None):
        super().__init__(text, parent)
        self.ms = ms
        self.on_seek = on_seek
        self.size = size
        self.pad = pad
        self.state = "idle"
        self._hover = False
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        if on_seek is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Pulsa para ir a este momento de la canción")
        self._restyle()

    def set_state(self, state: str):
        if state != self.state:
            self.state = state
            self._restyle()

    def set_size(self, size: int):
        if size != self.size:
            self.size = size
            self._restyle()

    def _restyle(self):
        # mismo tamaño y grosor en todos los estados: así la frase no cambia de forma al pasar de una a otra
        self.setStyleSheet(f"color: {COLORS[self.state]}; font-size: {self.size}px; font-weight: 800; "
                           f"background: transparent; padding: {self.pad};")
        font = self.font()
        font.setUnderline(self._hover and self.on_seek is not None)
        self.setFont(font)

    def enterEvent(self, event):
        self._hover = True
        self._restyle()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._restyle()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.on_seek is not None:
            self.on_seek(self.ms)
            event.accept()
            return
        super().mousePressEvent(event)
