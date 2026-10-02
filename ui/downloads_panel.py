"""Descargas en curso: seguimiento de todas las canciones que se están bajando y panel para verlas."""
from PySide6.QtCore import Qt, QObject, Signal, QTimer, QPoint
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QScrollArea, QWidget, QFrame
)

from services import pending_downloads
from ui.friendly import friendly_error
from ui.overlay import InlineDialog
from ui.widgets import ElidedLabel

ACTIVE_STATES = ("active", "converting")


class DownloadsTracker(QObject):
    """Registra las descargas (de una canción o de una lista) y avisa cuando algo cambia.

    Los avisos se agrupan (4 por segundo como máximo) para no repintar la interfaz en cada porcentaje."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: dict = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.changed.emit)

    def _notify(self, immediate: bool = False):
        if immediate:
            self._timer.stop()
            self.changed.emit()
        elif not self._timer.isActive():
            self._timer.start()

    def track(self, worker, info: dict):
        key = id(worker)
        self.entries[key] = {
            "title": info.get("title", "Canción"),
            "artist": info.get("uploader", ""),
            "percent": 0,
            "state": "active",
            "error": "",
        }
        worker.progress_signal.connect(lambda d, k=key: self._progress(k, d))
        worker.finished_signal.connect(lambda r, k=key: self._finished(k, r))
        while len(self.entries) > 30:   # se conservan las últimas 30
            old = next((k for k, e in self.entries.items() if e["state"] not in ACTIVE_STATES), None)
            if old is None:
                break
            self.entries.pop(old)
        self._notify(immediate=True)

    def _progress(self, key, data: dict):
        entry = self.entries.get(key)
        if not entry:
            return
        entry["percent"] = int(data.get("percent", 0) or 0)
        entry["state"] = "converting" if data.get("status") == "converting" else "active"
        self._notify()

    def _finished(self, key, result: dict):
        entry = self.entries.get(key)
        if not entry:
            return
        ok = bool(result.get("success"))
        entry["state"] = "done" if ok else "error"
        entry["percent"] = 100 if ok else entry["percent"]
        entry["error"] = "" if ok else friendly_error(result.get("error"))
        self._notify(immediate=True)

    def active(self) -> list:
        return [e for e in self.entries.values() if e["state"] in ACTIVE_STATES]

    def overall_percent(self) -> int:
        act = self.active()
        return int(sum(e["percent"] for e in act) / len(act)) if act else 100

    def clear_finished(self):
        self.entries = {k: e for k, e in self.entries.items() if e["state"] in ACTIVE_STATES}
        self._notify(immediate=True)


class _Row(QFrame):
    """Fila de una descarga. Se reutiliza: solo se actualizan sus textos y su barra."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.name = ElidedLabel("")
        self.name.setObjectName("SongTitle")
        self.name.setStyleSheet("font-size: 13px;")
        lay.addWidget(self.name)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 12px;")
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        lay.addWidget(self.bar)
        self._shown = None

    def update_from(self, entry: dict):
        title = f"{entry['artist']} - {entry['title']}" if entry["artist"] else entry["title"]
        if self.name.fullText() != title:
            self.name.setText(title)
        state = entry["state"]
        if state == "active":
            text, color = f"Descargando… {entry['percent']}%", "#1ED760"
        elif state == "converting":
            text, color = "Preparando tu canción...", "#1ED760"
        elif state == "done":
            text, color = "Lista en tu música", "#1ED760"
        else:
            text, color = entry["error"] or "No se pudo descargar", "#FF6B6B"
        self.status.setStyleSheet(f"font-size: 12px; color: {color};")
        self.status.setText(text)
        busy = state in ACTIVE_STATES
        self.bar.setVisible(busy)
        if busy:
            if state == "converting":
                self.bar.setRange(0, 0)
            else:
                self.bar.setRange(0, 100)
                self.bar.setValue(entry["percent"])


