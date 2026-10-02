"""«Seguir escuchando»: en Inicio, la canción que sonaba cuando cerraste la aplicación, con una barra fina que enseña el
punto exacto en que ibas y un botón para retomarla."""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget

from ui.controls import CoverLabel
from ui.covers import placeholder_cover
from ui.icons import icon
from ui.imageloader import LocalCoverLoader
from ui.styles import accent
from ui.widgets import ElidedLabel

COVER = 72


class _ThinBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self.fraction = 0.0

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(self.rect(), 2, 2)
        p.setBrush(QColor(accent()))
        p.drawRoundedRect(0, 0, int(self.width() * max(0.0, min(1.0, self.fraction))), self.height(), 2, 2)


class ContinueCard(QFrame):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.setObjectName("CoverCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 18, 12)
        lay.setSpacing(16)
        self.cover = CoverLabel(radius=8)
        self.cover.setFixedSize(COVER, COVER)
        lay.addWidget(self.cover)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        head = QLabel("SEGUIR ESCUCHANDO")
        head.setObjectName("SectionSubtitle")
        head.setStyleSheet("font-size: 11px; font-weight: 800; letter-spacing: 1px; background: transparent;")
        texts.addWidget(head)
        self.title = ElidedLabel("")
        self.title.setObjectName("CoverTitle")
        self.title.setStyleSheet("font-size: 18px; background: transparent;")
        texts.addWidget(self.title)
        self.artist = ElidedLabel("")
        self.artist.setObjectName("CoverSub")
        texts.addWidget(self.artist)
        self.bar = _ThinBar()
        texts.addWidget(self.bar)
        lay.addLayout(texts, stretch=1)
        self.btn = QPushButton(" Seguir")
        self.btn.setObjectName("GiantActionBtn")
        self.btn.setIcon(icon("play_black.svg"))
        self.btn.setIconSize(QSize(16, 16))
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self._resume)
        lay.addWidget(self.btn)
        self._loader = None
        self._path = None
        self.setVisible(False)

    def refresh(self):
        """Se muestra solo si hay una canción cargada y en pausa que viene de la sesión anterior."""
        w = self.window_ref
        info = w.current_item_info
        show = bool(info and info.get("local_path") and getattr(w, "_resume_pending", False) and not w.is_playing_now())
        if not show:
            self.setVisible(False)
            return
        path = info["local_path"]
        if path != self._path:
            self._path = path
            self.title.setText(info.get("title", ""))
            self.artist.setText(info.get("uploader", ""))
            self.cover.setPixmap(placeholder_cover(info.get("title", ""), COVER, 8))
            if os.path.isfile(path):
                self._loader = LocalCoverLoader(path, False, (COVER, COVER), 8)
                self._loader.image_loaded.connect(self._cover_ready)
                self._loader.start()
        duration = w.player.duration() or int(info.get("duration_secs", 0) or 0) * 1000
        self.bar.fraction = (w.player.position() / duration) if duration > 0 else 0.0
        self.bar.update()
        self.setVisible(True)

    def _cover_ready(self, pix):
        try:
            self.cover.setPixmap(pix)
        except RuntimeError:
            pass

    def _resume(self):
        self.window_ref._resume_pending = False
        self.window_ref.toggle_play_pause()
        self.setVisible(False)
