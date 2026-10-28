"""Modo DJ: menú de arriba a la izquierda (carpeta general y qué parte suena) y página DJ para llevar la sesión.

De momento la sesión DJ pone las canciones elegidas en orden aleatorio y las mezcla con el fundido que ya existe (que
iguala el ritmo). Las mezclas por frases, el cambio de graves y lo demás llegan por fases (ver docs/PLAN_DJ.md)."""
import os
import random

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QFileDialog, QMenu

from services import dj_service
from services.dj_service import SOURCE_ALL, SOURCE_ROOT, DjScanWorker
from ui.dj_page import DjPage, UPCOMING_SHOWN
from ui.icons import icon
from ui.pages import Page
from ui.playback_mixin import track_key

DJ_FADE_SECONDS = 8          # si el fundido está apagado, la sesión DJ lo enciende con esta duración
FIRST_SCAN_MS = 6000         # la carpeta se lee un poco después de abrir (así el menú ya la tiene)
MAX_MISSING_SKIPS = 50       # canciones borradas seguidas que se saltan antes de rendirse


class DjMixin:
    """Mezcla para MainWindow. Requiere: topbar, stacked_widget, switch_to_page(), set_context(), _context,
    _context_position(), _shuffle_active(), _ensure_shuffle_plan(), _shuffle_plan, _history, _forward, playback_queue,
    current_item_info, peek_next(), upcoming_tracks(), play_next(), stop_player(), reset_shuffle(), _play_entry(),
    _local_track_info(), crossfade_ms(), set_fade_seconds(), _fade_ms, _xf_active, is_loop_enabled, player,
    format_time() y notify()."""

    def init_dj_state(self):
        self._dj_summary = None        # resumen de la carpeta general (se lee en segundo plano)
        self._dj_worker = None
        self._dj_rescan = False        # pedir otra lectura en cuanto termine la que está en marcha
        self._dj_start_when_ready = False
        self._dj_context = None        # la lista de la sesión DJ (es la misma lista que `_context` mientras dura)
        self._dj_in_session = False    # lo que suena es de la sesión DJ (se calcula al cambiar de canción)
        self._dj_last_key = None       # la última canción de la sesión que sonó
        self._dj_has_next = False
        self.page_dj = None
        if dj_service.used_before():       # solo si ya se ha usado el DJ: si no, la carpeta se lee al abrir el menú
            QTimer.singleShot(FIRST_SCAN_MS, self.refresh_dj_folder)

    def build_dj_page(self):
        self.page_dj = DjPage(self)
        self.page_dj.start_requested.connect(self.start_dj_session)
        self.page_dj.folder_requested.connect(self.open_dj_menu)
        self.page_dj.skip_requested.connect(self.dj_skip)
        self.page_dj.drop_next_requested.connect(self.dj_drop_next)
        self.page_dj.block_requested.connect(self.dj_block_current)
        self.page_dj.reshuffle_requested.connect(self.dj_reshuffle)
        self.page_dj.unblock_all_requested.connect(self.dj_unblock_all)
        self.stacked_widget.addWidget(self.page_dj)
        assert self.stacked_widget.indexOf(self.page_dj) == Page.DJ

    # ------------------------------------------------------------ carpeta
    def refresh_dj_folder(self):
        if self._dj_worker is not None:          # ya se está leyendo: se lee otra vez al terminar
            self._dj_rescan = True
            return
        self._dj_rescan = False
        worker = DjScanWorker(dj_service.get_root(), self)
        worker.ready.connect(self._on_dj_scanned)
        worker.finished.connect(self._on_dj_worker_done)
        self._dj_worker = worker
        worker.start()

    def _on_dj_scanned(self, summary: dict):
        if summary.get("root") != dj_service.get_root():     # se cambió de carpeta mientras se leía
            self._dj_rescan = True
            return
        self._dj_summary = summary
        self.refresh_dj_page()
        if self._dj_start_when_ready:
            self._dj_start_when_ready = False
            self.start_dj_session()

    def _on_dj_worker_done(self):
        worker, self._dj_worker = self._dj_worker, None
        if worker is not None:
            worker.deleteLater()
        if self._dj_rescan:
            self.refresh_dj_folder()

    def _reread_dj_folder(self):
        self._dj_summary = None
        self.refresh_dj_folder()
        self.refresh_dj_page()

    def choose_dj_root(self):
        chosen = QFileDialog.getExistingDirectory(self, "Elegir la carpeta general del DJ", dj_service.get_root())
        if chosen and os.path.isdir(chosen):
            dj_service.set_root(chosen)
            self._reread_dj_folder()
            self.notify(f"Carpeta del DJ: «{os.path.basename(chosen) or chosen}». Sonará todo lo que hay dentro.")

    def set_dj_source(self, source: str):
        dj_service.set_source(source)
        self.refresh_dj_page()

    def _dj_source(self) -> str:
        return dj_service.effective_source(self._dj_summary, dj_service.get_source())

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
        source = self._dj_source()
        menu = QMenu(self)

        head = menu.addAction(icon("folder.svg"), f"Carpeta general: {os.path.basename(root) or root}")
        head.setEnabled(False)
        menu.addAction(icon("new_folder.svg"), "Elegir la carpeta general…").triggered.connect(self.choose_dj_root)
        menu.addSeparator()

        if summary is None:
            menu.addAction("Leyendo la carpeta…").setEnabled(False)
        elif summary.get("missing"):
            menu.addAction("La carpeta ya no existe: elige otra").setEnabled(False)
        else:
            group = QActionGroup(menu)
            options = [(SOURCE_ALL, f"Toda la carpeta, con subcarpetas · {dj_service.count_all(summary)}")]
            if summary["loose"] and summary["folders"]:
                options.append((SOURCE_ROOT, f"Solo la carpeta general · {len(summary['loose'])}"))
            options += [(name, f"{name} · {len(paths)}") for name, paths in summary["folders"].items()]
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
        menu.addAction(icon("sliders.svg"), "Abrir la página DJ").triggered.connect(self.open_dj_page)
        menu.addAction(icon("refresh.svg"), "Volver a leer la carpeta").triggered.connect(self._reread_dj_folder)
        menu.addAction(icon("folder.svg"), "Abrir la carpeta en el explorador").triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(root)))
        btn = self.topbar.btn_dj
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        menu.deleteLater()

    # ------------------------------------------------------------ sesión
    def dj_session_active(self) -> bool:
        """True mientras lo que suena sale de la sesión DJ (si pones otra lista o un álbum, la sesión termina)."""
        return (self._dj_context is not None and self._context is self._dj_context and self._dj_in_session
                and bool(self.current_item_info))

    def start_dj_session(self):
        if self._dj_summary is None:            # aún se está leyendo: empieza en cuanto termine
            self._dj_start_when_ready = True
            self.refresh_dj_folder()
            self.notify("Leyendo la carpeta del DJ…")
            return
        if not dj_service.used_before():
            dj_service.set_source(dj_service.get_source())     # a partir de ahora la carpeta se lee al abrir el programa
        source = self._dj_source()
        paths = dj_service.without_blocked(dj_service.tracks_for(self._dj_summary, source))
        random.shuffle(paths)
        skipped = 0
        while paths and skipped < MAX_MISSING_SKIPS and not os.path.isfile(paths[0]):   # borradas desde que se leyó
            paths.pop(0)
            skipped += 1
        if not paths or not os.path.isfile(paths[0]):
            self.notify("No hay canciones en esa carpeta (mp3, mp4, m4a, wav, flac, ogg o wma)."
                        if not skipped else "Las canciones de esa carpeta han cambiado: pulsa «Volver a leer la carpeta».")
            return
        tracks = [self._local_track_info(p, {}) for p in paths]   # sin leer etiquetas aquí: se leen al sonar cada una
        self.set_context(tracks)
        self._dj_context = self._context
        self._dj_in_session = True
        self._dj_last_key = None
        fade_note = ""
        if self._fade_ms <= 0:
            self.set_fade_seconds(DJ_FADE_SECONDS)
            fade_note = f" Se ha activado el fundido de {DJ_FADE_SECONDS} s."
        self._play_entry(tracks[0], crossfade_ms=self.crossfade_ms())
        self.open_dj_page()
        self.notify(f"Modo DJ: {len(tracks)} canciones de {self._dj_source_label(source)}.{fade_note}")

    def dj_track_changed(self):
        """Cambió la canción que suena: ¿sigue siendo de la sesión DJ?, la siguiente existe todavía y la página al día."""
        if self._dj_context is None or self._context is not self._dj_context or not self.current_item_info:
            self._dj_in_session = False
        else:
            self._dj_in_session = True
            key = track_key(self.current_item_info)
            if self._context_position() < 0:
                # suena algo de fuera (de la cola o «Reproducir» en otra lista): entra en la sesión justo después de la
                # última que sonó, para que al terminar siga la sesión en vez de cortarse
                at = next((i for i, t in enumerate(self._dj_context) if track_key(t) == self._dj_last_key), -1)
                self._dj_context.insert(at + 1, dict(self.current_item_info))
            self._dj_last_key = key
            self._dj_prune_next()
        self._dj_has_next = bool(self.dj_session_active() and self.peek_next())
        self.refresh_dj_page()

    def _dj_prune_next(self):
        """Si la siguiente se borró del disco desde que se leyó la carpeta, se quita (y así con las que sigan)."""
        for _ in range(MAX_MISSING_SKIPS):
            nxt = self.peek_next()
            path = (nxt or {}).get("local_path")
            if not path or os.path.isfile(path):
                return
            self._dj_remove(nxt)

    def dj_skip(self):
        if self.dj_session_active():
            self._dj_prune_next()
            self.play_next()

    def _dj_remove(self, info: dict):
        """Quita una canción de todo lo que puede volver a sonar (cola, historial, sesión)."""
        key = track_key(info)
        self.playback_queue[:] = [t for t in self.playback_queue if track_key(t) != key]
        self._history[:] = [e for e in self._history if track_key(e["info"]) != key]
        self._forward[:] = [e for e in self._forward if track_key(e["info"]) != key]
        self._shuffle_plan[:] = [t for t in self._shuffle_plan if track_key(t) != key]
        if self._dj_context is not None:
            self._dj_context[:] = [t for t in self._dj_context if track_key(t) != key]   # misma lista: la sesión sigue

    def dj_drop_next(self):
        if not self.dj_session_active():
            return
        nxt = self.peek_next()
        if nxt:
            self._dj_remove(nxt)
            self.dj_queue_changed()
            self.notify(f"Quitada de la sesión: {nxt.get('title', '')}")

    def dj_block_current(self):
        if not self.dj_session_active():
            return
        cur = dict(self.current_item_info)
        path = cur.get("local_path")
        if not path:
            return
        dj_service.block(path)
        self._dj_prune_next()
        nxt = self.peek_next()
        if nxt and not self._dj_is(nxt, cur):
            self.play_next()        # primero pasa a la siguiente (la sesión necesita la actual para saber dónde va)
            self._dj_remove(cur)
            self.dj_queue_changed()
            self.notify(f"«{cur.get('title', '')}» no volverá a salir en el modo DJ.")
        else:
            self._dj_remove(cur)
            self.stop_player()      # era la última: no tiene sentido que siga sonando
            self.notify(f"«{cur.get('title', '')}» no volverá a salir. Era la última: la sesión termina.")

    @staticmethod
    def _dj_is(a: dict, b: dict) -> bool:
        return bool(a and b) and track_key(a) == track_key(b)

    def dj_reshuffle(self):
        if not self.dj_session_active():
            return
        pos = self._context_position()
        if pos < 0:
            return
        rest = self._dj_context[pos + 1:]       # solo lo que queda: lo que ya sonó se queda donde estaba
        random.shuffle(rest)
        self._dj_context[pos + 1:] = rest
        self.reset_shuffle()
        self.dj_queue_changed()
        self.notify("Orden nuevo para lo que queda.")

    def dj_unblock_all(self):
        dj_service.unblock_all()
        self.refresh_dj_page()
        self.notify("Todas las canciones vuelven a poder sonar en el modo DJ.")

    def dj_queue_changed(self):
        """Cambió lo que viene (cola, aleatorio, botones del DJ): la siguiente y la página se ponen al día."""
        self._dj_has_next = bool(self.dj_session_active() and self.peek_next())
        self.refresh_dj_page()

    # ------------------------------------------------------------ página
    def open_dj_page(self):
        if self._dj_summary is None:
            self.refresh_dj_folder()
        self.switch_to_page(Page.DJ)
        self.refresh_dj_page()

    def _dj_remaining(self) -> int:
        if self._shuffle_active():
            return len(self._ensure_shuffle_plan())
        pos = self._context_position()
        return max(0, len(self._context) - pos - 1) if pos >= 0 else 0

    def refresh_dj_page(self):
        """Solo si la página está a la vista (si no, se pone al día al abrirla)."""
        page = self.page_dj
        if page is None or self.stacked_widget.currentWidget() is not page:
            return
        root = dj_service.get_root()
        source = self._dj_source()
        where = f"Carpeta: {os.path.basename(root) or root} · suena {self._dj_source_label(source)}"
        if self._dj_summary is None:
            where += " · leyendo la carpeta…"
        elif self._dj_summary.get("missing"):
            where += " · la carpeta ya no existe"
        else:
            total = len(dj_service.without_blocked(dj_service.tracks_for(self._dj_summary, source)))
            where += f" · {total} " + ("canción" if total == 1 else "canciones")
        page.set_source(where, len(dj_service.get_blocked()))
        if not self.dj_session_active():
            page.set_session(False)
            return
        upcoming = self.upcoming_tracks(UPCOMING_SHOWN)
        page.set_session(True, self.current_item_info, self.peek_next(), upcoming, self._dj_remaining())
        self.dj_tick(self.player.position())

    def dj_tick(self, position_ms: int):
        """Con cada avance de la canción: cuánto falta para que empiece la mezcla (solo si la página está a la vista)."""
        page = self.page_dj
        if page is None or not page.isVisible() or not self.dj_session_active():
            return
        duration = self.player.duration()
        if getattr(self, "_xf_active", False):
            text = "Mezclando con la siguiente…"
        elif self.player.playbackState() != QMediaPlayer.PlayingState:
            text = "En pausa"
        elif not self._dj_has_next:
            text = "Es la última canción de la sesión"
        elif self.is_loop_enabled:
            text = "Repetición activada: esta canción vuelve a empezar"
        elif self._fade_ms <= 0:
            text = "Sin fundido: la siguiente empieza al terminar esta"
        elif duration <= 0:
            text = ""
        elif duration <= self._fade_ms * 3:
            text = "Canción corta: la siguiente entra al terminar, sin mezcla"
        else:
            left = duration - position_ms - self._fade_ms
            text = f"La mezcla empieza en {self.format_time(left)}" if left > 0 else "Mezclando con la siguiente…"
        page.set_countdown(text)