class DownloadsPanel(InlineDialog):
    """Ventana flotante interna con las descargas en curso y las terminadas (no oscurece el resto)."""

    def __init__(self, tracker: DownloadsTracker, window, anchor_button: QWidget):
        super().__init__(window, auto_delete=False, modal=False,
                         anchor=lambda: anchor_button.mapTo(window, QPoint(anchor_button.width() - 400,
                                                                           anchor_button.height() + 8)))
        self.tracker = tracker
        self.window_ref = window
        self.setFixedWidth(400)
        self._rows: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Descargas")
        title.setObjectName("SectionTitle")
        title.setStyleSheet("font-size: 18px;")
        head.addWidget(title)
        head.addStretch()
        self.btn_clear = QPushButton("Limpiar terminadas")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self.tracker.clear_finished)
        head.addWidget(self.btn_clear)
        root.addLayout(head)

        # Pendientes (descargas que esperan a que vuelva internet)
        self.pending_box = QFrame()
        self.pending_box.setObjectName("OfflineBanner")
        pl = QHBoxLayout(self.pending_box)
        pl.setContentsMargins(12, 8, 8, 8)
        pl.setSpacing(8)
        self.pending_lbl = QLabel("")
        self.pending_lbl.setWordWrap(True)
        self.pending_lbl.setStyleSheet("background: transparent; font-size: 12px; font-weight: 600;")
        pl.addWidget(self.pending_lbl, stretch=1)
        self.pending_now = QPushButton("Descargar ahora")
        self.pending_now.setCursor(Qt.PointingHandCursor)
        self.pending_now.clicked.connect(self._pending_now)
        pl.addWidget(self.pending_now)
        self.pending_cancel = QPushButton("Cancelar")
        self.pending_cancel.setCursor(Qt.PointingHandCursor)
        self.pending_cancel.clicked.connect(self._pending_cancel)
        pl.addWidget(self.pending_cancel)
        root.addWidget(self.pending_box)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 4, 0)
        self.body_layout.setSpacing(12)
        self.body_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll)

        self.empty = QLabel("No hay descargas en curso.\nCuando descargues una canción la verás aquí.")
        self.empty.setObjectName("SectionSubtitle")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("padding: 24px 0px;")
        self.body_layout.addWidget(self.empty)

        # Solo se actualiza mientras está visible
        self.tracker.changed.connect(self._on_changed)

    def _on_changed(self):
        if self.isVisible():
            self.refresh()

    def refresh_pending(self):
        n = pending_downloads.count()
        self.pending_box.setVisible(n > 0)
        if n:
            offline = self.window_ref.is_offline()
            self.pending_lbl.setText(f"{n} canción{'es' if n != 1 else ''} esperando: "
                                     + ("se descargarán cuando vuelva internet." if offline else "listas para descargarse."))
            self.pending_now.setVisible(not offline)

    def _pending_now(self):
        self.window_ref.resume_pending_downloads()

    def _pending_cancel(self):
        pending_downloads.clear()
        self.window_ref._reload_pending_keys()
        self.window_ref.refresh_download_marks()
        self.refresh_pending()

    def refresh(self):
        entries = self.tracker.entries
        for key in [k for k in self._rows if k not in entries]:
            row = self._rows.pop(key)
            self.body_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        for pos, (key, entry) in enumerate(reversed(list(entries.items()))):
            row = self._rows.get(key)
            if row is None:
                row = _Row()
                self._rows[key] = row
                self.body_layout.insertWidget(pos, row)
            else:
                current = self.body_layout.itemAt(pos).widget() if pos < self.body_layout.count() else None
                if current is not row:
                    self.body_layout.removeWidget(row)
                    self.body_layout.insertWidget(pos, row)
            row.update_from(entry)
        self.refresh_pending()
        self.empty.setVisible(not entries)
        self.btn_clear.setVisible(any(e["state"] not in ACTIVE_STATES for e in entries.values()))
        self.scroll.setFixedHeight(max(70, min(380, self.body.sizeHint().height() + 6)))

    def toggle(self):
        if self.isVisible():
            self.reject()
        else:
            self.refresh()
            self.open()
