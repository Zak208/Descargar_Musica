"""Menú DJ (arriba a la izquierda): elegir la carpeta general, qué parte de ella suena y empezar a pinchar.

De momento la sesión DJ pone las canciones elegidas en orden aleatorio y las mezcla con el fundido que ya existe (que
iguala el ritmo). Las mezclas por frases, el cambio de graves y lo demás llegan por fases (ver docs/PLAN_DJ.md)."""
import os
import random

from PySide6.QtCore import QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMenu

from services import dj_service
from services.dj_service import SOURCE_ALL, SOURCE_ROOT, DjScanWorker
from ui.icons import icon

DJ_FADE_SECONDS = 8          # si el fundido está apagado, la sesión DJ lo enciende con esta duración


class DjMixin:
    """Mezcla para MainWindow. Requiere: topbar, set_context(), _play_entry(), _local_track_info(), crossfade_ms(),
    set_fade_seconds(), _fade_ms y notify()."""

    def init_dj_state(self):
        self._dj_summary = None        # resumen de la carpeta general (se lee al abrir el menú por primera vez)
        self._dj_worker = None
        self._dj_start_when_ready = False

    # ------------------------------------------------------------ carpeta
    def refresh_dj_folder(self):
        if self._dj_worker is not None and self._dj_worker.isRunning():
            return
        self._dj_worker = DjScanWorker(dj_service.get_root(), self)
        self._dj_worker.ready.connect(self._on_dj_scanned)
        self._dj_worker.start()

    def _on_dj_scanned(self, summary: dict):
        if summary.get("root") != dj_service.get_root():     # se cambió de carpeta mientras se leía
            self._dj_summary = None
            self.refresh_dj_folder()
            return
        self._dj_summary = summary
        if self._dj_start_when_ready:
            self._dj_start_when_ready = False
            self.start_dj_session()

    def choose_dj_root(self):
        chosen = QFileDialog.getExistingDirectory(self, "Elegir la carpeta general del DJ", dj_service.get_root())
        if chosen and os.path.isdir(chosen):
            dj_service.set_root(chosen)
            self._dj_summary = None
            self.refresh_dj_folder()
            self.notify(f"Carpeta del DJ: «{os.path.basename(chosen) or chosen}». Sonará todo lo que hay dentro.")

    def set_dj_source(self, source: str):
        dj_service.set_source(source)

    @staticmethod
    def _dj_source_label(source: str) -> str:
        if source == SOURCE_ALL:
            return "toda la carpeta"
        if source == SOURCE_ROOT:
            return "la carpeta general"
        return source

    # ------------------------------------------------------------ menú
    def open_dj_menu(self):
        if self._dj_summary is None:
            self.refresh_dj_folder()
        summary = self._dj_summary
        root = dj_service.get_root()
        source = dj_service.get_source()
        menu = QMenu(self)

        head = menu.addAction(icon("folder.svg"), f"Carpeta general: {os.path.basename(root) or root}")
        head.setEnabled(False)
        menu.addAction(icon("new_folder.svg"), "Elegir la carpeta general…").triggered.connect(self.choose_dj_root)
        menu.addSeparator()

        if summary is None:
            menu.addAction("Leyendo la carpeta…").setEnabled(False)
        else:
            group = QActionGroup(menu)
            options = [(SOURCE_ALL, f"Toda la carpeta, con subcarpetas · {dj_service.count_all(summary)}")]
            if summary["loose"] and summary["folders"]:
                options.append((SOURCE_ROOT, f"Solo la carpeta general · {len(summary['loose'])}"))
            options += [(name, f"{name} · {len(paths)}") for name, paths in summary["folders"].items()]
            if source not in {key for key, _text in options}:     # la subcarpeta elegida ya no existe: suena todo
                source = SOURCE_ALL
            title = menu.addAction("Qué suena (canciones)")
            title.setEnabled(False)
            for key, text in options:
                act = menu.addAction(text)
                act.setCheckable(True)
                act.setChecked(key == source)
                group.addAction(act)
                act.triggered.connect(lambda _=False, k=key: self.set_dj_source(k))
            if summary["truncated"]:
                menu.addAction(f"Solo se han leído las primeras {dj_service.MAX_FILES} canciones").setEnabled(False)

        menu.addSeparator()
        start = menu.addAction(icon("play.svg"), "Empezar a pinchar")
        start.triggered.connect(self.start_dj_session)
        start.setEnabled(summary is None or bool(dj_service.tracks_for(summary, source)))
        menu.addAction(icon("refresh.svg"), "Volver a leer la carpeta").triggered.connect(self._reread_dj_folder)
        menu.addAction(icon("folder.svg"), "Abrir la carpeta en el explorador").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(root)))
        btn = self.topbar.btn_dj
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _reread_dj_folder(self):
        self._dj_summary = None
        self.refresh_dj_folder()

    # ------------------------------------------------------------ sesión
    def start_dj_session(self):
        if self._dj_summary is None:            # aún se está leyendo: empieza en cuanto termine
            self._dj_start_when_ready = True
            self.refresh_dj_folder()
            self.notify("Leyendo la carpeta del DJ…")
            return
        source = dj_service.get_source()
        paths = dj_service.tracks_for(self._dj_summary, source)
        if not paths:
            self.notify("No hay canciones en esa carpeta (mp3, mp4, m4a, wav, flac, ogg o wma).")
            return
        random.shuffle(paths)
        tracks = [self._local_track_info(p, {}) for p in paths]   # sin leer etiquetas aquí: se leen al sonar cada una
        self.set_context(tracks)
        fade_note = ""
        if self._fade_ms <= 0:
            self.set_fade_seconds(DJ_FADE_SECONDS)
            fade_note = f" Se ha activado el fundido de {DJ_FADE_SECONDS} s."
        self._play_entry(tracks[0], crossfade_ms=self.crossfade_ms())
        self.notify(f"Modo DJ: {len(tracks)} canciones de {self._dj_source_label(source)}.{fade_note}")
