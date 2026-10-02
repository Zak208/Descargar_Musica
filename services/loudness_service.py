"""Igualar el volumen entre canciones: se mide una sola vez cuánto «suena de fuerte» cada canción (LUFS, con FFmpeg)
y se guarda; al reproducirla se baja un poco el volumen de las que suenan más fuerte que la media. No se reprocesa
el audio: es solo un ajuste de volumen del reproductor."""
import logging
import os
import re
import subprocess

from PySide6.QtCore import QThread, Signal

from services import library_db
from services.ffmpeg_service import FFmpegService

logger = logging.getLogger(__name__)

TARGET_LUFS = -14.0       # el mismo nivel de referencia que usan los servicios de streaming
MAX_CUT_DB = 12.0         # nunca se baja más de 12 dB
_INTEGRATED = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")


def gain_for(lufs: float | None) -> float:
    """Factor de volumen (0-1) que iguala la canción al nivel de referencia. Solo se baja: las suaves no se suben."""
    if lufs is None:
        return 1.0
    cut_db = min(0.0, TARGET_LUFS - lufs)
    cut_db = max(-MAX_CUT_DB, cut_db)
    return 10 ** (cut_db / 20.0)


def parse_integrated(stderr_text: str) -> float | None:
    """Última lectura «I: -9.3 LUFS» del resumen de FFmpeg (ebur128)."""
    found = _INTEGRATED.findall(stderr_text or "")
    return float(found[-1]) if found else None


def measure(path: str, timeout: int = 180) -> float | None:
    ffmpeg = FFmpegService.get_ffmpeg_path()
    if not ffmpeg or not os.path.isfile(path):
        return None
    try:
        proc = subprocess.run([ffmpeg, "-nostats", "-hide_banner", "-i", path, "-vn", "-af", "ebur128", "-f", "null", "-"],
                              capture_output=True, timeout=timeout)
    except Exception as e:
        logger.warning(f"No se pudo medir el volumen de {path}: {e}")
        return None
    return parse_integrated(proc.stderr.decode("utf-8", "ignore"))


def stored(path: str) -> float | None:
    """Volumen ya medido (si el archivo no cambió desde entonces)."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    return library_db.get_loudness(path, mtime)


class LoudnessWorker(QThread):
    """Mide una canción en segundo plano (de una en una y con prioridad baja) y avisa con el resultado."""
    done = Signal(str, float)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        from services.heavy import heavy_task
        self.setPriority(QThread.LowPriority)
        with heavy_task():
            known = stored(self.path)
            if known is not None:
                self.done.emit(self.path, known)
                return
            lufs = measure(self.path)
        if lufs is not None:
            try:
                library_db.set_loudness(self.path, os.path.getmtime(self.path), lufs)
            except OSError:
                pass
            self.done.emit(self.path, lufs)
