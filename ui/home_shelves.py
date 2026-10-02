"""Piezas de la página de inicio y de los perfiles de artista: tarjetas de canción, artista, mix y accesos rápidos."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from services.playlist_service import PlaylistService
from ui.animations import reveal_widget
from ui.controls import CoverLabel
from ui.hover import GlowHover
from ui.covers import list_cover_pixmap, artist_avatar_pixmap, mix_cover, GENRE_COLORS
from ui.formatting import format_total
from ui.icons import icon
from ui.save_popup import save_icon
from ui.imageloader import ImageLoaderThread
from ui.spotify_views import HorizontalCarouselScrollArea
from ui.styles import accent
from ui.widgets import ElidedLabel

TILE_W = 164
COVER = 140


def make_shelf(title: str, height: int, subtitle: str = ""):
    """Sección horizontal estilo Spotify: título, flechas para moverse y carrusel. Devuelve (contenedor, layout)."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 8, 0, 0)
    lay.setSpacing(2)

    head = QHBoxLayout()
    head.setContentsMargins(0, 0, 4, 0)
    texts = QVBoxLayout()
    texts.setSpacing(2)
    title_lbl = QLabel(title)
    title_lbl.setObjectName("SectionTitle")
    texts.addWidget(title_lbl)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("SectionSubtitle")
        texts.addWidget(sub)
    head.addLayout(texts)
    head.addStretch()
    btn_prev = QPushButton("")
    btn_next = QPushButton("")
    for btn, name in ((btn_prev, "chevron_left.svg"), (btn_next, "chevron_right.svg")):
        btn.setObjectName("ArrowBtn")
        btn.setIcon(icon(name))
        btn.setIconSize(QSize(16, 16))
        btn.setCursor(Qt.PointingHandCursor)
        head.addWidget(btn)
    lay.addLayout(head)

    scroll = HorizontalCarouselScrollArea()
    scroll.setFixedHeight(height)
    inner = QWidget()
    inner.setObjectName("ShelfInner")
    inner.setStyleSheet("#ShelfInner { background: transparent; }")
    row = QHBoxLayout(inner)
    row.setContentsMargins(0, 6, 0, 8)
    row.setSpacing(12)
    row.setAlignment(Qt.AlignLeft)
    scroll.setWidget(inner)
    lay.addWidget(scroll)

    bar = scroll.horizontalScrollBar()

    def update_arrows(*_):
        overflow = bar.maximum() > bar.minimum()
        btn_prev.setVisible(overflow)
        btn_next.setVisible(overflow)
        btn_prev.setEnabled(bar.value() > bar.minimum())
        btn_next.setEnabled(bar.value() < bar.maximum())

    bar.valueChanged.connect(update_arrows)
    bar.rangeChanged.connect(update_arrows)
    btn_prev.clicked.connect(lambda: scroll.scroll_page(-1))
    btn_next.clicked.connect(lambda: scroll.scroll_page(1))
    update_arrows()
    box.scroll = scroll
    return box, row


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.setParent(None)
            w.deleteLater()


