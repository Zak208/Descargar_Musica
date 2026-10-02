"""Perfil de artista estilo Spotify: foto, seguir, populares, álbumes y 'los fans también escuchan'."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea

from services.artist_service import ArtistService
from services.recommendation_service import RelatedArtistsWorker
from ui.animations import fade_in
from ui.controls import CoverLabel, FollowButton
from ui.loading import LoadingBlock
from ui.scrolling import BackToTop, polish_scroll_area
from ui.textfx import reveal_up
from ui.covers import artist_avatar_pixmap, artist_avatar_path
from ui.home_shelves import ArtistTile, make_shelf, clear_layout
from ui.icons import icon
from ui.track_row import TrackRow
from ui.imageloader import ImageLoaderThread
from ui.spotify_views import AlbumCard
from ui.styles import accent

AVATAR = 168


class ArtistProfilePage(QWidget):
    back_clicked = Signal()
    album_selected = Signal(int)
    download_all_requested = Signal(list)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.artist_data = {}
        self._related_worker = None
        self._loader = None
        self.init_ui()

    # ------------------------------------------------------------------ UI
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

        # Cabecera (el estilo solo afecta a este marco, no a lo que lleva dentro)
        self.header_frame = QFrame()
        self.header_frame.setObjectName("ArtistHeader")
        h = QHBoxLayout(self.header_frame)
        h.setContentsMargins(28, 28, 28, 28)
        h.setSpacing(28)

        self.avatar_lbl = CoverLabel(radius=AVATAR // 2, placeholder="#00000000")
        self.avatar_lbl.setFixedSize(AVATAR, AVATAR)
        self.avatar_lbl.setPixmap(artist_avatar_pixmap("x", AVATAR))
        h.addWidget(self.avatar_lbl)

        info = QVBoxLayout()
        info.setAlignment(Qt.AlignVCenter)
        info.setSpacing(6)
        badge = QLabel("ARTISTA")
        badge.setObjectName("SectionSubtitle")
        badge.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 1px; background: transparent;")
        self.name_lbl = QLabel("Artista")
        self.name_lbl.setStyleSheet("font-size: 44px; font-weight: bold; background: transparent;")
        self.name_lbl.setWordWrap(True)
        self.meta_lbl = QLabel("")
        self.meta_lbl.setObjectName("SectionSubtitle")
        self.meta_lbl.setStyleSheet("background: transparent;")
        info.addWidget(badge)
        info.addWidget(self.name_lbl)
        info.addWidget(self.meta_lbl)
        h.addLayout(info, stretch=1)
        self.content_layout.addWidget(self.header_frame)

        # Acciones
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.btn_play = QPushButton("")
        self.btn_play.setObjectName("BigPlayBtn")
        self.btn_play.setIcon(icon("play_black.svg"))
        self.btn_play.setIconSize(QSize(24, 24))
        self.btn_play.setToolTip("Reproducir lo más popular")
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.clicked.connect(self._play_popular)
        actions.addWidget(self.btn_play)

        self.btn_follow = FollowButton("Seguir")
        self.btn_follow.setObjectName("FollowBtn")
        self.btn_follow.setCheckable(True)
        self.btn_follow.setCursor(Qt.PointingHandCursor)
        self.btn_follow.clicked.connect(self._toggle_follow)
        actions.addWidget(self.btn_follow)

        self.btn_download_top = QPushButton(" Descargar lo más popular")
        self.btn_download_top.setObjectName("DownloadBtn")
        self.btn_download_top.setIcon(icon("download_black.svg"))
        self.btn_download_top.setIconSize(QSize(16, 16))
        self.btn_download_top.setCursor(Qt.PointingHandCursor)
        self.btn_download_top.clicked.connect(self._on_download_top)
        actions.addWidget(self.btn_download_top)
        actions.addStretch()
        self.content_layout.addLayout(actions)

        # Populares
        top_title = QLabel("Populares")
        top_title.setObjectName("SectionTitle")
        self.content_layout.addWidget(top_title)
        self.tracks_widget = QWidget()
        self.tracks_container = QVBoxLayout(self.tracks_widget)
        self.tracks_container.setContentsMargins(0, 0, 0, 0)
        self.tracks_container.setSpacing(2)
        self.content_layout.addWidget(self.tracks_widget)

        # Álbumes
        self.albums_box, self.albums_layout = make_shelf("Álbumes", 258)
        self.content_layout.addWidget(self.albums_box)

        # Los fans también escuchan
        self.related_box, self.related_layout = make_shelf("Los fans también escuchan", 238)
        self.related_box.setVisible(False)
        self.content_layout.addWidget(self.related_box)
        self.content_layout.addStretch()

        scroll.setWidget(content)
        main.addWidget(scroll, stretch=1)
        self.back_top = BackToTop(scroll, self)

    # --------------------------------------------------------------- datos
    def start_loading(self, name: str):
        """Estado inicial mientras llegan los datos del artista."""
        self.artist_data = {}
        self.name_lbl.setText(name)
        self.meta_lbl.setText("Cargando...")
        clear_layout(self.tracks_container)
        self.tracks_container.addWidget(LoadingBlock("Cargando las canciones...", skeleton=True))
        clear_layout(self.albums_layout)
        clear_layout(self.related_layout)
        self.related_box.setVisible(False)
        self.avatar_lbl.setPixmap(artist_avatar_pixmap("x", AVATAR))
        self.btn_follow.setEnabled(False)

    def load_artist_data(self, data: dict, main_window):
        self.artist_data = data
        name = data.get("name", "Artista")
        self.name_lbl.setText(name)
        tracks = data.get("top_tracks", [])
        albums = data.get("albums", [])
        n_t = len(tracks)
        n_a = len(albums)
        self.meta_lbl.setText(f"{n_t} canciones populares  ·  {n_a} álbumes")

        # Color de la cabecera según el tema
        c = QColor(accent())
        self.header_frame.setStyleSheet(
            "#ArtistHeader { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 rgba({c.red()}, {c.green()}, {c.blue()}, 110), stop:1 rgba({c.red()}, {c.green()}, {c.blue()}, 0));"
            " border-radius: 16px; }"
        )

        # Foto
        art_id = data.get("id")
        self.avatar_lbl.setPixmap(artist_avatar_pixmap(art_id, AVATAR))
        url = data.get("avatar")
        import os
        if url and not os.path.exists(artist_avatar_path(art_id)):
            self._loader = ImageLoaderThread(url, True, (AVATAR, AVATAR))
            self._loader.image_loaded.connect(self._set_avatar)
            self._loader.start()

        self._update_follow_button()
        self.btn_follow.setEnabled(True)
        self.btn_play.setEnabled(bool(tracks))
        self.btn_download_top.setEnabled(bool(tracks))

        clear_layout(self.tracks_container)
        for i, item in enumerate(tracks):
            self.tracks_container.addWidget(TrackRow(item, main_window, number=i + 1, list_mode=False))

        clear_layout(self.albums_layout)
        for alb in albums:
            card = AlbumCard(alb)
            card.clicked.connect(self.album_selected.emit)
            self.albums_layout.addWidget(card)
        self.albums_box.setVisible(bool(albums))
        fade_in(self.header_frame, 300)
        reveal_up(self.name_lbl, 60)

        # Artistas parecidos (en segundo plano)
        self.related_box.setVisible(False)
        self._related_worker = RelatedArtistsWorker(name)
        self._related_worker.ready.connect(lambda items, n=name: self._show_related(items, n))
        self._related_worker.start()

    def _set_avatar(self, pix):
        try:
            self.avatar_lbl.setPixmap(pix)
            from ui.now_playing import cover_color
            color = cover_color(pix)
            if color is not None:
                self.header_frame.setStyleSheet(
                    "#ArtistHeader { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                    f" stop:0 rgba({color.red()}, {color.green()}, {color.blue()}, 150),"
                    f" stop:1 rgba({color.red()}, {color.green()}, {color.blue()}, 0)); border-radius: 16px; }}")
                fade_in(self.header_frame, 400)
        except RuntimeError:
            pass

    def _show_related(self, items: list, for_name: str):
        if for_name != self.artist_data.get("name"):
            return
        clear_layout(self.related_layout)
        for art in items:
            tile = ArtistTile(art)
            tile.clicked.connect(self.window_ref.open_artist_by_name)
            self.related_layout.addWidget(tile)
        self.related_box.setVisible(bool(items))

    # ------------------------------------------------------------ acciones
    def _update_follow_button(self):
        following = ArtistService.is_following(self.artist_data.get("id"))
        self.btn_follow.setChecked(following)
        self.btn_follow.setText("Siguiendo" if following else "Seguir")

    def _toggle_follow(self):
        if not self.artist_data:
            return
        self.window_ref.toggle_follow_artist(
            self.artist_data.get("id"), self.artist_data.get("name", ""), self.artist_data.get("avatar", ""))
        self._update_follow_button()

    def _play_popular(self):
        tracks = self.artist_data.get("top_tracks", [])
        if tracks:
            self.window_ref.play_list(tracks, 0)

    def _on_download_top(self):
        tracks = self.artist_data.get("top_tracks", [])
        if tracks:
            self.download_all_requested.emit(tracks)
