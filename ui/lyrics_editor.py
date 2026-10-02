"""Editor de letras dentro de la propia ventana: se escribe el momento de la canción en un campo y la frase en otro,
y al pulsar «Añadir» la línea sube a la lista. Sirve para crear una letra desde cero o corregir la que generó el sistema."""
import re

from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QApplication, QProgressBar
)

from services.lyrics_store import parse_text
from ui.overlay import InlineDialog

_TIME = re.compile(r"^\[?\s*(?:(\d+):)?(\d+)(?:[.,](\d{1,3}))?\s*\]?$")
_FIELD_OK = ("QLineEdit { background: #1A1A1A; color: #FFFFFF; border: 1px solid #3A3A3A; border-radius: 10px; "
             "padding: 8px 10px; font-size: 14px; } QLineEdit:focus { border-color: #FFFFFF; }")
_FIELD_BAD = _FIELD_OK.replace("#3A3A3A", "#E5484D")


def parse_time(text: str):
    """Entiende «1:23», «01:23.50», «[01:23.5]» o «83» (segundos). Devuelve milisegundos o None si no es un tiempo."""
    m = _TIME.match((text or "").strip())
    if not m:
        return None
    mins, secs, frac = m.group(1), int(m.group(2)), m.group(3)
    if mins is None and ":" not in text:        # solo segundos: «83»
        return int(secs * 1000 + (int(frac.ljust(3, "0")) if frac else 0))
    if secs >= 60:
        return None
    return int((int(mins or 0) * 60 + secs) * 1000 + (int(frac.ljust(3, "0")) if frac else 0))


def fmt_time(ms: int) -> str:
    total = max(0, ms) / 1000
    return f"{int(total // 60):02d}:{total % 60:05.2f}"


