"""Modo DJ: menú de arriba a la izquierda (carpeta general y qué parte suena) y página DJ para llevar la sesión.

La sesión DJ ordena las canciones (`dj_planner`) y las mezcla con el fundido cruzado que ya existe (que iguala el
ritmo), empezando la mezcla donde dice el análisis de cada canción (`mix_points`, fase 8). Las mezclas por frases, el
cambio de graves y lo demás llegan por fases (ver docs/PLAN_DJ.md)."""
import os
import random

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QFileDialog, QMenu

from services import dj_planner, dj_service, key_detect, mix_points, tempo
from services.dj_service import ORDER_RANDOM, ORDER_SMART, SOURCE_ALL, SOURCE_ROOT, DjScanWorker
from services.mix_types import KIND_CUT
from services.track_analysis import AnalysisWorker
from ui.dialogs import ask_text
from ui.dj_page import DjPage, UPCOMING_SHOWN
from ui.icons import icon
from ui.pages import Page
from ui.playback_mixin import track_key

DJ_FADE_SECONDS = 8          # si el fundido está apagado, la sesión DJ lo enciende con esta duración
FIRST_SCAN_MS = 6000         # la carpeta se lee un poco después de abrir (así el menú ya la tiene)
MAX_MISSING_SKIPS = 50       # canciones borradas seguidas que se saltan antes de rendirse
REFRESH_DELAY_MS = 400       # mientras llegan muchos análisis seguidos, la página se pone al día como mucho así de a menudo


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
        self._dj_analysis = {}         # ruta → análisis (tempo, tono, energía, intro y final)
        self._dj_replan_pending = False  # la sesión empezó con canciones sin analizar: se reordena al terminar el análisis
        self._dj_an_worker = None
        self._dj_an_restart = False
        self._dj_an_progress = (0, 0)  # (analizadas, por analizar) en la tanda en marcha
        self._dj_mix = None            # (ruta de la que suena, su duración, (ruta de la siguiente, plan)) de la próxima mezcla
        self._dj_refresh_timer = QTimer()
        self._dj_refresh_timer.setSingleShot(True)
        self._dj_refresh_timer.setInterval(REFRESH_DELAY_MS)
        self._dj_refresh_timer.timeout.connect(self.refresh_dj_page)
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
        self.page_dj.bpm_requested.connect(self.dj_bpm)
        self.page_dj.vote_requested.connect(self.dj_vote)
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
        self._dj_start_analysis()
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
        self._dj_start_analysis()

    # ------------------------------------------------------------ análisis de las canciones
    def _dj_start_analysis(self):
        """Analiza (una vez por canción, en segundo plano) las canciones que van a sonar."""
        if self._dj_summary is None:
            return
        if self._dj_an_worker is not None:          # hay una tanda en marcha: para y empieza la nueva al terminar
            self._dj_an_restart = True
            self._dj_an_worker.cancel()
            return
        self._dj_an_restart = False
        self._dj_an_progress = (0, 0)
        paths = dj_service.without_blocked(dj_service.tracks_for(self._dj_summary, self._dj_source()))
        self._dj_reapply_overrides(paths)
        worker = AnalysisWorker(paths, self)
        worker.result.connect(self._on_dj_analysis)
        worker.progress.connect(self._on_dj_analysis_progress)
        worker.finished.connect(self._on_dj_analysis_done)
        self._dj_an_worker = worker
        worker.start()

    def _on_dj_analysis(self, path: str, result: dict):
        self._dj_analysis[path] = result
        mix = self._dj_mix
        if mix is not None and (path == mix[0] or (mix[2] is not None and path == mix[2][0])):
            self._dj_mix = None                    # llegó el análisis de una de las dos de la próxima mezcla
        self._dj_apply_bpm(path)                   # el fundido ya no tiene que calcularlo
        if self.dj_engine_on():
            self.dj_engine_analysis_arrived(path)   # el motor rehace la mezcla ya preparada con el análisis nuevo
        if not self._dj_refresh_timer.isActive():
            self._dj_refresh_timer.start()

    def _on_dj_analysis_progress(self, done: int, total: int):
        self._dj_an_progress = (done, total)
        if self.page_dj is not None:
            self.page_dj.set_progress(self._dj_progress_text())

    def _on_dj_analysis_done(self):
        worker, self._dj_an_worker = self._dj_an_worker, None
        if worker is not None:
            worker.deleteLater()
        if self._dj_an_restart:
            self._dj_start_analysis()
        else:
            self._dj_an_progress = (0, 0)
            if self.page_dj is not None:
                self.page_dj.set_progress("")
            if self._dj_replan_pending:
                self._dj_replan_pending = False
                self.dj_replan(auto=True)

    def _dj_progress_text(self) -> str:
        done, total = self._dj_an_progress
        if not total or done >= total:
            return ""
        return f"Analizando canciones (ritmo, tono, intro y final): {done} de {total}…"

    # ------------------------------------------------------------ corregir el BPM
    def _dj_effective_bpm(self, path: str) -> tuple:
        """(BPM, corregido_a_mano): el que se puso a mano si lo hay y, si no, el del análisis (o None)."""
        manual = dj_service.get_bpm_override(path)
        if manual:
            return manual, True
        return (self._dj_analysis.get(path) or {}).get("bpm"), False

    def _dj_apply_bpm(self, path: str):
        """El fundido usa el mismo tempo que se ve en la página."""
        bpm, _manual = self._dj_effective_bpm(path)
        if bpm is None and path not in self._dj_analysis:
            tempo.forget(path)                      # aún no hay nada decidido: que lo calcule el fundido, como siempre
        else:
            tempo.set_bpm(path, bpm)

    def _dj_reapply_overrides(self, paths: list):
        """Al abrir el programa, las correcciones a mano ya valen para el fundido (sin esperar al análisis)."""
        for path, bpm in dj_service.overrides_for(paths).items():
            tempo.set_bpm(path, bpm)

    @staticmethod
    def _bpm_text(bpm) -> str:
        """«95» o «92,5»: un decimal solo si hace falta (así «Guardar» sin tocar nada no cambia el valor)."""
        return f"{bpm:.1f}".rstrip("0").rstrip(".") if bpm else ""

    def _dj_title(self, path: str) -> str:
        for info in self._dj_context or []:
            if info.get("local_path") == path:
                return info.get("title") or os.path.basename(path)
        return os.path.splitext(os.path.basename(path))[0]

    def dj_bpm(self, path: str, action: str):
        """Corrige el tempo de una canción: «half» (÷2), «double» (×2), «set» (escribirlo) o «auto» (el calculado)."""
        if not path:
            return
        title = self._dj_title(path)
        current, _manual = self._dj_effective_bpm(path)
        if action == "auto":
            had_manual = dj_service.get_bpm_override(path) is not None
            dj_service.clear_bpm_override(path)
            message = (f"«{title}»: vuelve al ritmo automático." if had_manual
                       else f"«{title}»: ya usa el ritmo automático.")
        else:
            if action == "set":
                text, ok = ask_text(self, "BPM de la canción", f"Pulsos por minuto de «{title}»:",
                                    text=self._bpm_text(current), ok="Guardar", placeholder="Por ejemplo, 95")
                if not ok:
                    return
                bpm = dj_service.parse_bpm(text)
                if bpm is None:
                    self.notify(f"Escribe un número entre {int(dj_service.MIN_BPM_MANUAL)} y {int(dj_service.MAX_BPM_MANUAL)}.")
                    return
            elif not current:
                self.notify("Esta canción no tiene un ritmo claro: usa «Escribir BPM…».")
                return
            else:
                candidate = current / 2 if action == "half" else current * 2
                bpm = dj_service.parse_bpm(candidate)
                if bpm is None:
                    self.notify(f"«{title}»: {round(candidate)} BPM queda fuera de lo razonable "
                                f"(de {int(dj_service.MIN_BPM_MANUAL)} a {int(dj_service.MAX_BPM_MANUAL)}).")
                    return
            dj_service.set_bpm_override(path, bpm)
            message = f"«{title}»: {round(bpm)} BPM."
        self._dj_apply_bpm(path)
        self.refresh_dj_page()
        self.notify(message)

    def dj_describe(self, info: dict) -> str:
        """Texto corto con el análisis de una canción, o "" si aún no está."""
        path = (info or {}).get("local_path")
        found = self._dj_analysis.get(path)
        bpm, manual = self._dj_effective_bpm(path) if path else (None, False)
        if not found and not manual:
            return ""
        found = found or {}
        parts = [f"{round(bpm)} BPM" + (" (a mano)" if manual else "") if bpm else "sin pulso claro"]
        if found.get("tone"):                    # tono en la rueda Camelot; con «?» si no está claro (las etiquetas valen 1,0)
            parts.append(found["tone"] + ("" if (found.get("tone_conf") or 0) >= key_detect.CONFIDENT else "?"))
        if found.get("energy") is not None and found.get("loudness_db") is not None:
            parts.append(f"energía {1 + round(found['energy'] * 9)}")      # del 1 al 10
        if found.get("intro_ms"):
            parts.append(f"intro {self.format_time(found['intro_ms'])}")
        if found.get("outro_ms"):
            parts.append(f"final {self.format_time(found['outro_ms'])}")
        return " · ".join(parts)

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
        order_menu = menu.addMenu(icon("shuffle.svg"), "Orden de las canciones")
        order_group = QActionGroup(order_menu)
        for key, text in ((ORDER_SMART, "Inteligente (ritmo, tono, energía y género)"), (ORDER_RANDOM, "Aleatorio")):
            act = order_menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(key == self._dj_order())
            order_group.addAction(act)
            act.triggered.connect(lambda _=False, k=key: self.set_dj_order(k))
        engine_act = menu.addAction("Mezclar con el motor propio (graves, frases y ritmo)")
        engine_act.setCheckable(True)
        engine_act.setChecked(self.dj_engine_wanted())
        engine_act.toggled.connect(self.set_dj_engine_wanted)
        why_not = self.dj_engine_unavailable_reason()
        if why_not:
            menu.addAction(f"No disponible: {why_not}").setEnabled(False)
        menu.addSeparator()
        start = menu.addAction(icon("play.svg"), "Empezar a pinchar")
        start.triggered.connect(self.start_dj_session)
        start.setEnabled(summary is None or bool(dj_service.tracks_for(summary, source)))
        menu.addAction(icon("sliders.svg"), "Abrir la página DJ").triggered.connect(self.open_dj_page)
        if self.dj_recording():
            menu.addAction("Cancelar la grabación del mix").triggered.connect(self.dj_record_cancel)
        else:
            record = menu.addAction("Grabar lo que queda de la sesión en un archivo…")
            record.triggered.connect(self.dj_record_ask)
            record.setEnabled(self.dj_session_active())
        menu.addAction("Sesión de votos (escuchar mezclas y votar)…").triggered.connect(self.open_vote_session)
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
        tracks = [self._local_track_info(p, {}) for p in paths]   # sin leer etiquetas aquí: se leen al sonar cada una
        smart = self._dj_order() == ORDER_SMART
        if smart:
            tracks = self._dj_plan(tracks, None, 0, len(tracks))
        skipped = 0
        while tracks and skipped < MAX_MISSING_SKIPS and not os.path.isfile(tracks[0]["local_path"]):   # borradas desde que se leyó
            tracks.pop(0)
            skipped += 1
        if not tracks or not os.path.isfile(tracks[0]["local_path"]):
            self.notify("No hay canciones en esa carpeta (mp3, mp4, m4a, wav, flac, ogg o wma)."
                        if not skipped else "Las canciones de esa carpeta han cambiado: pulsa «Volver a leer la carpeta».")
            return
        self.set_context(tracks)
        self._dj_context = self._context
        self._dj_in_session = True
        self._dj_last_key = None
        notes = ""
        if smart:
            # solo se promete afinarlo si hay un análisis en marcha que pueda traer lo que falta
            self._dj_replan_pending = (self._dj_an_worker is not None
                                       and any(info["local_path"] not in self._dj_analysis for info in tracks))
            notes += " Orden inteligente" + (" (se afinará al terminar el análisis)." if self._dj_replan_pending else ".")
            if getattr(self, "is_shuffle_enabled", False):       # el aleatorio del reproductor desharía el orden
                self.toggle_shuffle()
                notes += " Se ha desactivado el aleatorio del reproductor."
        if self._fade_ms <= 0:
            self.set_fade_seconds(DJ_FADE_SECONDS)
            notes += f" Se ha activado el fundido de {DJ_FADE_SECONDS} s."
        if self.dj_engine_enter():
            notes += " Mezcla con el motor propio."
        self._play_entry(tracks[0], crossfade_ms=self.crossfade_ms())
        self.open_dj_page()
        self.notify(f"Modo DJ: {len(tracks)} canciones de {self._dj_source_label(source)}.{notes}")

    def dj_track_changed(self):
        """Cambió la canción que suena: ¿sigue siendo de la sesión DJ?, la siguiente existe todavía y la página al día."""
        if self._dj_context is None or self._context is not self._dj_context or not self.current_item_info:
            self._dj_in_session = False
            self.dj_engine_leave()                  # fuera de la sesión suena el reproductor de siempre
        else:
            self._dj_in_session = True
            key = track_key(self.current_item_info)
            if self._context_position() < 0:
                # suena algo de fuera (de la cola o «Reproducir» en otra lista): entra en la sesión justo después de la
                # última que sonó, para que al terminar siga la sesión en vez de cortarse
                at = next((i for i, t in enumerate(self._dj_context) if track_key(t) == self._dj_last_key), -1)
                self._dj_context.insert(at + 1, dict(self.current_item_info))
            self._dj_last_key = key
            self.dj_mix_happened(self.current_item_info.get("local_path"))
            self._dj_prune_next()
        self._dj_mix = None
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
        """Orden nuevo para lo que queda por sonar (lo que ya sonó y lo que suena se quedan como están)."""
        if not self.dj_session_active():
            return
        pos = self._context_position()
        if pos < 0:
            return
        if self._dj_order() == ORDER_SMART:
            self.dj_replan()
            return
        rest = self._dj_context[pos + 1:]
        random.shuffle(rest)
        self._dj_context[pos + 1:] = rest
        self.reset_shuffle()
        self.dj_queue_changed()
        self.notify("Orden nuevo para lo que queda.")

    # ------------------------------------------------------------ orden inteligente
    def _dj_order(self) -> str:
        return dj_service.get_order()

    def set_dj_order(self, order: str):
        if order == self._dj_order():
            return
        dj_service.set_order(order)
        if self.dj_session_active():
            self.dj_reshuffle()                 # con el modo nuevo: inteligente o aleatorio
        else:
            self.refresh_dj_page()

    def _dj_track(self, info: dict):
        """Los datos de una canción con los que decide el planificador (lo que se sepa de su análisis)."""
        path = info.get("local_path")
        found = self._dj_analysis.get(path) or {}
        bpm, _manual = self._dj_effective_bpm(path) if path else (None, False)
        energy = found.get("energy") if found.get("loudness_db") is not None else None
        return dj_planner.Track(info, bpm, found.get("tone") or None, found.get("tone_conf") or 0.0, energy,
                                found.get("genre") or "", found.get("artist") or "")

    def _dj_plan(self, infos: list, previous, start_index: int, total: int) -> list:
        """`infos` en el orden en que conviene que suenen (ver `dj_planner`)."""
        ordered = dj_planner.plan([self._dj_track(i) for i in infos], self._dj_track(previous) if previous else None,
                                  start_index, total)
        return [track.ref for track in ordered]

    def dj_replan(self, auto: bool = False) -> bool:
        """Vuelve a ordenar lo que queda por sonar con lo que se sabe ahora de las canciones. `auto`: lo hace el programa al
        terminar el análisis, no el usuario. Devuelve si reordenó algo."""
        if not self.dj_session_active() or self._dj_order() != ORDER_SMART:
            return False
        pos = self._context_position()
        context = self._dj_context
        if pos < 0 or len(context) - pos - 1 < 2:
            if not auto:
                self.notify("No quedan canciones suficientes para reordenar.")
            return False
        context[pos + 1:] = self._dj_plan(context[pos + 1:], context[pos], pos + 1, len(context))
        self.reset_shuffle()
        if not auto and self._dj_an_worker is not None:      # con el análisis a medias: se afina otra vez cuando termine
            self._dj_replan_pending = True
        self.dj_queue_changed()
        self.notify("Orden inteligente listo con el análisis completo." if auto else "Orden nuevo para lo que queda.")
        return True

    def dj_unblock_all(self):
        dj_service.unblock_all()
        self.refresh_dj_page()
        self._dj_start_analysis()          # las desbloqueadas también se analizan
        self.notify("Todas las canciones vuelven a poder sonar en el modo DJ.")

    def dj_queue_changed(self):
        """Cambió lo que viene (cola, aleatorio, botones del DJ): la siguiente y la página se ponen al día."""
        self._dj_mix = None
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
        order = "aleatorio"
        if self._dj_order() == ORDER_SMART:
            order = ("inteligente (anulado: el aleatorio del reproductor está activado)"
                     if getattr(self, "is_shuffle_enabled", False) else "inteligente")
        where = f"Carpeta: {os.path.basename(root) or root} · suena {self._dj_source_label(source)} · orden {order}"
        if self._dj_summary is None:
            where += " · leyendo la carpeta…"
        elif self._dj_summary.get("missing"):
            where += " · la carpeta ya no existe"
        else:
            total = len(dj_service.without_blocked(dj_service.tracks_for(self._dj_summary, source)))
            where += f" · {total} " + ("canción" if total == 1 else "canciones")
        page.set_source(where, len(dj_service.get_blocked()))
        page.set_progress(self._dj_progress_text())
        if not self.dj_session_active():
            page.set_session(False)
            return
        upcoming = self.upcoming_tracks(UPCOMING_SHOWN)
        page.set_session(True, self.current_item_info, self.peek_next(), upcoming, self._dj_remaining(), self.dj_describe)
        page.set_vote_target(self.dj_vote_text())
        self.dj_tick()

    # ------------------------------------------------------------ punto de mezcla (fase 8)
    def dj_mix_plan(self):
        """(ruta de la siguiente, `TransitionPlan`) de la mezcla de la que suena con la siguiente, con el punto que sale
        de su análisis (`mix_points`), o None si no hay sesión DJ, la que suena aún no está analizada o no hay siguiente
        en el equipo: entonces vale el fundido fijo de los Ajustes, como fuera del modo DJ.

        Se calcula una vez por canción (y otra si cambia lo que viene o llega el análisis de alguna de las dos), porque
        se consulta con cada avance de la canción y `peek_next` recorre la sesión entera."""
        if not self.dj_session_active():
            return None
        a_path = self.current_item_info.get("local_path")
        duration = int(self.player.duration())
        mix = self._dj_mix
        if mix is not None and mix[0] == a_path and mix[1] == duration:
            return mix[2]
        result = None
        found = self._dj_analysis.get(a_path) if a_path else None
        if found:
            b_path = (self.peek_next() or {}).get("local_path")
            if b_path and os.path.isfile(b_path):
                plan = mix_points.plan(found, self._dj_analysis.get(b_path), duration / 1000.0 if duration > 0 else None)
                result = (b_path, plan)
                self.dj_note_mix(a_path, b_path, plan)
        self._dj_mix = (a_path, duration, result)
        return result

    def _dj_current_mix(self):
        """La mezcla que se va a oír: la que prepara el motor propio si está activo, o la del fundido de siempre."""
        if self.dj_engine_on():
            plan = self.dj_engine_plan()
            return None if plan is None else (None, plan)
        return self.dj_mix_plan()

    def dj_forget_mix(self):
        """La próxima mezcla se vuelve a planificar en la siguiente consulta."""
        self._dj_mix = None

    def dj_tick(self, position_ms: int = None):
        """Con cada avance de la canción: cuánto falta para que empiece la mezcla (solo si la página está a la vista).
        Sin `position_ms` se lee del reproductor, pero solo cuando hace falta (no en cada cambio de estado)."""
        page = self.page_dj
        if page is None or not page.isVisible() or not self.dj_session_active():
            return
        if position_ms is None:
            position_ms = self.player.position()
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
        elif (mix := self._dj_current_mix()) is not None:      # punto de mezcla según el análisis (el mismo del fundido)
            plan = mix[1]
            if plan.kind == KIND_CUT:
                text = (plan.reason[:1].upper() + plan.reason[1:]) if self.dj_engine_on() and plan.reason else \
                    "Canción corta: la siguiente entra al terminar, sin mezcla"
            else:
                left = int(plan.a_start_s * 1000) - position_ms
                text = (f"La mezcla empieza en {self.format_time(left)} · dura {round(plan.length_s)} s" if left > 0
                        else "Mezclando con la siguiente…")
        elif duration <= self._fade_ms * 3:
            text = "Canción corta: la siguiente entra al terminar, sin mezcla"
        else:
            left = duration - position_ms - self._fade_ms
            text = f"La mezcla empieza en {self.format_time(left)}" if left > 0 else "Mezclando con la siguiente…"
        page.set_countdown(text)
        page.set_vote_target(self.dj_vote_text())          # al empezar la mezcla se vota esa y no la anterior
