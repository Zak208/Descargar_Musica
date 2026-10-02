"""Carga de yt-dlp (el motor que busca y descarga) y su actualización.

* Se importa solo cuando hace falta la primera vez (ahorra memoria y CPU al abrir la aplicación).
* YouTube cambia a menudo y rompe las descargas: por eso el motor se puede actualizar desde la propia aplicación sin
  esperar a una versión nueva del programa. La versión descargada se guarda en la carpeta de datos y, si es más
  reciente que la incluida, tiene prioridad.
"""
import logging
import os
import re
import sys
import zipfile

from config import APP_DATA_DIR

logger = logging.getLogger(__name__)

UPDATE_DIR = APP_DATA_DIR / "yt_dlp"
UPDATED = UPDATE_DIR / "yt-dlp"           # el yt-dlp oficial de GitHub (un único archivo .zip ejecutable)
_module = None


def parse_version(text: str) -> tuple:
    """«2026.08.19» → (2026, 8, 19) para poder compararlas."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4])


def updated_version() -> str | None:
    """Versión del yt-dlp descargado (si hay), leída de dentro del archivo."""
    try:
        with zipfile.ZipFile(UPDATED) as z:
            text = z.read("yt_dlp/version.py").decode("utf-8", "ignore")
        m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
        return m.group(1) if m else None
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def bundled_version() -> str:
    """Versión del yt-dlp que viene con el programa (sin importarlo)."""
    from version import BUNDLED_YTDLP
    return BUNDLED_YTDLP


def get():
    """El módulo yt_dlp (importándolo la primera vez, y usando el actualizado si es más reciente)."""
    global _module
    if _module is None:
        newer = updated_version()
        if newer and parse_version(newer) > parse_version(bundled_version()) and str(UPDATED) not in sys.path:
            sys.path.insert(0, str(UPDATED))
        import yt_dlp
        _module = yt_dlp
    return _module


def active_version() -> str:
    """Versión que se está usando (o se usará) ahora mismo."""
    if _module is not None:
        return _module.version.__version__
    newer = updated_version()
    if newer and parse_version(newer) > parse_version(bundled_version()):
        return newer
    return bundled_version()


def is_loaded() -> bool:
    return _module is not None


def remove_updated() -> None:
    try:
        os.remove(UPDATED)
    except OSError:
        pass
