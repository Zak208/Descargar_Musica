"""Página de una lista (estilo Spotify): Canciones que te gustan, Mis descargas, una playlist propia o un mix."""
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
    QLineEdit, QListWidget, QListWidgetItem, QMenu
)

from services.playlist_service import PlaylistService
from ui.animations import fade_in
from ui.covers import list_cover_pixmap, tile_colors, MIX_COLORS, GENRE_COLORS
from ui.dialogs import ask_text, ask_confirm
from ui.formatting import format_total, parse_added
from ui.icons import icon
from ui.loading import LoadingBlock
from ui.overlay import InlineDialog
from ui.track_row import TrackRow, IDX_COL, ROW_COVER, ALBUM_COL, DATE_COL, ICON_COL, DUR_COL, ROW_SPACING

KIND_TITLES = {"favorites": "LISTA", "downloads": "LISTA", "playlist": "PLAYLIST", "mix": "MIX PARA TI", "genre": "GÉNERO"}

# Formas de ordenar una lista (clave -> texto del menú)
SORT_OPTIONS = {
    "custom": "Orden de la lista",
    "title": "Título",
    "artist": "Artista",
    "album": "Álbum",
    "added": "Añadidas recientemente",
    "duration": "Duración",
}
ROW_BATCH = 40           # filas que se crean de golpe; el resto se crea al desplazarse (ahorra memoria y CPU)
COLUMNS_MIN_WIDTH = 900  # por debajo de este ancho se ocultan las columnas de álbum y fecha


def _sort_value(key: str, item: dict):
    if key == "title":
        return (item.get("title") or "").lower()
    if key == "artist":
        return ((item.get("uploader") or "").lower(), (item.get("title") or "").lower())
    if key == "album":
        return ((item.get("album") or "").lower(), (item.get("title") or "").lower())
    if key == "added":
        return item.get("_added_ts", 0)
    if key == "duration":
        return int(item.get("duration_secs", 0) or 0)
    return item.get("_order", 0)


