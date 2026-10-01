import os
import sys
import logging
import subprocess

from PySide6.QtCore import (
    Qt, QUrl, QSize, QThread, QTimer, Signal, QPropertyAnimation, QEasingCurve, QObject, QEvent
)
from PySide6.QtGui import QPixmap, QImage, QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QApplication, QFileDialog, QStackedWidget, QGraphicsOpacityEffect, QSystemTrayIcon
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices

from config import (
    get_download_dir, set_download_dir, set_audio_quality, get_theme, set_theme
)
from services.youtube_service import (
    PreviewAudioWorker, is_youtube_url
)
from services.spotify_service import is_spotify_url
from services.catalog_service import (
    ArtistDetailsWorker, AlbumDetailsWorker
)
from services.ffmpeg_service import FFmpegService
from services.metadata_service import MetadataService
from services.playlist_service import PlaylistService
from ui.styles import MAIN_STYLE, get_theme_stylesheet, THEME_CONFIGS, set_active_theme, accent, retheme_stylesheet
from ui.icons import icon
from ui.playback_mixin import PlaybackMixin
from ui.lists_mixin import ListsMixin
from ui.home_mixin import HomeMixin
from ui.search_mixin import SearchMixin
from ui.downloads_mixin import DownloadsMixin
from ui.artist_page import ArtistProfilePage
from ui.album_page import AlbumDetailsPage
from ui.list_page import ListPage
from ui.library_page import LibraryPage
from services.equalizer_service import (
    EqRenderWorker, load_eq_settings, active_bands, rendered_path_for, clean_cache
)
from ui.toast import Toast
from ui.topbar import TopBar
from ui.downloads_panel import DownloadsTracker, DownloadsPanel
from ui.animations import pop_icon
from ui.dialogs import ask_text, ask_confirm, show_message
from ui.imageloader import prune_disk_cache
from ui.friendly import friendly_error
from ui.common import resource_path
from ui.song_card import SongResultCard, square_cover
from ui.sidebar import build_sidebar
from ui.home_page import build_home_page
from ui.player_bar import build_player_bar
from ui.lyrics_dialog import LyricsDialog
from ui.metadata_dialog import MetadataDialog
from ui.equalizer_dialog import EqualizerDialog
from ui.queue_dialog import QueueDialog

