"""Tu biblioteca: cuadrícula con todas tus listas (me gusta, descargas y playlists propias)."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea, QMenu
)

from ui.icons import icon
from ui.covers import list_cover_pixmap
from ui.animations import fade_in
from ui.controls import CoverLabel
from ui.hover import TileHover
from ui.scrolling import polish_scroll_area
from ui.widgets import ElidedLabel
from ui.home_shelves import QuickGrid

CARD_W = 158
TILE = 126


class ListCard(TileHover, QFrame):
    clicked = Signal(str, str)           # (tipo, id)
    context_requested = Signal(str, str, object)

    def __init__(self, kind: str, list_id: str, name: str, count: int, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.list_id = list_id
        self.setObjectName("CoverCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(CARD_W)
        self.init_glow(10)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)

        tile = CoverLabel(radius=10 if kind != "artist" else TILE // 2)
        self.tile_cover = tile
        tile.setFixedSize(TILE, TILE)
        tile.setPixmap(list_cover_pixmap(kind, list_id, TILE, 10))
        lay.addWidget(tile)

        title = ElidedLabel(name)
        title.setObjectName("CoverTitle")
        title.setFixedHeight(20)
        title.setToolTip(name)
        lay.addWidget(title)

        if count < 0:
            sub_text = "Artista"
        else:
            sub_text = "1 canción" if count == 1 else f"{count} canciones"
        sub = ElidedLabel(sub_text)
        sub.setObjectName("CoverSub")
        sub.setFixedHeight(18)
        lay.addWidget(sub)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            win = self.window()
            if hasattr(win, "remember_cover_source") and self.tile_cover is not None:
                win.remember_cover_source(self.tile_cover)
            self.clicked.emit(self.kind, self.list_id)
        super().mouseReleaseEvent(ev)

    def contextMenuEvent(self, ev):
        self.context_requested.emit(self.kind, self.list_id, ev.globalPos())


class NewListCard(QFrame):
    """Tarjeta de bienvenida cuando todavía no hay ninguna lista propia: invita a crear la primera."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NewListCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(CARD_W)
        self.setMinimumHeight(TILE + 70)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setAlignment(Qt.AlignCenter)
        plus = QLabel()
        plus.setPixmap(icon("plus_circle.svg", "#B3B3B3", 64).pixmap(44, 44))
        plus.setAlignment(Qt.AlignCenter)
        plus.setStyleSheet("background: transparent;")
        lay.addWidget(plus)
        text = QLabel("Crea tu primera lista")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        text.setStyleSheet("font-weight: 700; background: transparent;")
        lay.addWidget(text)
        sub = QLabel("Para guardar tus canciones por ambiente, artista o lo que quieras")
        sub.setObjectName("CoverSub")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


class LibraryPage(QWidget):
    list_selected = Signal(str, str)
    new_list_requested = Signal()
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    cover_requested = Signal(str)
    unfollow_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(16)

        head = QHBoxLayout()
        title = QLabel("Tu biblioteca")
        title.setStyleSheet("font-size: 30px; font-weight: bold;")
        head.addWidget(title)
        head.addStretch()
        self.btn_new = QPushButton(" Nueva lista")
        self.btn_new.setObjectName("GiantActionBtn")
        self.btn_new.setIcon(icon("plus.svg", "#000000"))
        self.btn_new.setIconSize(QSize(16, 16))
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.clicked.connect(self.new_list_requested.emit)
        head.addWidget(self.btn_new)
        main.addLayout(head)

        hint = QLabel("Tus canciones favoritas, tu música descargada, tus listas y los artistas que sigues.")
        hint.setObjectName("SectionSubtitle")
        hint.setWordWrap(True)
        main.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        polish_scroll_area(scroll)
        # las tarjetas se colocan por filas según el ancho que haya (antes eran siempre 4 columnas)
        inner = self.cards = QuickGrid(min_tile=CARD_W + 14, max_columns=8, spacing=14, fill=False, margins=(0, 8, 0, 20))
        scroll.setWidget(inner)
        main.addWidget(scroll, stretch=1)

    def load(self, favorites_count: int, downloads_count: int, playlists: dict, artists: list = None,
             animate: bool = True, smart: list = None):
        cards = [
            ("favorites", "favorites", "Canciones que te gustan", favorites_count),
            ("downloads", "downloads", "Mis descargas", downloads_count),
        ]
        for p_id, data in playlists.items():
            cards.append(("playlist", p_id, data.get("name", "Playlist"), len(data.get("tracks", []))))

        for art in artists or []:
            cards.append(("artist", art["id"], art["name"], -1))
        for key, name, count in smart or []:         # listas automáticas (se arman solas con tu música)
            cards.append(("smart", key, name, count))

        widgets = []
        for kind, list_id, name, count in cards:
            card = ListCard(kind, list_id, name, count)
            card.clicked.connect(self.list_selected.emit)
            card.context_requested.connect(self._context)
            widgets.append(card)
        if not playlists:       # todavía no hay listas propias: se invita a crear la primera
            invite = NewListCard()
            invite.clicked.connect(self.new_list_requested.emit)
            widgets.append(invite)
        self.cards.set_tiles(widgets)
        if animate:
            for i, card in enumerate(widgets):
                fade_in(card, 260, min(i, 10) * 45)

    def _context(self, kind: str, list_id: str, pos):
        if kind == "artist":
            menu = QMenu(self)
            menu.addAction(icon("x.svg"), "Dejar de seguir").triggered.connect(lambda: self.unfollow_requested.emit(list_id))
            menu.exec(pos)
            return
        if kind != "playlist":
            return
        menu = QMenu(self)
        menu.addAction(icon("edit.svg"), "Cambiar nombre").triggered.connect(lambda: self.rename_requested.emit(list_id))
        menu.addAction(icon("palette.svg"), "Cambiar imagen").triggered.connect(lambda: self.cover_requested.emit(list_id))
        menu.addSeparator()
        menu.addAction(icon("trash.svg"), "Eliminar lista").triggered.connect(lambda: self.delete_requested.emit(list_id))
        menu.exec(pos)
