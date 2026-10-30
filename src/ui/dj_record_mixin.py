"""Modo DJ: grabar la sesión en un archivo de audio (fase 17). Lo que queda por sonar de la sesión (desde la canción de ahora, en su
orden) se renderiza fuera de línea con la misma sesión del motor que toca en directo (`services/mix_recorder.py`) y se guarda como
mp3, wav, flac o m4a, con un listado de canciones y tiempos (.txt y .cue) al lado. Va en un hilo aparte y se puede cancelar."""
import logging
import os
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFileDialog

from services import mix_recorder

logger = logging.getLogger(__name__)

MAX_RECORDED_TRACKS = 80         # una grabación no pasa de tantas canciones (unas 5 horas)


class MixRecordWorker(QThread):
    """Renderiza la lista de canciones en segundo plano."""
    progress = Signal(int, int, float)       # (canción por la que va, total, segundos de mix hechos)
    done = Signal(dict)                      # resultado de `mix_recorder.render_session`
    failed = Signal(str)

    def __init__(self, paths: list, info_for, out_path: str, parent=None):
        super().__init__(parent)
        self.paths, self.info_for, self.out_path = list(paths), info_for, out_path
        self._cancel = False

    def cancel(self):
        self._cancel = True
        self.requestInterruption()

    def run(self):
        self.setPriority(QThread.LowPriority)
        try:
            result = mix_recorder.render_session(self.paths, self.info_for, self.out_path,
                                                 progress=lambda i, n, s: self.progress.emit(int(i), int(n), float(s)),
                                                 cancel=lambda: self._cancel)
        except Exception as e:                # FFmpeg ausente, disco lleno, ruta inválida...
            logger.warning(f"No se pudo grabar el mix: {e}")
            self.failed.emit(str(e))
            return
        self.done.emit(result)


class DjRecordMixin:
    """Mezcla para MainWindow. Requiere: _dj_context, _context_position(), _dj_engine_info(), page_dj, notify(), dj_session_active()."""

    def init_dj_record_state(self):
        self._dj_recorder = None

    def dj_recording(self) -> bool:
        return self._dj_recorder is not None and self._dj_recorder.isRunning()

    def dj_record_tracks(self) -> list:
        """Las rutas que se grabarían: la canción de ahora y lo que queda de la sesión, en orden y solo las que existen."""
        ctx = self._dj_context or []
        pos = max(0, self._context_position())
        paths = [t.get("local_path") for t in ctx[pos:pos + MAX_RECORDED_TRACKS]]
        return [p for p in paths if p and os.path.isfile(p)]

    def dj_record_ask(self):
        """Pregunta dónde guardar y empieza a grabar."""
        if self.dj_recording():
            self.notify("Ya se está grabando un mix.")
            return
        if not self.dj_session_active() or not self.dj_record_tracks():
            self.notify("Empieza una sesión DJ para poder grabarla.")
            return
        exts = " ".join(f"*{e}" for e in mix_recorder.supported_extensions())
        stamp = time.strftime("%Y-%m-%d_%H-%M")
        path, _ = QFileDialog.getSaveFileName(self, "Grabar la sesión DJ", os.path.join(os.path.expanduser("~"), "Music", f"Mix DJ {stamp}.mp3"),
                                              f"Audio ({exts})")
        if path:
            self.dj_record_session(path)

    def dj_record_session(self, out_path: str) -> bool:
        """Empieza a grabar lo que queda de la sesión en `out_path`. False si no se pudo empezar."""
        if self.dj_recording():
            return False
        if os.path.splitext(out_path)[1].lower() not in mix_recorder.supported_extensions():
            self.notify("Formato no admitido: usa mp3, wav, flac o m4a.")
            return False
        paths = self.dj_record_tracks()
        if not paths:
            self.notify("No hay canciones que grabar.")
            return False
        worker = MixRecordWorker(paths, self._dj_engine_info, out_path, self)
        worker.progress.connect(self._on_dj_record_progress)
        worker.done.connect(self._on_dj_record_done)
        worker.failed.connect(self._on_dj_record_failed)
        worker.finished.connect(self._on_dj_record_finished)
        self._dj_recorder = worker
        self._dj_record_total = len(paths)
        self.notify(f"Grabando {len(paths)} canciones en segundo plano…")
        worker.start()
        return True

    def dj_record_cancel(self):
        if self.dj_recording():
            self._dj_recorder.cancel()
            self.notify("Cancelando la grabación…")

    def dj_record_shutdown(self):
        """Al cerrar la aplicación: se cancela la grabación en marcha y se espera un momento a que termine (sin dejar archivos a medias)."""
        if self.dj_recording():
            self._dj_recorder.cancel()
            self._dj_recorder.wait(8000)

    def _on_dj_record_progress(self, index: int, total: int, seconds: float):
        if self.page_dj is not None:
            self.page_dj.set_progress(f"Grabando el mix: canción {index} de {total} · {int(seconds // 60)} min {int(seconds % 60):02d} s")

    def _on_dj_record_done(self, result: dict):
        if result.get("cancelled") or not result.get("out_path"):
            self.notify("Grabación cancelada: no se guardó nada.")
            return
        out = result["out_path"]
        base = os.path.splitext(out)[0]
        try:
            mix_recorder.write_tracklist(result, base + ".txt")
            mix_recorder.write_cue(result, base + ".cue")
        except Exception as e:
            logger.warning(f"No se pudo escribir el listado del mix: {e}")
        minutes = result.get("duration_s", 0) / 60
        warn = " Ojo: el volumen pasó de 0 dB en algún momento y se recortó al guardar." if result.get("peak", 0) > 1.0 else ""
        self.notify(f"Mix guardado: {os.path.basename(out)} ({minutes:.1f} min, {len(result.get('tracklist', []))} canciones).{warn}")

    def _on_dj_record_failed(self, message: str):
        self.notify(f"No se pudo grabar el mix: {message}")

    def _on_dj_record_finished(self):
        worker, self._dj_recorder = self._dj_recorder, None
        if worker is not None:
            worker.deleteLater()
        if self.page_dj is not None:
            self.page_dj.set_progress(self._dj_progress_text())       # vuelve el texto del análisis, si hay
