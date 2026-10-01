"""Ecualizador real: genera una copia temporal del audio con ffmpeg aplicando graves/medios/agudos."""
import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from config import APP_DATA_DIR, EQUALIZER_FILE, atomic_write_json
from services.ffmpeg_service import FFmpegService

logger = logging.getLogger(__name__)

EQ_CACHE_DIR = APP_DATA_DIR / "eq_cache"
MAX_SOURCE_MB = 150  # no se procesan archivos enormes (la copia temporal es WAV)

BAND_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
# Cuánto influye cada control (graves, medios, agudos) en cada banda
BAND_WEIGHTS = [
    (1, 0, 0), (1, 0, 0), (1, 0, 0), (0.6, 0.4, 0),
    (0, 1, 0), (0, 1, 0), (0, 0.5, 0.5),
    (0, 0, 1), (0, 0, 1), (0, 0, 1),
]

# nombre -> (graves, medios, agudos) en dB
PRESETS = {
    "Normal": (0, 0, 0),
    "Más graves": (7, 0, 0),
    "Más voces": (-2, 5, 2),
    "Más agudos": (0, 0, 6),
    "Rock": (4, -1, 4),
    "Pop": (1, 3, 2),
    "Acústico": (3, 1, 3),
    "Cine": (5, 0, 4),
    "Electrónica": (5, -1, 4),
    "Jazz": (3, 0, 3),
}

DEFAULT_SETTINGS = {"enabled": False, "preset": "Normal", "bass": 0, "mid": 0, "treble": 0}


def bands_from_tone(bass: float, mid: float, treble: float) -> list[float]:
    return [round(bass * wb + mid * wm + treble * wt, 1) for wb, wm, wt in BAND_WEIGHTS]


def load_eq_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    try:
        if EQUALIZER_FILE.exists():
            with open(EQUALIZER_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                if "bass" in saved:
                    data.update({k: saved[k] for k in DEFAULT_SETTINGS if k in saved})
                # compatibilidad con el formato antiguo de 10 bandas
                elif isinstance(saved.get("values"), list) and len(saved["values"]) == 10:
                    v = saved["values"]
                    data["bass"] = round(sum(v[0:3]) / 3)
                    data["mid"] = round(sum(v[4:7]) / 3)
                    data["treble"] = round(sum(v[7:10]) / 3)
                    data["enabled"] = bool(saved.get("enabled", False))
    except Exception as e:
        logger.warning(f"No se pudo leer el ecualizador: {e}")
    return data


def save_eq_settings(data: dict) -> None:
    try:
        atomic_write_json(EQUALIZER_FILE, {k: data.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS})
    except Exception as e:
        logger.warning(f"No se pudo guardar el ecualizador: {e}")


def active_bands(settings: dict) -> list[float] | None:
    """Bandas a aplicar, o None si el ecualizador está apagado o en 'Normal'."""
    if not settings.get("enabled"):
        return None
    bands = bands_from_tone(settings.get("bass", 0), settings.get("mid", 0), settings.get("treble", 0))
    return bands if any(abs(b) > 0.05 for b in bands) else None


def rendered_path_for(src: str, bands: list[float]) -> Path:
    try:
        mtime = os.path.getmtime(src)
    except OSError:
        mtime = 0
    key = hashlib.sha1(f"{os.path.abspath(src)}|{mtime}|{bands}".encode("utf-8")).hexdigest()[:20]
    return EQ_CACHE_DIR / f"{key}.wav"


def clean_cache(keep: str | None = None) -> None:
    try:
        if not EQ_CACHE_DIR.exists():
            return
        for f in EQ_CACHE_DIR.iterdir():
            if keep and str(f) == str(keep):
                continue
            try:
                f.unlink()
            except OSError:
                pass
    except Exception:
        pass


def build_filter(bands: list[float]) -> str:
    parts = [f"equalizer=f={freq}:width_type=o:w=1:g={gain}" for freq, gain in zip(BAND_FREQS, bands) if abs(gain) > 0.05]
    parts.append("alimiter=limit=0.95")
    return ",".join(parts)


class EqRenderWorker(QThread):
    """Genera la copia con ecualización en segundo plano."""
    done = Signal(str, str)    # (archivo original, archivo procesado)
    failed = Signal(str)

    def __init__(self, src: str, bands: list[float], parent=None):
        super().__init__(parent)
        self.src = src
        self.bands = bands
        self.is_cancelled = False

    def run(self):
        ffmpeg = FFmpegService.get_ffmpeg_path()
        if not ffmpeg:
            self.failed.emit("ffmpeg")
            return
        try:
            if os.path.getsize(self.src) > MAX_SOURCE_MB * 1024 * 1024:
                self.failed.emit("archivo demasiado grande")
                return
        except OSError as e:
            self.failed.emit(str(e))
            return

        EQ_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = rendered_path_for(self.src, self.bands)
        if out.exists():
            self.done.emit(self.src, str(out))
            return

        tmp = out.with_suffix(".part.wav")
        cmd = [ffmpeg, "-y", "-v", "error", "-i", self.src, "-vn", "-af", build_filter(self.bands),
               "-c:a", "pcm_s16le", str(tmp)]
        try:
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            proc = subprocess.run(cmd, capture_output=True, timeout=300, creationflags=flags)
            if proc.returncode != 0 or not tmp.exists():
                self.failed.emit(proc.stderr.decode("utf-8", "ignore")[:200])
                return
            os.replace(tmp, out)
        except Exception as e:
            self.failed.emit(str(e))
            return
        if not self.is_cancelled:
            self.done.emit(self.src, str(out))
