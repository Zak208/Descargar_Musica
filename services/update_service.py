"""Actualizaciones: del motor de descargas (yt-dlp) y aviso de versiones nuevas de la aplicación.

Todo sale de GitHub (peticiones públicas, sin cuenta). Solo se consulta una vez cada 24 horas y solo con conexión."""
import hashlib
import logging
import os
import tempfile
import time

from PySide6.QtCore import QThread, Signal

from config import load_settings, save_settings
from services import http, network_service, ytdlp_loader
from version import __version__

logger = logging.getLogger(__name__)

YTDLP_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
YTDLP_ASSET = "https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/yt-dlp"
YTDLP_SUMS = "https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/SHA2-256SUMS"
APP_API = "https://api.github.com/repos/Zak208/Descargar_Musica/releases/latest"
APP_TAGS = "https://api.github.com/repos/Zak208/Descargar_Musica/tags"
APP_PAGE = "https://github.com/Zak208/Descargar_Musica/releases"
CHECK_EVERY = 24 * 3600


def due(setting_key: str) -> bool:
    """¿Toca volver a consultar? (una vez cada 24 horas)."""
    return time.time() - float(load_settings().get(setting_key, 0) or 0) > CHECK_EVERY


def mark_checked(setting_key: str) -> None:
    settings = load_settings()
    settings[setting_key] = time.time()
    save_settings(settings)


def latest_ytdlp_tag() -> str | None:
    r = http.get(YTDLP_API, headers={"Accept": "application/vnd.github+json"}, timeout=10)
    if r.status_code != 200:
        return None
    return (r.json().get("tag_name") or "").strip() or None


def latest_app_version() -> str | None:
    """Versión más reciente publicada de la aplicación (sin la «v»)."""
    r = http.get(APP_API, headers={"Accept": "application/vnd.github+json"}, timeout=10)
    if r.status_code == 200:
        tag = (r.json().get("tag_name") or "").strip()
        if tag:
            return tag.lstrip("vV")
    r = http.get(APP_TAGS, headers={"Accept": "application/vnd.github+json"}, timeout=10)
    if r.status_code == 200:
        tags = [t.get("name", "") for t in r.json() if isinstance(t, dict)]
        tags = [t.lstrip("vV") for t in tags if t]
        if tags:
            return max(tags, key=ytdlp_loader.parse_version)
    return None


def app_update_available() -> str | None:
    latest = latest_app_version()
    if latest and ytdlp_loader.parse_version(latest) > ytdlp_loader.parse_version(__version__):
        return latest
    return None


class UpdateCheckWorker(QThread):
    """Mira si hay versión nueva de la aplicación y del motor de descargas. `result(app, ytdlp)`: las versiones nuevas
    (o cadena vacía)."""
    result = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        self.setPriority(QThread.LowPriority)
        app_new = ytdlp_new = ""
        if not network_service.is_online():
            self.result.emit("", "")
            return
        try:
            app_new = app_update_available() or ""
        except Exception as e:
            logger.info(f"No se pudo mirar si hay versión nueva: {e}")
        try:
            tag = latest_ytdlp_tag()
            if tag and ytdlp_loader.parse_version(tag) > ytdlp_loader.parse_version(ytdlp_loader.active_version()):
                ytdlp_new = tag
        except Exception as e:
            logger.info(f"No se pudo mirar la versión del motor de descargas: {e}")
        self.result.emit(app_new, ytdlp_new)


class YtdlpUpdateWorker(QThread):
    """Descarga el yt-dlp nuevo, comprueba su huella SHA-256 y lo deja listo para usarse."""
    progress = Signal(int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, tag: str, parent=None):
        super().__init__(parent)
        self.tag = tag

    def run(self):
        tmp_path = None
        try:
            sums = http.get(YTDLP_SUMS.format(tag=self.tag), timeout=15)
            sums.raise_for_status()
            expected = None
            for line in sums.text.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].lstrip("*") == "yt-dlp":
                    expected = parts[0].lower()
            if not expected:
                raise RuntimeError("No se pudo comprobar la huella de la descarga.")
            ytdlp_loader.UPDATE_DIR.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=str(ytdlp_loader.UPDATE_DIR), suffix=".part")
            sha = hashlib.sha256()
            with http.get(YTDLP_ASSET.format(tag=self.tag), stream=True, timeout=30) as r, os.fdopen(fd, "wb") as f:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0)) or 1
                done = 0
                for chunk in r.iter_content(chunk_size=128 * 1024):
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    self.progress.emit(int(100 * done / total))
            if sha.hexdigest() != expected:
                raise RuntimeError("La descarga llegó dañada. Inténtalo de nuevo.")
            os.replace(tmp_path, ytdlp_loader.UPDATED)
            tmp_path = None
            version = ytdlp_loader.updated_version()
            if not version:
                ytdlp_loader.remove_updated()
                raise RuntimeError("El archivo descargado no es válido.")
            self.done.emit(version)
        except Exception as e:
            logger.warning(f"No se pudo actualizar yt-dlp: {e}")
            self.failed.emit(str(e) or "No se pudo descargar.")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
