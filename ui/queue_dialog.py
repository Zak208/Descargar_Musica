"""Siguientes canciones: lo que suena ahora, la cola que has añadido y lo que viene en la lista."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea, QWidget
)

from ui.icons import icon
from ui.overlay import InlineDialog
from ui.widgets import ElidedLabel


class QueueDialog(InlineDialog):
    play_item_requested = Signal(dict)
    queue_updated = Signal()

    def __init__(self, current_track: dict, queue_tracks: list, upcoming: list = None, parent=None):
        super().__init__(parent)
        self.current_track = current_track
        self.queue_tracks = queue_tracks
        self.upcoming = upcoming or []
        self.setWindowTitle("Siguientes canciones")
        self.setMinimumSize(520, 560)
        self.init_ui()

    # ---------------------------------------------------------------- UI
    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SettingsLabel")
        lbl.setStyleSheet("font-size: 14px; margin-top: 6px;")
        return lbl

    def _row(self, item: dict, removable: bool) -> QFrame:
        row = QFrame()
        row.setObjectName("ResultCard")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = ElidedLabel(item.get("title", "Canción"))
        title.setObjectName("SongTitle")
        title.setStyleSheet("font-size: 14px;")
        artist = ElidedLabel(item.get("uploader", ""))
        artist.setObjectName("ArtistName")
        artist.setStyleSheet("font-size: 12px;")
        texts.addWidget(title)
        texts.addWidget(artist)
        lay.addLayout(texts, stretch=1)

        btn_play = QPushButton("")
        btn_play.setObjectName("IconBtn")
        btn_play.setIcon(icon("play.svg"))
        btn_play.setIconSize(QSize(16, 16))
        btn_play.setToolTip("Reproducir ahora")
        btn_play.setCursor(Qt.PointingHandCursor)
        btn_play.clicked.connect(lambda _=False, it=item: self._play_now(it))
        lay.addWidget(btn_play)

        if removable:
            btn_del = QPushButton("")
            btn_del.setObjectName("IconBtn")
            btn_del.setIcon(icon("x.svg", "#B3B3B3"))
            btn_del.setIconSize(QSize(16, 16))
            btn_del.setToolTip("Quitar de la cola")
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.clicked.connect(lambda _=False, it=item: self._remove_item(it))
            lay.addWidget(btn_del)
        return row

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(10)

        title = QLabel("Siguientes canciones")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignTop)

        # Sonando ahora
        lay.addWidget(self._section("Sonando ahora"))
        if self.current_track:
            now = self._row(self.current_track, False)
            for b in now.findChildren(QPushButton):
                b.setVisible(False)
            lay.addWidget(now)
        else:
            lay.addWidget(self._hint("No hay ninguna canción sonando."))

        # Cola manual
        head = QHBoxLayout()
        head.addWidget(self._section(f"En tu cola ({len(self.queue_tracks)})"))
        head.addStretch()
        if self.queue_tracks:
            btn_clear = QPushButton("Vaciar cola")
            btn_clear.setCursor(Qt.PointingHandCursor)
            btn_clear.clicked.connect(self._clear_queue)
            head.addWidget(btn_clear)
        lay.addLayout(head)
        if self.queue_tracks:
            for item in self.queue_tracks:
                lay.addWidget(self._row(item, True))
        else:
            lay.addWidget(self._hint("Vacía. Para añadir canciones usa el botón «+» o el clic derecho sobre una canción."))

        # Lo que viene de la lista
        if self.upcoming:
            lay.addWidget(self._section("A continuación en la lista"))
            for item in self.upcoming:
                lay.addWidget(self._row(item, False))

        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        btn_close = QPushButton("Cerrar")
        btn_close.setObjectName("GiantActionBtn")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        root.addWidget(btn_close, alignment=Qt.AlignRight)

    def _hint(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionSubtitle")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("padding: 6px 2px;")
        return lbl

    # ------------------------------------------------------------ acciones
    def _play_now(self, item):
        if item in self.queue_tracks:
            self.queue_tracks.remove(item)
            self.queue_updated.emit()
        self.play_item_requested.emit(item)
        self.accept()

    def _remove_item(self, item):
        if item in self.queue_tracks:
            self.queue_tracks.remove(item)
            self.queue_updated.emit()
            self.accept()

    def _clear_queue(self):
        self.queue_tracks.clear()
        self.queue_updated.emit()
        self.accept()
