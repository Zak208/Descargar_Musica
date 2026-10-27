"""Modo DJ: de qué carpeta salen las canciones que se mezclan.

Se elige una carpeta general (por defecto, la de descargas) y, dentro de ella, qué suena: todo (con todas las
subcarpetas), solo los archivos sueltos de la carpeta general o una de sus subcarpetas (con lo que tenga dentro).
La carpeta se lee en segundo plano y una sola vez por cambio; el menú solo enseña el resumen ya hecho."""
import os

from PySide6.QtCore import QThread, Signal

from config import get_download_dir, load_settings, save_settings
from services.library_service import AUDIO_EXTS

DJ_EXTS = AUDIO_EXTS + ('.mp4',)
SOURCE_ALL = "*"           # toda la carpeta general, con sus subcarpetas
SOURCE_ROOT = ""           # solo los archivos sueltos de la carpeta general
MAX_FILES = 20000          # por si se elige una carpeta enorme (un disco entero): se deja de buscar


def get_root() -> str:
    root = load_settings().get("dj_root") or ""
    return root if root and os.path.isdir(root) else str(get_download_dir())


def get_source() -> str:
    return str(load_settings().get("dj_source", SOURCE_ALL))


def _store(**values):
    settings = load_settings()
    settings.update(values)
    save_settings(settings)


def set_root(root: str):
    """Carpeta general nueva: vuelve a sonar todo lo que hay dentro."""
    _store(dj_root=root, dj_source=SOURCE_ALL)


def set_source(source: str):
    _store(dj_source=source)


def _walk(folder: str, found: list, limit: int):
    stack = [folder]
    while stack and len(found) < limit:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.name.lower().endswith(DJ_EXTS):
                    found.append(entry.path)
            except OSError:
                continue


def scan(root: str) -> dict:
    """{"root": ruta, "loose": [archivos sueltos], "folders": {nombre: [archivos, con subcarpetas]}, "truncated": bool}."""
    loose, subdirs = [], []
    try:
        with os.scandir(root) as it:
            for entry in sorted(it, key=lambda e: e.name.lower()):
                try:
                    if entry.is_dir(follow_symlinks=False):
                        subdirs.append(entry)
                    elif entry.name.lower().endswith(DJ_EXTS):
                        loose.append(entry.path)
                except OSError:
                    continue
    except OSError:
        pass
    total = len(loose)
    folders = {}
    for entry in subdirs:
        found = []
        _walk(entry.path, found, MAX_FILES - total)
        total += len(found)
        if found:
            folders[entry.name] = found
        if total >= MAX_FILES:
            break
    return {"root": root, "loose": loose, "folders": folders, "truncated": total >= MAX_FILES}


def tracks_for(summary: dict, source: str) -> list:
    """Las canciones que suenan con la fuente elegida (si la subcarpeta ya no existe, suena todo)."""
    if not summary:
        return []
    if source == SOURCE_ROOT:
        return list(summary["loose"])
    if source in summary["folders"]:
        return list(summary["folders"][source])
    out = list(summary["loose"])
    for paths in summary["folders"].values():
        out.extend(paths)
    return out


def count_all(summary: dict) -> int:
    return len(tracks_for(summary, SOURCE_ALL))


class DjScanWorker(QThread):
    """Lee la carpeta general en segundo plano para no bloquear la interfaz."""
    ready = Signal(dict)

    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root

    def run(self):
        self.setPriority(QThread.LowPriority)
        from services.heavy import heavy_task
        with heavy_task():
            summary = scan(self.root)
        self.ready.emit(summary)
