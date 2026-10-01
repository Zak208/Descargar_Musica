"""Búsqueda: canciones, artistas y álbumes con filtros, carga automática al llegar al final y modo enlace."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QWidget, QFrame, QScrollArea

from services.catalog_service import CatalogSearchWorker
from services.spotify_service import is_spotify_url
from services.youtube_service import SearchWorker, is_youtube_url
from ui.friendly import friendly_error
from ui.home_shelves import ArtistTile, make_shelf
from ui.loading import LoadingBlock
from ui.song_card import SongResultCard
from ui.spotify_views import AlbumCard
from ui.widgets import ReflowGrid

FILTERS = (("all", "Todo"), ("tracks", "Canciones"), ("artists", "Artistas"), ("albums", "Álbumes"))
CATEGORY_FOR_FILTER = {"all": "tracks", "tracks": "tracks", "artists": "artists", "albums": "albums"}
MAX_TRACKS = 150
MAX_GRID = 60


def _key(category: str, item: dict):
    if category == "tracks":
        return (item.get("title", "").lower(), item.get("uploader", "").lower())
    return item.get("id") or item.get("name", "").lower()


class SearchMixin:
    """Mezcla para MainWindow. Requiere: stacked_widget, results_layout, scroll_area, status_label,
    batch_banner, topbar, notify(), open_artist_by_name(), open_album_details()."""

    def init_search_state(self):
        self._q = ""
        self._filter = "all"
        self._res = {"artists": [], "albums": [], "tracks": []}
        self._limits = {"artists": 7, "tracks": 20, "albums": 12}
        self._exhausted = set()
        self._loading_more = False
        self._catalog_worker = None
        self._direct_worker = None
        self._direct_mode = False
        self._artists_target = None
        self._albums_target = None

    # ------------------------------------------------------------------ interfaz
    def build_results_page(self):
        """Página de resultados: filtros, estado, banner de descarga en lote, lista y animaciones de carga."""
        self.page_results = QWidget()
        lay = QVBoxLayout(self.page_results)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.build_search_header(lay)

        self.status_label = QLabel("Escribe un artista, álbum o canción para comenzar")
        self.status_label.setObjectName("StatusDetail")
        self.status_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #B3B3B3;")
        lay.addWidget(self.status_label)

        # Banner de descarga en lote
        self.batch_banner = QFrame()
        self.batch_banner.setObjectName("BatchBanner")
        self.batch_banner.setVisible(False)
        banner = QHBoxLayout(self.batch_banner)
        banner.setContentsMargins(16, 12, 16, 12)
        banner.setSpacing(16)
        self.batch_banner_label = QLabel("Lista disponible")
        self.batch_banner_label.setStyleSheet("color: #FFFFFF; font-size: 14px; font-weight: bold;")
        banner.addWidget(self.batch_banner_label, stretch=1)
        self.btn_download_batch = QPushButton("Descargar todo")
        self.btn_download_batch.setObjectName("BatchDownloadBtn")
        self.btn_download_batch.setCursor(Qt.PointingHandCursor)
        banner.addWidget(self.btn_download_batch)
        lay.addWidget(self.batch_banner)

        self.build_search_loading(lay)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignTop)
        self.results_layout.setSpacing(14)
        self.scroll_area.setWidget(self.results_container)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_results_scroll)
        lay.addWidget(self.scroll_area, stretch=1)

        self.build_more_loading(lay)
        self.stacked_widget.addWidget(self.page_results)

    def build_search_header(self, layout):
        """Filtros (Todo / Canciones / Artistas / Álbumes) en la parte alta de los resultados."""
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search_chips = {}
        for key, label in FILTERS:
            chip = QPushButton(label)
            chip.setObjectName("TabBtn")
            chip.setCheckable(True)
            chip.setChecked(key == "all")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, k=key: self.set_search_filter(k))
            row.addWidget(chip)
            self.search_chips[key] = chip
        row.addStretch()
        layout.addLayout(row)

    def build_search_loading(self, layout):
        self.search_loading = LoadingBlock("Buscando...")
        self.search_loading.setVisible(False)
        layout.addWidget(self.search_loading)

    def build_more_loading(self, layout):
        self.more_loading = LoadingBlock("Cargando más resultados...")
        self.more_loading.layout().setContentsMargins(0, 8, 0, 8)
        self.more_loading.setVisible(False)
        layout.addWidget(self.more_loading)

    def clear_results_container(self):
        """Limpia la vista de resultados anteriores."""
        self.current_preview_btn = None
        self.batch_banner.setVisible(False)
        self._artists_target = self._albums_target = None
        for i in reversed(range(self.results_layout.count())):
            item = self.results_layout.takeAt(i)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

    # ------------------------------------------------------------------ búsqueda
    def perform_search(self, query):
        if not query:
            self.notify("Escribe qué canción o artista quieres buscar.")
            return
        self.switch_to_page(1)
        self.clear_results_container()
        for worker in (self._catalog_worker, self._direct_worker):
            if worker is not None and worker.isRunning():
                worker.is_cancelled = True

        self._q = query
        self._res = {"artists": [], "albums": [], "tracks": []}
        self._limits = {"artists": 7, "tracks": 20, "albums": 12}
        self._exhausted = set()
        self._loading_more = False
        self.more_loading.setVisible(False)
        self.status_label.setText("")
        self.search_loading.set_text(f"Buscando «{query}»...")
        self.search_loading.setVisible(True)

        if is_youtube_url(query) or is_spotify_url(query):
            self._direct_mode = True
            for chip in self.search_chips.values():
                chip.setVisible(False)
            self._run_direct(query)
        else:
            self._direct_mode = False
            for chip in self.search_chips.values():
                chip.setVisible(True)
            self._start_catalog(initial=True)

    def _run_direct(self, query: str):
        self._direct_worker = SearchWorker(query)
        self._direct_worker.results_ready.connect(self.display_direct_results)
        self._direct_worker.error_occurred.connect(self.handle_search_error)
        self._direct_worker.start()

    def _start_catalog(self, initial: bool):
        worker = CatalogSearchWorker(self._q, dict(self._limits))
        worker.results_ready.connect(lambda res, w=worker: self._on_catalog_results(res, initial, w))
        worker.error_occurred.connect(self.handle_search_error)
        self._catalog_worker = worker
        worker.start()

    def _on_catalog_results(self, results: dict, initial: bool, worker):
        if worker is not self._catalog_worker or getattr(worker, "is_cancelled", False):
            return
        self.search_loading.setVisible(False)
        self.more_loading.setVisible(False)
        self._loading_more = False

        if initial:
            if not any(results.get(k) for k in ("artists", "albums", "tracks")):
                self.search_loading.set_text("Buscando en YouTube...")
                self.search_loading.setVisible(True)
                self._direct_mode = True
                self._run_direct(self._q)
                return
            for cat in self._res:
                self._res[cat] = list(results.get(cat, []))
            self._render_results()
        else:
            self._merge_results(results)
        QTimer.singleShot(250, self._maybe_load_more)

    # -------------------------------------------------------------- mostrar
    def set_search_filter(self, key: str):
        self._filter = key
        for k, chip in self.search_chips.items():
            chip.setChecked(k == key)
        if self._direct_mode:
            return
        self._render_results()
        # al entrar en Artistas / Álbumes se piden más para llenar la pantalla
        cat = CATEGORY_FOR_FILTER[key]
        wanted = {"artists": 24, "albums": 30, "tracks": 40}[cat]
        if key != "all" and self._limits[cat] < wanted and cat not in self._exhausted:
            self._limits[cat] = wanted
            self._fetch_more(show_loader=True)

    def _render_results(self):
        self.clear_results_container()
        res, f = self._res, self._filter
        total = sum(len(v) for v in res.values())
        self.status_label.setText("" if total else "No hemos encontrado nada. Prueba con otras palabras o pega un enlace.")

        if f == "all":
            if res["artists"]:
                box, row = make_shelf("Artistas", 238)
                for a in res["artists"]:
                    row.addWidget(self._artist_tile(a))
                self.results_layout.addWidget(box)
            if res["albums"]:
                box, row = make_shelf("Álbumes", 262)
                for alb in res["albums"]:
                    row.addWidget(self._album_card(alb))
                self.results_layout.addWidget(box)
                self._albums_target = row
            if res["tracks"]:
                title = QLabel("Canciones")
                title.setObjectName("SectionTitle")
                self.results_layout.addWidget(title)
                for t in res["tracks"]:
                    self.results_layout.addWidget(SongResultCard(t, parent_window=self))
        elif f == "tracks":
            for t in res["tracks"]:
                self.results_layout.addWidget(SongResultCard(t, parent_window=self))
        elif f == "artists":
            grid = ReflowGrid(164)
            for a in res["artists"]:
                grid.add(self._artist_tile(a))
            self.results_layout.addWidget(grid)
            self._artists_target = grid
        elif f == "albums":
            grid = ReflowGrid(155)
            for alb in res["albums"]:
                grid.add(self._album_card(alb))
            self.results_layout.addWidget(grid)
            self._albums_target = grid
        if f != "all" and not res[CATEGORY_FOR_FILTER[f]]:
            self.status_label.setText("No hay resultados en esta categoría.")

    def _artist_tile(self, artist: dict):
        tile = ArtistTile(artist)
        tile.clicked.connect(self.open_artist_by_name)
        return tile

    def _album_card(self, album: dict):
        card = AlbumCard(album)
        card.clicked.connect(self.open_album_details)
        return card

    # ------------------------------------------------- cargar más al llegar al final
    def _on_results_scroll(self, _value: int):
        if self.stacked_widget.currentIndex() == 1:
            self._maybe_load_more()

    def _maybe_load_more(self):
        if self._direct_mode or self._loading_more or not self._q or self.stacked_widget.currentIndex() != 1:
            return
        cat = CATEGORY_FOR_FILTER[self._filter]
        if cat in self._exhausted:
            return
        cap = MAX_TRACKS if cat == "tracks" else MAX_GRID
        if self._limits[cat] >= cap or not self._res[cat]:
            return
        bar = self.scroll_area.verticalScrollBar()
        if bar.maximum() <= 0 or bar.value() >= bar.maximum() - 400:
            self._limits[cat] = min(cap, self._limits[cat] * 2)
            self._fetch_more(show_loader=True)

    def _fetch_more(self, show_loader: bool):
        if self._loading_more:
            return
        self._loading_more = True
        if show_loader:
            self.more_loading.setVisible(True)
        self._start_catalog(initial=False)

    def _merge_results(self, results: dict):
        """Añade solo lo nuevo, sin recargar lo que ya se está viendo."""
        for cat in ("artists", "albums", "tracks"):
            known = {_key(cat, i) for i in self._res[cat]}
            new_items = [i for i in results.get(cat, []) if _key(cat, i) not in known]
            if not new_items:
                if cat == CATEGORY_FOR_FILTER[self._filter] and self._limits[cat] >= len(results.get(cat, [])):
                    self._exhausted.add(cat)
                continue
            self._res[cat].extend(new_items)
            self._append_widgets(cat, new_items)

    def _append_widgets(self, cat: str, items: list):
        f = self._filter
        if cat == "tracks" and f in ("all", "tracks"):
            for t in items:
                self.results_layout.addWidget(SongResultCard(t, parent_window=self))
        elif cat == "albums" and self._albums_target is not None and f in ("all", "albums"):
            for alb in items:
                card = self._album_card(alb)
                if hasattr(self._albums_target, "add"):
                    self._albums_target.add(card)
                else:
                    self._albums_target.addWidget(card)
        elif cat == "artists" and f == "artists" and self._artists_target is not None:
            for a in items:
                self._artists_target.add(self._artist_tile(a))

    # ------------------------------------------------------------- enlaces
    def display_direct_results(self, results: list):
        self.search_loading.setVisible(False)
        if not results:
            self.status_label.setText("No hemos encontrado nada. Prueba con otras palabras o pega un enlace.")
            return
        for chip in self.search_chips.values():
            chip.setVisible(False)
        self.status_label.setText(f"Hemos encontrado {len(results)} canciones:")

        if len(results) > 1:
            self.batch_banner.setVisible(True)
            self.batch_banner_label.setText(f"Colección detectada: {len(results)} canciones")
            try:
                self.btn_download_batch.clicked.disconnect()
            except Exception:
                pass
            self.btn_download_batch.clicked.connect(lambda: self.start_batch_download(results))

        for item in results:
            self.results_layout.addWidget(SongResultCard(item, parent_window=self))

    def handle_search_error(self, err_msg: str):
        self.search_loading.setVisible(False)
        self.more_loading.setVisible(False)
        self._loading_more = False
        self.status_label.setText(friendly_error(err_msg))