class TrackTile(QFrame, GlowHover):
    """Canción sugerida: portada con botón de reproducir al pasar el ratón, título, artista, me gusta y descargar."""

    def __init__(self, info: dict, window, shelf_tracks: list, parent=None):
        super().__init__(parent)
        self.info = info
        self.window_ref = window
        self.shelf_tracks = shelf_tracks
        self.setObjectName("CoverCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(TILE_W)
        self.init_glow(10)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(2)

        self.cover = CoverLabel(radius=8)
        self.cover.setFixedSize(COVER, COVER)
        self.cover.setStyleSheet("background-color: #2A2A2A; border-radius: 8px;")
        lay.addWidget(self.cover)

        self.play_btn = QPushButton("", self.cover)
        self.play_btn.setObjectName("TilePlayBtn")
        self.play_btn.setIcon(icon("play_black.svg"))
        self.play_btn.setIconSize(QSize(18, 18))
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.move(COVER - 52, COVER - 52)
        self.play_btn.clicked.connect(self.play)
        self.play_btn.hide()

        title = ElidedLabel(info.get("title", "Canción"))
        title.setObjectName("CoverTitle")
        title.setToolTip(info.get("title", ""))
        title.setFixedHeight(22)
        lay.addSpacing(4)
        lay.addWidget(title)
        artist = ElidedLabel(info.get("uploader", ""))
        artist.setObjectName("CoverSub")
        artist.setFixedHeight(18)
        lay.addWidget(artist)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(2)
        actions.addStretch()
        self.heart_btn = QPushButton("")
        self.heart_btn.setObjectName("IconBtn")
        self.heart_btn.setIconSize(QSize(17, 17))
        self.heart_btn.setToolTip("Guardar en una lista")
        self.heart_btn.setCursor(Qt.PointingHandCursor)
        self.heart_btn.clicked.connect(self._toggle_like)
        actions.addWidget(self.heart_btn)
        self.dl_btn = QPushButton("")
        self.dl_btn.setObjectName("IconBtn")
        self.dl_btn.setIconSize(QSize(17, 17))
        self.dl_btn.setCursor(Qt.PointingHandCursor)
        self.dl_btn.clicked.connect(self._download)
        actions.addWidget(self.dl_btn)
        lay.addLayout(actions)
        self.refresh_state()

        url = info.get("thumbnail")
        if url:
            self._loader = ImageLoaderThread(url, False, (COVER, COVER))
            self._loader.image_loaded.connect(self._set_cover)
            self._loader.start()

    # ------------------------------------------------------------ estado
    def refresh_state(self):
        saved = bool(PlaylistService.lists_containing(self.info))
        self.heart_btn.setIcon(save_icon(saved, "#8A8A8A"))
        local = self.window_ref.resolve_local(self.info)
        if local:
            self.dl_btn.setIcon(icon("check.svg", accent()))
            self.dl_btn.setToolTip("Ya descargada")
        else:
            self.dl_btn.setIcon(icon("download.svg", "#8A8A8A"))
            self.dl_btn.setToolTip("Descargar")
        self._local = local

    def _set_cover(self, pix: QPixmap):
        try:
            self.cover.setPixmap(pix)
        except RuntimeError:
            pass

    # ----------------------------------------------------------- acciones
    def play(self):
        item = dict(self.info)
        if self._local:
            item["local_path"] = self._local
            item["already_downloaded"] = True
        self.window_ref.play_shelf(self.shelf_tracks, item, self.cover.pixmap())

    def _toggle_like(self):
        self.window_ref.save_button_clicked(dict(self.info), self.heart_btn)
        self.refresh_state()

    def _download(self):
        if self._local:
            self.window_ref.notify("Esta canción ya está en tu música")
            return
        self.window_ref.quick_download(dict(self.info))

    def enterEvent(self, event):
        reveal_widget(self.play_btn, True)          # el ▶ sube y aparece
        self.cover.zoom_hover(True)
        self.glow_to(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        reveal_widget(self.play_btn, False)
        self.cover.zoom_hover(False)
        self.glow_to(False)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self.glow_move(event)
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        self.paint_glow()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.cover.geometry().translated(self.layout().contentsMargins().left(),
                                                                              self.layout().contentsMargins().top()).contains(ev.pos()):
            self.play()
        super().mouseReleaseEvent(ev)

    def contextMenuEvent(self, ev):
        self.window_ref.open_track_menu(self.info, ev.globalPos())


class ArtistTile(QFrame, GlowHover):
    """Artista con foto redonda. Emite sus datos al hacer clic."""
    clicked = Signal(dict)

    def __init__(self, artist: dict, parent=None):
        super().__init__(parent)
        self.artist = artist
        self.setObjectName("CoverCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(TILE_W)
        self.init_glow(10)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(2)

        self.avatar = CoverLabel(radius=COVER // 2, placeholder="#00000000")
        self.avatar.setFixedSize(COVER, COVER)
        self.avatar.setPixmap(artist_avatar_pixmap(artist.get("id", "x"), COVER))
        lay.addWidget(self.avatar)
        lay.addSpacing(6)
        name = ElidedLabel(artist.get("name", "Artista"))
        name.setObjectName("CoverTitle")
        name.setToolTip(artist.get("name", ""))
        name.setFixedHeight(22)
        lay.addWidget(name)
        sub = QLabel("Artista")
        sub.setObjectName("CoverSub")
        lay.addWidget(sub)

        url = artist.get("avatar") or artist.get("picture")
        from ui.covers import artist_avatar_path
        import os
        if url and not os.path.exists(artist_avatar_path(artist.get("id", "x"))):
            self._loader = ImageLoaderThread(url, True, (COVER, COVER))
            self._loader.image_loaded.connect(self._set_avatar)
            self._loader.start()

    def _set_avatar(self, pix: QPixmap):
        try:
            self.avatar.setPixmap(pix)
        except RuntimeError:
            pass

    def enterEvent(self, event):
        self.avatar.zoom_hover(True)
        self.glow_to(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.avatar.zoom_hover(False)
        self.glow_to(False)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self.glow_move(event)
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        self.paint_glow()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit(self.artist)
        super().mouseReleaseEvent(ev)


class MixTile(QFrame, GlowHover):
    """Mix hecho a partir de tus gustos: portada de color, nombre, artistas que lo forman y duración."""
    clicked = Signal(dict)

    def __init__(self, mix: dict, index: int, parent=None):
        super().__init__(parent)
        self.mix = mix
        self.setObjectName("CoverCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(TILE_W)
        self.init_glow(10)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(2)
        self.cover = CoverLabel(radius=10)
        self.cover.setFixedSize(COVER, COVER)
        self.cover.setPixmap(mix_cover(index, COVER, 10))
        lay.addWidget(self.cover)
        lay.addSpacing(6)
        title = ElidedLabel(mix.get("name", "Mix"))
        title.setObjectName("CoverTitle")
        title.setFixedHeight(22)
        lay.addWidget(title)
        artists = mix.get("artists", [])
        names = ", ".join(artists[:2]) + (" y más" if len(artists) > 2 else "")
        tracks = mix.get("tracks", [])
        total = format_total(sum(int(t.get("duration_secs", 0) or 0) for t in tracks))
        info = f"{len(tracks)} canciones" + (f" · {total}" if total else "")
        sub = QLabel(f"{names}\n{info}" if names else info)
        sub.setObjectName("CoverSub")
        sub.setWordWrap(True)
        sub.setFixedHeight(50)
        sub.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(sub)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit(self.mix)
        super().mouseReleaseEvent(ev)

    def enterEvent(self, event):
        self.cover.zoom_hover(True)
        self.glow_to(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.cover.zoom_hover(False)
        self.glow_to(False)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self.glow_move(event)
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        self.paint_glow()


class GenreTile(QFrame):
    """Género musical para explorar: rectángulo de color con su nombre."""
    clicked = Signal(dict)

    def __init__(self, genre: dict, index: int, parent=None):
        super().__init__(parent)
        self.genre = genre
        self.index = index
        self.setObjectName("GenreTile")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(TILE_W, 96)
        color = GENRE_COLORS[index % len(GENRE_COLORS)]
        self.setStyleSheet(f"#GenreTile {{ background-color: {color}; border-radius: 10px; border: 2px solid transparent; }}"
                           "#GenreTile:hover { border: 2px solid rgba(255, 255, 255, 0.9); }")
        self.setProperty("noRetheme", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        name = QLabel(genre.get("name", ""))
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 16px; font-weight: 700; color: #FFFFFF; background: transparent;")
        lay.addWidget(name, alignment=Qt.AlignTop | Qt.AlignLeft)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit(dict(self.genre, index=self.index))
        super().mouseReleaseEvent(ev)


class QuickTile(QFrame):
    """Acceso rápido de la parte superior de Inicio (como los de Spotify): portada pequeña y nombre."""
    clicked = Signal()

    def __init__(self, kind: str, list_id, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("QuickTile")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(60)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(12)
        cover = QLabel()
        cover.setFixedSize(60, 60)
        cover.setPixmap(list_cover_pixmap(kind, list_id, 60, 8 if kind != "artist" else 30))
        lay.addWidget(cover)
        name = ElidedLabel(title)
        name.setObjectName("SideItemTitle")
        lay.addWidget(name, stretch=1)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)
