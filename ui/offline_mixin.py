"""Modo sin conexión: la aplicación sigue siendo útil sin internet.

  * Avisa de forma amable (banner) y se recupera sola cuando vuelve la conexión.
  * Las canciones que no están descargadas se oscurecen y no se pueden seleccionar.
  * Inicio muestra tu música, tus listas y mixes hechos con lo que tienes descargado.
  * La búsqueda pasa a buscar solo dentro de tu música descargada.
  * Las descargas que pidas (o que fallen por falta de red) quedan pendientes y se reanudan solas.
"""
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from services import library_search, local_mixes, network_service, pending_downloads, library_db
from services.library_search import fold
from ui.icons import icon
from ui.song_card import SongResultCard
from ui.track_row import TrackRow


class OfflineBanner(QFrame):
    """Franja discreta bajo la barra superior: «Sin conexión…» con botón para reintentar."""

    def __init__(self, window):
        super().__init__()
        self.window_ref = window
        self.setObjectName("OfflineBanner")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(12)
        self.icon_lbl = QLabel()
        self.icon_lbl.setPixmap(icon("offline.svg", "#FFD166").pixmap(20, 20))
        self.icon_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self.icon_lbl)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setStyleSheet("background: transparent; font-weight: 600; font-size: 13px;")
        lay.addWidget(self.text, stretch=1)
        self.btn = QPushButton("Reintentar")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self._retry)
        lay.addWidget(self.btn)
        self.setVisible(False)

    def set_state(self, offline: bool, forced: bool):
        self.setVisible(offline)
        if forced:
            self.text.setText("Modo sin conexión activado. Tu música descargada y tus listas funcionan igual.")
            self.btn.setText("Volver a conectar")
        else:
            self.text.setText("Sin conexión a internet. Puedes seguir escuchando tu música descargada y usando tus listas.")
            self.btn.setText("Reintentar")

    def _retry(self):
        net = self.window_ref.network
        if net.forced_offline:
            net.set_forced_offline(False)
            self.window_ref.settings_dialog.chk_offline.setChecked(False)
            return
        net.check_now()
        self.window_ref.notify("Comprobando la conexión...")
        QTimer.singleShot(3200, lambda: self.window_ref.is_offline() and self.window_ref.notify("Sigue sin haber conexión."))


