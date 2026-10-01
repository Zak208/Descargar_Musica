"""Fila de canción al estilo Spotify para listas, álbumes y artistas.

Por defecto solo se ve el número, la portada, el título y artista, el álbum, cuándo se añadió y la duración.
  * Al pasar el ratón, el número se convierte en el símbolo de reproducir.
  * Un clic marca la fila y aparecen los tres puntitos (menú); doble clic reproduce la canción.
"""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy

from services.playlist_service import PlaylistService
from ui.formatting import format_added
from ui.icons import icon
from ui.imageloader import ImageLoaderThread, LocalCoverLoader
from ui.styles import accent
from ui.widgets import ElidedLabel

IDX_COL = 40
ROW_COVER = 48
ALBUM_COL = 200
DATE_COL = 110
ICON_COL = 30
DUR_COL = 52
ROW_SPACING = 12

IDLE = "#B3B3B3"
HOT = "#FFFFFF"
_EMPTY = QIcon()


class TrackRow(QFrame):
    def __init__(self, item_info: dict, parent_window, number: int = 1, list_mode: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("TrackRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.item_info = item_info
        self.parent_window = parent_window
        self.number = number
        self.list_mode = list_mode
        self.extra_menu = None
        self.context_provider = None   # función que devuelve la lista completa (para siguiente / anterior)
        self._hot = False
        self._selected = False
        self._playing = False
        self._downloading = False
        self._thumb_loader = None
        self._detect_downloaded()
        self.setProperty("selected", False)
        self.init_ui()
        self.refresh_state()

    # ------------------------------------------------------------------ datos
    def _detect_downloaded(self):
        """Si la canción ya está en tu música, se reproduce desde el disco y se marca como descargada."""
        if self.item_info.get("already_downloaded") and self.item_info.get("local_path"):
            return
        resolver = getattr(self.parent_window, "resolve_local", None)
        if not resolver:
            return
        try:
            path = resolver(self.item_info)
        except Exception:
            path = None
        if path:
            self.item_info = dict(self.item_info, local_path=path, already_downloaded=True)

    # --------------------------------------------------------------------- UI
    def init_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 14, 6)
        lay.setSpacing(ROW_SPACING)

        self.idx_label = QLabel(str(self.number))
        self.idx_label.setObjectName("RowIndex")
        self.idx_label.setFixedWidth(IDX_COL)
        self.idx_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.idx_label)

        self.cover = QLabel()
        self.cover.setFixedSize(ROW_COVER, ROW_COVER)
        self.cover.setStyleSheet("background-color: #2A2A2A; border-radius: 5px;")
        lay.addWidget(self.cover)
        self._load_cover()

        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.setAlignment(Qt.AlignVCenter)
        self.title_label = ElidedLabel(self.item_info.get("title", "Sin título"))
        self.title_label.setObjectName("SongTitle")
        self.title_label.setStyleSheet("font-size: 14px; background: transparent;")
        self.title_label.setToolTip(self.item_info.get("title", ""))
        self.artist_label = ElidedLabel(self.item_info.get("uploader", ""))
        self.artist_label.setObjectName("ArtistName")
        self.artist_label.setStyleSheet("font-size: 12px; background: transparent;")
        texts.addWidget(self.title_label)
        texts.addWidget(self.artist_label)
        lay.addLayout(texts, stretch=1)

        self.album_label = self.date_label = None
        if self.list_mode:
            self.album_label = ElidedLabel(self.item_info.get("album", ""))
            self.album_label.setObjectName("ArtistName")
            self.album_label.setStyleSheet("background: transparent;")
            self.album_label.setFixedWidth(ALBUM_COL)
            self.album_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            self.album_label.setToolTip(self.item_info.get("album", ""))
            lay.addWidget(self.album_label)
            self.date_label = QLabel(format_added(self.item_info.get("_added_ts")))
            self.date_label.setObjectName("ArtistName")
            self.date_label.setStyleSheet("background: transparent;")
            self.date_label.setFixedWidth(DATE_COL)
            lay.addWidget(self.date_label)

        self.heart_btn = self._icon_button("Me gusta", self._toggle_like)
        lay.addWidget(self.heart_btn)
        self.dl_btn = self._icon_button("Descargar", self._download)
        lay.addWidget(self.dl_btn)

        self.duration_label = QLabel(self.item_info.get("duration_str", ""))
        self.duration_label.setObjectName("ArtistName")
        self.duration_label.setStyleSheet("background: transparent;")
        self.duration_label.setFixedWidth(DUR_COL)
        self.duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.duration_label)

        self.more_btn = self._icon_button("Más opciones", self._open_menu)
        lay.addWidget(self.more_btn)

    def _icon_button(self, tip: str, slot) -> QPushButton:
        btn = QPushButton("")
        btn.setObjectName("IconBtn")
        btn.setIconSize(QSize(18, 18))
        btn.setFixedSize(ICON_COL, ICON_COL)
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _load_cover(self):
        url = self.item_info.get("thumbnail")
        local = self.item_info.get("local_path")
        if url:
            loader = ImageLoaderThread(url, False, (ROW_COVER, ROW_COVER), 5)
        elif local and os.path.isfile(local):
            loader = LocalCoverLoader(local, False, (ROW_COVER, ROW_COVER), 5)
        else:
            return
        loader.image_loaded.connect(self._set_cover)
        self._thumb_loader = loader
        loader.start()

    def _set_cover(self, pix):
        try:
            self.cover.setPixmap(pix)
        except RuntimeError:
            pass

    # ------------------------------------------------------------- aspecto
    def refresh_state(self):
        """Pone al día número/símbolo, corazón, descarga y puntitos según el estado de la fila."""
        active = self._hot or self._selected
        color = HOT if active else IDLE

        # número, símbolo de reproducir o indicador de «está sonando»
        if self._hot:
            self.idx_label.setPixmap(icon("play.svg", HOT).pixmap(16, 16))
        elif self._playing:
            self.idx_label.setPixmap(icon("volume.svg", accent()).pixmap(16, 16))
        else:
            self.idx_label.setText(str(self.number))

        liked = PlaylistService.is_favorite(self.item_info.get("id"), self.item_info.get("title"))
        if liked:
            self.heart_btn.setIcon(icon("heart_filled.svg", accent()))
        else:
            self.heart_btn.setIcon(icon("heart.svg", color) if active else _EMPTY)

        local = bool(self.item_info.get("local_path"))
        if local:
            self.dl_btn.setIcon(icon("check_circle.svg", accent()))
            self.dl_btn.setToolTip("Descargada")
            self.dl_btn.setEnabled(False)
        elif self._downloading:
            self.dl_btn.setIcon(icon("clock.svg", accent()))
            self.dl_btn.setToolTip("Descargando…")
            self.dl_btn.setEnabled(False)
        else:
            self.dl_btn.setIcon(icon("download.svg", color) if active else _EMPTY)
            self.dl_btn.setToolTip("Descargar")
            self.dl_btn.setEnabled(True)

        self.more_btn.setIcon(icon("more.svg", HOT) if active else _EMPTY)

    def update_heart_state(self):
        self.refresh_state()

    def set_number(self, number: int):
        if number != self.number:
            self.number = number
            if not self._hot and not self._playing:
                self.idx_label.setText(str(number))

    def set_playing(self, playing: bool):
        """La canción que suena se marca con el color del tema y el símbolo de volumen."""
        if playing == self._playing:
            return
        self._playing = playing
        color = accent() if playing else ""
        self.title_label.setStyleSheet(
            f"font-size: 14px; background: transparent;{(' color: ' + color + ';') if color else ''}")
        self.refresh_state()

    def set_selected(self, selected: bool):
        if selected == self._selected:
            return
        self._selected = selected
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.refresh_state()

    def refresh_date(self):
        if self.date_label is not None:
            self.date_label.setText(format_added(self.item_info.get("_added_ts")))

    def set_columns_visible(self, visible: bool):
        for w in (self.album_label, self.date_label):
            if w is not None:
                w.setVisible(visible)

    # --------------------------------------------------------------- acciones
    def play(self):
        w = self.parent_window
        if self.context_provider is not None:
            w.set_context(self.context_provider())
        elif hasattr(w, "set_context_from_card"):
            w.set_context_from_card(self)
        local = self.item_info.get("local_path")
        if local and os.path.isfile(local):
            w.play_local_file(local)
        else:
            w.play_preview(self.item_info, None, self.cover.pixmap())

    def _toggle_like(self):
        self.parent_window.toggle_info_favorite(dict(self.item_info))
        self.refresh_state()

    def _download(self):
        if self.item_info.get("local_path") or self._downloading:
            return
        self._downloading = True
        self.refresh_state()
        self.parent_window.quick_download(dict(self.item_info), on_done=self._download_done)

    def _download_done(self, result: dict):
        try:
            self._downloading = False
            if result.get("success") and result.get("mp3_path"):
                self.item_info = dict(self.item_info, local_path=result["mp3_path"], already_downloaded=True)
            self.refresh_state()
        except RuntimeError:
            pass

    def _open_menu(self):
        self.parent_window.open_track_menu(self.item_info, self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()),
                                           self.extra_menu)

    # ----------------------------------------------------------------- ratón
    def enterEvent(self, event):
        self._hot = True
        self.refresh_state()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hot = False
        self.refresh_state()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and hasattr(self.parent_window, "select_row"):
            self.parent_window.select_row(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.play()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if hasattr(self.parent_window, "select_row"):
            self.parent_window.select_row(self)
        self.parent_window.open_track_menu(self.item_info, event.globalPos(), self.extra_menu)
