"""Tu biblioteca: cuadrícula con todas tus listas (me gusta, descargas y playlists propias)."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea, QGridLayout, QMenu
)

from ui.icons import icon
from ui.covers import list_cover_pixmap
from ui.animations import fade_in
from ui.widgets import ElidedLabel

COLUMNS = 4
CARD_W = 158
TILE = 126


class ListCard(QFrame):
    clicked = Signal(str, str)           # (tipo, id)
    context_requested = Signal(str, str, object)

    def __init__(self, kind: str, list_id: str, name: str, count: int, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.list_id = list_id
        self.setObjectName("CoverCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(CARD_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)

        tile = QLabel()
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
            self.clicked.emit(self.kind, self.list_id)
        super().mouseReleaseEvent(ev)

    def contextMenuEvent(self, ev):
        self.context_requested.emit(self.kind, self.list_id, ev.globalPos())


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
        main.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.grid = QGridLayout(inner)
        self.grid.setContentsMargins(0, 8, 0, 20)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(inner)
        main.addWidget(scroll, stretch=1)

    def load(self, favorites_count: int, downloads_count: int, playlists: dict, artists: list = None,
             animate: bool = True):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        cards = [
            ("favorites", "favorites", "Canciones que te gustan", favorites_count),
            ("downloads", "downloads", "Mis descargas", downloads_count),
        ]
        for p_id, data in playlists.items():
            cards.append(("playlist", p_id, data.get("name", "Playlist"), len(data.get("tracks", []))))

        for art in artists or []:
            cards.append(("artist", art["id"], art["name"], -1))

        for i, (kind, list_id, name, count) in enumerate(cards):
            card = ListCard(kind, list_id, name, count)
            card.clicked.connect(self.list_selected.emit)
            card.context_requested.connect(self._context)
            self.grid.addWidget(card, i // COLUMNS, i % COLUMNS)
            if animate:
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
