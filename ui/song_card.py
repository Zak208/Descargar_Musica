"""Fila de canción de los resultados de búsqueda."""
import os
import sys
import subprocess

from ui.animations import fade_in, pop_icon, press_feedback

from PySide6.QtCore import Qt, QUrl, QSize, QRectF
from PySide6.QtGui import QPixmap, QDesktopServices, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QSizePolicy,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QProgressBar, QMenu
)

from config import get_download_dir, get_audio_quality
from services.youtube_service import DownloadWorker
from services.playlist_service import PlaylistService
from ui.styles import accent
from ui.icons import icon
from ui.save_popup import save_icon
from ui.widgets import ElidedLabel
from ui.friendly import friendly_error

from ui.common import _ACTIVE_THREADS
from ui.formatting import format_added
from ui.perf import eco
from ui.imageloader import ImageLoaderThread, LocalCoverLoader


COVER_SIZE = 56
ALBUM_COL = 200      # anchos de las columnas de las listas (la cabecera de columnas usa los mismos)
DATE_COL = 110
DOWNLOAD_COL = 164


def square_cover(pixmap: QPixmap, size: int, radius: int = 6) -> QPixmap:
    """Recorta al centro la imagen en formato cuadrado y le redondea las esquinas."""
    dpr = 2
    px = size * dpr
    scaled = pixmap.scaled(px, px, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = (scaled.width() - px) // 2
    y = (scaled.height() - px) // 2
    scaled = scaled.copy(x, y, px, px)
    result = QPixmap(px, px)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, px, px), radius * dpr, radius * dpr)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    result.setDevicePixelRatio(dpr)
    return result


ACTION_IDLE = "#8A8A8A"  # color de los botones secundarios en reposo (siempre visibles)
ACTION_HOT = "#FFFFFF"   # color al pasar el ratón por la fila


