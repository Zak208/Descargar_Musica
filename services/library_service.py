"""Biblioteca de música local: búsqueda de archivos, lectura de etiquetas con caché y vigilancia de la carpeta.

Para gastar poca memoria y CPU:
  * las etiquetas (título, artista, álbum, duración) se leen una sola vez por archivo y se guardan en un JSON;
  * solo se vuelven a leer los archivos nuevos o modificados;
  * se vigila la carpeta con QFileSystemWatcher (casi sin coste) en lugar de un modelo completo de archivos.
"""
import json
import logging
import os

from PySide6.QtCore import QObject, QThread, QTimer, Signal, QFileSystemWatcher

from config import APP_DATA_DIR, get_download_dir, atomic_write_json

logger = logging.getLogger(__name__)

AUDIO_EXTS = ('.mp3', '.m4a', '.wav', '.flac', '.ogg', '.wma')
CACHE_FILE = APP_DATA_DIR / "biblioteca_cache.json"
MAX_WATCHED_DIRS = 40


def local_id(path: str) -> str:
    return "local::" + os.path.normcase(os.path.abspath(path))


def scan_files(root: str) -> list:
    """[(ruta, fecha de modificación)] de todos los audios bajo `root`."""
    found = []
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.name.lower().endswith(AUDIO_EXTS):
                            found.append((entry.path, entry.stat().st_mtime))
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def read_basic_tags(path: str) -> dict:
    """Título, artista, álbum y duración (sin cargar la carátula)."""
    out = {"title": "", "artist": "", "album": "", "duration": 0}
    try:
        import mutagen
        audio = mutagen.File(path, easy=True)
        if audio is not None:
            if audio.info is not None:
                out["duration"] = int(getattr(audio.info, "length", 0) or 0)
            tags = audio.tags or {}
            for key, field in (("title", "title"), ("artist", "artist"), ("album", "album")):
                values = tags.get(key)
                if values:
                    out[field] = str(values[0])
    except Exception:
        pass
    return out


def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def build_item(path: str, mtime: float, tags: dict) -> dict:
    secs = int(tags.get("duration") or 0)
    return {
        "id": local_id(path),
        "title": tags.get("title") or os.path.splitext(os.path.basename(path))[0],
        "uploader": tags.get("artist") or "Música local",
        "album": tags.get("album") or "",
        "duration_secs": secs,
        "duration_str": f"{secs // 60}:{secs % 60:02d}" if secs else "",
        "url": path,
        "local_path": path,
        "already_downloaded": True,
        "thumbnail": "",
        "added_ts": mtime,
    }


def load_items_sync(root: str | None = None) -> list:
    """Biblioteca completa, de la más reciente a la más antigua. Usa la caché de etiquetas."""
    root = root or str(get_download_dir())
    cache = _load_cache()
    new_cache = {}
    items = []
    for path, mtime in sorted(scan_files(root), key=lambda x: x[1], reverse=True):
        entry = cache.get(path)
        if entry and entry.get("mtime") == mtime:
            tags = entry
        else:
            tags = read_basic_tags(path)
            tags["mtime"] = mtime
        new_cache[path] = tags
        items.append(build_item(path, mtime, tags))
    if new_cache != cache:
        try:
            atomic_write_json(CACHE_FILE, new_cache)
        except Exception as e:
            logger.warning(f"No se pudo guardar la caché de la biblioteca: {e}")
    return items


class LibraryScanWorker(QThread):
    """Lee la biblioteca en segundo plano para no bloquear la interfaz."""
    ready = Signal(list)

    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root

    def run(self):
        self.setPriority(QThread.LowPriority)
        self.ready.emit(load_items_sync(self.root))


class LibraryWatcher(QObject):
    """Avisa (con una pequeña espera para agrupar cambios) cuando se añade, borra o renombra un archivo."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._fire)

    def watch(self, root: str):
        old = self._watcher.directories()
        if old:
            self._watcher.removePaths(old)
        dirs = [root]
        try:
            with os.scandir(root) as it:
                dirs.extend(e.path for e in it if e.is_dir(follow_symlinks=False))
        except OSError:
            pass
        self._watcher.addPaths([d for d in dirs[:MAX_WATCHED_DIRS] if os.path.isdir(d)])

    def _schedule(self, _path: str):
        self._timer.start()

    def _fire(self):
        self.changed.emit()
