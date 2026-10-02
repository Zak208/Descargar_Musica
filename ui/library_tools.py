"""Herramientas para cuidar tu música: canciones repetidas y mejora de etiquetas (artista, álbum y portada)."""
import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea, QWidget, QCheckBox, QProgressBar
)

from services import duplicates, recycle, tag_fixer
from services.storage_service import format_bytes
from ui.overlay import InlineDialog


class _DuplicatesWorker(QThread):
    ready = Signal(list)

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.items = items

    def run(self):
        self.setPriority(QThread.LowPriority)
        from services.heavy import heavy_task
        with heavy_task():
            self.ready.emit(duplicates.find_duplicates(self.items))


def _scroll_body(min_h: int = 320, max_h: int = 460):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setMinimumHeight(min_h)
    scroll.setMaximumHeight(max_h)
    body = QWidget()
    body.setObjectName("ToolsBody")
    body.setStyleSheet("#ToolsBody { background: transparent; }")
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 8, 0)
    lay.setSpacing(10)
    lay.setAlignment(Qt.AlignTop)
    scroll.setWidget(body)
    return scroll, lay


class DuplicatesDialog(InlineDialog):
    """Canciones repetidas: se marca para quitar la de menos calidad y todo va a la papelera de Windows."""

    def __init__(self, window):
        super().__init__(window)
        self.window_ref = window
        self.checks = []        # [(QCheckBox, ruta)]
        self.setMinimumWidth(680)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)
        title = QLabel("Canciones repetidas")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        self.hint = QLabel("Buscando canciones repetidas en tu música…")
        self.hint.setObjectName("SettingsHint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self.scroll, self.body = _scroll_body()
        root.addWidget(self.scroll)
        row = QHBoxLayout()
        row.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.setMinimumHeight(44)
        btn_close.clicked.connect(self.reject)
        row.addWidget(btn_close)
        self.btn_remove = QPushButton("Enviar a la papelera")
        self.btn_remove.setObjectName("GiantActionBtn")
        self.btn_remove.setEnabled(False)
        self.btn_remove.clicked.connect(self._remove)
        row.addWidget(self.btn_remove)
        root.addLayout(row)
        self.worker = _DuplicatesWorker(window.library_items(), self)
        self.worker.ready.connect(self._show)
        self.worker.start()

    def _show(self, groups: list):
        if not groups:
            self.hint.setText("No hay canciones repetidas. ¡Tu música está en orden!")
            self.scroll.setVisible(False)
            return
        self.hint.setText(f"Hay {len(groups)} canción{'es' if len(groups) != 1 else ''} repetida{'s' if len(groups) != 1 else ''}. "
                          "Dejamos marcadas las de menor calidad; las enviadas a la papelera se pueden recuperar.")
        for entries in groups:
            box = QFrame()
            box.setObjectName("SettingsGroup")
            lay = QVBoxLayout(box)
            lay.setContentsMargins(14, 10, 14, 10)
            lay.setSpacing(4)
            name = QLabel(entries[0]["item"].get("title", ""))
            name.setObjectName("SettingsLabel")
            lay.addWidget(name)
            for e in entries:
                it = e["item"]
                mins = int(e["duration"]) // 60
                detail = f"{e['bitrate']} kbps · {format_bytes(e['size'])} · {mins}:{int(e['duration']) % 60:02d}"
                text = f"{os.path.basename(it['local_path'])}   ({detail})" + ("   ← la mejor" if e["keep"] else "")
                chk = QCheckBox(text)
                chk.setChecked(not e["keep"])
                chk.toggled.connect(self._update_button)
                lay.addWidget(chk)
                self.checks.append((chk, it["local_path"]))
            self.body.addWidget(box)
        self._update_button()

    def _marked(self) -> list:
        return [p for chk, p in self.checks if chk.isChecked()]

    def _update_button(self, *_):
        n = len(self._marked())
        self.btn_remove.setEnabled(n > 0)
        self.btn_remove.setText(f"Enviar a la papelera ({n})" if n else "Enviar a la papelera")

    def _remove(self):
        removed = sum(1 for p in self._marked() if recycle.move_to_recycle_bin(p))
        self.accept()
        self.window_ref.rescan_library()
        self.window_ref.notify(f"{removed} canción{'es' if removed != 1 else ''} enviada{'s' if removed != 1 else ''} a la papelera")


class TagFixDialog(InlineDialog):
    """Mejorar etiquetas: propone artista, álbum y portada para canciones con datos pobres."""

    def __init__(self, window):
        super().__init__(window)
        self.window_ref = window
        self.rows = []          # [(QCheckBox, sugerencia)]
        self.setMinimumWidth(720)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)
        title = QLabel("Mejorar los datos de tus canciones")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        self.hint = QLabel("")
        self.hint.setObjectName("SettingsHint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        root.addWidget(self.progress)
        self.scroll, self.body = _scroll_body()
        root.addWidget(self.scroll)
        row = QHBoxLayout()
        row.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.setMinimumHeight(44)
        btn_close.clicked.connect(self._close)
        row.addWidget(btn_close)
        self.btn_apply = QPushButton("Aplicar")
        self.btn_apply.setObjectName("GiantActionBtn")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply)
        row.addWidget(self.btn_apply)
        root.addLayout(row)
        self.worker = None
        self._start()

    def _start(self):
        items = tag_fixer.candidates(self.window_ref.library_items())
        if self.window_ref.is_offline():
            self.hint.setText("Necesitas conexión a internet para buscar los datos de tus canciones.")
            self.progress.setVisible(False)
            return
        if not items:
            self.hint.setText("Todas tus canciones tienen artista y álbum. ¡No hay nada que mejorar!")
            self.progress.setVisible(False)
            return
        self.hint.setText(f"Buscando los datos de {len(items)} canciones con artista o álbum por completar…")
        self.progress.setRange(0, len(items))
        self.worker = tag_fixer.TagSuggestWorker(items, self)
        self.worker.suggestion.connect(self._add)
        self.worker.progress.connect(lambda i, n: self.progress.setValue(i))
        self.worker.finished_all.connect(self._finished)
        self.worker.start()

    def _add(self, s: dict):
        cur, new = s["current"], s["proposed"]
        box = QFrame()
        box.setObjectName("SettingsGroup")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(2)
        chk = QCheckBox(f"{new['title']} — {new['artist']}" + (f"  ·  {new['album']}" if new["album"] else ""))
        chk.setChecked(s["score"] >= 0.8)
        chk.toggled.connect(self._update_button)
        lay.addWidget(chk)
        was = QLabel(f"Antes: {cur['title'] or '—'} — {cur['artist'] or 'sin artista'}"
                     + (f"  ·  {cur['album']}" if cur["album"] else "  ·  sin álbum"))
        was.setObjectName("SettingsHint")
        was.setContentsMargins(26, 0, 0, 0)
        lay.addWidget(was)
        self.body.addWidget(box)
        self.rows.append((chk, s))
        self._update_button()

    def _finished(self, found: int):
        self.progress.setVisible(False)
        self.hint.setText(f"Encontramos datos para {found} canciones. Revisa las marcadas y pulsa «Aplicar»."
                          if found else "No encontramos mejores datos para tus canciones.")

    def _marked(self) -> list:
        return [s for chk, s in self.rows if chk.isChecked()]

    def _update_button(self, *_):
        n = len(self._marked())
        self.btn_apply.setEnabled(n > 0)
        self.btn_apply.setText(f"Aplicar ({n})" if n else "Aplicar")

    def _apply(self):
        done = tag_fixer.apply_suggestions(self._marked())
        self._close()
        self.window_ref.rescan_library()
        self.window_ref.notify(f"Datos mejorados en {done} canción{'es' if done != 1 else ''}")

    def _close(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.is_cancelled = True
        self.reject()