class SongResultCard(QFrame):
    def __init__(self, item_info: dict, parent_window, parent=None, list_mode: bool = False):
        super().__init__(parent)
        self.setObjectName("ResultCard")
        self.item_info = item_info
        self.parent_window = parent_window
        self.list_mode = list_mode
        self._shown_once = False
        self._hot = False
        self._detect_downloaded()
        self.init_ui()

    def _detect_downloaded(self):
        """Si la canción ya está en tu música, la fila lo indica y se reproduce desde el disco."""
        if self.item_info.get('already_downloaded') and self.item_info.get('local_path'):
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

    def showEvent(self, event):
        """Aparición suave la primera vez que se muestra la fila (con un pequeño escalonado)."""
        if not self._shown_once:
            self._shown_once = True
            if eco():
                super().showEvent(event)
                return
            parent = self.parentWidget()
            order = 0
            if parent is not None:
                try:
                    order = [c for c in parent.children() if isinstance(c, SongResultCard)].index(self)
                except ValueError:
                    order = 0
            fade_in(self, 260, min(order, 10) * 35)
        super().showEvent(event)

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 16, 8)
        layout.setSpacing(14)

        # 1. Portada cuadrada
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(COVER_SIZE, COVER_SIZE)
        self.thumb_label.setStyleSheet("background-color: #2A2A2A; border-radius: 6px;")
        self.load_thumbnail()
        layout.addWidget(self.thumb_label)

        # 2. Título / artista (+ progreso de descarga)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        info_layout.setAlignment(Qt.AlignVCenter)

        self.title_label = ElidedLabel(self.item_info.get('title', 'Sin título'))
        self.title_label.setObjectName("SongTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setToolTip(self.item_info.get('title', ''))
        info_layout.addWidget(self.title_label)

        self.artist_label = ElidedLabel(self.item_info.get('uploader', 'Artista'))
        self.artist_label.setObjectName("ArtistName")
        info_layout.addWidget(self.artist_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setVisible(False)
        info_layout.addWidget(self.progress_bar)

        self.status_detail_label = QLabel("")
        self.status_detail_label.setObjectName("StatusDetail")
        self.status_detail_label.setVisible(False)
        info_layout.addWidget(self.status_detail_label)

        layout.addLayout(info_layout, stretch=1)

        # Columnas de las listas (álbum y fecha en que se añadió), como en Spotify
        self.album_label = self.date_label = None
        if self.list_mode:
            self.album_label = ElidedLabel(self.item_info.get('album', ''))
            self.album_label.setObjectName("ArtistName")
            self.album_label.setFixedWidth(ALBUM_COL)
            self.album_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)   # ancho fijo: si no, la columna se colapsa
            self.album_label.setToolTip(self.item_info.get('album', ''))
            layout.addWidget(self.album_label)
            self.date_label = QLabel(format_added(self.item_info.get('_added_ts')))
            self.date_label.setObjectName("ArtistName")
            self.date_label.setFixedWidth(DATE_COL)
            layout.addWidget(self.date_label)

        # 3. Acciones secundarias: solo aparecen al pasar el ratón (como en Spotify)
        self.hover_actions = QWidget()
        self.hover_actions.setStyleSheet("background: transparent;")
        hover_layout = QHBoxLayout(self.hover_actions)
        hover_layout.setContentsMargins(0, 0, 0, 0)
        hover_layout.setSpacing(2)
        self.hover_actions.setFixedWidth(94)   # ancho fijo (3 botones) aunque falte el de carpeta: así las columnas no se mueven
        hover_layout.addStretch()

        self.heart_btn = QPushButton("")
        self.heart_btn.setObjectName("IconBtn")
        self.heart_btn.setIconSize(QSize(18, 18))
        self.heart_btn.setToolTip("Guardar en una lista")
        self.heart_btn.setCursor(Qt.PointingHandCursor)
        self.heart_btn.clicked.connect(self.toggle_favorite_card)
        press_feedback(self.heart_btn)
        hover_layout.addWidget(self.heart_btn)
        self.update_heart_state()

        self.menu_btn = QPushButton("")
        self.menu_btn.setObjectName("IconBtn")
        self.menu_btn.setIcon(icon("more.svg", ACTION_IDLE))
        self.menu_btn.setIconSize(QSize(18, 18))
        self.menu_btn.setToolTip("Más opciones")
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.menu_btn.clicked.connect(self.show_track_menu)
        hover_layout.addWidget(self.menu_btn)

        self.open_folder_btn = QPushButton("")
        self.open_folder_btn.setObjectName("IconBtn")
        self.open_folder_btn.setIcon(icon("folder.svg", ACTION_IDLE))
        self.open_folder_btn.setIconSize(QSize(18, 18))
        self.open_folder_btn.setToolTip("Ver en carpeta")
        self.open_folder_btn.setCursor(Qt.PointingHandCursor)
        self.open_folder_btn.clicked.connect(self.open_in_folder)
        hover_layout.addWidget(self.open_folder_btn)
        # Importante: se muestra u oculta DESPUÉS de meterlo en su contenedor. Si se hacía antes, el botón
        # aún no tenía "padre" y Windows abría un instante una ventanita suelta por cada canción descargada.
        self.open_folder_btn.setVisible(bool(self.item_info.get('already_downloaded')))

        layout.addWidget(self.hover_actions)

        # 4. Duración
        self.duration_label = QLabel(self.item_info.get('duration_str', '0:00'))
        self.duration_label.setObjectName("ArtistName")
        self.duration_label.setFixedWidth(48)
        self.duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.duration_label)

        # 5. Reproducir (vista previa) y descargar: siempre visibles
        self.preview_btn = QPushButton("")
        self.preview_btn.setObjectName("RoundPlayBtn")
        self.preview_btn.setProperty("iconOnly", True)
        self.preview_btn.setIcon(icon("play_black.svg"))
        self.preview_btn.setIconSize(QSize(18, 18))
        self.preview_btn.setToolTip("Escuchar vista previa")
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.clicked.connect(self.toggle_preview)
        press_feedback(self.preview_btn)
        layout.addWidget(self.preview_btn)

        if self.item_info.get('already_downloaded'):
            self.download_btn = QPushButton(" Ya descargada")
            self.download_btn.setIcon(icon("check.svg", accent()))
            self.download_btn.setObjectName("DownloadedBtn")
        else:
            self.download_btn = QPushButton(" Descargar")
            self.download_btn.setIcon(icon("download_black.svg"))
            self.download_btn.setObjectName("DownloadBtn")
        self.download_btn.setIconSize(QSize(16, 16))
        self.download_btn.setFixedWidth(DOWNLOAD_COL)
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.clicked.connect(self.start_download)
        layout.addWidget(self.download_btn)

    def _paint_actions(self):
        """Los botones secundarios se ven siempre en gris; al pasar el ratón por la fila se iluminan."""
        color = ACTION_HOT if self._hot else ACTION_IDLE
        self.menu_btn.setIcon(icon("more.svg", color))
        self.open_folder_btn.setIcon(icon("folder.svg", color))
        self.update_heart_state()

    def enterEvent(self, event):
        self._hot = True
        self._paint_actions()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hot = False
        self._paint_actions()
        super().leaveEvent(event)

    def update_heart_state(self):
        saved = bool(PlaylistService.lists_containing(self.item_info))
        self.heart_btn.setIcon(save_icon(saved, ACTION_HOT if self._hot else ACTION_IDLE))

    def toggle_favorite_card(self):
        if self.parent_window and hasattr(self.parent_window, "save_button_clicked"):
            self.parent_window.save_button_clicked(dict(self.item_info), self.heart_btn)
        self.update_heart_state()
        pop_icon(self.heart_btn)

    def show_track_menu(self):
        if not self.parent_window:
            return
        menu = QMenu(self)

        act_queue = menu.addAction(icon("queue.svg"), "Añadir a la cola de reproducción")
        act_queue.triggered.connect(lambda: self.parent_window.add_to_queue(self.item_info))

        playlists = PlaylistService.get_playlists()
        pl_menu = menu.addMenu(icon("playlist.svg"), "Añadir a playlist")

        act_new_pl = pl_menu.addAction(icon("plus.svg"), "Crear nueva playlist...")
        act_new_pl.triggered.connect(lambda: self.parent_window.create_playlist_with_track(self.item_info))

        if playlists:
            pl_menu.addSeparator()
            for p_id, p_data in playlists.items():
                p_name = p_data.get("name", "Playlist")
                act_add = pl_menu.addAction(p_name)
                act_add.triggered.connect(lambda _, pid=p_id: self.parent_window.add_track_to_playlist(pid, self.item_info))

        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def load_thumbnail(self):
        url = self.item_info.get('thumbnail')
        local = self.item_info.get('local_path')
        if url:
            loader = ImageLoaderThread(url, False, (COVER_SIZE, COVER_SIZE), 6)
        elif local and os.path.isfile(local):
            loader = LocalCoverLoader(local, False, (COVER_SIZE, COVER_SIZE), 6)
        else:
            return
        loader.image_loaded.connect(self._set_thumb)
        self._thumb_loader = loader
        loader.start()

    def _set_thumb(self, pix):
        try:
            self.thumb_label.setPixmap(pix)
        except RuntimeError:
            pass

    def open_in_folder(self):
        target_path = getattr(self, 'downloaded_path', None)
        if target_path and os.path.exists(target_path):
            folder = os.path.dirname(target_path)
        else:
            folder = str(get_download_dir())

        if sys.platform == "win32":
            subprocess.run(['explorer', '/select,', os.path.normpath(target_path if target_path and os.path.exists(target_path) else folder)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def refresh_date(self):
        """Actualiza el texto de 'añadida' (pasan los minutos y cambia de '5 min' a '6 min')."""
        if self.date_label is not None:
            self.date_label.setText(format_added(self.item_info.get('_added_ts')))

    def set_columns_visible(self, visible: bool):
        """Muestra u oculta las columnas de álbum y fecha (se ocultan si no caben)."""
        for w in (self.album_label, self.date_label):
            if w is not None:
                w.setVisible(visible)

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Arrastrar el resultado hacia una lista de la barra lateral lo añade a ella."""
        pos = getattr(self, "_press_pos", None)
        if (event.buttons() & Qt.LeftButton) and pos is not None:
            from PySide6.QtWidgets import QApplication
            if (event.position().toPoint() - pos).manhattanLength() > QApplication.startDragDistance() + 6:
                self._press_pos = None
                from ui.dragdrop import start_track_drag
                start_track_drag(self, dict(self.item_info))
                return
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event):
        if self.parent_window and hasattr(self.parent_window, "open_track_menu"):
            self.parent_window.open_track_menu(self.item_info, event.globalPos(), getattr(self, "extra_menu", None))

    def toggle_preview(self):
        pixmap = self.thumb_label.pixmap()
        if hasattr(self.parent_window, "set_context_from_card"):
            self.parent_window.set_context_from_card(self)
        self.parent_window.play_preview(self.item_info, self.preview_btn, pixmap)

    def start_download(self):
        if self.item_info.get('local_path'):
            self.downloaded_path = self.item_info['local_path']
            self.open_in_folder()
            return
        duration_secs = self.item_info.get('duration_secs', 0)
        if duration_secs > 1200:
            from ui.dialogs import ask_confirm
            if not ask_confirm(
                self, "Canción muy larga",
                f"Este audio dura {self.item_info.get('duration_str', '')} (más de 20 minutos).\n¿Quieres descargarlo de todas formas?",
                ok="Descargar"):
                return

        self.download_btn.setEnabled(False)
        self.download_btn.setText(" Guardando...")
        self.progress_bar.setVisible(True)
        self.status_detail_label.setVisible(True)

        download_dir = str(get_download_dir())
        quality = get_audio_quality()

        self.worker = DownloadWorker(self.item_info, download_dir, quality)
        if hasattr(self.parent_window, "downloads"):
            self.parent_window.downloads.track(self.worker, self.item_info)
        _ACTIVE_THREADS.add(self.worker)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.download_finished)
        self.worker.finished_signal.connect(lambda res, w=self.worker: _ACTIVE_THREADS.discard(w))
        self.worker.start()

    def update_progress(self, info: dict):
        try:
            percent = info.get('percent', 0)
            info.get('speed_mb', 0)
            status = info.get('status', '')

            self.progress_bar.setValue(percent)
            if status == 'converting':
                self.status_detail_label.setText("Preparando tu canción...")
            else:
                self.status_detail_label.setText(f"Descargando… {percent}%")
        except RuntimeError:
            pass

    def download_finished(self, result: dict):
        try:
            if getattr(self.worker, 'is_cancelled', False):
                return
            if result['success']:
                self.downloaded_path = result.get('mp3_path')
                self.progress_bar.setValue(100)
                self.download_btn.setText(" Ya descargada")
                self.download_btn.setObjectName("DownloadedBtn")
                self.download_btn.setIcon(icon("check.svg", accent()))
                self.download_btn.style().unpolish(self.download_btn)
                self.download_btn.style().polish(self.download_btn)
                self.status_detail_label.setText("Guardada en tu música")
                self.open_folder_btn.setVisible(True)

                self.parent_window.refresh_sidebar_library()
                self.parent_window.notify(f"«{self.item_info.get('title', 'Canción')}» descargada")
            else:
                self.download_btn.setEnabled(True)
                self.download_btn.setText(" Reintentar")
                self.download_btn.setIcon(icon("download_black.svg"))
                self.status_detail_label.setText(friendly_error(result.get('error')))
        except RuntimeError:
            pass
