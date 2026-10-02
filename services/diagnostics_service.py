"""Informe de problemas (sin datos privados) y reparación de cachés."""
import getpass
import logging
import os
import platform
import re
import sys

from config import APP_DATA_DIR, load_settings
from services import storage_service
from version import __version__

LOG_FILE = APP_DATA_DIR / "app_descargas.log"


def _scrub(text: str) -> str:
    """Quita nombre de usuario y rutas personales del texto."""
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    home = os.path.expanduser("~")
    if home:
        text = text.replace(home, "~").replace(home.replace("\\", "/"), "~")
    if user and len(user) > 2:
        text = re.sub(re.escape(user), "usuario", text, flags=re.IGNORECASE)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<correo>", text)
    text = re.sub(r"https?://\S+", "<enlace>", text)
    text = re.sub(r"\([^()\n]{3,80} - [^()\n]{2,80}\)", "(<canción>)", text)     # «Intento fallido (Artista - Título)»
    return text


def _last_log_lines(n: int = 40) -> str:
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-400:]
    except OSError:
        return "(sin registro)"
    important = [ln for ln in lines if any(k in ln for k in ("ERROR", "CRITICAL", "WARNING", "Traceback"))]
    chosen = (important or lines)[-n:]
    return _scrub("".join(chosen)).strip() or "(sin registro)"


def build_report() -> str:
    from PySide6 import __version__ as pyside_version
    settings = load_settings()
    safe = {k: v for k, v in settings.items()
            if k in ("quality", "theme", "eco_mode", "parallel_downloads", "offline_mode") and not isinstance(v, (dict, list))}
    try:
        import yt_dlp
        ytdlp = yt_dlp.version.__version__
    except Exception:
        ytdlp = "?"
    parts = [
        f"Descargador de Música {__version__}",
        f"Windows: {platform.platform()}",
        f"Python {sys.version.split()[0]} · PySide6 {pyside_version} · yt-dlp {ytdlp}",
        f"Ajustes: {safe}",
        "Espacio: " + ", ".join(f"{r['name']} {storage_service.format_bytes(r['bytes'])}"
                                for r in storage_service.usage()[:5]),
        "",
        "Últimos avisos del registro:",
        _last_log_lines(),
    ]
    return "\n".join(parts)


def repair_caches() -> int:
    """Borra las cachés que se reconstruyen solas (imágenes, copias del ecualizador, biblioteca y recomendaciones).
    Devuelve los bytes liberados. No toca listas, favoritos, ajustes ni letras."""
    freed = 0
    for key in ("imagenes", "ecualizador", "biblioteca", "recomendaciones"):
        freed += storage_service.clear(key)
    logging.info(f"Reparación de cachés: {freed} bytes liberados")
    return freed
