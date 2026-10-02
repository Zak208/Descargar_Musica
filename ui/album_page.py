"""Página de un álbum: portada, reproducir, descargar el álbum entero o descargarlo y crear una lista con él."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea

from ui.animations import fade_in
from ui.controls import CoverLabel
from ui.loading import LoadingBlock
from ui.scrolling import BackToTop, polish_scroll_area
from ui.textfx import reveal_up
from ui.formatting import format_total
from ui.home_shelves import clear_layout
from ui.icons import icon
from ui.imageloader import ImageLoaderThread
from ui.track_row import TrackRow
from ui.styles import accent

COVER = 168




class AlbumDetailsPage(QWidget):
    back_clicked = Signal()
    download_all_requested = Signal(list)
    save_list_requested = Signal(dict)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.album_data = {}
        self._loader = None
        self.init_ui()

    def init_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(14)

        nav = QHBoxLayout()
        self.btn_back = QPushButton(" Volver")
        self.btn_back.setIcon(icon("prev.svg"))
        self.btn_back.setIconSize(QSize(14, 14))
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.clicked.connect(self.back_clicked.emit)
        nav.addWidget(self.btn_back)
        nav.addStretch()
        main.addLayout(nav)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        polish_scroll_area(scroll)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 8, 20)
        self.content_layout.setSpacing(18)

        self.header_frame = QFrame()
        self.header_frame.setObjectName("AlbumHeader")
        h = QHBoxLayout(self.header_frame)
        h.setContentsMargins(28, 28, 28, 28)
        h.setSpacing(28)

        self.cover_lbl = CoverLabel(radius=8, placeholder="#202020")
        self.cover_lbl.setFixedSize(COVER, COVER)
        self.cover_lbl.setStyleSheet("background-color: #202020; border-radius: 8px;")
        h.addWidget(self.cover_lbl)

        info = QVBoxLayout()
        info.setAlignment(Qt.AlignVCenter)
        info.setSpacing(6)
        badge = QLabel("ÁLBUM")
        badge.setObjectName("SectionSubtitle")
        badge.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 1px; background: transparent;")
        self.title_lbl = QLabel("Álbum")
        self.title_lbl.setStyleSheet("font-size: 36px; font-weight: bold; background: transparent;")
        self.title_lbl.setWordWrap(True)
        self.meta_lbl = QLabel("")
        self.meta_lbl.setObjectName("SectionSubtitle")
        self.meta_lbl.setStyleSheet("background: transparent;")
        info.addWidget(badge)
        info.addWidget(self.title_lbl)
        info.addWidget(self.meta_lbl)
        h.addLayout(info, stretch=1)
        self.content_layout.addWidget(self.header_frame)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.btn_play = QPushButton("")
        self.btn_play.setObjectName("BigPlayBtn")
        self.btn_play.setIcon(icon("play_black.svg"))
        self.btn_play.setIconSize(QSize(24, 24))
        self.btn_play.setToolTip("Reproducir el álbum")
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.clicked.connect(self._play)
        actions.addWidget(self.btn_play)

        self.btn_download_album = QPushButton(" Descargar álbum completo")
        self.btn_download_album.setObjectName("DownloadBtn")
        self.btn_download_album.setIcon(icon("download_black.svg"))
        self.btn_download_album.setIconSize(QSize(16, 16))
        self.btn_download_album.setCursor(Qt.PointingHandCursor)
        self.btn_download_album.clicked.connect(self._on_download_album)
        actions.addWidget(self.btn_download_album)

        self.btn_save_list = QPushButton(" Descargar y crear lista")
        self.btn_save_list.setIcon(icon("playlist.svg"))
        self.btn_save_list.setIconSize(QSize(16, 16))
        self.btn_save_list.setToolTip("Descarga todo el álbum y crea una lista nueva con sus canciones")
        self.btn_save_list.setCursor(Qt.PointingHandCursor)
        self.btn_save_list.clicked.connect(lambda: self.save_list_requested.emit(self.album_data))
        actions.addWidget(self.btn_save_list)
        actions.addStretch()
        self.content_layout.addLayout(actions)

        title = QLabel("Canciones del álbum")
        title.setObjectName("SectionTitle")
        self.content_layout.addWidget(title)
        self.tracks_widget = QWidget()
        self.tracks_container = QVBoxLayout(self.tracks_widget)
        self.tracks_container.setContentsMargins(0, 0, 0, 0)
        self.tracks_container.setSpacing(2)
        self.content_layout.addWidget(self.tracks_widget)
        self.content_layout.addStretch()

        scroll.setWidget(content)
        main.addWidget(scroll, stretch=1)
        self.back_top = BackToTop(scroll, self)

    def start_loading(self):
        self.album_data = {}
        self.title_lbl.setText("Cargando álbum...")
        self.meta_lbl.setText("")
        clear_layout(self.tracks_container)
        self.tracks_container.addWidget(LoadingBlock("Cargando las canciones...", skeleton=True))
        self.cover_lbl.clear()
        for b in (self.btn_play, self.btn_download_album, self.btn_save_list):
            b.setEnabled(False)

    def load_album_data(self, data: dict, main_window):
        self.album_data = data
        self.title_lbl.setText(data.get("name", "Álbum"))
        tracks = data.get("tracks", [])
        total = sum(int(t.get("duration_secs", 0) or 0) for t in tracks)
        parts = [data.get("artist", ""), data.get("year", ""), f"{len(tracks)} canciones"]
        if total:
            parts.append(format_total(total))
        self.meta_lbl.setText("  ·  ".join(p for p in parts if p))

        c = QColor(accent())
        self.header_frame.setStyleSheet(
            "#AlbumHeader { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 rgba({c.red()}, {c.green()}, {c.blue()}, 90), stop:1 rgba({c.red()}, {c.green()}, {c.blue()}, 0));"
            " border-radius: 16px; }"
        )
        cover_url = data.get("cover")
        if cover_url:
            self._loader = ImageLoaderThread(cover_url, False, (COVER, COVER), 8)
            self._loader.image_loaded.connect(self.cover_lbl.setPixmap)
            self._loader.start()

        for b in (self.btn_play, self.btn_download_album, self.btn_save_list):
            b.setEnabled(bool(tracks))
        clear_layout(self.tracks_container)
        for i, item in enumerate(tracks):
            self.tracks_container.addWidget(TrackRow(item, main_window, number=int(item.get("track_number") or i + 1),
                                                      list_mode=False))
        fade_in(self.header_frame, 300)
        reveal_up(self.title_lbl, 60)

    def _play(self):
        tracks = self.album_data.get("tracks", [])
        if tracks:
            self.window_ref.play_list(tracks, 0)

    def _on_download_album(self):
        tracks = self.album_data.get("tracks", [])
        if tracks:
            self.download_all_requested.emit(tracks)
