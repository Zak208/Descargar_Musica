"""Página DJ: lo que suena, cuánto falta para la mezcla, lo que viene y los botones para llevar la sesión.

La página solo enseña y avisa (señales); la lógica está en ui/dj_mixin.py."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QListWidget, QAbstractItemView, QMenu
)

from services.transition_votes import TAGS
from ui.dj_votes_mixin import TAG_LABELS
from ui.icons import icon
from ui.widgets import ElidedLabel

UPCOMING_SHOWN = 30


COMPACT_MIN_W = 52             # ancho de un botón que se ha quedado solo con el icono
BUTTON_EXTRA_W = 16 + 44       # icono + relleno de los lados (lo que ocupa un botón además de su texto)


def _tight(btn: QPushButton, extra: int = 14) -> QPushButton:
    """El estilo de Qt pide al menos 80 px a un botón de texto, aunque sea «÷2»: se ajusta al ancho de su texto."""
    btn.ensurePolished()
    btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(btn.text()) + extra)
    return btn


def _action_button(text: str, icon_name: str, tip: str) -> QPushButton:
    btn = QPushButton(f" {text}")
    btn.setObjectName("TopPillBtn")
    btn.setIcon(icon(icon_name))
    btn.setIconSize(QSize(16, 16))
    btn.setToolTip(tip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumWidth(COMPACT_MIN_W)      # puede estrecharse: en una ventana estrecha se queda solo con el icono
    return btn


class DjPage(QWidget):
    start_requested = Signal()
    folder_requested = Signal()
    skip_requested = Signal()
    drop_next_requested = Signal()
    block_requested = Signal()
    reshuffle_requested = Signal()
    unblock_all_requested = Signal()
    bpm_requested = Signal(str, str)         # (ruta de la canción, «half», «double», «set» o «auto»)
    vote_requested = Signal(int, list)       # (+1 o -1, motivos marcados) de la mezcla que toca

    def __init__(self, parent=None):
        super().__init__(parent)
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(16)

        # --- cabecera: título, de dónde salen las canciones y empezar ---
        head = QHBoxLayout()
        self.title = QLabel("Modo DJ")
        self.title.setStyleSheet("font-size: 30px; font-weight: bold;")
        head.addWidget(self.title)
        head.addStretch()
        self.btn_start = QPushButton(" Empezar a pinchar")
        self.btn_start.setObjectName("GiantActionBtn")
        self.btn_start.setIcon(icon("play_black.svg", "#000000"))
        self.btn_start.setIconSize(QSize(16, 16))
        self.btn_start.setMinimumWidth(COMPACT_MIN_W)
        self.btn_start.setToolTip("Empezar a pinchar")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_requested.emit)
        head.addWidget(self.btn_start)
        main.addLayout(head)

        source_row = QHBoxLayout()
        self.source = QLabel("")
        self.source.setObjectName("SectionSubtitle")
        self.source.setWordWrap(True)
        source_row.addWidget(self.source, 1)
        self.btn_folder = QPushButton("Cambiar carpeta")
        self.btn_folder.setObjectName("LinkBtn")
        self.btn_folder.setCursor(Qt.PointingHandCursor)
        self.btn_folder.clicked.connect(self.folder_requested.emit)
        source_row.addWidget(self.btn_folder)
        self.btn_unblock = QPushButton("")
        self.btn_unblock.setObjectName("LinkBtn")
        self.btn_unblock.setCursor(Qt.PointingHandCursor)
        self.btn_unblock.setToolTip("Las canciones bloqueadas vuelven a poder sonar en el modo DJ")
        self.btn_unblock.clicked.connect(self.unblock_all_requested.emit)
        self.btn_unblock.hide()
        source_row.addWidget(self.btn_unblock)
        main.addLayout(source_row)
        self.progress = QLabel("")
        self.progress.setObjectName("SectionSubtitle")
        self.progress.setWordWrap(True)
        self.progress.hide()
        main.addWidget(self.progress)

        # --- sin sesión: qué hacer ---
        self.empty = QLabel("Elige la carpeta con «Cambiar carpeta» o con el botón DJ de arriba, y pulsa «Empezar a pinchar».")
        self.empty.setObjectName("SectionSubtitle")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setMinimumHeight(120)
        main.addWidget(self.empty)

        # --- con sesión ---
        self.session = QWidget()
        sess = QVBoxLayout(self.session)
        sess.setContentsMargins(0, 0, 0, 0)
        sess.setSpacing(14)

        now = QFrame()
        now.setObjectName("PanelCard")
        now.setAttribute(Qt.WA_StyledBackground, True)
        now_lay = QVBoxLayout(now)
        now_lay.setContentsMargins(20, 16, 20, 16)
        now_lay.setSpacing(4)
        cap = QLabel("AHORA SUENA")
        cap.setStyleSheet("font-size: 11px; font-weight: 800; color: #B3B3B3; letter-spacing: 1px; background: transparent;")
        now_lay.addWidget(cap)
        self.now_title = ElidedLabel("")
        self.now_title.setStyleSheet("font-size: 22px; font-weight: bold; background: transparent;")
        now_lay.addWidget(self.now_title)
        self.now_artist = ElidedLabel("")
        self.now_artist.setObjectName("SectionSubtitle")
        now_lay.addWidget(self.now_artist)
        self.now_detail = QLabel("")
        self.now_detail.setObjectName("SectionSubtitle")
        self.now_detail.setWordWrap(True)
        now_lay.addWidget(self.now_detail)
        bpm_row = QHBoxLayout()
        bpm_row.setSpacing(6)
        self.bpm_buttons = []              # si el ritmo está mal medido (95 visto como 190, por ejemplo)
        for text, action, tip in (("BPM ÷2", "half", "El ritmo está mal medido: es la mitad de lo que se ve"),
                                  ("BPM ×2", "double", "El ritmo está mal medido: es el doble de lo que se ve"),
                                  ("Escribir BPM…", "set", "Escribir el ritmo a mano"),
                                  ("Automático", "auto", "Volver al ritmo calculado solo")):
            btn = QPushButton(text)
            btn.setObjectName("LinkBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, a=action: self._emit_bpm(self._now_path, a))
            bpm_row.addWidget(_tight(btn))
            self.bpm_buttons.append(btn)
        bpm_row.addStretch()
        now_lay.addLayout(bpm_row)
        self.countdown = QLabel("")
        self.countdown.setStyleSheet("font-size: 14px; font-weight: 700; color: #1ED760; background: transparent;")
        self.countdown.setWordWrap(True)
        now_lay.addSpacing(6)
        now_lay.addWidget(self.countdown)
        vote_row = QHBoxLayout()
        vote_row.setSpacing(8)
        self.vote_caption = QLabel("Esta mezcla:")
        self.vote_caption.setStyleSheet("font-weight: 700; background: transparent;")
        vote_row.addWidget(self.vote_caption)
        self.btn_up = QPushButton("👍 Buena")
        self.btn_up.setObjectName("TopPillBtn")
        self.btn_up.setCursor(Qt.PointingHandCursor)
        self.btn_up.setToolTip("Votar la mezcla que suena (o la última) como buena: sirve para que el DJ aprenda tu gusto")
        self.btn_up.clicked.connect(lambda: self.vote_requested.emit(1, []))
        vote_row.addWidget(self.btn_up)
        self.btn_down = QPushButton("👎 Mala")
        self.btn_down.setObjectName("TopPillBtn")
        self.btn_down.setCursor(Qt.PointingHandCursor)
        self.btn_down.setToolTip("Votar la mezcla como mala, y marcar qué falló si quieres")
        down_menu = QMenu(self.btn_down)
        down_menu.addAction("Sin motivo").triggered.connect(lambda: self.vote_requested.emit(-1, []))
        down_menu.addSeparator()
        for tag in TAGS:
            down_menu.addAction(TAG_LABELS.get(tag, tag)).triggered.connect(lambda _=False, t=tag: self.vote_requested.emit(-1, [t]))
        self.btn_down.setMenu(down_menu)
        vote_row.addWidget(self.btn_down)
        self.vote_status = QLabel("")
        self.vote_status.setObjectName("SectionSubtitle")
        self.vote_status.setWordWrap(True)
        vote_row.addWidget(self.vote_status, 1)
        now_lay.addLayout(vote_row)
        sess.addWidget(now)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_skip = _action_button("Saltar", "next.svg", "Pasa ya a la siguiente, con un fundido corto")
        self.btn_skip.clicked.connect(self.skip_requested.emit)
        self.btn_drop = _action_button("Esta no", "x.svg", "Quita de la sesión la canción que iba a sonar después")
        self.btn_drop.clicked.connect(self.drop_next_requested.emit)
        self.btn_block = _action_button("Bloquear", "offline.svg",
                                        "La que suena no volverá a salir en el modo DJ (y se pasa a la siguiente)")
        self.btn_block.clicked.connect(self.block_requested.emit)
        self.btn_shuffle = _action_button("Barajar", "shuffle.svg", "Cambia el orden de lo que queda por sonar")
        self.btn_shuffle.clicked.connect(self.reshuffle_requested.emit)
        self._actions = (self.btn_skip, self.btn_drop, self.btn_block, self.btn_shuffle)
        for btn in self._actions:
            buttons.addWidget(btn)
        self._labels = {btn: btn.text() for btn in (self.btn_start, *self._actions)}   # textos completos
        self._compact = False
        self._now_path = ""                   # canción que suena (para los botones de BPM)
        self._upcoming_paths = []             # ruta de cada fila de «Lo que queda»
        buttons.addStretch()
        sess.addLayout(buttons)

        nxt = QHBoxLayout()
        nxt_cap = QLabel("A continuación:")
        nxt_cap.setStyleSheet("font-weight: 700;")
        nxt.addWidget(nxt_cap)
        self.next_title = ElidedLabel("")
        nxt.addWidget(self.next_title, 1)
        sess.addLayout(nxt)

        self.list_title = QLabel("")
        self.list_title.setObjectName("SectionTitle")
        self.list_title.setWordWrap(True)
        sess.addWidget(self.list_title)
        self.upcoming = QListWidget()
        self.upcoming.setSelectionMode(QAbstractItemView.NoSelection)
        self.upcoming.setFocusPolicy(Qt.NoFocus)
        self.upcoming.setContextMenuPolicy(Qt.CustomContextMenu)       # botón derecho: corregir el BPM de esa canción
        self.upcoming.customContextMenuRequested.connect(self._upcoming_menu)
        self.upcoming.setStyleSheet("QListWidget { background: transparent; border: none; font-size: 13px; }"
                                    "QListWidget::item { padding: 6px 4px; color: #B3B3B3; }")
        sess.addWidget(self.upcoming, 1)
        main.addWidget(self.session, 1)
        self.session.hide()

    # ------------------------------------------------------------------ estado
    def set_source(self, text: str, blocked: int):
        self.source.setText(text)
        self.btn_unblock.setText(f"Desbloquear ({blocked})")
        self.btn_unblock.setVisible(blocked > 0)

    def set_session(self, active: bool, now: dict = None, nxt: dict = None, upcoming: list = (), remaining: int = 0,
                    describe=None):
        """`describe(info)`: texto corto con el análisis de una canción («128 BPM · intro 0:12…»), o "" si no hay."""
        describe = describe or (lambda _info: "")
        self.empty.setVisible(not active)
        self.session.setVisible(active)
        self._labels[self.btn_start] = " Empezar de nuevo" if active else " Empezar a pinchar"
        self.btn_start.setToolTip(self._labels[self.btn_start].strip())
        self._apply_labels()
        if not active:
            return
        now = now or {}
        self._now_path = now.get("local_path", "")
        for btn in self.bpm_buttons:
            btn.setEnabled(bool(self._now_path))
        self.now_title.setText(now.get("title", ""))
        self.now_artist.setText(now.get("uploader", ""))
        self.now_detail.setText(describe(now))
        if nxt:
            extra = describe(nxt)
            self.next_title.setText(nxt.get("title", "") + (f"  ·  {extra}" if extra else ""))
        else:
            self.next_title.setText("Nada más: la sesión termina con esta canción")
        self.btn_drop.setEnabled(bool(nxt))
        self.btn_skip.setEnabled(bool(nxt))
        self.list_title.setText("Lo que queda" if remaining else "No queda nada más")
        if remaining > UPCOMING_SHOWN:
            self.list_title.setText(f"Lo que queda · {remaining} canciones (se ven las {UPCOMING_SHOWN} primeras)")
        elif remaining:
            self.list_title.setText(f"Lo que queda · {remaining} " + ("canción" if remaining == 1 else "canciones"))
        lines, paths = [], []
        for i, info in enumerate(list(upcoming)[:UPCOMING_SHOWN], 1):
            extra = describe(info)
            lines.append(f"{i}.  {info.get('title', '')}" + (f"  ·  {extra}" if extra else ""))
            paths.append(info.get("local_path", ""))
        if lines != [self.upcoming.item(i).text() for i in range(self.upcoming.count())] or paths != self._upcoming_paths:
            scroll = self.upcoming.verticalScrollBar().value()           # solo si algo cambió, y sin perder por dónde ibas
            self.upcoming.clear()
            self.upcoming.addItems(lines)
            self._upcoming_paths = paths
            self.upcoming.verticalScrollBar().setValue(scroll)

    # ------------------------------------------------------------ corregir el BPM
    def _emit_bpm(self, path: str, action: str):
        if path:
            self.bpm_requested.emit(path, action)

    def _upcoming_menu(self, pos):
        row = self.upcoming.row(self.upcoming.itemAt(pos)) if self.upcoming.itemAt(pos) else -1
        if not 0 <= row < len(self._upcoming_paths):
            return
        path = self._upcoming_paths[row]
        menu = QMenu(self)
        for text, action in (("El tempo es la mitad (÷2)", "half"), ("El tempo es el doble (×2)", "double"),
                             ("Escribir el BPM…", "set"), ("Volver al BPM automático", "auto")):
            menu.addAction(text).triggered.connect(lambda _=False, a=action: self._emit_bpm(path, a))
        menu.exec(self.upcoming.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def showEvent(self, event):
        super().showEvent(event)
        for btn in self.bpm_buttons:           # al mostrarse ya tiene el estilo de la ventana (al construirla, no)
            _tight(btn)

    # ------------------------------------------------------------ ancho
    def _needed_width(self) -> int:
        """Ancho que necesitan la cabecera y la fila de botones con todos sus textos."""
        def full(btn):
            return btn.fontMetrics().horizontalAdvance(self._labels[btn]) + BUTTON_EXTRA_W
        row = sum(full(b) for b in self._actions) + 10 * (len(self._actions) - 1)
        head = self.title.sizeHint().width() + 16 + full(self.btn_start)
        return max(row, head)

    def _apply_labels(self):
        for btn, text in self._labels.items():
            btn.setText("" if self._compact else text)

    def resizeEvent(self, event):
        """En una ventana estrecha (o con el panel de la derecha abierto) los botones se quedan solo con el icono, en
        vez de recortar su texto; el nombre sigue en la ayuda al pasar el ratón."""
        super().resizeEvent(event)
        compact = self.width() < self._needed_width()
        if compact != self._compact:
            self._compact = compact
            self._apply_labels()

    def set_progress(self, text: str):
        """Cómo va el análisis de las canciones («Analizando 34 de 100…»); vacío = oculto."""
        self.progress.setText(text)
        self.progress.setVisible(bool(text))

    def set_vote_target(self, text: str):
        """De qué mezcla se votaría ahora («A → B»), o vacío si todavía no hay ninguna."""
        self.btn_up.setEnabled(bool(text))
        self.btn_down.setEnabled(bool(text))
        self.vote_caption.setText(f"Votar {text}:" if text else "Votar la mezcla:")
        if not text:
            self.vote_status.setText("")

    def set_vote_status(self, text: str):
        self.vote_status.setText(text)

    def set_countdown(self, text: str):
        if self.countdown.text() != text:
            self.countdown.setText(text)
