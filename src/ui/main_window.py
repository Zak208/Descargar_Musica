import os
import time
import sys
import logging
import subprocess

from PySide6.QtCore import (
    Qt, QUrl, QSize, QRect, QPoint, QThread, QTimer, Signal, QPropertyAnimation, QEasingCurve, QObject, QEvent, QProcess
)
from PySide6.QtGui import QPixmap, QImage, QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QApplication, QFileDialog, QStackedWidget, QSystemTrayIcon
)
from PySide6.QtMultimedia import QMediaPlayer, QMediaDevices

from config import (
    get_download_dir, set_download_dir, set_audio_quality, get_theme, load_settings, save_settings
)
from services.youtube_service import (
    PreviewAudioWorker, is_youtube_url
)
from services.spotify_service import is_spotify_url
from services.catalog_service import (
    ArtistDetailsWorker, AlbumDetailsWorker
)
from services.ffmpeg_service import FFmpegService
from services.library_service import local_id
from services.metadata_service import MetadataService
from services.playlist_service import PlaylistService
from ui.styles import (MAIN_STYLE, get_theme_stylesheet, THEME_CONFIGS, set_active_theme, retheme_stylesheet,
                       contrast_stylesheet, high_contrast_enabled)
from ui.icons import icon
from version import __version__
from ui.home_shelves import TrackTile
from ui.save_popup import save_icon
from ui.playback_mixin import PlaybackMixin
from ui.lists_mixin import ListsMixin
from ui.home_mixin import HomeMixin
from ui.search_mixin import SearchMixin
from ui.downloads_mixin import DownloadsMixin
from ui.offline_mixin import OfflineMixin
from ui.usability_mixin import UsabilityMixin
from ui.playback_options import PlaybackOptionsMixin
from ui.updates_mixin import UpdatesMixin, UPDATE_POLL_MS
from ui.lyrics_mixin import LyricsMixin
from ui.session_mixin import SessionMixin
from ui.theme_mixin import ThemeMixin
from ui.equalizer_mixin import EqualizerMixin
from ui.artist_page import ArtistProfilePage
from ui.album_page import AlbumDetailsPage
from ui.list_page import ListPage
from ui.library_page import LibraryPage
from services.equalizer_service import (
    load_eq_settings, clean_cache
)
from ui.toast import Toast
from ui.topbar import TopBar
from ui.downloads_panel import DownloadsTracker, DownloadsPanel
from ui.animations import fade_in, install_ripples, pop_icon, press_pulse, slide_fade_in
from ui import motion, snapshot, winext, tooltips, focusring
from ui.anim_clock import clock
from ui.dialogs import ask_text, ask_confirm, show_message
from ui.imageloader import prune_disk_cache, clear_memory_cache
from ui import perf
from ui.friendly import friendly_error
from ui.common import resource_path, _ACTIVE_THREADS
from ui.song_card import SongResultCard, square_cover
from ui.track_row import TrackRow
from ui.now_playing import NowPlayingPanel
from ui.panel_grip import PanelGrip, GRIP_WIDTH, PANEL_DEFAULT, clamp_width
from ui.sidebar import build_sidebar, SidebarMixin
from ui.home_page import build_home_page
from ui.player_bar import build_player_bar
from services import backup_service
from services import http as web
from ui.metadata_dialog import MetadataDialog
from ui.queue_dialog import QueueDialog
from ui.help_dialog import HelpDialog
from ui.tour import TourOverlay
from ui.welcome import WelcomeDialog
from ui.pages import Page