class LyricsEditorDialog(InlineDialog):
    """Resultado: `text` (la letra, con «[mm:ss.xx]» delante de las líneas con tiempo) y `restore` (volver a la original)."""
    sync_requested = Signal(list)          # pide al sistema poner el tiempo a las frases (lista de textos)

    def __init__(self, parent, title: str, text: str, player=None, can_restore: bool = False, audio_path: str = ""):
        super().__init__(parent)
        self.player = player
        self.audio_path = audio_path
        self._tap = False
        self.text = text
        self.restore = False
        self._loading = False
        self.setMinimumWidth(640)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 22)
        lay.setSpacing(12)

        head = QLabel(f"Letra de «{title}»")
        head.setObjectName("SectionTitle")
        head.setStyleSheet("font-size: 20px;")
        head.setWordWrap(True)
        lay.addWidget(head)

        hint = QLabel("Escribe el momento de la canción (por ejemplo 1:23) y la frase, y pulsa «Añadir»: la línea sube a la "
                      "lista de abajo. Mientras suena la canción, «Tiempo actual» pone el momento por ti. "
                      "Para corregir una línea, haz doble clic en ella.")
        hint.setObjectName("DialogBody")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # ---- una línea nueva: tiempo + frase + añadir
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("0:00")
        self.time_input.setFixedWidth(92)
        self.time_input.setToolTip("Momento de la canción en que empieza la frase (minutos:segundos)")
        self.time_input.setStyleSheet(_FIELD_OK)
        self.time_input.textChanged.connect(lambda _t: self.time_input.setStyleSheet(_FIELD_OK))
        add_row.addWidget(self.time_input)
        self.btn_now = QPushButton("Tiempo actual")
        self.btn_now.setCursor(Qt.PointingHandCursor)
        self.btn_now.setMinimumHeight(40)
        self.btn_now.setEnabled(player is not None)
        self.btn_now.setToolTip("Pone aquí el momento en que va la canción ahora mismo")
        self.btn_now.clicked.connect(self._use_current_time)
        add_row.addWidget(self.btn_now)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Frase de la letra")
        self.text_input.setStyleSheet(_FIELD_OK)
        self.text_input.returnPressed.connect(self._add_line)
        add_row.addWidget(self.text_input, stretch=1)
        self.btn_add = QPushButton("Añadir")
        self.btn_add.setObjectName("GiantActionBtn")
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setMinimumHeight(40)
        self.btn_add.clicked.connect(self._add_line)
        add_row.addWidget(self.btn_add)
        lay.addLayout(add_row)

        # ---- lista de líneas
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Tiempo", "Frase"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 100)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setMinimumHeight(260)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(
            "QTableWidget { background: #1A1A1A; color: #FFFFFF; border: 1px solid #3A3A3A; border-radius: 10px; "
            "font-size: 14px; outline: 0; }"
            "QTableWidget::item { padding: 6px; border-bottom: 1px solid #262626; }"
            "QTableWidget::item:selected { background: rgba(255,255,255,0.18); color: #FFFFFF; }"
            "QHeaderView::section { background: #242424; color: #B3B3B3; border: none; padding: 7px; font-weight: 700; }")
        self.table.itemChanged.connect(self._item_changed)
        lay.addWidget(self.table, stretch=1)

        # ---- poner los tiempos sin escribirlos
        sync_box = QHBoxLayout()
        sync_box.setSpacing(8)
        self.btn_auto = QPushButton("Ponerles el tiempo automáticamente")
        self.btn_auto.setCursor(Qt.PointingHandCursor)
        self.btn_auto.setToolTip("El sistema escucha la canción y pone el momento de cada frase de tu letra (canciones descargadas)")
        self.btn_auto.setEnabled(bool(audio_path))
        self.btn_auto.clicked.connect(self._request_sync)
        sync_box.addWidget(self.btn_auto)
        self.btn_tap = QPushButton("Marcar con la barra espaciadora")
        self.btn_tap.setCursor(Qt.PointingHandCursor)
        self.btn_tap.setToolTip("La canción suena desde el principio: pulsa Espacio cuando empiece cada frase")
        self.btn_tap.setEnabled(player is not None)
        self.btn_tap.clicked.connect(self._toggle_tap)
        sync_box.addWidget(self.btn_tap)
        sync_box.addStretch()
        lay.addLayout(sync_box)
        self.sync_lbl = QLabel("")
        self.sync_lbl.setObjectName("SettingsHint")
        self.sync_lbl.setWordWrap(True)
        self.sync_lbl.setVisible(False)
        lay.addWidget(self.sync_lbl)
        self.sync_bar = QProgressBar()
        self.sync_bar.setTextVisible(False)
        self.sync_bar.setFixedHeight(6)
        self.sync_bar.setVisible(False)
        lay.addWidget(self.sync_bar)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.btn_remove = QPushButton("Quitar la línea marcada")
        self.btn_remove.setCursor(Qt.PointingHandCursor)
        self.btn_remove.clicked.connect(self._remove_selected)
        tools.addWidget(self.btn_remove)
        btn_paste = QPushButton("Pegar una letra")
        btn_paste.setCursor(Qt.PointingHandCursor)
        btn_paste.setToolTip("Añade las líneas que tengas copiadas (cada renglón es una línea; si empiezan por [mm:ss] se respeta el tiempo)")
        btn_paste.clicked.connect(self._paste)
        tools.addWidget(btn_paste)
        tools.addStretch()
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("SectionSubtitle")
        tools.addWidget(self.count_lbl)
        lay.addLayout(tools)

        row = QHBoxLayout()
        row.setSpacing(10)
        if can_restore:
            btn_restore = QPushButton("Volver a la original")
            btn_restore.setCursor(Qt.PointingHandCursor)
            btn_restore.setMinimumHeight(44)
            btn_restore.setToolTip("Borra tu versión y vuelve a la letra de internet o a la del sistema")
            btn_restore.clicked.connect(self._restore)
            row.addWidget(btn_restore)
        row.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setMinimumHeight(44)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        self.btn_ok = QPushButton("Guardar")
        self.btn_ok.setObjectName("GiantActionBtn")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self._save)
        row.addWidget(self.btn_ok)
        lay.addLayout(row)

        self.table.installEventFilter(self)
        self._fill(text)
        self.text_input.setFocus()

    # ------------------------------------------------------------ tabla
    def _fill(self, text: str):
        lines, synced = parse_text(text)
        self._loading = True
        for ms, frase in lines:
            self._append_row(fmt_time(ms) if synced else "", frase)
        self._loading = False
        self._update_count()

    def _append_row(self, time_text: str, phrase: str, at: int = -1):
        row = self.table.rowCount() if at < 0 else at
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(time_text))
        self.table.setItem(row, 1, QTableWidgetItem(phrase))
        return row

    def _row_time(self, row: int):
        item = self.table.item(row, 0)
        return parse_time(item.text()) if item and item.text().strip() else None

    def _insert_position(self, ms):
        """Dónde va una línea nueva para que la lista siga ordenada por tiempo."""
        if ms is None:
            return self.table.rowCount()
        for row in range(self.table.rowCount()):
            t = self._row_time(row)
            if t is not None and t > ms:
                return row
        return self.table.rowCount()

    def _update_count(self):
        n = self.table.rowCount()
        self.count_lbl.setText("Sin líneas todavía" if n == 0 else f"{n} línea" + ("" if n == 1 else "s"))

    # ---------------------------------------------------------- acciones
    def _use_current_time(self):
        if self.player is not None:
            self.time_input.setText(fmt_time(self.player.position()))

    def _add_line(self):
        phrase = self.text_input.text().strip()
        if not phrase:
            self.text_input.setFocus()
            return
        raw = self.time_input.text().strip()
        ms = parse_time(raw) if raw else None
        if raw and ms is None:
            self.time_input.setStyleSheet(_FIELD_BAD)      # el tiempo no se entiende: se marca en rojo
            self.time_input.setFocus()
            return
        row = self._append_row(fmt_time(ms) if ms is not None else "", phrase, self._insert_position(ms))
        self.table.scrollToItem(self.table.item(row, 1))
        self.table.selectRow(row)
        self.text_input.clear()
        self.time_input.clear()
        self.text_input.setFocus()
        self._update_count()

    def _item_changed(self, item):
        if self._loading or item.column() != 0:
            return
        text = item.text().strip()
        if not text:
            return
        ms = parse_time(text)
        self._loading = True
        item.setText(fmt_time(ms) if ms is not None else "")     # lo que no es un tiempo se quita
        self._loading = False

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._update_count()

    def _paste(self):
        clip = QApplication.clipboard().text()
        if not clip.strip():
            return
        lines, synced = parse_text(clip)
        self._loading = True
        for ms, phrase in lines:
            self._append_row(fmt_time(ms) if synced else "", phrase)
        self._loading = False
        self._update_count()

    # ----------------------------------------------- tiempos automáticos y con el teclado
    def phrases(self) -> list:
        return [(self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip() for r in range(self.table.rowCount())]

    def _request_sync(self):
        lines = [p for p in self.phrases() if p]
        if not lines:
            self.set_sync_busy("Escribe o pega primero la letra: el sistema le pondrá los tiempos.")
            return
        self.btn_auto.setEnabled(False)
        self.set_sync_busy("Preparando…", 0)
        self.sync_requested.emit(lines)

    def set_sync_busy(self, text: str, percent: int = -1):
        """Texto y barra mientras el sistema trabaja. percent: -1 sin barra, -2 barra que avanza sola."""
        self.sync_lbl.setText(text)
        self.sync_lbl.setVisible(bool(text))
        self.sync_bar.setVisible(percent != -1)
        if percent == -2:
            self.sync_bar.setRange(0, 0)
        elif percent >= 0:
            self.sync_bar.setRange(0, 100)
            self.sync_bar.setValue(percent)
        if percent == -1:
            self.btn_auto.setEnabled(bool(self.audio_path))

    def apply_times(self, times: list):
        """Pone en la tabla los tiempos calculados (uno por cada frase con texto, en orden)."""
        self._loading = True
        it = iter(times)
        for row in range(self.table.rowCount()):
            if not (self.table.item(row, 1) and self.table.item(row, 1).text().strip()):
                continue
            ms = next(it, None)
            self.table.setItem(row, 0, QTableWidgetItem(fmt_time(ms) if ms is not None else ""))
        self._loading = False
        self.set_sync_busy("Listo: revisa los tiempos y corrige los que no te cuadren (doble clic).")
        self.btn_auto.setEnabled(bool(self.audio_path))

    def _toggle_tap(self):
        self._set_tap(not self._tap)

    def _set_tap(self, on: bool):
        self._tap = on
        if on:
            if self.table.rowCount() == 0:
                self._tap = False
                self.set_sync_busy("Escribe o pega primero la letra.")
                return
            self.btn_tap.setText("Terminar de marcar")
            self.set_sync_busy("Pulsa la barra espaciadora justo cuando empiece cada frase (Esc para terminar).")
            self.table.selectRow(0)
            self.table.setFocus()
            if self.player is not None:
                self.player.setPosition(0)
                self.player.play()
        else:
            self.btn_tap.setText("Marcar con la barra espaciadora")
            if self.sync_lbl.text().startswith("Pulsa la barra"):
                self.set_sync_busy("")
            if self.player is not None:
                self.player.pause()

    def _stamp_row(self):
        row = self.table.currentRow()
        if row < 0 or self.player is None:
            return
        ms = max(0, int(self.player.position()) - 180)       # se descuenta lo que tarda la mano en pulsar
        self._loading = True
        self.table.setItem(row, 0, QTableWidgetItem(fmt_time(ms)))
        self._loading = False
        self._flash_row(row)             # la fila marcada destella: se ve que ha contado
        if row + 1 < self.table.rowCount():
            self.table.selectRow(row + 1)
            self.table.scrollToItem(self.table.item(row + 1, 1))
        else:
            self._set_tap(False)
            self.set_sync_busy("Listo: has marcado todas las frases. Revisa los tiempos y guarda.")

    def _flash_row(self, row: int):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QWidget
        from ui.animations import flash
        from ui.styles import accent
        model = self.table.model()
        rect = self.table.visualRect(model.index(row, 0)).united(self.table.visualRect(model.index(row, 1)))
        if rect.isEmpty():
            return
        holder = QWidget(self.table.viewport())
        holder.setAttribute(Qt.WA_TransparentForMouseEvents)
        holder.setGeometry(rect)
        holder.show()
        flash(holder, accent(), 0.45, 380, 4)
        QTimer.singleShot(500, holder.deleteLater)

    def eventFilter(self, obj, event):
        if self._tap and obj is self.table and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Space:
                self._stamp_row()
                return True
            if event.key() == Qt.Key_Escape:
                self._set_tap(False)
                return True
        return super().eventFilter(obj, event)

    def _collect(self) -> str:
        out = []
        for row in range(self.table.rowCount()):
            phrase = (self.table.item(row, 1).text() if self.table.item(row, 1) else "").strip()
            if not phrase:
                continue
            ms = self._row_time(row)
            out.append(f"[{fmt_time(ms)}] {phrase}" if ms is not None else phrase)
        return "\n".join(out)

    def _save(self):
        self.text = self._collect()
        if not self.text:
            self.text_input.setFocus()
            return
        self.accept()

    def _restore(self):
        self.restore = True
        self.accept()
