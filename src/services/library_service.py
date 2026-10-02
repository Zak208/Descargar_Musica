"""Biblioteca de música local: búsqueda de archivos, lectura de etiquetas con caché y vigilancia de la carpeta.

Para gastar poca memoria y CPU:
  * las etiquetas (título, artista, álbum, duración, género, año) se leen una sola vez por archivo y se guardan en SQLite;
  * solo se vuelven a leer los archivos nuevos o modificados;
  * se vigila la carpeta con QFileSystemWatcher (casi sin coste) en lugar de un modelo completo de archivos.
"""
import logging
import os

from PySide6.QtCore import QObject, QThread, QTimer, Signal, QFileSystemWatcher

from config import get_download_dir
from services import library_db

logger = logging.getLogger(__name__)

AUDIO_EXTS = ('.mp3', '.m4a', '.wav', '.flac', '.ogg', '.wma')
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
    """Título, artista, álbum, duración, género, año y número de pista (sin cargar la carátula)."""
    out = {"title": "", "artist": "", "album": "", "duration": 0, "genre": "", "year": 0, "track_no": 0}
    try:
        import mutagen
        audio = mutagen.File(path, easy=True)
        if audio is not None:
            if audio.info is not None:
                out["duration"] = int(getattr(audio.info, "length", 0) or 0)
            tags = audio.tags or {}
            for key in ("title", "artist", "album", "genre"):
                values = tags.get(key)
                if values:
                    out[key] = str(values[0])
            date = tags.get("date") or tags.get("originaldate")
            if date:
                digits = "".join(ch for ch in str(date[0])[:4] if ch.isdigit())
                out["year"] = int(digits) if len(digits) == 4 else 0
            number = tags.get("tracknumber")
            if number:
                head = str(number[0]).split("/")[0].strip()
                out["track_no"] = int(head) if head.isdigit() else 0
    except Exception:
        pass
    return out


def build_item(path: str, mtime: float, tags: dict) -> dict:
    secs = int(tags.get("duration") or 0)
    return {
        "id": local_id(path),
        "title": tags.get("title") or os.path.splitext(os.path.basename(path))[0],
        "uploader": tags.get("artist") or "Música local",
        "album": tags.get("album") or "",
        "genre": tags.get("genre") or "",
        "year": int(tags.get("year") or 0),
        "track_no": int(tags.get("track_no") or 0),
        "duration_secs": secs,
        "duration_str": f"{secs // 60}:{secs % 60:02d}" if secs else "",
        "url": path,
        "local_path": path,
        "already_downloaded": True,
        "thumbnail": "",
        "added_ts": mtime,
    }


def _inside(path: str, root: str) -> bool:
    """¿Está `path` dentro de la carpeta `root`? (Music2 no está dentro de Music)"""
    try:
        base = os.path.normcase(os.path.abspath(root))
        return os.path.commonpath([os.path.normcase(os.path.abspath(path)), base]) == base
    except ValueError:
        return False


def load_items_sync(root: str | None = None) -> list:
    """Biblioteca completa, de la más reciente a la más antigua. Solo se leen las etiquetas de los archivos
    nuevos o modificados (el resto sale del índice SQLite)."""
    root = root or str(get_download_dir())
    library_db.import_old_json()
    known = library_db.load_all()
    found = scan_files(root)
    items, upserts = [], []
    for path, mtime in sorted(found, key=lambda x: x[1], reverse=True):
        row = known.get(path)
        if row and row["mtime"] == mtime and (row.get("tagver") or 0) >= library_db.TAG_VERSION:
            tags = row
        else:
            tags = read_basic_tags(path)
            upserts.append(dict(tags, path=path, mtime=mtime, tagver=library_db.TAG_VERSION))
        items.append(build_item(path, mtime, tags))
    present = {p for p, _m in found}
    removed = [p for p in known if p not in present and _inside(p, root)]
    if removed and (not os.path.isdir(root) or (not found and known)
                    or (len(removed) > 20 and len(removed) > len(known) * 0.5)):
        # la carpeta no responde (disco de red, OneDrive desconectado...): no se borra nada del índice
        logger.warning(f"Escaneo sospechoso ({len(removed)} de {len(known)} pistas desaparecidas): no se borra nada")
        removed = []
    if upserts or removed:
        try:
            library_db.apply_changes(upserts, removed)
        except Exception as e:
            logger.warning(f"No se pudo guardar el índice de la biblioteca: {e}")
    return items


class LibraryScanWorker(QThread):
    """Lee la biblioteca en segundo plano para no bloquear la interfaz."""
    ready = Signal(list)

    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root

    def run(self):
        self.setPriority(QThread.LowPriority)
        from services.heavy import heavy_task
        with heavy_task():
            items = load_items_sync(self.root)
        self.ready.emit(items)


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
