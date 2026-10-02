"""Fila de canción al estilo Spotify para listas, álbumes y artistas.

Por defecto solo se ve el número, la portada, el título y artista, el álbum, cuándo se añadió y la duración.
  * Al pasar el ratón, el número se convierte en el símbolo de reproducir.
  * Un clic marca la fila y aparecen los tres puntitos (menú); doble clic reproduce la canción.
"""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from services.playlist_service import PlaylistService
from ui.animations import fade_out_hide, flash, show_fading
from ui.controls import CoverLabel
from ui.covers import placeholder_cover
from ui.downloadfx import DownloadStateButton
from ui.formatting import format_added
from ui.hover import HoverFader, NowPlayingBars
from ui.save_popup import save_icon
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


class TrackRow(QFrame, HoverFader):
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
        self._press_pos = None
        self._collapse_on_release = False
        self.drag_source = None
        self._was_downloading = False
        self._blocked = False       # sin conexión y sin descargar: oscurecida y no se puede usar
        self._veil = None
        self._detect_downloaded()
        self.setProperty("selected", False)
        self.init_hover(0.10, 8)
        self.init_ui()
        self.refresh_state()
        self.apply_offline()

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
        bars_lay = QHBoxLayout(self.idx_label)
        bars_lay.setContentsMargins(0, 0, 0, 0)
        self.now_bars = NowPlayingBars(self.parent_window)       # «está sonando»: tres barras que se mueven
        self.now_bars.hide()
        bars_lay.addWidget(self.now_bars, alignment=Qt.AlignCenter)
        lay.addWidget(self.idx_label)

        self.cover = CoverLabel(radius=5)
        self.cover.setFixedSize(ROW_COVER, ROW_COVER)
        self.cover.setPixmap(placeholder_cover(self.item_info.get("title", ""), ROW_COVER, 5))
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
        self.title_label.set_marquee(True)           # si el título no cabe, se desplaza al pasar el ratón
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

        self.heart_btn = self._icon_button("Guardar en una lista", self._toggle_like)
        lay.addWidget(self.heart_btn)
        self.dl_btn = self._icon_button("Descargar", self._download, DownloadStateButton)   # columna «descargada»
        lay.addWidget(self.dl_btn)

        self.duration_label = QLabel(self.item_info.get("duration_str", ""))
        self.duration_label.setObjectName("ArtistName")
        self.duration_label.setStyleSheet("background: transparent;")
        self.duration_label.setFixedWidth(DUR_COL)
        self.duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.duration_label)

        self.more_btn = self._icon_button("Más opciones", self._open_menu)
        lay.addWidget(self.more_btn)

    def _icon_button(self, tip: str, slot, kind=QPushButton) -> QPushButton:
        btn = kind()
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
            self.now_bars.hide()
            self.idx_label.setPixmap(icon("play.svg", HOT).pixmap(16, 16))
        elif self._playing:
            self.idx_label.clear()
            self.now_bars.show()
        else:
            self.now_bars.hide()
            self.idx_label.setText(str(self.number))

        saved = bool(PlaylistService.lists_containing(self.item_info))
        if saved:
            self.heart_btn.setIcon(save_icon(True))
        else:
            self.heart_btn.setIcon(save_icon(False, color) if active else _EMPTY)

        local = bool(self.item_info.get("local_path"))
        pending = (not local) and getattr(self.parent_window, "is_pending", lambda _i: False)(self.item_info)
        if local:
            self.dl_btn.set_done(animate=self._was_downloading)
            self._was_downloading = False
            self.dl_btn.setToolTip("Descargada en tu equipo")
            self.dl_btn.setEnabled(False)
        elif pending and not self._downloading:
            self.dl_btn.set_idle()
            self.dl_btn.setIcon(icon("clock.svg", "#FFD166"))
            self.dl_btn.setToolTip("Pendiente: se descargará cuando vuelva internet")
            self.dl_btn.setEnabled(False)
        elif self._downloading:
            self.dl_btn.set_busy(self._download_fraction())     # anillo con el avance (o girando si no se sabe)
            self.dl_btn.setToolTip("Descargando…")
            self.dl_btn.setEnabled(False)
        else:
            self.dl_btn.set_idle()
            self.dl_btn.setIcon(icon("download.svg", color) if active else _EMPTY)
            self.dl_btn.setToolTip("Descargar")
            self.dl_btn.setEnabled(True)

        self.more_btn.setIcon(icon("more.svg", HOT) if active else _EMPTY)

    def update_heart_state(self):
        self.refresh_state()

    # ------------------------------------------------------------ sin conexión
    def apply_offline(self, delay: int = 0):
        """Sin internet, las canciones no descargadas se oscurecen y no se pueden seleccionar ni reproducir.
        `delay`: retraso del velo (las filas se oscurecen o se iluminan en cascada)."""
        checker = getattr(self.parent_window, "offline_blocks", None)
        blocked = bool(checker(self.item_info)) if checker else False
        if blocked == self._blocked:
            return
        self._blocked = blocked
        self.setEnabled(not blocked)
        if blocked:
            if self._veil is None:
                self._veil = QWidget(self)
                self._veil.setObjectName("OfflineVeil")
                self._veil.setAttribute(Qt.WA_StyledBackground, True)
                self._veil.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._veil.setGeometry(self.rect())
            self._veil.raise_()
            show_fading(self._veil, 240, delay)
            self.setToolTip("Sin conexión: esta canción no está descargada")
            if getattr(self.parent_window, "_selected_row", None) is self:
                self.set_selected(False)
        else:
            if self._veil is not None:
                fade_out_hide(self._veil, 240, delay)
            self.setToolTip("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._veil is not None and self._blocked:
            self._veil.setGeometry(self.rect())

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
        self.parent_window.save_button_clicked(dict(self.item_info), self.heart_btn)
        self.refresh_state()

    def _download(self):
        if self.item_info.get("local_path") or self._downloading:
            return
        self._downloading = True
        self._was_downloading = True
        self.refresh_state()
        tracker = getattr(self.parent_window, "downloads", None)
        if tracker is not None:
            tracker.changed.connect(self._on_downloads_changed)
        self.parent_window.quick_download(dict(self.item_info), on_done=self._download_done)

    def _download_fraction(self):
        getter = getattr(self.parent_window, "download_fraction", None)
        return getter(self.item_info) if getter else None

    def _on_downloads_changed(self):
        try:
            if self._downloading:
                self.dl_btn.set_busy(self._download_fraction())
        except RuntimeError:
            pass

    def _download_done(self, result: dict):
        try:
            self._downloading = False
            tracker = getattr(self.parent_window, "downloads", None)
            if tracker is not None:
                try:
                    tracker.changed.disconnect(self._on_downloads_changed)
                except (RuntimeError, TypeError):
                    pass
            ok = bool(result.get("success") and result.get("mp3_path"))
            if ok:
                self.item_info = dict(self.item_info, local_path=result["mp3_path"], already_downloaded=True)
            self._was_downloading = ok
            self.refresh_state()
            if ok:
                flash(self, accent(), 0.22, 700, 8)            # final feliz: un destello suave
        except RuntimeError:
            pass

    def _open_menu(self):
        self.parent_window.open_track_menu(self.item_info, self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()),
                                           self.extra_menu)

    # ----------------------------------------------------------------- ratón
    def enterEvent(self, event):
        self._hot = True
        self.hover_to(True)
        self.refresh_state()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hot = False
        self.hover_to(False)
        self.refresh_state()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        self.paint_hover()

    def mouseMoveEvent(self, event):
        """Arrastrar la canción (o todas las marcadas) hacia una lista de la barra lateral las añade a ella;
        dentro de una playlist, arrastrarlas cambia su orden."""
        if (event.buttons() & Qt.LeftButton) and self._press_pos is not None and not self._blocked:
            if (event.position().toPoint() - self._press_pos).manhattanLength() > QApplication.startDragDistance() + 6:
                self._press_pos = None
                self._collapse_on_release = False
                from ui.dragdrop import start_track_drag
                infos = [dict(self.item_info)]
                alive = getattr(self.parent_window, "_alive_rows", lambda: [])()
                if self in alive and len(alive) > 1:
                    infos = [dict(r.item_info) for r in alive]
                start_track_drag(self, infos, getattr(self, "drag_source", None))
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        if self._collapse_on_release and event.button() == Qt.LeftButton:
            self._collapse_on_release = False
            if hasattr(self.parent_window, "select_row"):
                self.parent_window.select_row(self)        # un clic sin arrastrar deja solo esta fila marcada
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint() if event.button() == Qt.LeftButton else None
        if event.button() == Qt.LeftButton:
            if self._hot and self.idx_label.geometry().contains(event.position().toPoint()):
                self.play()          # un clic sobre el símbolo ▶ reproduce directamente
                event.accept()
                return
            if hasattr(self.parent_window, "select_row"):
                mods = event.modifiers()
                alive = getattr(self.parent_window, "_alive_rows", lambda: [])()
                if mods & Qt.ControlModifier:
                    self.parent_window.select_row(self, "toggle")
                elif mods & Qt.ShiftModifier:
                    self.parent_window.select_row(self, "range")
                elif self in alive and len(alive) > 1:
                    self._collapse_on_release = True           # puede que vaya a arrastrar todas las marcadas
                else:
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
