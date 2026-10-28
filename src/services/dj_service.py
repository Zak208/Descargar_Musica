"""Modo DJ: de qué carpeta salen las canciones que se mezclan.

Se elige una carpeta general (por defecto, la de descargas) y, dentro de ella, qué suena: todo (con todas las
subcarpetas), solo los archivos sueltos de la carpeta general o una de sus subcarpetas (con lo que tenga dentro).
La carpeta se lee en segundo plano y una sola vez por cambio; el menú solo enseña el resumen ya hecho."""
import os

from PySide6.QtCore import QThread, Signal

from config import get_download_dir, load_settings, update_settings
from services.library_service import AUDIO_EXTS

DJ_EXTS = AUDIO_EXTS + ('.mp4',)
ORDER_SMART = "smart"      # el orden lo decide el planificador (ritmo, tono, energía y género)
ORDER_RANDOM = "random"    # aleatorio
SOURCE_ALL = "*"           # toda la carpeta general, con sus subcarpetas
SOURCE_ROOT = ""           # solo los archivos sueltos de la carpeta general
MAX_FILES = 20000          # por si se elige una carpeta enorme (un disco entero): se deja de buscar
MAX_FOLDERS = 20000        # y lo mismo con las carpetas (aunque no tengan música)


def get_root() -> str:
    """Sin mirar el disco (se llama desde la interfaz): si la carpeta ya no existe, la lectura lo dice."""
    return load_settings().get("dj_root") or str(get_download_dir())


def used_before() -> bool:
    settings = load_settings()
    return "dj_root" in settings or "dj_source" in settings


def get_order() -> str:
    """Cómo se ordenan las canciones de la sesión: ORDER_SMART (por defecto) u ORDER_RANDOM."""
    return ORDER_RANDOM if load_settings().get("dj_order") == ORDER_RANDOM else ORDER_SMART


def set_order(order: str):
    _store(dj_order=ORDER_RANDOM if order == ORDER_RANDOM else ORDER_SMART)


def get_source() -> str:
    return str(load_settings().get("dj_source", SOURCE_ALL))


def _store(**values):
    update_settings(**values)


def set_root(root: str):
    """Carpeta general nueva: vuelve a sonar todo lo que hay dentro."""
    _store(dj_root=root, dj_source=SOURCE_ALL)


def set_source(source: str):
    _store(dj_source=source)


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def get_blocked() -> set:
    """Canciones que no deben volver a salir en el modo DJ."""
    return set(load_settings().get("dj_blocked", []))


def block(path: str):
    blocked = get_blocked()
    blocked.add(_path_key(path))
    _store(dj_blocked=sorted(blocked))


def unblock_all():
    _store(dj_blocked=[])


def without_blocked(paths: list) -> list:
    blocked = get_blocked()
    if not blocked:
        return list(paths)
    return [p for p in paths if _path_key(p) not in blocked]


MIN_BPM_MANUAL, MAX_BPM_MANUAL = 40.0, 300.0     # lo que se acepta al corregir un tempo a mano


def parse_bpm(value):
    """Un BPM escrito a mano («95», «95,5») o un número, o None si no es un tempo razonable."""
    try:
        bpm = float(str(value).strip().replace(",", "."))
    except ValueError:
        return None
    return bpm if MIN_BPM_MANUAL <= bpm <= MAX_BPM_MANUAL else None


def get_bpm_overrides() -> dict:
    """Tempos corregidos a mano: {ruta normalizada: BPM}. Valen sobre lo que calcula el análisis."""
    raw = load_settings().get("dj_bpm_overrides", {})
    if not isinstance(raw, dict):
        return {}
    return {key: bpm for key, value in raw.items() if (bpm := parse_bpm(value)) is not None}


def get_bpm_override(path: str):
    """El BPM puesto a mano para esa canción, o None. Se mira solo esa entrada y se valida (esto se llama por cada fila)."""
    raw = load_settings().get("dj_bpm_overrides")
    return parse_bpm(raw.get(_path_key(path))) if isinstance(raw, dict) else None


def overrides_for(paths) -> dict:
    """{ruta: BPM a mano} de las canciones de `paths` que tienen corrección."""
    raw = load_settings().get("dj_bpm_overrides")
    if not isinstance(raw, dict) or not raw:
        return {}
    found = {}
    for path in paths:
        bpm = parse_bpm(raw.get(_path_key(path)))
        if bpm:
            found[path] = bpm
    return found


def set_bpm_override(path: str, bpm: float):
    overrides = get_bpm_overrides()
    overrides[_path_key(path)] = round(float(bpm), 2)
    _store(dj_bpm_overrides=overrides)


def clear_bpm_override(path: str):
    overrides = get_bpm_overrides()
    if overrides.pop(_path_key(path), None) is not None:
        _store(dj_bpm_overrides=overrides)


def _is_folder(entry) -> bool:
    """Carpeta de verdad (no un acceso directo de Windows a otra carpeta, que puede dar vueltas sin fin)."""
    return entry.is_dir(follow_symlinks=False) and not entry.is_junction()


def _walk(folder: str, found: list, limit: int):
    stack = [folder]
    visited = 0
    while stack and len(found) < limit and visited < MAX_FOLDERS:
        current = stack.pop()
        visited += 1
        try:
            with os.scandir(current) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            try:
                if _is_folder(entry):
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
                    if _is_folder(entry):
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
    return {"root": root, "loose": loose, "folders": folders, "truncated": total >= MAX_FILES,
            "missing": not os.path.isdir(root)}


def effective_source(summary: dict, source: str) -> str:
    """La fuente que de verdad suena: si la subcarpeta elegida ya no existe (o la carpeta general ya no tiene archivos
    sueltos), suena toda la carpeta. Así el menú, la página y la sesión dicen y hacen lo mismo."""
    if not summary or source == SOURCE_ALL:
        return SOURCE_ALL
    if source == SOURCE_ROOT:
        return SOURCE_ROOT if summary["loose"] else SOURCE_ALL
    return source if source in summary["folders"] else SOURCE_ALL


def tracks_for(summary: dict, source: str) -> list:
    """Las canciones que suenan con la fuente elegida (ver `effective_source`)."""
    if not summary:
        return []
    source = effective_source(summary, source)
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