class ThemeEventFilter(QObject):
    """Adapta al tema activo los estilos en línea (colores fijos) de cada widget cuando se muestra.
    Solo se instala si el tema no es el de por defecto (así no gasta CPU en el caso habitual)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget):
            qss = obj.styleSheet()
            if qss and "#" in qss and len(qss) < 20000 and not obj.property("noRetheme"):
                from ui.styles import _active_theme
                new_qss = retheme_stylesheet(qss, _active_theme)
                if high_contrast_enabled():
                    new_qss = contrast_stylesheet(new_qss)
                if new_qss != qss:
                    obj.setStyleSheet(new_qss)
        return False


class FFmpegDownloadWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(bool)

    def run(self):
        try:
            ok = FFmpegService.download_ffmpeg_portable(lambda msg: self.progress_signal.emit(msg))
            self.finished_signal.emit(bool(ok))
        except Exception:
            self.finished_signal.emit(False)


class MainWindow(QMainWindow, PlaybackMixin, ListsMixin, HomeMixin, SearchMixin, DownloadsMixin, OfflineMixin,
                 UsabilityMixin, PlaybackOptionsMixin, UpdatesMixin, LyricsMixin, SessionMixin, ThemeMixin, EqualizerMixin,
                 SidebarMixin):
    playing_changed = Signal(bool)          # empieza o se detiene el sonido (los indicadores de «sonando» lo siguen)

    def __init__(self):
        super().__init__()
        web.warm_up()          # prepara en segundo plano la conexión segura compartida (ahorra CPU en cada petición)
        self.setWindowTitle(f"Descargador de Música {__version__}")
        self.setWindowIcon(QIcon(resource_path("assets/app.ico")))
        self.setAcceptDrops(True)       # se pueden soltar enlaces de YouTube/Spotify o archivos de audio
        self.resize(1360, 860)
        self.setStyleSheet(MAIN_STYLE)

        # Reproductor
        self.player, self.audio_output = self._new_deck()
        self.current_preview_btn = None
        self.current_item_info = None
        self.preview_worker = None
        self.is_updating_seek = False
        self._page_scroll = {}

        # Modos y estados
        self.is_loop_enabled = False
        self.is_shuffle_enabled = False
        self.is_mini_mode = False
        self.normal_geometry = None
        self.lyrics_dialog = None
        self.previous_page_before_album = 1

        # Cola de reproducción interactiva
        self.playback_queue = []

        # Notificaciones nativas de Windows en bandeja
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "music.svg"))))
        self.tray_icon.setVisible(True)
        self.init_playback_options()        # temporizador, fundido, volumen igualado, control multimedia y bandeja

        self.equalizer_dialog = None

        # Historial, contexto de reproducción y biblioteca (ver playback_mixin / lists_mixin)
        self.init_playback_state()
        self.init_offline_state()
        self.init_usability_state()
        self.init_lists_state()
        self.init_home_state()
        self.init_search_state()
        self.init_downloads_state()

        # Ecualizador (graves / voces / agudos) aplicado a la música local
        self.eq_settings = load_eq_settings()
        self._eq_worker = None
        self._eq_source_path = None
        self._eq_active_render = None
        clean_cache()

        self._wire_player(self.player)

        self.current_theme = get_theme()
        set_active_theme(self.current_theme)
        self._theme_filter = ThemeEventFilter(self)
        self._set_theme_filter(self.current_theme != "spotify" or high_contrast_enabled())   # con el tema por defecto no hace falta vigilar nada
        self.toast = Toast(self)
        clock().degraded.connect(self._on_clock_degraded)
        self.downloads = DownloadsTracker(self)
        self._download_info_reset = QTimer(self)
        self._download_info_reset.setSingleShot(True)
        self._download_info_reset.timeout.connect(self.update_header_info)
        self.init_ui()
        self.restore_geometry_early()
        self.init_sidebar_state()
        self.apply_accessibility_names()
        self._reload_pending_keys()
        if self.is_offline():                       # por si se abre ya sin conexión (o con el modo sin conexión activado)
            QTimer.singleShot(0, lambda: self._on_connectivity(False))
        else:
            QTimer.singleShot(7000, self.resume_pending_downloads)
        self._session_timer = QTimer(self)             # mientras suena algo, se apunta el punto en que va (cada 20 s)
        self._session_timer.setInterval(20000)
        self._session_timer.timeout.connect(lambda: self.player_bar.isVisible() and self.save_session())
        self._session_timer.start()
        QTimer.singleShot(8000, backup_service.auto_backup_if_due)
        QTimer.singleShot(5000, self.check_updates)          # al abrir (si no se miró hace menos de 5 minutos), solo con conexión
        self._update_timer = QTimer(self)                     # y mientras la aplicación sigue abierta, cada 10 minutos
        self._update_timer.setInterval(UPDATE_POLL_MS)         # (son dos peticiones pequeñas; una versión nueva aparece sin reiniciar)
        self._update_timer.timeout.connect(self.check_updates)
        self._update_timer.start()
        self._app_update_worker = None
        self._update_state = None
        self._engine_state = None
        self._engine_version = ""
        self._engine_pct = 0
        QTimer.singleShot(1500, self._restore_pending_update)
        QTimer.singleShot(3500, self._announce_finished_update)
        QTimer.singleShot(25000, perf.trim_memory)       # tras el arranque se devuelve a Windows lo que sobra
        self._trim_timer = QTimer(self)                   # y cada 10 minutos mientras no se esté usando
        self._trim_timer.setInterval(600_000)
        self._trim_timer.timeout.connect(self._trim_if_idle)
        self._trim_timer.start()
        self.check_ffmpeg_and_update()
        QTimer.singleShot(0, self._fit_minimum_size)
        QTimer.singleShot(150, self.rescan_library)          # lee la biblioteca en segundo plano
        QTimer.singleShot(0, self.watch_library)
        QTimer.singleShot(4000, prune_disk_cache)
        QTimer.singleShot(500, self.play_home_intro)          # entrada suave de Inicio (solo la primera vez)
        self.taskbar = None
        QTimer.singleShot(700, self._init_windows_integration)

    # ---------- integración con Windows (barra de título, barra de tareas) ----------
    def _hwnd(self) -> int:
        try:
            return int(self.winId())
        except Exception:
            return 0

    def _init_windows_integration(self):
        """Barra de título del color del tema y, en la barra de tareas, progreso de descargas y botones en la miniatura."""
        if not winext.IS_WIN:
            return
        self._apply_title_bar()
        hwnd = self._hwnd()
        self.taskbar = winext.Taskbar(hwnd)
        if self.taskbar.ok:
            pix = lambda name: icon(name, "#FFFFFF").pixmap(24, 24)
            self.taskbar.add_thumb_buttons(
                {winext.Taskbar.PREV: pix("prev.svg"), winext.Taskbar.PLAY: pix("play.svg"), winext.Taskbar.NEXT: pix("next.svg")},
                self._on_thumb_button)

    def _apply_title_bar(self):
        bg = THEME_CONFIGS.get(self.current_theme, THEME_CONFIGS["spotify"]).get("bg_main", "#121212")
        winext.apply_title_bar(self._hwnd(), bg)

    def _on_thumb_button(self, button_id: int):
        if button_id == winext.Taskbar.PREV:
            self.play_previous()
        elif button_id == winext.Taskbar.PLAY:
            self.toggle_play_pause()
        elif button_id == winext.Taskbar.NEXT:
            self.play_next()

    def _on_clock_degraded(self, interval: int):
        """El equipo va justo: las animaciones continuas bajan de velocidad (o se limitan a las puntuales)."""
        if interval == 0:
            self.notify("Tu equipo va justo: se han reducido las animaciones para que todo vaya fluido.")

    def init_ui(self):
        # Aplicar tema visual activo
        self.setStyleSheet(get_theme_stylesheet(self.current_theme))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        self.main_vbox = QVBoxLayout(central_widget)
        self.main_vbox.setContentsMargins(8, 8, 8, 8)
        self.main_vbox.setSpacing(8)

        self.top_hbox = QHBoxLayout()
        self.top_hbox.setContentsMargins(0, 0, 0, 0)
        self.top_hbox.setSpacing(8)
        self.main_vbox.addLayout(self.top_hbox, stretch=1)

        build_sidebar(self)

        # === CONTENT AREA ===
        self.content_widget = QWidget()
        self.content_widget.setObjectName("ContentPanel")
        self.content_widget.setAttribute(Qt.WA_StyledBackground, True)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(28, 22, 28, 20)
        self.content_layout.setSpacing(18)
        self.top_hbox.addWidget(self.content_widget, stretch=1)
        self.build_offline_banner(self.content_layout)

        # Panel lateral derecho «En reproducción» (oculto hasta que se abre desde la barra de reproducción)
        self.now_panel = NowPlayingPanel(self)
        self.now_panel.close_requested.connect(self.toggle_now_playing)
        self.now_panel.full_requested.connect(self.open_full_player)
        self.full_player = None
        self.now_panel.setVisible(False)
        self.top_hbox.addWidget(self.now_panel)
        # tirador para cambiar el ancho del panel arrastrando (flota sobre el hueco entre el contenido y el panel)
        saved_width = int(load_settings().get("panel_width", PANEL_DEFAULT) or PANEL_DEFAULT)
        self.now_panel.setFixedWidth(clamp_width(saved_width, 4000, 0))
        self.panel_grip = PanelGrip(self.now_panel, self, self._width_besides_panel, central_widget)
        self.panel_grip.resizing.connect(self._on_panel_resizing)
        self.panel_grip.finished.connect(self._save_panel_width)
        self.panel_grip.hide()

        # Barra superior (de lado a lado): marca, inicio, buscador, información general y descargas en curso
        self.topbar = TopBar()
        self.topbar.search_submitted.connect(self.perform_search)
        self.topbar.home_clicked.connect(lambda: self.switch_to_page(Page.HOME))
        self.topbar.downloads_clicked.connect(self.show_downloads_panel)
        self.topbar.update_clicked.connect(self._on_update_clicked)
        self.main_vbox.insertWidget(0, self.topbar)   # ocupa todo el ancho, por encima de los paneles
        # El buscador es único; estos nombres antiguos apuntan a él
        self.downloads_panel = DownloadsPanel(self.downloads, self, self.topbar.btn_downloads)
        self.downloads.changed.connect(self.on_downloads_changed)

        self.stacked_widget = QStackedWidget()
        self.content_layout.addWidget(self.stacked_widget, stretch=1)

        build_home_page(self)

        # === PAGE 1: RESULTADOS DE BÚSQUEDA ===
        self.build_results_page()

        # === PAGE 2: ARTIST PROFILE ===
        self.page_artist = ArtistProfilePage(self)
        self.page_artist.back_clicked.connect(lambda: self.switch_to_page(Page.RESULTS))
        self.page_artist.album_selected.connect(self.open_album_details)
        self.page_artist.download_all_requested.connect(self.start_batch_download)
        self.stacked_widget.addWidget(self.page_artist)

        # === PAGE 3: ALBUM DETAILS ===
        self.page_album = AlbumDetailsPage(self)
        self.page_album.back_clicked.connect(self.go_back_from_album)
        self.page_album.download_all_requested.connect(self.start_batch_download)
        self.page_album.save_list_requested.connect(self.download_album_as_list)
        self.stacked_widget.addWidget(self.page_album)

        # === PAGE 4: PLAYLIST / FAVORITOS DETAILS ===
        self.page_playlist = ListPage(self)
        self.page_playlist.back_clicked.connect(self.go_back_from_list)
        self.page_playlist.download_all_requested.connect(self.start_batch_download)
        self.stacked_widget.addWidget(self.page_playlist)

        # === PAGE 5: TU BIBLIOTECA (todas tus listas) ===
        self.page_library = LibraryPage(self)
        self.page_library.list_selected.connect(self._library_card_clicked)
        self.page_library.unfollow_requested.connect(self.unfollow_from_library)
        self.page_library.new_list_requested.connect(self.create_new_playlist_dialog)
        self.page_library.rename_requested.connect(self.rename_playlist)
        self.page_library.cover_requested.connect(self.change_playlist_cover)
        self.page_library.delete_requested.connect(self.delete_playlist)
        self.stacked_widget.addWidget(self.page_library)

        build_player_bar(self)
        install_ripples(self)           # onda al pulsar en los botones principales
        tooltips.install()              # ayudas propias (con el atajo de teclado)
        self._focus_ring = focusring.install(self)

    # ---------- soltar enlaces y archivos sobre la ventana ----------
    def dragEnterEvent(self, event):
        from ui.dragdrop import can_accept_window_drop
        if can_accept_window_drop(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        from ui.dragdrop import handle_window_drop
        if handle_window_drop(self, event.mimeData()):
            event.acceptProposedAction()

    def import_audio_files(self, files: list):
        """Archivos de audio soltados sobre la ventana: se ofrecen para añadirlos a tu música (se copian)."""
        from ui.dragdrop import copy_into
        n = len(files)
        if not ask_confirm(self, "Añadir a tu música",
                           f"¿Quieres añadir {n} canción{'es' if n != 1 else ''} a tu música? Se copiarán a tu carpeta de música.",
                           ok="Añadir"):
            return
        copied = copy_into(str(get_download_dir()), files)
        if copied:
            self.notify(f"{len(copied)} canción{'es' if len(copied) != 1 else ''} añadida{'s' if len(copied) != 1 else ''} a tu música")
            self.rescan_library()
        else:
            self.notify("Esas canciones ya estaban en tu música.")

    def keyPressEvent(self, event):
        """Atajos de teclado globales para control multimedia."""
        focus_w = QApplication.focusWidget()
        if isinstance(focus_w, QLineEdit):
            super().keyPressEvent(event)
            return

        key = event.key()
        if event.modifiers() == Qt.ControlModifier and key == Qt.Key_V:
            self.paste_link_from_clipboard()
            event.accept()
            return
        if event.modifiers() == Qt.ControlModifier and key == Qt.Key_Z:
            self.perform_undo()
            event.accept()
            return
        if event.modifiers() == Qt.NoModifier and self.list_key_navigation(event):
            event.accept()
            return
        if key == Qt.Key_Escape and len(self._alive_rows()) > 0 and self.stacked_widget.currentIndex() == Page.LIST:
            self.clear_selection()
            event.accept()
            return
        if key == Qt.Key_F11:
            self.open_full_player()
            event.accept()
            return
        if key == Qt.Key_Space:
            press_pulse(self.btn_play_pause)          # se ve qué botón hace el atajo
            self.toggle_play_pause()
            event.accept()
            return
        elif key == Qt.Key_Left:
            cur = self.player.position()
            self.player.setPosition(max(0, cur - 5000))
            self.show_seek_osd(-5)
            event.accept()
            return
        elif key == Qt.Key_Right:
            cur = self.player.position()
            dur = self.player.duration()
            self.player.setPosition(min(dur, cur + 5000))
            self.show_seek_osd(5)
            event.accept()
            return
        elif key in (Qt.Key_Up, Qt.Key_Down) and event.modifiers() == Qt.ControlModifier:
            self.volume_slider.setValue(max(0, min(100, self.volume_slider.value() + (5 if key == Qt.Key_Up else -5))))
            self.show_volume_osd()
            event.accept()
            return
        elif key == Qt.Key_M:
            cur_vol = self.volume_slider.value()
            if cur_vol > 0:
                self._prev_vol = cur_vol
                self.volume_slider.setValue(0)
            else:
                self.volume_slider.setValue(getattr(self, '_prev_vol', 100))
            self.show_volume_osd()
            event.accept()
            return
        elif event.modifiers() == Qt.ControlModifier and key == Qt.Key_F:
            self.focus_search()
            event.accept()
            return
        elif key in [Qt.Key_MediaPlay, Qt.Key_MediaPause, Qt.Key_MediaTogglePlayPause]:
            press_pulse(self.btn_play_pause)
            self.toggle_play_pause()
            event.accept()
            return
        elif key == Qt.Key_MediaNext:
            press_pulse(self.btn_next)
            self.play_next()
            event.accept()
            return
        elif key == Qt.Key_MediaPrevious:
            press_pulse(self.btn_prev)
            self.play_previous()
            event.accept()
            return

        super().keyPressEvent(event)

    # ---------- pantalla completa «Ahora suena» ----------
    def open_full_player(self):
        if not self.current_item_info:
            self.notify("Reproduce una canción primero.")
            return
        if self.full_player is None:
            from ui.nowplaying_full import NowPlayingFull
            self.full_player = NowPlayingFull(self)
        fp = self.full_player
        fp.set_duration(self.player.duration())
        fp.set_playing(self.is_playing_now())
        fp.set_track(self.current_item_info, self._cover_color(), self.player_thumb.pixmap())
        fp.set_position(self.player.position())
        fp.showFullScreen()

    def _full_player_visible(self) -> bool:
        fp = getattr(self, "full_player", None)
        try:
            return fp is not None and fp.isVisible()
        except RuntimeError:
            return False

    def celebrate(self, reason: str = ""):
        """Confeti (nivel «Completas») o un destello del botón de descargas cuando pasa algo que merece la pena."""
        from ui.celebrate import celebrate
        celebrate(self, fallback=lambda: self.topbar.download_finished_flash())

    def toggle_mini_player(self):
        """Reproductor pequeño: solo la barra de reproducción, siempre visible encima de otras ventanas."""
        if not self.is_mini_mode and not self.player_bar.isVisible():
            self.notify("Reproduce una canción primero.")
            return

        self.is_mini_mode = not self.is_mini_mode
        if not self.is_mini_mode:
            self.btn_play_pause.set_ring(None)
        extras = [
            self.btn_shuffle, self.btn_loop, self.btn_lyrics, self.btn_queue, self.btn_eq, self.btn_panel, self.btn_options,
            self.vol_icon, self.volume_slider, self.player_status, self.visualizer,
            self.player_heart_btn, self.btn_close_player,
        ]
        if self.is_mini_mode:
            self.normal_geometry = self.geometry()
            self._normal_min_size = self.minimumSize()
            self._panel_was_open = self.now_panel.isVisible()
            self.now_panel.setVisible(False)
            self.topbar.setVisible(False)
            self.sidebar.setVisible(False)
            self.content_widget.setVisible(False)
            for w in extras:
                w.setVisible(False)
            self.info_widget.setMaximumWidth(230)
            self.seek_slider.setMaximumWidth(260)
            self.setMinimumSize(0, 0)
            self._set_always_on_top(True)
            geo = self.geometry()
            self._animate_geometry(QRect(geo.x(), geo.y(), 640, self.player_bar.height() + 16))
            QTimer.singleShot(400, lambda: self.is_mini_mode and self.resize(640, self.player_bar.height() + 16))
            self.btn_play_pause.set_ring(0.0)
        else:
            for w in extras:
                w.setVisible(True)
            self.visualizer.setVisible(self.visualizer.enabled)
            self.info_widget.setMaximumWidth(280)
            self.seek_slider.setMaximumWidth(560)
            self.topbar.setVisible(True)
            self.sidebar.setVisible(True)
            self.now_panel.setVisible(getattr(self, '_panel_was_open', False))
            self.content_widget.setVisible(True)
            self.setMinimumSize(getattr(self, "_normal_min_size", QSize(0, 0)))
            self._set_always_on_top(False)
            if self.normal_geometry:
                self._animate_geometry(self.normal_geometry)

    def _set_always_on_top(self, on: bool):
        """«Siempre encima» del reproductor pequeño: en Windows se cambia sin recrear la ventana (sin parpadeo)."""
        if winext.IS_WIN and winext.set_topmost(self._hwnd(), on):
            return
        flags = self.windowFlags()
        self.setWindowFlags(flags | Qt.WindowStaysOnTopHint if on else flags & ~Qt.WindowStaysOnTopHint)
        self.show()

    def _animate_geometry(self, rect):
        """La ventana se encoge o crece hasta `rect` (con el contenido ya cambiado)."""
        if not motion.enabled() or not self.isVisible():
            self.setGeometry(rect)
            return
        anim = getattr(self, "_geo_anim", None)
        if anim is None:
            anim = self._geo_anim = QPropertyAnimation(self, b"geometry", self)
            anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.stop()
        anim.setDuration(motion.DUR_BASE + 40)
        anim.setStartValue(self.geometry())
        anim.setEndValue(rect)
        anim.start()

    def choose_custom_download_dir(self):
        current = str(get_download_dir())
        chosen = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta para guardar música", current)
        if chosen and os.path.isdir(chosen):
            set_download_dir(chosen)
            self._lib_items = None
            self.watch_library()
            self.refresh_sidebar_library()
            self.notify("Listo: las próximas canciones se guardarán en esa carpeta.")

    def refresh_sidebar_library(self):
        """Algo cambió en tu música (descarga, edición...): se vuelve a leer en segundo plano, sin recargar la pantalla."""
        if hasattr(self, "settings_dialog"):
            self.settings_dialog.refresh_download_dir()
        self.rescan_library()

    def changeEvent(self, event):
        """Al volver a la ventana, si hay un enlace de YouTube/Spotify copiado, lo ofrece en el buscador.
        Minimizada, la aplicación deja de animar y libera memoria."""
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._suggest_clipboard_link()
        elif event.type() == QEvent.WindowStateChange:
            self._set_background(self.isMinimized())
        if event.type() == QEvent.ActivationChange and self.isActiveWindow() and getattr(self, "taskbar", None):
            self.taskbar.set_overlay(None)             # al volver a la ventana, la marca de «descargas terminadas» se quita
        super().changeEvent(event)

    def _set_background(self, background: bool):
        self._in_background = background
        clock().set_paused(background)          # minimizada: no se anima nada
        if hasattr(self, "visualizer"):
            self.visualizer.set_window_active(not background)
        if background:
            QTimer.singleShot(45_000, self._trim_if_idle)      # si sigue minimizada, se libera memoria
        else:
            self.update_position(self.player.position())

    def _trim_if_idle(self):
        if getattr(self, "_in_background", False) or not self.isActiveWindow():
            clear_memory_cache()
            perf.trim_memory()

    def _suggest_clipboard_link(self):
        try:
            text = (QApplication.clipboard().text() or "").strip()
        except Exception:
            return
        if (not text or len(text) > 300 or text == getattr(self, "_last_clip_link", None)
                or self.topbar.text().strip()):
            return
        if is_youtube_url(text) or is_spotify_url(text):
            self._last_clip_link = text
            self.topbar.set_text(text, silent=True)
            self.notify("Hemos pegado el enlace que copiaste. Pulsa Intro para buscar.")

    def play_from_library(self, path: str):
        """Reproduce una canción de la biblioteca; 'siguiente' recorre toda tu música descargada."""
        self.set_context(self.library_items())
        self.play_local_file(path)

    CONTENT_MIN_WIDTH = 600

    def _fit_minimum_size(self):
        """El tamaño mínimo de la ventana es el que necesita la aplicación para no recortar ni encoger nada: se recalcula
        al abrir o cerrar el panel de la derecha, al cambiar su ancho y al plegar la barra de la izquierda."""
        self.content_widget.setMinimumWidth(self.CONTENT_MIN_WIDTH)
        layout = self.centralWidget().layout()
        self.top_hbox.invalidate()
        layout.invalidate()
        layout.activate()                          # el mínimo se calcula con la distribución al día
        hint = self.minimumSizeHint()
        hint.setHeight(max(hint.height(), 720))   # alto razonable: las listas se desplazan, pero el resto no debe agobiarse
        self.setMinimumSize(hint)
        if self.width() < hint.width() or self.height() < hint.height():
            self.resize(max(self.width(), hint.width()), max(self.height(), hint.height()))
        self.top_hbox.activate()
        self._place_panel_grip()

    def _width_besides_panel(self) -> int:
        """Ancho que ocupa todo lo que no es el panel de la derecha (barra lateral, contenido mínimo y márgenes)."""
        margins = self.main_vbox.contentsMargins()
        spacing = self.top_hbox.spacing()
        return margins.left() + margins.right() + self.sidebar.width() + self.CONTENT_MIN_WIDTH + spacing * 2

    def _on_panel_resizing(self, _width: int):
        # mientras se arrastra solo se recoloca el tirador; el tamaño mínimo se recalcula al soltar (hacerlo en cada
        # movimiento cambiaba el tamaño de la ventana y el panel daba saltos)
        self.top_hbox.activate()
        self._place_panel_grip()

    def _save_panel_width(self, width: int):
        settings = load_settings()
        settings["panel_width"] = int(width)
        save_settings(settings)
        self._fit_minimum_size()

    def _place_panel_grip(self):
        """El tirador flota justo a la izquierda del panel (solo cuando el panel se ve)."""
        grip = getattr(self, "panel_grip", None)
        if grip is None:
            return
        panel = self.now_panel
        grip.setVisible(panel.isVisible())
        if panel.isVisible():
            g = panel.geometry()
            grip.setGeometry(g.x() - GRIP_WIDTH, g.y(), GRIP_WIDTH, g.height())
            grip.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._place_panel_grip)

    def toast_margin(self) -> int:
        """Distancia al borde inferior para los avisos: por encima de la barra de reproducción si se ve."""
        return (self.player_bar.height() + 24) if self.player_bar.isVisible() else 40

    def notify(self, text: str):
        """Muestra un aviso breve y no intrusivo en la parte inferior."""
        margin = self.toast_margin()
        self.toast.show_message(text, bottom_margin=margin)

    def focus_search(self):
        self.topbar.search.setFocus()
        self.topbar.search.selectAll()

    def open_settings(self):
        self.settings_dialog.refresh_download_dir()
        self.settings_dialog.exec()

    def open_help(self):
        if getattr(self, "help_dialog", None) is None:
            self.help_dialog = HelpDialog(self)
        self.help_dialog.refresh_updates()
        self.help_dialog.exec()

    def restart_app(self):
        """Cierra y vuelve a abrir la aplicación (por ejemplo, tras restaurar una copia de seguridad)."""
        args = [] if getattr(sys, "frozen", False) else [a for a in sys.argv if a != "--reiniciando"]
        QProcess.startDetached(sys.executable, args + ["--reiniciando"])     # la nueva espera a que esta termine de cerrar
        self._quitting = True
        self.close()
        QApplication.quit()

    def bring_to_front(self):
        """Otra copia de la aplicación intentó abrirse: se enseña esta ventana."""
        self.show_from_tray()

    # ---------- primer uso y recorrido ----------
    def maybe_show_welcome(self):
        """Solo la primera vez que alguien abre la aplicación sin datos: asistente de 3 pasos y recorrido."""
        settings = load_settings()
        if settings.get("first_run_done"):
            return
        has_data = bool(settings.get("theme") or settings.get("quality") or settings.get("download_dir")
                        or self.library_items() or PlaylistService.get_playlists() or PlaylistService.get_favorites())
        settings["first_run_done"] = True       # se marca antes: así nunca se repite, aunque algo falle
        save_settings(settings)
        if has_data:
            return
        dlg = WelcomeDialog(self)
        dlg.exec()
        if dlg.start_tour:
            self.start_tour()

    def start_tour(self):
        """Recorrido guiado: resalta cada parte de la aplicación y la explica en una burbuja."""
        steps = [
            (lambda: self.topbar.search, "Busca aquí",
             "Escribe una canción, un artista o un álbum. También puedes pegar un enlace de YouTube o Spotify."),
            (lambda: self.btn_nav_library, "Tu biblioteca",
             "Aquí están tus listas y los artistas que sigues. Con el «+» creas una lista nueva."),
            (lambda: self.btn_nav_home, "Inicio",
             "Te recomienda música parecida a la que ya tienes y te deja volver a lo último que escuchaste."),
            (lambda: self.topbar.btn_downloads, "Descargas",
             "Aquí ves lo que se está descargando ahora mismo."),
            (None, "Cuando suene una canción",
             "Abajo verás los controles. El «+» la guarda en tus listas, el micrófono muestra la letra y el botón de "
             "panel abre «En reproducción» con la portada, la letra y la información del artista."),
            (lambda: self.btn_nav_settings, "Ajustes",
             "Cambia la calidad, la carpeta, los colores, libera espacio o haz una copia de seguridad."),
            (lambda: self.btn_nav_help, "Ayuda",
             "Si algo no va bien o quieres repetir este recorrido, lo encuentras aquí."),
        ]
        self.tour = TourOverlay(self, steps)
        self.tour.start()

    def on_quality_changed(self):
        selected_code = self.quality_combo.currentData()
        if selected_code:
            set_audio_quality(selected_code)

    def show_format_info_dialog(self):
        """Ayuda breve y sin tecnicismos para elegir la calidad de descarga."""
        show_message(
            self, "¿Qué calidad me conviene?",
            "<p><b>Alta calidad (recomendado)</b><br>"
            "Suena muy bien y funciona en cualquier móvil, coche, televisión o altavoz.</p>"
            "<p><b>Fidelidad original</b><br>"
            "Es el audio tal cual lo da la fuente, sin comprimirlo otra vez: la opción que más fielmente conserva "
            "el sonido original. Funciona en móviles y reproductores modernos.</p>"
            "<p><b>Calidad normal</b><br>Casi igual de buena al oído, pero ocupa menos espacio.</p>"
            "<p><b>Sin pérdida (FLAC) y estudio (WAV)</b><br>"
            "Ocupan muchísimo más, pero <b>no suenan mejor</b>: las canciones se descargan de internet con el audio "
            "ya comprimido, y estos formatos no pueden recuperar lo que ya se perdió. "
            "Solo tienen sentido si vas a editar el audio.</p>",
            ok="Entendido")

    _PAGE_DEPTH = {0: 0, 5: 0, 1: 1, 4: 1, 2: 2, 3: 3}      # inicio y biblioteca arriba; el detalle, más hondo

    def switch_to_page(self, target_index: int):
        """Cambia de página con un cruce suave: se hace una foto de la página que se va y esa foto se desvanece (y se
        desplaza un poco hacia donde se «avanza» o se «vuelve»). Al volver, la lista recupera el punto de scroll."""
        current = self.stacked_widget.currentIndex()
        if current == target_index:
            return
        if target_index == 0 and self._home_dirty:
            self._home_dirty = False
            self.refresh_home()
        target_widget = self.stacked_widget.widget(target_index)
        if not target_widget:
            return
        QTimer.singleShot(0, self.apply_accessibility_names)
        old_widget = self.stacked_widget.currentWidget()
        self._remember_scroll(old_widget, current)
        snap = snapshot.grab(old_widget) if (motion.enabled() and old_widget is not None and old_widget.isVisible()) else None
        self.stacked_widget.setCurrentIndex(target_index)
        direction = self._PAGE_DEPTH.get(target_index, 1) - self._PAGE_DEPTH.get(current, 1)
        if direction < 0:
            QTimer.singleShot(0, lambda: self._restore_scroll(target_widget, target_index))
        if snap is not None:
            snapshot.crossfade(self.stacked_widget, snap, motion.DUR_BASE - 40,
                               dx=-24.0 if direction > 0 else (24.0 if direction < 0 else 0.0))

    def _remember_scroll(self, page, index: int):
        from PySide6.QtWidgets import QScrollArea
        if page is None:
            return
        area = page.findChild(QScrollArea)
        if area is not None:
            self._page_scroll[index] = area.verticalScrollBar().value()

    def _restore_scroll(self, page, index: int):
        from PySide6.QtWidgets import QScrollArea
        value = self._page_scroll.get(index)
        area = page.findChild(QScrollArea) if page is not None else None
        if area is not None and value:
            area.verticalScrollBar().setValue(value)

    def toggle_loop(self):
        self.is_loop_enabled = not self.is_loop_enabled
        icon_name = "repeat_active.svg" if self.is_loop_enabled else "repeat.svg"
        self.btn_loop.setIcon(QIcon(resource_path(os.path.join("assets", "icons", icon_name))))
        self.btn_loop.set_active(self.is_loop_enabled)

    def toggle_shuffle(self):
        self.is_shuffle_enabled = not self.is_shuffle_enabled
        icon_name = "shuffle_active.svg" if self.is_shuffle_enabled else "shuffle.svg"
        self.btn_shuffle.setIcon(QIcon(resource_path(os.path.join("assets", "icons", icon_name))))
        self.btn_shuffle.set_active(self.is_shuffle_enabled)
        self.reset_shuffle()                      # el orden de lo que viene se decide de nuevo
        if hasattr(self, "now_panel") and self.now_panel.isVisible():
            self.now_panel.refresh_next()         # y el panel «A continuación» enseña lo que de verdad sonará

    def check_ffmpeg_and_update(self):
        if os.environ.get("SELFTEST_SIN_FFMPEG"):
            return          # la autocomprobación de la compilación automática no descarga FFmpeg
        if not FFmpegService.is_ffmpeg_available():
            self.status_label.setText("Preparando la aplicación por primera vez, un momento...")
            self.ffmpeg_worker = FFmpegDownloadWorker()
            self.ffmpeg_worker.progress_signal.connect(lambda msg: self.status_label.setText(f"{msg}"))
            self.ffmpeg_worker.finished_signal.connect(self.on_ffmpeg_finished)
            self.ffmpeg_worker.start()
        else:
            self.on_ffmpeg_finished(True)

    def on_ffmpeg_finished(self, success):
        self._ffmpeg_missing = not success
        if success:
            self.status_label.setText("Escribe el nombre de una canción o artista para empezar.")
        else:
            self.status_label.setText("Falta un componente de audio. Se volverá a intentar cuando haya internet.")
            self.notify("No se pudo preparar el componente de audio (FFmpeg). Lo intentaremos de nuevo cuando haya conexión.")

    def open_music_folder(self):
        folder = str(get_download_dir())
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def open_artist_profile(self, artist_id: int, artist_name: str, avatar: str):
        """Abre la página completa de perfil de un artista."""
        self.switch_to_page(Page.ARTIST)
        self.page_artist.start_loading(artist_name)

        self.artist_worker = ArtistDetailsWorker(artist_id, artist_name, avatar)
        self.artist_worker.details_ready.connect(lambda data: self.page_artist.load_artist_data(data, self))
        self.artist_worker.error_occurred.connect(lambda err: self.notify(friendly_error(err)))
        self.artist_worker.start()

    def open_album_details(self, album_id: int):
        """Abre la página detallada de un álbum."""
        self.previous_page_before_album = self.stacked_widget.currentIndex()
        self.switch_to_page(Page.ALBUM)
        self.page_album.start_loading()
        self._travel_cover(lambda: self.page_album.cover_lbl)

        self.album_worker = AlbumDetailsWorker(album_id)
        self.album_worker.details_ready.connect(lambda data: self.page_album.load_album_data(data, self))
        self.album_worker.error_occurred.connect(lambda err: self.notify(friendly_error(err)))
        self.album_worker.start()

    # ---------- una miniatura vuela hasta donde ha ido la canción ----------
    def fly_to(self, info: dict, end_widget, start_global=None, on_done=None):
        """Una miniatura de la canción vuela del cursor (o de `start_global`) hasta `end_widget`: se ve adónde ha ido."""
        from PySide6.QtGui import QCursor
        from ui.covers import placeholder_cover
        if end_widget is None or not end_widget.isVisible():
            if on_done:
                on_done()
            return
        start = start_global or QCursor.pos()
        end = end_widget.mapToGlobal(end_widget.rect().center())
        pix = placeholder_cover((info or {}).get("title", ""), 34, 6)
        snapshot.fly(self, pix, start, end, 34, 320, on_done=on_done)

    def side_item(self, kind: str, list_id):
        entry = getattr(self, "_side_items", {}).get(f"{kind}:{list_id}")
        return entry[0] if entry else None

    # ---------- la portada viaja de la tarjeta a la cabecera de la página ----------
    def remember_cover_source(self, widget):
        pix = widget.pixmap() if hasattr(widget, "pixmap") else None
        if pix is None or pix.isNull():
            self._cover_src = None
            return
        self._cover_src = (pix, QRect(widget.mapTo(self, QPoint(0, 0)), widget.size()), 8)

    def _travel_cover(self, target_widget_fn):
        """Si la página se abrió desde una portada, esa portada viaja hasta su hueco en la cabecera (280 ms)."""
        src, self._cover_src = getattr(self, "_cover_src", None), None
        if not src or not motion.enabled():
            return
        pix, from_rect, radius = src

        def to_rect():
            w = target_widget_fn()
            if w is None or not w.isVisible():
                return None
            return QRect(w.mapTo(self, QPoint(0, 0)), w.size())

        QTimer.singleShot(40, lambda: snapshot.travel(self, pix, from_rect, to_rect, 280, radius))

    def go_back_from_album(self):
        """Regresa a la página que abrió el álbum."""
        target = self.previous_page_before_album if self.previous_page_before_album in [1, 2] else 1
        self.switch_to_page(target)

    def toggle_player_heart(self):
        if self.current_item_info:
            self.save_button_clicked(dict(self.current_item_info), self.player_heart_btn)
            pop_icon(self.player_heart_btn, ring=True)

    def update_player_heart_icon(self):
        saved = bool(self.current_item_info and PlaylistService.lists_containing(self.current_item_info))
        self.player_heart_btn.setIcon(save_icon(saved))

    def create_new_playlist_dialog(self):
        name, ok = ask_text(self, "Nueva lista", "Ponle un nombre a tu lista", ok="Crear", placeholder="Mi lista")
        if ok and name.strip():
            p_id = PlaylistService.create_playlist(name)
            self.refresh_playlists_sidebar()
            self.open_playlist_page(p_id)

    def create_playlist_with_track(self, track_info: dict):
        name, ok = ask_text(self, "Nueva lista", "Ponle un nombre a tu lista", ok="Crear", placeholder="Mi lista")
        if ok and name.strip():
            p_id = PlaylistService.create_playlist(name)
            PlaylistService.add_track_to_playlist(p_id, track_info)
            self.refresh_playlists_sidebar()
            self.notify(f"Añadida a «{name}»")

    def add_track_to_playlist(self, p_id: str, track_info: dict):
        ok = PlaylistService.add_track_to_playlist(p_id, track_info)
        playlists = PlaylistService.get_playlists()
        pl_name = playlists.get(p_id, {}).get("name", "Playlist")
        if ok:
            self.notify(f"Añadida a «{pl_name}»")
        else:
            self.notify(f"Esa canción ya está en «{pl_name}»")

    # ================= COLA, ECUALIZADOR Y TEMAS =================
    def add_to_queue(self, track_info: dict):
        self.fly_to(track_info, self.btn_queue)
        self.playback_queue.append(track_info)
        self.notify("Sonará a continuación")
        if self.now_panel.isVisible():
            self.now_panel.refresh_next()

    def open_queue_dialog(self):
        cur = self.current_item_info or {}
        dialog = QueueDialog(cur, self.playback_queue, self.upcoming_tracks(), self)
        dialog.play_item_requested.connect(lambda item: self._play_entry(item))
        dialog.queue_updated.connect(lambda: self.now_panel.isVisible() and self.now_panel.refresh_next())
        dialog.exec()

    def notify_track_changed(self, title: str, artist: str):
        """Muestra una notificación nativa de Windows en la bandeja del sistema (se puede desactivar en Ajustes)."""
        if not load_settings().get("notify_track_change", True):
            return
        try:
            if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
                msg = f"{artist} - {title}" if artist else title
                self.tray_icon.showMessage(
                    "Reproduciendo ahora",
                    msg,
                    QSystemTrayIcon.Information,
                    2500
                )
        except Exception:
            pass

    def play_preview(self, item_info: dict, btn: QPushButton = None, pixmap=None):
        # Canciones ya descargadas (desde playlists, favoritos o la cola): se reproducen desde el disco
        local = item_info.get('local_path')
        if local:
            if os.path.isfile(local):
                self.play_local_file(local)
            else:
                self.notify("No encontramos ese archivo. Puede que lo hayas movido o borrado.")
            return
        if self.is_offline():
            self.notify("Sin conexión: esta canción no está descargada.")
            return

        url = item_info['url']
        title = item_info.get('title', 'Desconocido')
        artist = item_info.get('uploader', 'Desconocido')

        if btn and self.current_preview_btn == btn and self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            return
        elif btn and self.current_preview_btn == btn and self.player.playbackState() == QMediaPlayer.PausedState:
            self.player.play()
            return

        if self.current_preview_btn:
            self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")

        self._remember_current(item_info)
        self._eq_source_path = None
        self._eq_active_render = None
        self.current_preview_btn = btn
        self.current_item_info = item_info
        self._show_player_bar()
        self.player_title.setText(title)
        self.player_artist.setText(artist)
        self.update_player_heart_icon()
        self.notify_track_changed(title, artist)
        self._refresh_lyrics_if_open()
        self._on_track_changed()

        if pixmap:
            self.player_thumb.setPixmap(pixmap)
        self.player_status.setText("Cargando...")
        self.btn_play_pause.setEnabled(False)

        if hasattr(self, 'preview_worker') and self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.is_cancelled = True
            try:
                self.preview_worker.ready.disconnect()
            except Exception:
                pass
            try:
                self.preview_worker.error.disconnect()
            except Exception:
                pass

        self._finish_crossfade()
        self.player.stop()

        self.preview_worker = PreviewAudioWorker(url)
        self.preview_worker.ready.connect(self._on_preview_ready)
        self.preview_worker.error.connect(self._on_preview_error)
        self.preview_worker.start()

    def open_metadata_dialog(self, file_path: str):
        dlg = MetadataDialog(file_path, parent=self)
        if dlg.exec():
            self.refresh_sidebar_library()

    def release_file(self, path: str) -> bool:
        """Suelta el archivo si algún reproductor lo tiene abierto: Windows no deja borrar ni renombrar un archivo abierto,
        aunque la canción esté parada o en pausa. Devuelve True si era el que estaba cargado como principal."""
        key = os.path.normcase(os.path.abspath(path))
        decks = [self.player] + ([self._spare_deck[0]] if self._spare_deck else []) + ([self._out_deck[0]] if self._out_deck else [])
        was_current = False
        for deck in decks:
            try:
                source = deck.source().toLocalFile()
                if source and os.path.normcase(os.path.abspath(source)) == key:
                    deck.stop()
                    deck.setSource(QUrl())
                    was_current = was_current or deck is self.player
            except RuntimeError:
                continue
        if was_current:
            QApplication.processEvents()
            time.sleep(0.15)                     # el reproductor tarda un instante en soltar el archivo
        return was_current

    def rename_file(self, path: str):
        """Cambia el nombre del archivo (la extensión se conserva)."""
        stem, ext = os.path.splitext(os.path.basename(path))
        new_name, ok = ask_text(self, "Cambiar nombre", "Nuevo nombre del archivo", text=stem, ok="Guardar")
        if ok and new_name.strip() and new_name.strip() != stem:
            from services.youtube_service import sanitize_filename
            new_path = os.path.join(os.path.dirname(path), sanitize_filename(new_name) + ext)
            if os.path.exists(new_path) and os.path.normcase(new_path) != os.path.normcase(path):
                show_message(self, "No se pudo cambiar el nombre", "Ya hay un archivo con ese nombre.")
                return
            if self.release_file(path):
                self.stop_player()
            try:
                os.rename(path, new_path)
            except Exception as e:
                show_message(self, "No se pudo cambiar el nombre", str(e))
                return
            PlaylistService.relocate(path, new_path)         # listas y favoritos siguen encontrando la canción
            self.rescan_library()

    def show_in_explorer(self, path):
        if not path or not os.path.exists(path):
            path = str(get_download_dir())

        if sys.platform == "win32":
            subprocess.run(['explorer', '/select,', os.path.normpath(path)])
        else:
            if os.path.isdir(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def delete_file(self, path: str):
        """Manda la canción a la papelera de Windows (se puede recuperar desde allí)."""
        from services import recycle
        name = os.path.basename(path)
        if self.release_file(path):
            self.stop_player()                     # era la canción cargada: se descarga del reproductor para poder borrarla
        deleted = recycle.move_to_recycle_bin(path)
        if not deleted:                              # puede que algo aún lo tenga abierto un instante: se reintenta una vez
            QApplication.processEvents()
            time.sleep(0.3)
            deleted = recycle.move_to_recycle_bin(path)
        if deleted:
            PlaylistService.relocate(path)
            self.rescan_library()
            margin = self.toast_margin()
            self.toast.show_message(f"«{name}» está en la papelera de Windows", bottom_margin=margin,
                                    action=("Ver papelera", recycle.open_recycle_bin))
            return
        # sin papelera disponible (otra unidad, otro sistema): se pide confirmación antes de borrar para siempre
        if ask_confirm(self, "Borrar de tu música",
                       f"¿Seguro que quieres borrar «{name}» de tu música?\nEsta acción no se puede deshacer.",
                       ok="Borrar", danger=True):
            try:
                os.remove(path)
            except Exception as e:
                show_message(self, "No se pudo borrar", str(e))
                return
            PlaylistService.relocate(path)
            self.rescan_library()

    def play_local_file(self, path: str, autoplay: bool = True, start_ms: int = 0):
        """Reproduce un audio local (desde la biblioteca lateral o las tarjetas de inicio).
        Con autoplay=False solo lo deja cargado y en pausa (en el punto start_ms)."""
        if not path or not os.path.isfile(path):
            return
        if not path.lower().endswith(('.mp3', '.m4a', '.wav', '.flac', '.ogg', '.wma')):
            return

        self._remember_current({'local_path': path})
        xf_ms = self._xf_request if (autoplay and self.player.playbackState() == QMediaPlayer.PlayingState) else 0
        self._xf_request = 0
        if xf_ms > 0:
            self._begin_crossfade(xf_ms, path)       # lo que suena sigue sonando en otro reproductor y baja; este recibe la nueva
        else:
            self._finish_crossfade()
            self.player.stop()
        if hasattr(self, 'preview_worker') and self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.is_cancelled = True

        if self.current_preview_btn:
            self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
            self.current_preview_btn = None

        meta = MetadataService.read_metadata(path)
        self.current_item_info = self._local_track_info(path, meta)
        title = self.current_item_info['title']
        artist = self.current_item_info['uploader']

        self._show_player_bar()
        self.player_title.setText(title)
        self.player_artist.setText(artist)
        self.update_player_heart_icon()
        if autoplay:
            self.notify_track_changed(title, artist)
        self._refresh_lyrics_if_open()
        self._on_track_changed()

        if meta.get("has_cover") and meta.get("cover_data"):
            img = QImage()
            if img.loadFromData(meta["cover_data"]):
                self.player_thumb.setPixmap(square_cover(QPixmap.fromImage(img), 56))
            else:
                self.player_thumb.setPixmap(QPixmap(resource_path(os.path.join("assets", "icons", "music.svg"))).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.player_thumb.setPixmap(QPixmap(resource_path(os.path.join("assets", "icons", "music.svg"))).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        self.player_status.setText("Reproduciendo" if autoplay else "Pausado")
        self.btn_play_pause.setEnabled(True)

        self._current_audio_device = QMediaDevices.defaultAudioOutput()
        self.audio_output.setDevice(self._current_audio_device)
        # Ecualizador: si la versión ajustada ya está lista se usa directamente; si no, se empieza con el original
        source, render = self._eq_source(path)
        self.player.setSource(QUrl.fromLocalFile(source))
        if autoplay:
            self.player.play()
        else:
            self.player.pause()
            if start_ms > 0:
                self._seek_when_loaded(start_ms)

        self._eq_source_path = path
        self._eq_active_render = render
        self._apply_eq_if_needed()

    def _show_player_bar(self):
        """La barra de reproducción aparece subiendo un poco la primera vez que suena algo."""
        if self.player_bar.isVisible():
            return
        self.player_bar.setVisible(True)
        QTimer.singleShot(40, lambda: slide_fade_in(self.player_bar, 16, motion.DUR_BASE + 40))

    def _seek_when_loaded(self, ms: int):
        """Coloca la canción en `ms` en cuanto el reproductor la tiene cargada (sin hacerla sonar)."""
        def on_status(status):
            if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
                try:
                    self.player.mediaStatusChanged.disconnect(on_status)
                except (RuntimeError, TypeError):
                    pass
                self.player.setPosition(ms)
        self.player.mediaStatusChanged.connect(on_status)

    # ---------- ayudas de reproducción ----------
    @staticmethod
    def _local_id(path: str) -> str:
        return local_id(path)

    def _local_track_info(self, path: str, meta: dict = None) -> dict:
        """Datos de una canción de la biblioteca, con el mismo formato que los resultados de búsqueda."""
        meta = meta if meta is not None else MetadataService.read_metadata(path)
        return {
            'id': self._local_id(path),
            'title': meta.get("title") or os.path.splitext(os.path.basename(path))[0],
            'uploader': meta.get("artist") or "Música local",
            'url': path,
            'local_path': path,
            'already_downloaded': True,
            'duration_str': '',
            'thumbnail': '',
        }

    def _alive_rows(self) -> list:
        alive = []
        for r in getattr(self, "_selected_rows", []):
            try:
                r.isVisible()
                alive.append(r)
            except RuntimeError:
                pass
        return alive

    def _rows_in_order(self, row) -> list:
        if row in self.page_playlist._cards.values():
            return self.page_playlist._ordered_rows()
        parent = row.parentWidget()
        siblings = [c for c in (parent.findChildren(TrackRow) if parent is not None else []) if c.parentWidget() is parent]
        return sorted(siblings, key=lambda c: c.y())

    def select_row(self, row, mode: str = "single"):
        """Marca filas de canción. «single»: solo esa; «toggle» (Ctrl): suma o quita; «range» (Mayús): desde la última."""
        old = self._alive_rows()
        current = list(old)
        if mode == "toggle":
            if row in current:
                current.remove(row)
            else:
                current.append(row)
        elif mode == "range" and current:
            ordered = self._rows_in_order(row)
            if row in ordered and current[-1] in ordered:
                a, b = sorted((ordered.index(current[-1]), ordered.index(row)))
                current = ordered[a:b + 1]
            else:
                current = [row]
        else:
            current = [row]
        for r in old:
            if r not in current:
                try:
                    r.set_selected(False)
                except RuntimeError:
                    pass
        for r in current:
            r.set_selected(True)
        self._selected_rows = current
        self._selected_row = current[-1] if current else None
        self.page_playlist.update_selection_bar(current)

    def clear_selection(self):
        for r in self._alive_rows():
            try:
                r.set_selected(False)
            except RuntimeError:
                pass
        self._selected_rows = []
        self._selected_row = None
        self.page_playlist.update_selection_bar([])

    def _on_track_changed(self):
        """La canción que suena cambió: se marca en la lista y se actualiza el panel lateral."""
        for page in (self.page_playlist,):
            page.update_playing()
        for page in (self.page_album, self.page_artist):
            for row in page.findChildren(TrackRow):
                try:
                    row.set_playing(self.is_current(row.item_info))
                except RuntimeError:
                    pass
        self.on_track_started()
        if load_settings().get("dynamic_accent", False):
            QTimer.singleShot(900, self._update_live_accent)         # cuando ya llegó la portada
        if self._full_player_visible() and self.current_item_info:
            self.full_player.set_track(self.current_item_info, None, None)
            QTimer.singleShot(900, lambda: self._full_player_visible() and self.full_player.set_track(
                self.current_item_info, self._cover_color(), self.player_thumb.pixmap()))
        if (not self.now_panel.isVisible() and self.current_item_info and not self.is_mini_mode
                and not getattr(self, "_panel_user_closed", False)):
            self.set_now_playing_visible(True)     # al reproducir, el panel aparece solo (como en Spotify)
        elif self.now_panel.isVisible():
            self.now_panel.set_track(self.current_item_info)

    def toggle_now_playing(self):
        """Abre o cierra el panel lateral derecho «En reproducción» (si lo cierras tú, no se vuelve a abrir solo)."""
        self._panel_user_closed = self.now_panel.isVisible()
        self.set_now_playing_visible(not self.now_panel.isVisible())

    def set_now_playing_visible(self, show: bool):
        if show == self.now_panel.isVisible():
            return
        self.now_panel.setVisible(show)
        if show:
            self.now_panel.set_track(self.current_item_info)
            fade_in(self.now_panel, 240)
        # la ventana necesita sitio para el panel: el mínimo crece (o vuelve a su valor) con él
        self.top_hbox.activate()
        self._fit_minimum_size()
        QTimer.singleShot(0, self._fit_minimum_size)

    def sync_favorite_hearts(self):
        """Mantiene sincronizados todos los corazones (barra inferior y tarjetas de la pantalla)."""
        self.update_player_heart_icon()
        for kind in (SongResultCard, TrackRow, TrackTile):
            for card in self.findChildren(kind):
                try:
                    card.refresh_state() if kind is TrackTile else card.update_heart_state()
                except RuntimeError:
                    pass
        if self.now_panel.isVisible():
            self.now_panel.refresh_like()

    def update_position(self, position_ms):
        self.playback_tick(position_ms)
        if getattr(self, "_in_background", False):
            dlg = self.lyrics_dialog
            if not (dlg is not None and dlg.isVisible()):
                return          # minimizada: no hace falta mover la barra ni la letra
        self.is_updating_seek = True
        try:
            if hasattr(self, "visualizer"):
                self.visualizer.set_position(position_ms)
            if self._full_player_visible():
                self.full_player.set_position(position_ms)
            if not self.seek_slider.isSliderDown():
                self.seek_slider.setValue(position_ms)
            self.time_current_label.setText(self.format_time(position_ms))
            if self.is_mini_mode:
                duration = self.player.duration()
                self.btn_play_pause.set_ring(position_ms / duration if duration > 0 else 0.0)

            if hasattr(self, 'lyrics_dialog') and self.lyrics_dialog and self.lyrics_dialog.isVisible():
                self.lyrics_dialog.update_position(position_ms)
            if self.now_panel.isVisible():
                self.now_panel.update_position(position_ms)

        finally:
            self.is_updating_seek = False

    def update_duration(self, duration_ms):
        if self._full_player_visible():
            self.full_player.set_duration(duration_ms)
        self.seek_slider.setRange(0, duration_ms)
        self.time_total_label.setText(self.format_time(duration_ms))

    def on_seek_changed(self, value):
        if not getattr(self, 'is_updating_seek', False):
            self.player.setPosition(value)

    def format_time(self, ms: int) -> str:
        if ms <= 0:
            return "00:00"
        total_seconds = int(ms // 1000)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        hours = minutes // 60
        minutes = minutes % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _on_preview_ready(self, stream_url):
        if self.player.playbackState() != QMediaPlayer.StoppedState:
            self.player.stop()

        self._current_audio_device = QMediaDevices.defaultAudioOutput()
        self.audio_output.setDevice(self._current_audio_device)

        self.player.setSource(QUrl(stream_url))
        self.player.play()
        self.player_status.setText("Reproduciendo")
        self.btn_play_pause.set_state(True)
        self.btn_play_pause.setEnabled(True)

    def _on_preview_error(self, error_msg):
        self.player_status.setText(friendly_error(error_msg))
        self.btn_play_pause.set_state(False)
        self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
        self.player.stop()

    def handle_player_error(self, error, error_string):
        self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
        self.player_status.setText(friendly_error(error_string))
        self.btn_play_pause.set_state(False)
        self.player.stop()

    def handle_media_status(self, status):
        if status == QMediaPlayer.InvalidMedia:
            self.handle_player_error(QMediaPlayer.FormatError, "Formato multimedia no compatible.")
        elif status == QMediaPlayer.EndOfMedia:
            if self._sleep_end_of_track:
                self.on_end_of_track()          # el temporizador pide parar al terminar esta canción
            elif self.is_loop_enabled:
                self.player.setPosition(0)
                self.player.play()
            else:
                self.on_end_of_track()          # marca el avance natural (para el fundido de entrada)
                self.play_next()

    def is_playing_now(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlayingState

    def handle_playback_state(self, state):
        self.update_system_status(state == QMediaPlayer.PlayingState)
        self.playing_changed.emit(state == QMediaPlayer.PlayingState)
        if state == QMediaPlayer.PlayingState:
            self._resume_pending = False
            if not getattr(self, "_panel_first_play_done", False):
                self._panel_first_play_done = True          # la primera vez que suena algo, el panel se abre siempre
                self._panel_user_closed = False
                if not self.now_panel.isVisible() and not self.is_mini_mode and self.current_item_info:
                    self.set_now_playing_visible(True)
        if hasattr(self, "home_continue"):
            self.home_continue.refresh()
        if self._full_player_visible():
            self.full_player.set_playing(state == QMediaPlayer.PlayingState)
        if getattr(self, "taskbar", None) is not None and self.taskbar.ok:
            self.taskbar.update_play_icon(icon("pause.svg" if state == QMediaPlayer.PlayingState else "play.svg",
                                               "#FFFFFF").pixmap(24, 24))
        if state == QMediaPlayer.PlayingState:
            self._set_info_dim(False)
            self.player_status.setText("Reproduciendo")
            self.btn_play_pause.set_state(True)
            self._safe_set_btn_text(self.current_preview_btn, " Pausa", "pause.svg")
            if hasattr(self, 'visualizer'):
                self.visualizer.set_playing(True)
        elif state == QMediaPlayer.PausedState:
            self._finish_crossfade()            # si se pausa a mitad de un fundido, la canción que se apagaba se corta
            self._set_info_dim(True)
            self.player_status.setText("Pausado")
            self.btn_play_pause.set_state(False)
            self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
            if hasattr(self, 'visualizer'):
                self.visualizer.set_playing(False)
        elif state == QMediaPlayer.StoppedState:
            self._set_info_dim(True)
            self.player_status.setText("Detenido")
            self.btn_play_pause.set_state(False)
            self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
            if hasattr(self, 'visualizer'):
                self.visualizer.set_playing(False)

    def _set_info_dim(self, dim: bool):
        """Con la música en pausa, la portada y el texto de la barra se ven más apagados."""
        self.player_thumb.set_dim(dim)
        for label in (self.player_title, self.player_artist):
            if bool(label.property("dim")) != dim:
                label.setProperty("dim", dim)
                label.style().unpolish(label)
                label.style().polish(label)
                label.update()

    def toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _safe_set_btn_text(self, btn, text, icon_name=None):
        if btn:
            try:
                if btn.property("iconOnly"):
                    # Botón circular solo-icono: play / pausa en negro
                    black = {"play.svg": "play_black.svg", "pause.svg": "pause_black.svg"}
                    if icon_name:
                        btn.setIcon(icon(black.get(icon_name, icon_name)))
                    return
                btn.setText(text)
                if icon_name:
                    btn.setIcon(QIcon(resource_path(os.path.join("assets", "icons", icon_name))))
            except RuntimeError:
                pass

    def stop_player(self):
        if self.is_mini_mode:
            self.toggle_mini_player()
        self._finish_crossfade()
        self.player.stop()
        self.player_bar.setVisible(False)
        self.seek_slider.setValue(0)
        self.time_current_label.setText("00:00")
        self.time_total_label.setText("00:00")
        self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
        self.current_preview_btn = None
        self.current_item_info = None
        if hasattr(self, 'preview_worker') and self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.is_cancelled = True
        self._on_track_changed()

    def stop_background_work(self, wait_ms: int = 2500):
        """Pide a todos los procesos en segundo plano (descargas, búsquedas, actualización, letras...) que paren y espera un
        momento a que lo hagan, para no dejar archivos a medias al salir."""
        running = []
        for thread in list(_ACTIVE_THREADS):
            try:
                if not thread.isRunning() or thread is QThread.currentThread():
                    continue
                if hasattr(thread, "cancel"):
                    thread.cancel()
                else:
                    thread.is_cancelled = True
                running.append(thread)
            except (RuntimeError, AttributeError):
                continue
        deadline = time.time() + wait_ms / 1000
        for thread in running:
            try:
                thread.wait(max(1, int((deadline - time.time()) * 1000)))
            except RuntimeError:
                pass

    def closeEvent(self, event):
        if self.should_close_to_tray():          # «seguir sonando en la bandeja»
            event.ignore()
            self.hide_to_tray()
            return
        logging.info("Cerrando aplicación...")
        self.save_session()
        self.shutdown_playback_options()

        self.stop_background_work()

        if getattr(self, "full_player", None) is not None:
            try:
                self.full_player.close()
            except RuntimeError:
                pass
        tooltips.uninstall()
        focusring.uninstall(self._focus_ring)
        self._set_blocked_click_filter(False)
        if getattr(self, "taskbar", None) is not None:
            self.taskbar.set_progress(None)
            self.taskbar.shutdown()
        if hasattr(self, 'player'):
            self.player.stop()
            self.player.setSource(QUrl())

        clean_cache()
        from ui.imageloader import shutdown as shutdown_images
        shutdown_images()
        event.accept()
