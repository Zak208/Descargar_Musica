"""Widgets de la pantalla de inicio: tarjetas de portada y carga de canciones recientes."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel

from ui.imageloader import LocalCoverLoader
from ui.widgets import ElidedLabel

CARD_COVER = 140


class RecentTrackCard(QFrame):
    """Tarjeta cuadrada con portada, título y artista de una canción de tu biblioteca. Emite la ruta al pulsarla."""
    clicked = Signal(str)

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.path = info["local_path"]
        self.setObjectName("CoverCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(CARD_COVER + 24)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)

        self.cover = QLabel()
        self.cover.setFixedSize(CARD_COVER, CARD_COVER)
        self.cover.setStyleSheet("background-color: #2A2A2A; border-radius: 8px;")
        lay.addWidget(self.cover)

        t = ElidedLabel(info.get("title", ""))
        t.setObjectName("CoverTitle")
        t.setToolTip(info.get("title", ""))
        t.setFixedHeight(20)
        lay.addWidget(t)
        a = ElidedLabel(info.get("uploader", ""))
        a.setObjectName("CoverSub")
        a.setFixedHeight(18)
        lay.addWidget(a)

        # la carátula se lee en segundo plano (no bloquea la pantalla)
        self._loader = LocalCoverLoader(self.path, False, (CARD_COVER, CARD_COVER), 8)
        self._loader.image_loaded.connect(self._set_cover)
        self._loader.start()

    def _set_cover(self, pix):
        try:
            self.cover.setPixmap(pix)
        except RuntimeError:
            pass

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit(self.path)
        super().mouseReleaseEvent(ev)