class CoverTileButton(QPushButton):
    """Portada de la lista. En playlists propias, al pasar el ratón ofrece cambiar la imagen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlat(True)
        self.setFixedSize(140, 140)
        self.setIconSize(QSize(140, 140))
        self.setStyleSheet("QPushButton { border: none; background: transparent; padding: 0px; }")
        self.editable = False
        self.overlay = QLabel("Elegir imagen", self)
        self.overlay.setAlignment(Qt.AlignCenter)
        self.overlay.setGeometry(0, 0, 140, 140)
        self.overlay.setStyleSheet(
            "background-color: rgba(0, 0, 0, 150); color: #FFFFFF; border-radius: 12px; font-weight: 600; font-size: 13px;")
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.overlay.hide()

    def set_editable(self, editable: bool):
        self.editable = editable
        self.setCursor(Qt.PointingHandCursor if editable else Qt.ArrowCursor)
        self.setToolTip("Cambiar la imagen de la lista" if editable else "")
        if not editable:
            self.overlay.hide()

    def enterEvent(self, event):
        if self.editable:
            self.overlay.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.overlay.hide()
        super().leaveEvent(event)


class AddSongsDialog(InlineDialog):
    """Elegir canciones descargadas para meterlas en una playlist."""

    def __init__(self, window, playlist_id: str, playlist_name: str):
        super().__init__(window)
        self.window_ref = window
        self.playlist_id = playlist_id
        self.setMinimumSize(520, 560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(12)

        title = QLabel(f"Añadir a «{playlist_name}»")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)
        hint = QLabel("Marca las canciones descargadas que quieres en esta lista.")
        hint.setObjectName("SettingsHint")
        lay.addWidget(hint)

        self.filter = QLineEdit()
        self.filter.setObjectName("SidebarFilterInput")
        self.filter.setPlaceholderText("Buscar en mis descargas...")
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)

        self.list = QListWidget()
        self.list.itemChanged.connect(self._update_button)
        lay.addWidget(self.list, stretch=1)

        already = {str(t.get("id")) for t in PlaylistService.get_playlists().get(playlist_id, {}).get("tracks", [])}
        for info in window.library_items():
            if str(info.get("id")) in already:
                continue
            artist = info.get("uploader", "")
            label = f"{info['title']}  ·  {artist}" if artist else info["title"]
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, info)
            self.list.addItem(item)

        row = QHBoxLayout()
        row.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        self.btn_add = QPushButton("Añadir")
        self.btn_add.setObjectName("GiantActionBtn")
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._accept)
        row.addWidget(self.btn_add)
        lay.addLayout(row)

        if self.list.count() == 0:
            hint.setText("No hay más canciones descargadas para añadir.")

    def _apply_filter(self, text: str):
        text = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(text) and text not in it.text().lower())

    def _selected(self) -> list:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def _update_button(self, *_):
        n = len(self._selected())
        self.btn_add.setEnabled(n > 0)
        self.btn_add.setText(f"Añadir ({n})" if n else "Añadir")

    def _accept(self):
        for info in self._selected():
            PlaylistService.add_track_to_playlist(self.playlist_id, info)
        self.accept()


class ColumnHeader(QFrame):
    """Cabecera de columnas (Título, Álbum, Fecha, Duración). Al pulsar una se ordena la lista por ella."""
    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ColumnHeader")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 14, 4)
        lay.setSpacing(ROW_SPACING)
        self.buttons = {}

        def spacer(width):
            w = QWidget()
            w.setFixedWidth(width)
            return w

        def column(key, text, width=None):
            b = QPushButton(text)
            b.setObjectName("ColumnBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setIconSize(QSize(10, 10))
            b.setLayoutDirection(Qt.RightToLeft)  # la flecha queda a la derecha del texto
            if width:
                b.setFixedWidth(width)
            b.clicked.connect(lambda _=False, k=key: self.clicked.emit(k))
            self.buttons[key] = b
            return b

        hash_lbl = QLabel("#")
        hash_lbl.setObjectName("ColumnBtn")
        hash_lbl.setFixedWidth(IDX_COL)
        hash_lbl.setAlignment(Qt.AlignCenter)
        hash_lbl.setStyleSheet("padding: 6px 0px;")
        lay.addWidget(hash_lbl)
        lay.addWidget(spacer(ROW_COVER))
        lay.addWidget(column("title", "TÍTULO"), stretch=1)
        self.album_btn = column("album", "ÁLBUM", ALBUM_COL)
        lay.addWidget(self.album_btn)
        self.date_btn = column("added", "AÑADIDA", DATE_COL)
        lay.addWidget(self.date_btn)
        lay.addWidget(spacer(ICON_COL))                 # me gusta
        lay.addWidget(spacer(ICON_COL))                 # descargada
        lay.addWidget(column("duration", "DUR.", DUR_COL))
        lay.addWidget(spacer(ICON_COL))                 # tres puntitos

    def set_sort(self, key: str, descending: bool):
        for k, b in self.buttons.items():
            if k == key:
                b.setIcon(icon("arrow_down.svg" if descending else "arrow_up.svg", "#FFFFFF"))
            else:
                b.setIcon(QIcon())

    def set_columns_visible(self, visible: bool):
        self.album_btn.setVisible(visible)
        self.date_btn.setVisible(visible)


class ListPage(QWidget):
    back_clicked = Signal()
    download_all_requested = Signal(list)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.kind = "playlist"
        self.list_id = None
        self.list_name = ""
        self.raw_tracks = []
        self.items = []
        self.tab = "all"
        self.sort_key = "custom"
        self.sort_desc = False
        self._cards = {}
        self._cover_sig = None
        self._materialized = ROW_BATCH
        self._columns_shown = True
        self._date_timer = QTimer(self)
        self._date_timer.setInterval(60_000)
        self._date_timer.timeout.connect(self._refresh_dates)
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

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 8, 20)
        self.content_layout.setSpacing(16)

        # Cabecera
        self.header = QFrame()
        self.header.setObjectName("ListHeader")
        h = QHBoxLayout(self.header)
        h.setContentsMargins(24, 24, 24, 24)
        h.setSpacing(24)
        self.tile = CoverTileButton()
        self.tile.clicked.connect(self._tile_clicked)
        h.addWidget(self.tile)
        info = QVBoxLayout()
        info.setAlignment(Qt.AlignVCenter)
        info.setSpacing(6)
        self.badge = QLabel("LISTA")
        self.badge.setObjectName("SectionSubtitle")
        self.badge.setStyleSheet("font-size: 11px; font-weight: bold; letter-spacing: 1px; background: transparent;")
        self.title_lbl = QLabel("Lista")
        self.title_lbl.setStyleSheet("font-size: 34px; font-weight: bold; background: transparent;")
        self.title_lbl.setWordWrap(True)
        self.meta_lbl = QLabel("")
        self.meta_lbl.setObjectName("SectionSubtitle")
        self.meta_lbl.setStyleSheet("background: transparent;")
        info.addWidget(self.badge)
        info.addWidget(self.title_lbl)
        info.addWidget(self.meta_lbl)
        h.addLayout(info, stretch=1)
        self.content_layout.addWidget(self.header)

        # Acciones
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.btn_play = QPushButton("")
        self.btn_play.setObjectName("BigPlayBtn")
        self.btn_play.setIcon(icon("play_black.svg"))
        self.btn_play.setIconSize(QSize(24, 24))
        self.btn_play.setToolTip("Reproducir la lista")
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.clicked.connect(self.play_all)
        actions.addWidget(self.btn_play)

        self.btn_shuffle = QPushButton("")
        self.btn_shuffle.setObjectName("IconBtn")
        self.btn_shuffle.setIcon(icon("shuffle.svg", "#B3B3B3"))
        self.btn_shuffle.setIconSize(QSize(22, 22))
        self.btn_shuffle.setToolTip("Reproducir en orden aleatorio")
        self.btn_shuffle.setCursor(Qt.PointingHandCursor)
        self.btn_shuffle.clicked.connect(self.play_shuffled)
        actions.addWidget(self.btn_shuffle)

        self.btn_add = QPushButton(" Añadir canciones")
        self.btn_add.setIcon(icon("plus.svg"))
        self.btn_add.setIconSize(QSize(16, 16))
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.clicked.connect(self.add_songs)
        actions.addWidget(self.btn_add)

        self.btn_save = QPushButton(" Guardar como lista")
        self.btn_save.setIcon(icon("plus.svg"))
        self.btn_save.setIconSize(QSize(16, 16))
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_as_playlist)
        actions.addWidget(self.btn_save)

        self.btn_download = QPushButton(" Descargar lo que falta")
        self.btn_download.setObjectName("DownloadBtn")
        self.btn_download.setIcon(icon("download_black.svg"))
        self.btn_download.setIconSize(QSize(16, 16))
        self.btn_download.setCursor(Qt.PointingHandCursor)
        self.btn_download.clicked.connect(self._download_missing)
        actions.addWidget(self.btn_download)

        self.btn_more = QPushButton("")
        self.btn_more.setObjectName("IconBtn")
        self.btn_more.setIcon(icon("more.svg", "#B3B3B3"))
        self.btn_more.setIconSize(QSize(20, 20))
        self.btn_more.setToolTip("Más opciones")
        self.btn_more.setCursor(Qt.PointingHandCursor)
        self.btn_more.clicked.connect(self._show_more)
        actions.addWidget(self.btn_more)
        actions.addStretch()

        self.search = QLineEdit()
        self.search.setObjectName("SidebarFilterInput")
        self.search.setPlaceholderText("Buscar en esta lista...")
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self._on_search)
        actions.addWidget(self.search)

        self.btn_sort = QPushButton(" Orden")
        self.btn_sort.setObjectName("SortBtn")
        self.btn_sort.setIcon(icon("sort.svg", "#B3B3B3"))
        self.btn_sort.setIconSize(QSize(16, 16))
        self.btn_sort.setToolTip("Ordenar la lista")
        self.btn_sort.setCursor(Qt.PointingHandCursor)
        self.btn_sort.clicked.connect(self._show_sort_menu)
        actions.addWidget(self.btn_sort)
        self.content_layout.addLayout(actions)

        # Pestañas (solo en "Canciones que te gustan")
        self.tabs_box = QWidget()
        tabs = QHBoxLayout(self.tabs_box)
        tabs.setContentsMargins(0, 0, 0, 0)
        tabs.setSpacing(8)
        self.tab_buttons = {}
        for key, label in (("all", "Todas"), ("downloaded", "Descargadas"), ("pending", "Sin descargar")):
            b = QPushButton(label)
            b.setObjectName("TabBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_tab(k))
            tabs.addWidget(b)
            self.tab_buttons[key] = b
        tabs.addStretch()
        self.content_layout.addWidget(self.tabs_box)

        # Cabecera de columnas
        self.columns = ColumnHeader()
        self.columns.clicked.connect(self._column_clicked)
        self.content_layout.addWidget(self.columns)

        self.loading = LoadingBlock("Cargando tu lista...")
        self.loading.setVisible(False)
        self.content_layout.addWidget(self.loading)

        self.empty_lbl = QLabel("")
        self.empty_lbl.setObjectName("SectionSubtitle")
        self.empty_lbl.setWordWrap(True)
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setStyleSheet("padding: 40px 0px; font-size: 14px;")
        self.content_layout.addWidget(self.empty_lbl)

        self.tracks_widget = QWidget()
        self.tracks_container = QVBoxLayout(self.tracks_widget)
        self.tracks_container.setContentsMargins(0, 0, 0, 0)
        self.tracks_container.setSpacing(2)
        self.content_layout.addWidget(self.tracks_widget)
        self.content_layout.addStretch()

        self.scroll.setWidget(content)
        main.addWidget(self.scroll, stretch=1)

    # ------------------------------------------------------------- datos
    def _prepare_items(self, tracks: list) -> list:
        items = []
        for order, t in enumerate(tracks):
            item = dict(t)
            item["_order"] = order
            item["_added_ts"] = parse_added(item)
            if self.kind != "downloads":
                local = self.window_ref.resolve_local(item)
                if local:
                    item["local_path"] = local
                    item["already_downloaded"] = True
            items.append(item)
        return items

    @staticmethod
    def _item_key(item: dict) -> str:
        return str(item.get("id") or item.get("title"))

    def _apply_header(self, kind: str, list_id, name: str):
        """Cabecera de la lista: portada, colores y título. Solo repinta lo que cambió."""
        if kind == "mix":
            c1 = MIX_COLORS[int(list_id or 0) % len(MIX_COLORS)][0]
        elif kind == "genre":
            c1 = GENRE_COLORS[int(list_id or 0) % len(GENRE_COLORS)]
        else:
            c1 = tile_colors(kind)[0]
        cover = PlaylistService.get_cover_path(list_id) if kind == "playlist" else None
        signature = (kind, str(list_id), cover, c1, name if kind == "genre" else "")
        if signature != self._cover_sig:
            self._cover_sig = signature
            self.tile.setIcon(QIcon(list_cover_pixmap(kind, list_id, 140, 12, label=name)))
            r, g, bl = QColor(c1).red(), QColor(c1).green(), QColor(c1).blue()
            self.header.setStyleSheet(
                "#ListHeader { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                f" stop:0 rgba({r}, {g}, {bl}, 150), stop:1 rgba({r}, {g}, {bl}, 0)); border-radius: 16px; }}"
            )
        self.tile.set_editable(kind == "playlist")
        self.badge.setText(KIND_TITLES.get(kind, "LISTA"))
        if self.title_lbl.text() != name:
            self.title_lbl.setText(name)
        self.btn_add.setVisible(kind == "playlist")
        self.btn_more.setVisible(kind == "playlist")
        self.btn_save.setVisible(kind in ("mix", "genre"))
        self.tabs_box.setVisible(kind == "favorites")

    def load(self, kind: str, list_id, name: str, tracks: list):
        """Abre una lista desde cero (al navegar a ella). Muestra primero una animación de carga."""
        self.kind = kind
        self.list_id = list_id
        self.list_name = name
        self.raw_tracks = list(tracks)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.tab = "all"
        self.sort_key, self.sort_desc = ("added", True) if kind in ("favorites", "downloads") else ("custom", False)
        self._materialized = ROW_BATCH
        self._clear_cards()
        self._cover_sig = None
        self.items = []
        self._apply_header(kind, list_id, name)
        self.empty_lbl.setVisible(False)
        self.columns.setVisible(False)
        self.loading.setVisible(len(tracks) > 0)
        self.meta_lbl.setText("")
        QTimer.singleShot(0, lambda: self._finish_load(kind, list_id, tracks))

    def _finish_load(self, kind: str, list_id, tracks: list):
        if kind != self.kind or list_id != self.list_id:
            return   # mientras tanto se abrió otra lista
        self.items = self._prepare_items(tracks)
        self.loading.setVisible(False)
        self._reconcile()
        fade_in(self.header, 320)

    def sync(self, name: str, tracks: list):
        """Pone la lista al día sin recargarla: solo se añaden, quitan o cambian las filas que lo necesitan."""
        self.list_name = name
        self.raw_tracks = list(tracks)
        self.items = self._prepare_items(tracks)
        self._apply_header(self.kind, self.list_id, name)
        self._reconcile()

    def _clear_cards(self):
        for card in self._cards.values():
            self.tracks_container.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = {}

    # ------------------------------------------------------ orden y filtros
    def _visible_items(self) -> list:
        items = self.items
        if self.kind == "favorites":
            if self.tab == "downloaded":
                items = [i for i in items if i.get("local_path")]
            elif self.tab == "pending":
                items = [i for i in items if not i.get("local_path")]
        text = self.search.text().strip().lower()
        if text:
            items = [i for i in items
                     if text in f"{i.get('title', '')} {i.get('uploader', '')} {i.get('album', '')}".lower()]
        if self.sort_key != "custom" or self.sort_desc:
            items = sorted(items, key=lambda i: _sort_value(self.sort_key, i), reverse=self.sort_desc)
        return items

    def set_tab(self, key: str):
        self.tab = key
        self._materialized = ROW_BATCH
        self._reconcile()

    def _on_search(self, *_):
        self._materialized = ROW_BATCH
        self._reconcile()

    def set_sort(self, key: str, descending: bool | None = None):
        """Ordena por `key`; si se repite la misma clave se invierte el sentido."""
        if descending is None:
            descending = (not self.sort_desc) if key == self.sort_key else (key == "added")
        self.sort_key, self.sort_desc = key, descending
        self._materialized = ROW_BATCH
        self._reconcile()

    def _column_clicked(self, key: str):
        self.set_sort(key)

    def _show_sort_menu(self):
        menu = QMenu(self)
        for key, text in SORT_OPTIONS.items():
            act = menu.addAction(("✓  " if key == self.sort_key else "     ") + text)
            act.triggered.connect(lambda _=False, k=key: self.set_sort(k, k == "added"))
        menu.addSeparator()
        menu.addAction("Invertir el orden").triggered.connect(lambda: self.set_sort(self.sort_key, not self.sort_desc))
        menu.exec(self.btn_sort.mapToGlobal(self.btn_sort.rect().bottomLeft()))

    # ------------------------------------------------- filas (creación perezosa)
    def _on_scroll(self, value: int):
        if value >= self.scroll.verticalScrollBar().maximum() - 500:
            self._grow()

    def _grow(self):
        if self.items and self._materialized < len(self._visible_items()):
            self._materialized += ROW_BATCH
            self._reconcile()

    def showEvent(self, event):
        self._date_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._date_timer.stop()
        super().hideEvent(event)

    def _refresh_dates(self):
        for card in self._cards.values():
            card.refresh_date()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wide = self.width() >= COLUMNS_MIN_WIDTH
        if wide != self._columns_shown:
            self._columns_shown = wide
            self.columns.set_columns_visible(wide)
            for card in self._cards.values():
                card.set_columns_visible(wide)

    def _reconcile(self):
        """Hace coincidir las filas mostradas con las que deben verse, tocando lo mínimo."""
        full = self._visible_items()
        visible = full[:self._materialized]
        keys = [self._item_key(i) for i in visible]
        wanted = set(keys)

        for key in [k for k in self._cards if k not in wanted]:
            card = self._cards.pop(key)
            self.tracks_container.removeWidget(card)
            card.setParent(None)
            card.deleteLater()

        for pos, item in enumerate(visible):
            key = keys[pos]
            card = self._cards.get(key)
            if card is not None and bool(card.item_info.get("local_path")) != bool(item.get("local_path")):
                # cambió su estado (por ejemplo, acaba de descargarse): se rehace solo esta fila
                self.tracks_container.removeWidget(card)
                card.setParent(None)
                card.deleteLater()
                self._cards.pop(key)
                card = None
            if card is None:
                card = TrackRow(item, self.window_ref, number=pos + 1, list_mode=True)
                card.set_columns_visible(self._columns_shown)
                card.context_provider = self._visible_items
                card.set_playing(self.window_ref.is_current(card.item_info))
                if self.kind == "playlist":
                    card.extra_menu = [("Quitar de esta lista", lambda it=item: self._remove_track(it))]
                self._cards[key] = card
                self.tracks_container.insertWidget(pos, card)
            else:
                card.set_number(pos + 1)
                current = self.tracks_container.itemAt(pos).widget() if pos < self.tracks_container.count() else None
                if current is not card:
                    self.tracks_container.removeWidget(card)
                    self.tracks_container.insertWidget(pos, card)

        self.columns.set_sort(self.sort_key if self.sort_key != "custom" else "", self.sort_desc)
        self._update_texts(full)
        if len(full) > len(visible):
            QTimer.singleShot(150, self._fill_viewport)

    def update_playing(self):
        """Marca en la lista la canción que está sonando."""
        for card in self._cards.values():
            card.set_playing(self.window_ref.is_current(card.item_info))

    def _fill_viewport(self):
        """Si las filas creadas no llenan la pantalla, se crean más."""
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() <= 0 or bar.value() >= bar.maximum() - 500:
            self._grow()

    def _update_texts(self, full: list):
        total = len(self.items)
        downloaded = sum(1 for i in self.items if i.get("local_path"))
        pending = total - downloaded
        if self.kind == "favorites":
            self.tab_buttons["all"].setText(f"Todas ({total})")
            self.tab_buttons["downloaded"].setText(f"Descargadas ({downloaded})")
            self.tab_buttons["pending"].setText(f"Sin descargar ({pending})")
            for k, b in self.tab_buttons.items():
                b.setChecked(k == self.tab)
        parts = ["1 canción" if total == 1 else f"{total} canciones"]
        duration = format_total(sum(int(i.get("duration_secs", 0) or 0) for i in self.items))
        if duration:
            parts.append(duration)
        if self.kind != "downloads":
            parts.append(f"{downloaded} descargadas")
        self.meta_lbl.setText("  ·  ".join(parts))
        # En "Descargadas" no hay nada que descargar, así que el botón desaparece
        hide_download = self.kind == "downloads" or (self.kind == "favorites" and self.tab == "downloaded")
        self.btn_download.setVisible(not hide_download)
        self.btn_download.setEnabled(pending > 0)
        self.btn_play.setEnabled(bool(full))
        self.btn_shuffle.setEnabled(bool(full))
        self.columns.setVisible(bool(full))
        loading = self.loading.isVisible()
        if not full and not loading:
            self.empty_lbl.setText(self._empty_message())
        self.empty_lbl.setVisible(not full and not loading)

    def _empty_message(self) -> str:
        if self.search.text().strip():
            return "No hay canciones que coincidan con tu búsqueda."
        if self.kind == "favorites":
            if self.raw_tracks:
                return ("Aún no tienes canciones descargadas entre tus favoritas."
                        if self.tab == "downloaded" else "Todas tus canciones favoritas están descargadas.")
            return "Aún no hay canciones aquí. Pulsa el corazón en cualquier canción para guardarla."
        if self.kind == "downloads":
            return "Todavía no has descargado música. Busca una canción y pulsa «Descargar»."
        return "Esta lista está vacía. Pulsa «Añadir canciones» para elegir entre tu música descargada."

    # ----------------------------------------------------------- acciones
    def play_all(self):
        visible = self._visible_items()
        if visible:
            self.window_ref.play_list(visible, 0)

    def play_shuffled(self):
        visible = self._visible_items()
        if visible:
            self.window_ref.play_list(visible, None, shuffle=True)

    def add_songs(self):
        if self.kind != "playlist":
            return
        if AddSongsDialog(self.window_ref, self.list_id, self.list_name).exec():
            self.window_ref.reload_current_list()
            self.window_ref.notify("Canciones añadidas")

    def _download_missing(self):
        missing = [i for i in self.items if not i.get("local_path")]
        if missing:
            self.download_all_requested.emit(missing)

    def _remove_track(self, item: dict):
        if self.kind == "playlist" and PlaylistService.remove_track_from_playlist(self.list_id, str(item.get("id"))):
            self.window_ref.reload_current_list()
            self.window_ref.notify("Quitada de la lista")

    def _show_more(self):
        menu = QMenu(self)
        menu.addAction(icon("edit.svg"), "Cambiar nombre").triggered.connect(self.rename_list)
        menu.addAction(icon("palette.svg"), "Cambiar imagen").triggered.connect(self._tile_clicked)
        if PlaylistService.get_cover_path(self.list_id):
            menu.addAction(icon("x.svg"), "Quitar imagen").triggered.connect(
                lambda: self.window_ref.remove_playlist_cover(self.list_id))
        menu.addSeparator()
        menu.addAction(icon("trash.svg"), "Eliminar lista").triggered.connect(self.delete_list)
        menu.exec(self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft()))

    def save_as_playlist(self):
        """Guarda un mix como una lista tuya (se queda en tu biblioteca)."""
        pid = PlaylistService.create_playlist(self.list_name)
        for item in self.raw_tracks:
            PlaylistService.add_track_to_playlist(pid, item)
        self.window_ref.refresh_playlists_sidebar()
        self.window_ref.notify(f"«{self.list_name}» guardada en tu biblioteca")
        self.window_ref.open_list("playlist", pid)

    def _tile_clicked(self):
        if self.kind == "playlist":
            self.window_ref.change_playlist_cover(self.list_id)

    def rename_list(self):
        name, ok = ask_text(self, "Cambiar nombre", "Nuevo nombre de la lista", text=self.list_name, ok="Guardar")
        if ok and name.strip():
            PlaylistService.rename_playlist(self.list_id, name.strip())
            self.window_ref.refresh_playlists_sidebar()
            self.window_ref.open_list("playlist", self.list_id)

    def delete_list(self):
        if ask_confirm(self, "Eliminar lista",
                       f"¿Seguro que quieres eliminar «{self.list_name}»?\nTus canciones descargadas no se borran.",
                       ok="Eliminar", danger=True):
            PlaylistService.delete_playlist(self.list_id)
            self.window_ref.refresh_playlists_sidebar()
            self.window_ref.open_library()
            self.window_ref.notify("Lista eliminada")
