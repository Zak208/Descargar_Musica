"""Envolvente de cada canción para el visualizador: cuánto suenan los graves, los medios y los agudos cada 0,1 s.

Se calcula UNA vez por canción (en segundo plano, con prioridad baja y de una en una, con FFmpeg) y se guarda en el
índice de tu música (unos 7 KB por canción). Al reproducir solo se lee `datos[posición // 100]`: las barras siguen la
música de verdad sin analizar el audio en vivo, así que reproducir no gasta nada de más."""
import logging
import os
import re
import subprocess
import tempfile

from PySide6.QtCore import QThread, Signal

from services import library_db
from services.ffmpeg_service import FFmpegService

logger = logging.getLogger(__name__)

STEP_MS = 100                      # una lectura cada 100 ms
BANDS = 3                          # graves, medios y agudos
VERSION = 1
_RMS = re.compile(r"RMS_level=(-?\d+(?:\.\d+)?|-inf)")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS envelope (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    version INTEGER NOT NULL,
    data BLOB NOT NULL
)
"""

FILTER = (
    "[0:a]aresample=8000,asplit=3[a][b][c];"
    "[a]lowpass=f=250,asetnsamples=n=800:p=0,astats=metadata=1:reset=1,"
    "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=low.txt[o1];"
    "[b]highpass=f=250,lowpass=f=2000,asetnsamples=n=800:p=0,astats=metadata=1:reset=1,"
    "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=mid.txt[o2];"
    "[c]highpass=f=2000,asetnsamples=n=800:p=0,astats=metadata=1:reset=1,"
    "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=high.txt[o3]"
)


def parse_levels(text: str) -> list:
    """Niveles en dB (la lista de lecturas) del archivo que escribe FFmpeg."""
    out = []
    for raw in _RMS.findall(text or ""):
        out.append(-90.0 if raw == "-inf" else float(raw))
    return out


def normalize(levels: list) -> list:
    """Cada banda se ajusta a su propio rango (así hasta una canción suave se mueve): 0 a 255."""
    if not levels:
        return []
    ordered = sorted(levels)
    lo = ordered[int(len(ordered) * 0.10)]
    hi = ordered[min(len(ordered) - 1, int(len(ordered) * 0.97))]
    span = max(6.0, hi - lo)
    return [int(max(0.0, min(1.0, (v - lo) / span)) * 255) for v in levels]


def pack(bands: list) -> bytes:
    """Une las bandas (listas de 0-255) en un solo bloque: graves, medios y agudos de cada instante seguidos."""
    n = min((len(b) for b in bands), default=0)
    return bytes(bands[k][i] for i in range(n) for k in range(len(bands)))


def level_at(data: bytes, position_ms: int):
    """(graves, medios, agudos) en 0..1 en ese instante, o None si no hay datos."""
    if not data:
        return None
    i = max(0, int(position_ms) // STEP_MS) * BANDS
    if i + BANDS > len(data):
        return None
    return data[i] / 255.0, data[i + 1] / 255.0, data[i + 2] / 255.0


def compute(path: str, timeout: int = 240):
    """Calcula la envolvente de una canción (bloque de bytes) o None si no se pudo."""
    ffmpeg = FFmpegService.get_ffmpeg_path()
    if not ffmpeg or not os.path.isfile(path):
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="envolvente_", ignore_cleanup_errors=True) as tmp:
            cmd = [ffmpeg, "-nostats", "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-filter_complex", FILTER,
                   "-map", "[o1]", "-map", "[o2]", "-map", "[o3]", "-f", "null", "-"]
            subprocess.run(cmd, cwd=tmp, capture_output=True, timeout=timeout)
            bands = []
            for name in ("low.txt", "mid.txt", "high.txt"):
                file = os.path.join(tmp, name)
                if not os.path.isfile(file):
                    return None
                with open(file, "r", encoding="utf-8", errors="ignore") as f:
                    bands.append(normalize(parse_levels(f.read())))
        return pack(bands) or None
    except Exception as e:
        logger.warning(f"No se pudo calcular la envolvente de {path}: {e}")
        return None


def stored(path: str):
    """Envolvente ya guardada (si el archivo no cambió), o None."""
    try:
        mtime = os.path.getmtime(path)
        with library_db.connect() as con:
            con.execute(_SCHEMA)
            row = con.execute("SELECT mtime, version, data FROM envelope WHERE path=?", (path,)).fetchone()
        if row and abs(row["mtime"] - mtime) < 1 and row["version"] == VERSION:
            return bytes(row["data"])
    except Exception:
        pass
    return None


def save(path: str, data: bytes) -> None:
    try:
        with library_db.connect() as con:
            con.execute(_SCHEMA)
            con.execute("INSERT INTO envelope(path, mtime, version, data) VALUES (?,?,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, version=excluded.version, data=excluded.data",
                        (path, os.path.getmtime(path), VERSION, data))
    except Exception as e:
        logger.warning(f"No se pudo guardar la envolvente: {e}")


class EnvelopeWorker(QThread):
    """Calcula la envolvente en segundo plano (de una en una y con prioridad baja)."""
    done = Signal(str, bytes)

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
            data = compute(self.path)
        if data:
            save(self.path, data)
            self.done.emit(self.path, data)