class OfflineMixin:
    """Mezcla para MainWindow. Requiere: topbar, stacked_widget, settings_dialog, notify(), refresh_home(),
    reload_current_list(), library_items() y resolve_local()."""

    def init_offline_state(self):
        self.network = network_service.monitor()
        self.network.changed.connect(self._on_connectivity)
        self._local_mixes = []
        self._pending_keys = set()

    def build_offline_banner(self, layout):
        self.offline_banner = OfflineBanner(self)
        layout.insertWidget(0, self.offline_banner)

    # -------------------------------------------------------------- estado
    def is_offline(self) -> bool:
        return not self.network.is_online()

    def offline_blocks(self, info: dict) -> bool:
        """True si sin conexión esta canción no se puede usar (no está descargada)."""
        return self.is_offline() and not self.resolve_local(info or {})

    def _on_connectivity(self, online: bool):
        self.offline_banner.set_state(not online, self.network.forced_offline)
        self.topbar.set_offline(not online)
        chk = self.settings_dialog.chk_offline
        chk.blockSignals(True)
        chk.setChecked(self.network.forced_offline)
        chk.blockSignals(False)
        self.page_playlist.on_connectivity(not online)
        self.apply_offline_to_cards()
        self.refresh_home()
        if online:
            self.notify("Conexión recuperada")
            QTimer.singleShot(400, self.refresh_recommendations)
            QTimer.singleShot(1200, self.resume_pending_downloads)
        else:
            self.notify("Sin conexión: tu música descargada y tus listas siguen funcionando")
        self.reload_current_list()

    def apply_offline_to_cards(self):
        for row in self.findChildren(TrackRow):
            try:
                row.apply_offline()
            except RuntimeError:
                pass

    # ------------------------------------------------- reproducción sin red
    def playable(self, info: dict) -> bool:
        return not self.offline_blocks(info)

    def first_playable_index(self, items: list, start: int = 0) -> int:
        for i in range(max(0, start), len(items)):
            if self.playable(items[i]):
                return i
        return -1

    # --------------------------------------------------- búsqueda sin red
    def local_search(self, query: str):
        """Con o sin conexión forzada: busca solo dentro de tu música descargada."""
        self.switch_to_page(1)
        self.clear_results_container()
        for worker in (self._catalog_worker, self._direct_worker):
            if worker is not None and worker.isRunning():
                worker.is_cancelled = True
        self._q = query
        self._res = {"artists": [], "albums": [], "tracks": []}
        self._direct_mode = True
        self._loading_more = False
        self.more_loading.setVisible(False)
        self.search_loading.setVisible(False)
        for chip in self.search_chips.values():
            chip.setVisible(False)
        found = library_search.search_items(self.library_items(), query)
        if found:
            self.status_label.setText(f"Sin conexión: {len(found)} resultado{'s' if len(found) != 1 else ''} en tu música descargada")
        else:
            self.status_label.setText("Sin conexión: no hay nada así en tu música descargada.")
        self.set_context(found)
        for it in found:
            self.results_layout.addWidget(SongResultCard(it, parent_window=self))

    # --------------------------------------------- listas locales (sin red)
    def local_artist_items(self, name: str) -> list:
        from ui.formatting import split_artists
        wanted = fold(name)
        out = []
        for it in self.library_items():
            parts = [fold(p) for p in split_artists(it.get("uploader", ""))] or [fold(it.get("uploader", ""))]
            if wanted in parts or fold(it.get("uploader", "")) == wanted:
                out.append(it)
        return out

    def local_album_items(self, album: str) -> list:
        wanted = fold(album)
        items = [it for it in self.library_items() if fold(it.get("album", "")) == wanted]
        return sorted(items, key=lambda t: (t.get("track_no") or 999, t.get("title", "")))

    def smart_list_items(self, key: str):
        for k, name, tracks in local_mixes.smart_lists(self.library_items(), library_db.play_stats()):
            if k == key:
                return name, tracks
        return None

    def refresh_local_mixes(self):
        self._local_mixes = local_mixes.build_local_mixes(self.library_items())

    # --------------------------------------------- descargas pendientes
    def is_pending(self, info: dict) -> bool:
        key = str(info.get("id") or info.get("url") or info.get("title"))
        return key in self._pending_keys

    def queue_download(self, infos) -> int:
        """Deja canciones en la cola de pendientes (se bajarán cuando haya conexión)."""
        infos = [infos] if isinstance(infos, dict) else list(infos)
        added = pending_downloads.add(infos)
        self._reload_pending_keys()
        self.refresh_download_marks()
        return added

    def _reload_pending_keys(self):
        self._pending_keys = {str(i.get("id") or i.get("url") or i.get("title")) for i in pending_downloads.load()}

    def refresh_download_marks(self):
        for row in self.findChildren(TrackRow):
            try:
                row.refresh_state()
            except RuntimeError:
                pass
        if hasattr(self, "downloads_panel"):
            self.downloads_panel.refresh_pending()
        self.on_downloads_changed()

    def resume_pending_downloads(self):
        """Cuando vuelve internet (o al abrir la aplicación con conexión), se retoman las descargas pendientes."""
        if self.is_offline():
            return
        items = pending_downloads.load()
        if not items:
            return
        remaining = [i for i in items if not self.resolve_local(i)]
        if len(remaining) != len(items):
            pending_downloads.clear()
            pending_downloads.add(remaining)
        self._reload_pending_keys()
        if not remaining:
            return
        self.notify(f"Retomando {len(remaining)} descarga{'s' if len(remaining) != 1 else ''} pendiente{'s' if len(remaining) != 1 else ''}…")
        self.start_batch_download(remaining, from_pending=True)