class ThemeEventFilter(QObject):
    """Adapta al tema activo los estilos en línea (colores fijos) de cada widget cuando se muestra.
    Solo se instala si el tema no es el de por defecto (así no gasta CPU en el caso habitual)."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget):
            qss = obj.styleSheet()
            if qss and "#" in qss and len(qss) < 20000 and not obj.property("noRetheme"):
                from ui.styles import _active_theme
                new_qss = retheme_stylesheet(qss, _active_theme)
                if new_qss != qss:
                    obj.setStyleSheet(new_qss)
        return False


class FFmpegDownloadWorker(QThread):
    progress_signal = Signal(str)
    finished_signal = Signal(bool)

    def run(self):
        try:
            FFmpegService.download_ffmpeg_portable(lambda msg: self.progress_signal.emit(msg))
            self.finished_signal.emit(True)
        except Exception:
            self.finished_signal.emit(False)


class MainWindow(QMainWindow, PlaybackMixin, ListsMixin, HomeMixin, SearchMixin, DownloadsMixin):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Descargador de Música")
        self.setWindowIcon(QIcon(resource_path("assets/logo.jpg")))
        self.resize(1360, 860)
        self.setStyleSheet(MAIN_STYLE)

        # Reproductor
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.current_preview_btn = None
        self.current_item_info = None
        self.preview_worker = None
        self.is_updating_seek = False

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

        self.equalizer_dialog = None

        # Historial, contexto de reproducción y biblioteca (ver playback_mixin / lists_mixin)
        self.init_playback_state()
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

        self.player.errorOccurred.connect(self.handle_player_error)
        self.player.mediaStatusChanged.connect(self.handle_media_status)
        self.player.playbackStateChanged.connect(self.handle_playback_state)
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)

        self.current_theme = get_theme()
        set_active_theme(self.current_theme)
        self._theme_filter = ThemeEventFilter(self)
        self._set_theme_filter(self.current_theme != "spotify")   # con el tema por defecto no hace falta vigilar nada
        self.toast = Toast(self)
        self.downloads = DownloadsTracker(self)
        self._download_info_reset = QTimer(self)
        self._download_info_reset.setSingleShot(True)
        self._download_info_reset.timeout.connect(self.update_header_info)
        self.init_ui()
        self.check_ffmpeg_and_update()
        QTimer.singleShot(0, self._fit_minimum_size)
        QTimer.singleShot(150, self.rescan_library)          # lee la biblioteca en segundo plano
        QTimer.singleShot(0, self.watch_library)
        QTimer.singleShot(4000, prune_disk_cache)

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

        # Barra superior (de lado a lado): marca, inicio, buscador, información general y descargas en curso
        self.topbar = TopBar()
        self.topbar.search_submitted.connect(self.perform_search)
        self.topbar.home_clicked.connect(lambda: self.switch_to_page(0))
        self.topbar.downloads_clicked.connect(self.show_downloads_panel)
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
        self.page_artist.back_clicked.connect(lambda: self.switch_to_page(1))
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

    def keyPressEvent(self, event):
        """Atajos de teclado globales para control multimedia."""
        focus_w = QApplication.focusWidget()
        if isinstance(focus_w, QLineEdit):
            super().keyPressEvent(event)
            return

        key = event.key()
        if key == Qt.Key_Space:
            self.toggle_play_pause()
            event.accept()
            return
        elif key == Qt.Key_Left:
            cur = self.player.position()
            self.player.setPosition(max(0, cur - 5000))
            event.accept()
            return
        elif key == Qt.Key_Right:
            cur = self.player.position()
            dur = self.player.duration()
            self.player.setPosition(min(dur, cur + 5000))
            event.accept()
            return
        elif key == Qt.Key_M:
            cur_vol = self.volume_slider.value()
            if cur_vol > 0:
                self._prev_vol = cur_vol
                self.volume_slider.setValue(0)
            else:
                self.volume_slider.setValue(getattr(self, '_prev_vol', 100))
            event.accept()
            return
        elif event.modifiers() == Qt.ControlModifier and key == Qt.Key_F:
            self.focus_search()
            event.accept()
            return
        elif key in [Qt.Key_MediaPlay, Qt.Key_MediaPause, Qt.Key_MediaTogglePlayPause]:
            self.toggle_play_pause()
            event.accept()
            return
        elif key == Qt.Key_MediaNext:
            self.play_next()
            event.accept()
            return
        elif key == Qt.Key_MediaPrevious:
            self.play_previous()
            event.accept()
            return

        super().keyPressEvent(event)

    def open_lyrics(self):
        """Abre la ventana de letras. Solo puede haber una: si ya está abierta, se trae al frente."""
        if not self.current_item_info:
            self.notify("Reproduce una canción primero para ver su letra.")
            return

        existing = self.lyrics_dialog
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                pass
            self.lyrics_dialog = None

        title = self.current_item_info.get('title', '')
        artist = self.current_item_info.get('uploader', '')
        dlg = LyricsDialog(title, artist, player=self.player, parent=self)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.destroyed.connect(lambda *_: setattr(self, 'lyrics_dialog', None))
        self.lyrics_dialog = dlg
        dlg.show()

    def toggle_mini_player(self):
        """Reproductor pequeño: solo la barra de reproducción, siempre visible encima de otras ventanas."""
        if not self.is_mini_mode and not self.player_bar.isVisible():
            self.notify("Reproduce una canción primero.")
            return

        self.is_mini_mode = not self.is_mini_mode
        extras = [
            self.btn_shuffle, self.btn_loop, self.btn_lyrics, self.btn_queue, self.btn_eq,
            self.vol_icon, self.volume_slider, self.player_status, self.visualizer,
            self.player_heart_btn, self.btn_close_player,
        ]
        if self.is_mini_mode:
            self.normal_geometry = self.geometry()
            self._normal_min_size = self.minimumSize()
            self.topbar.setVisible(False)
            self.sidebar.setVisible(False)
            self.content_widget.setVisible(False)
            for w in extras:
                w.setVisible(False)
            self.info_widget.setMaximumWidth(230)
            self.seek_slider.setMaximumWidth(260)
            self.setMinimumSize(0, 0)
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.resize(640, self.player_bar.height() + 16)
            self.show()
            QTimer.singleShot(0, lambda: self.is_mini_mode and self.resize(640, self.player_bar.height() + 16))
        else:
            for w in extras:
                w.setVisible(True)
            self.info_widget.setMaximumWidth(280)
            self.seek_slider.setMaximumWidth(560)
            self.topbar.setVisible(True)
            self.sidebar.setVisible(True)
            self.content_widget.setVisible(True)
            self.setMinimumSize(getattr(self, "_normal_min_size", QSize(0, 0)))
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            if self.normal_geometry:
                self.setGeometry(self.normal_geometry)
            self.show()

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
        """Al volver a la ventana, si hay un enlace de YouTube/Spotify copiado, lo ofrece en el buscador."""
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._suggest_clipboard_link()
        super().changeEvent(event)

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

    def _fit_minimum_size(self):
        """El tamaño mínimo de la ventana es el que necesita la aplicación para no recortar ni encoger nada."""
        self.content_widget.setMinimumWidth(720)
        hint = self.minimumSizeHint()
        hint.setHeight(max(hint.height(), 720))   # alto razonable: las listas se desplazan, pero el resto no debe agobiarse
        self.setMinimumSize(hint)
        if self.width() < hint.width() or self.height() < hint.height():
            self.resize(max(self.width(), hint.width()), max(self.height(), hint.height()))

    def notify(self, text: str):
        """Muestra un aviso breve y no intrusivo en la parte inferior."""
        margin = (self.player_bar.height() + 24) if self.player_bar.isVisible() else 40
        self.toast.show_message(text, bottom_margin=margin)

    def focus_search(self):
        self.topbar.search.setFocus()
        self.topbar.search.selectAll()

    def open_settings(self):
        self.settings_dialog.refresh_download_dir()
        self.settings_dialog.exec()

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

    def switch_to_page(self, target_index: int):
        """Cambia de página con una animación suave de desvanecimiento (Fade-in)."""
        current = self.stacked_widget.currentIndex()
        if current == target_index:
            return
        if target_index == 0 and self._home_dirty:
            self._home_dirty = False
            self.refresh_home()
        target_widget = self.stacked_widget.widget(target_index)
        if not target_widget:
            return
        self.stacked_widget.setCurrentIndex(target_index)

        eff = QGraphicsOpacityEffect(target_widget)
        target_widget.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.15)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._page_transition_anim = anim

    def toggle_loop(self):
        self.is_loop_enabled = not self.is_loop_enabled
        icon_name = "repeat_active.svg" if self.is_loop_enabled else "repeat.svg"
        self.btn_loop.setIcon(QIcon(resource_path(os.path.join("assets", "icons", icon_name))))

    def toggle_shuffle(self):
        self.is_shuffle_enabled = not self.is_shuffle_enabled
        icon_name = "shuffle_active.svg" if self.is_shuffle_enabled else "shuffle.svg"
        self.btn_shuffle.setIcon(QIcon(resource_path(os.path.join("assets", "icons", icon_name))))

    def check_ffmpeg_and_update(self):
        if not FFmpegService.is_ffmpeg_available():
            self.status_label.setText("Preparando la aplicación por primera vez, un momento...")
            self.ffmpeg_worker = FFmpegDownloadWorker()
            self.ffmpeg_worker.progress_signal.connect(lambda msg: self.status_label.setText(f"{msg}"))
            self.ffmpeg_worker.finished_signal.connect(self.on_ffmpeg_finished)
            self.ffmpeg_worker.start()
        else:
            self.on_ffmpeg_finished(True)

    def on_ffmpeg_finished(self, success):
        self.status_label.setText("Escribe el nombre de una canción o artista para empezar.")

    def open_music_folder(self):
        folder = str(get_download_dir())
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def open_artist_profile(self, artist_id: int, artist_name: str, avatar: str):
        """Abre la página completa de perfil de un artista."""
        self.switch_to_page(2)
        self.page_artist.start_loading(artist_name)

        self.artist_worker = ArtistDetailsWorker(artist_id, artist_name, avatar)
        self.artist_worker.details_ready.connect(lambda data: self.page_artist.load_artist_data(data, self))
        self.artist_worker.error_occurred.connect(lambda err: self.notify(friendly_error(err)))
        self.artist_worker.start()

    def open_album_details(self, album_id: int):
        """Abre la página detallada de un álbum."""
        self.previous_page_before_album = self.stacked_widget.currentIndex()
        self.switch_to_page(3)
        self.page_album.start_loading()

        self.album_worker = AlbumDetailsWorker(album_id)
        self.album_worker.details_ready.connect(lambda data: self.page_album.load_album_data(data, self))
        self.album_worker.error_occurred.connect(lambda err: self.notify(friendly_error(err)))
        self.album_worker.start()

    def go_back_from_album(self):
        """Regresa a la página que abrió el álbum."""
        target = self.previous_page_before_album if self.previous_page_before_album in [1, 2] else 1
        self.switch_to_page(target)

    # ================= MÉTODOS DE FAVORITOS Y PLAYLISTS =================
    def refresh_favorites_ui(self):
        """Actualiza el corazón de la barra inferior y de todas las canciones visibles."""
        self.sync_favorite_hearts()
        self.refresh_playlists_sidebar()

    def toggle_player_heart(self):
        if not self.current_item_info:
            return
        is_fav = PlaylistService.toggle_favorite(self.current_item_info)
        self.sync_favorite_hearts()
        pop_icon(self.player_heart_btn)
        self.refresh_playlists_sidebar()
        self.notify("Añadida a «Canciones que te gustan»" if is_fav else "Quitada de «Canciones que te gustan»")

    def update_player_heart_icon(self):
        if not self.current_item_info:
            self.player_heart_btn.setIcon(icon("heart.svg", "#B3B3B3"))
            return
        is_fav = PlaylistService.is_favorite(
            self.current_item_info.get("id"),
            self.current_item_info.get("title")
        )
        self.player_heart_btn.setIcon(icon("heart_filled.svg", accent()) if is_fav else icon("heart.svg", "#B3B3B3"))

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
        self.playback_queue.append(track_info)
        self.notify("Sonará a continuación")

    def open_queue_dialog(self):
        cur = self.current_item_info or {}
        dialog = QueueDialog(cur, self.playback_queue, self.upcoming_tracks(), self)
        dialog.play_item_requested.connect(lambda item: self._play_entry(item))
        dialog.exec()

    def open_equalizer(self):
        if not self.equalizer_dialog:
            self.equalizer_dialog = EqualizerDialog(self)
            self.equalizer_dialog.eq_changed.connect(self.on_eq_changed)
        self.equalizer_dialog.exec()

    def _set_theme_filter(self, active: bool):
        app = QApplication.instance()
        if active:
            app.installEventFilter(self._theme_filter)
        else:
            app.removeEventFilter(self._theme_filter)

    def on_theme_changed(self):
        theme_key = self.theme_combo.currentData()
        if theme_key:
            set_theme(theme_key)
            set_active_theme(theme_key)
            self._set_theme_filter(theme_key != "spotify")
            self.current_theme = theme_key
            self.setStyleSheet(get_theme_stylesheet(theme_key))
            accent_hex = THEME_CONFIGS.get(theme_key, {}).get("accent", "#1ED760")
            if hasattr(self, 'visualizer'):
                self.visualizer.set_accent_color(accent_hex)
            self.update_player_heart_icon()
            self.topbar.refresh_accent()
            for w in self.findChildren(QWidget):
                qss = w.styleSheet()
                if qss and len(qss) < 20000 and not w.property("noRetheme"):
                    new_qss = retheme_stylesheet(qss, theme_key)
                    if new_qss != qss:
                        w.setStyleSheet(new_qss)

    def notify_track_changed(self, title: str, artist: str):
        """Muestra una notificación nativa de Windows en la bandeja del sistema."""
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
        self.player_bar.setVisible(True)
        self.player_title.setText(title)
        self.player_artist.setText(artist)
        self.update_player_heart_icon()
        self.notify_track_changed(title, artist)
        self._refresh_lyrics_if_open()

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

        self.player.stop()

        self.preview_worker = PreviewAudioWorker(url)
        self.preview_worker.ready.connect(self._on_preview_ready)
        self.preview_worker.error.connect(self._on_preview_error)
        self.preview_worker.start()

    def open_metadata_dialog(self, file_path: str):
        dlg = MetadataDialog(file_path, parent=self)
        if dlg.exec():
            self.refresh_sidebar_library()

    def rename_file(self, path: str):
        """Cambia el nombre del archivo (la extensión se conserva)."""
        stem, ext = os.path.splitext(os.path.basename(path))
        new_name, ok = ask_text(self, "Cambiar nombre", "Nuevo nombre del archivo", text=stem, ok="Guardar")
        if ok and new_name.strip() and new_name.strip() != stem:
            new_path = os.path.join(os.path.dirname(path), new_name.strip() + ext)
            try:
                os.rename(path, new_path)
            except Exception as e:
                show_message(self, "No se pudo cambiar el nombre", str(e))
                return
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
        """Borra la canción de tu música (pide confirmación)."""
        if ask_confirm(self, "Borrar de tu música",
                       f"¿Seguro que quieres borrar «{os.path.basename(path)}» de tu música?\nEsta acción no se puede deshacer.",
                       ok="Borrar", danger=True):
            try:
                os.remove(path)
            except Exception as e:
                show_message(self, "No se pudo borrar", str(e))
                return
            self.rescan_library()

    def play_local_file(self, path: str):
        """Reproduce un audio local (desde la biblioteca lateral o las tarjetas de inicio)."""
        if not path or not os.path.isfile(path):
            return
        if not path.lower().endswith(('.mp3', '.m4a', '.wav', '.flac', '.ogg', '.wma')):
            return

        self._remember_current({'local_path': path})
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

        self.player_bar.setVisible(True)
        self.player_title.setText(title)
        self.player_artist.setText(artist)
        self.update_player_heart_icon()
        self.notify_track_changed(title, artist)
        self._refresh_lyrics_if_open()

        if meta.get("has_cover") and meta.get("cover_data"):
            img = QImage()
            if img.loadFromData(meta["cover_data"]):
                self.player_thumb.setPixmap(square_cover(QPixmap.fromImage(img), 56))
            else:
                self.player_thumb.setPixmap(QPixmap(resource_path(os.path.join("assets", "icons", "music.svg"))).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.player_thumb.setPixmap(QPixmap(resource_path(os.path.join("assets", "icons", "music.svg"))).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        self.player_status.setText("Reproduciendo")
        self.btn_play_pause.setEnabled(True)

        self._current_audio_device = QMediaDevices.defaultAudioOutput()
        self.audio_output.setDevice(self._current_audio_device)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

        # Ecualizador: se empieza con el original y se cambia a la versión ajustada cuando está lista
        self._eq_source_path = path
        self._eq_active_render = None
        self._apply_eq_if_needed()

    # ---------- ayudas de reproducción ----------
    @staticmethod
    def _local_id(path: str) -> str:
        return "local::" + os.path.normcase(os.path.abspath(path))

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

    def _refresh_lyrics_if_open(self):
        """Si la ventana de letras está abierta, la cambia a la canción que acaba de empezar."""
        dlg = self.lyrics_dialog
        try:
            if dlg is not None and dlg.isVisible() and self.current_item_info:
                dlg.close()
                self.lyrics_dialog = None
                self.open_lyrics()
        except RuntimeError:
            self.lyrics_dialog = None

    def sync_favorite_hearts(self):
        """Mantiene sincronizados todos los corazones (barra inferior y tarjetas de la pantalla)."""
        self.update_player_heart_icon()
        for card in self.findChildren(SongResultCard):
            try:
                card.update_heart_state()
            except RuntimeError:
                pass

    # ---------- ecualizador ----------
    def _apply_eq_if_needed(self):
        path = self._eq_source_path
        if not path:
            return
        bands = active_bands(self.eq_settings)
        if bands is None:
            if self._eq_active_render:
                self._swap_source(path)
                self._eq_active_render = None
            return
        out = rendered_path_for(path, bands)
        if out.exists():
            if self._eq_active_render != str(out):
                self._swap_source(str(out))
                self._eq_active_render = str(out)
            return
        if self._eq_worker is not None and self._eq_worker.isRunning():
            self._eq_worker.is_cancelled = True
        self._eq_worker = EqRenderWorker(path, bands)
        self._eq_worker.done.connect(self._on_eq_rendered)
        self._eq_worker.failed.connect(lambda msg: logging.warning(f"Ecualizador: {msg}"))
        self._eq_worker.start()

    def _on_eq_rendered(self, src: str, rendered: str):
        if src != self._eq_source_path or active_bands(self.eq_settings) is None:
            return
        if str(rendered_path_for(src, active_bands(self.eq_settings))) != str(rendered):
            return  # el ajuste cambió mientras se procesaba
        self._swap_source(rendered)
        self._eq_active_render = rendered

    def _swap_source(self, file_path: str):
        """Cambia el archivo que suena (original <-> con ecualizador) conservando el punto de la canción."""
        if not os.path.isfile(file_path):
            return
        pos = self.player.position()
        resume = self.player.playbackState() != QMediaPlayer.PausedState
        self._swap_token = getattr(self, '_swap_token', 0) + 1
        token = self._swap_token
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(file_path))
        # El reproductor necesita un instante tras cambiar de archivo; si se le pide sonar de inmediato se queda parado.
        QTimer.singleShot(300, lambda: self._swap_resume(token, pos, resume))

    def _swap_resume(self, token: int, pos: int, resume: bool):
        if token != getattr(self, '_swap_token', 0):
            return  # mientras tanto empezó otra canción
        if resume:
            self.player.play()
        if pos > 500:
            QTimer.singleShot(500, lambda: token == self._swap_token and self.player.setPosition(pos))

    def on_eq_changed(self, data: dict):
        self.eq_settings = data
        playing_local = bool(self._eq_source_path) and self.player_bar.isVisible()
        if active_bands(data) is None:
            self.notify("Sonido normal")
        elif playing_local:
            self.notify("Aplicando el ajuste de sonido...")
        else:
            self.notify("Listo. Se notará en las canciones de tu biblioteca.")
        self._apply_eq_if_needed()

    def update_position(self, position_ms):
        self.is_updating_seek = True
        try:
            if not self.seek_slider.isSliderDown():
                self.seek_slider.setValue(position_ms)
            self.time_current_label.setText(self.format_time(position_ms))

            if hasattr(self, 'lyrics_dialog') and self.lyrics_dialog and self.lyrics_dialog.isVisible():
                self.lyrics_dialog.update_position(position_ms)

        finally:
            self.is_updating_seek = False

    def update_duration(self, duration_ms):
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
        self.btn_play_pause.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "pause_black.svg"))))
        self.btn_play_pause.setEnabled(True)

    def _on_preview_error(self, error_msg):
        self.player_status.setText(friendly_error(error_msg))
        self.btn_play_pause.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "play_black.svg"))))
        self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
        self.player.stop()

    def handle_player_error(self, error, error_string):
        self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
        self.player_status.setText(friendly_error(error_string))
        self.btn_play_pause.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "play_black.svg"))))
        self.player.stop()

    def handle_media_status(self, status):
        if status == QMediaPlayer.InvalidMedia:
            self.handle_player_error(QMediaPlayer.FormatError, "Formato multimedia no compatible.")
        elif status == QMediaPlayer.EndOfMedia:
            if self.is_loop_enabled:
                self.player.setPosition(0)
                self.player.play()
            else:
                self.play_next()

    def handle_playback_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self.info_anim.stop()
            self.info_anim.setEndValue(1.0)
            self.info_anim.start()
            self.player_status.setText("Reproduciendo")
            self.btn_play_pause.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "pause_black.svg"))))
            self._safe_set_btn_text(self.current_preview_btn, " Pausa", "pause.svg")
            if hasattr(self, 'visualizer'):
                self.visualizer.set_playing(True)
        elif state == QMediaPlayer.PausedState:
            self.info_anim.stop()
            self.info_anim.setEndValue(0.5)
            self.info_anim.start()
            self.player_status.setText("Pausado")
            self.btn_play_pause.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "play_black.svg"))))
            self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
            if hasattr(self, 'visualizer'):
                self.visualizer.set_playing(False)
        elif state == QMediaPlayer.StoppedState:
            self.info_anim.stop()
            self.info_anim.setEndValue(0.5)
            self.info_anim.start()
            self.player_status.setText("Detenido")
            self.btn_play_pause.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "play_black.svg"))))
            self._safe_set_btn_text(self.current_preview_btn, " Escuchar", "play.svg")
            if hasattr(self, 'visualizer'):
                self.visualizer.set_playing(False)

    def toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def change_volume(self, value):
        self.audio_output.setVolume(value / 100.0)

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

    def closeEvent(self, event):
        logging.info("Cerrando aplicación...")

        if hasattr(self, 'catalog_worker') and self.catalog_worker and self.catalog_worker.isRunning():
            self.catalog_worker.is_cancelled = True

        if hasattr(self, 'search_worker') and self.search_worker and self.search_worker.isRunning():
            self.search_worker.is_cancelled = True

        if hasattr(self, 'preview_worker') and self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.is_cancelled = True

        if hasattr(self, 'ffmpeg_worker') and self.ffmpeg_worker and self.ffmpeg_worker.isRunning():
            self.ffmpeg_worker.is_cancelled = True

        if hasattr(self, 'updater') and self.updater and self.updater.isRunning():
            self.updater.is_cancelled = True

        if self._eq_worker is not None and self._eq_worker.isRunning():
            self._eq_worker.is_cancelled = True
            self._eq_worker.wait(1500)

        if hasattr(self, 'player'):
            self.player.stop()
            self.player.setSource(QUrl())

        clean_cache()
        from ui.imageloader import shutdown as shutdown_images
        shutdown_images()
        event.accept()
