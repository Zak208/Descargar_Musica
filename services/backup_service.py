"""Copia de seguridad de tus datos (listas, favoritos, ajustes, letras...) en un solo archivo .zip, y restauración.

No incluye las cachés ni tus canciones (esas están en tu carpeta de música). Cada vez que se restaura, antes se guarda
una copia del estado actual por si hubo un error. Además se hace una copia automática semanal (solo las 5 últimas).
"""
import json
import logging
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

from config import APP_DATA_DIR, load_settings, reset_settings_cache, save_settings

logger = logging.getLogger(__name__)

BACKUP_DIR = APP_DATA_DIR / "copias"
AUTO_KEEP = 5
MAX_RESTORE_BYTES = 200 * 1024 * 1024
AUTO_EVERY_DAYS = 7
# Lo que forma parte de la copia (archivos sueltos y carpetas dentro de la carpeta de datos)
INCLUDE_FILES = ("settings.json", "favoritos.json", "playlists.json", "artistas_seguidos.json", "equalizer.json",
                 "historial_descargas.json")
INCLUDE_DIRS = ("letras", "covers")


def _members() -> list:
    """[(ruta real, nombre dentro del zip)]"""
    out = []
    for name in INCLUDE_FILES:
        p = APP_DATA_DIR / name
        if p.is_file():
            out.append((p, name))
    for d in INCLUDE_DIRS:
        base = APP_DATA_DIR / d
        if base.is_dir():
            for f in base.rglob("*"):
                if f.is_file():
                    out.append((f, f"{d}/{f.relative_to(base).as_posix()}"))
    return out


def create_backup(dest: str | os.PathLike) -> int:
    """Crea el .zip y devuelve cuántos archivos guardó."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    members = _members()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for real, arc in members:
            z.write(real, arc)
        z.writestr("COPIA.txt", f"Copia de seguridad de Descargador de Música · {datetime.now():%Y-%m-%d %H:%M}")
    os.replace(tmp, dest)
    return len(members)


def default_backup_name() -> str:
    return f"copia-descargador-{datetime.now():%Y-%m-%d}.zip"


def inspect_backup(path: str | os.PathLike) -> dict | None:
    """Comprueba que el archivo es una copia válida. Devuelve {'archivos': n, 'listas': n} o None."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "COPIA.txt" not in names:
                return None
            return {"archivos": len([n for n in names if n != "COPIA.txt"]),
                    "listas": 1 if "playlists.json" in names else 0}
    except (zipfile.BadZipFile, OSError):
        return None


def _safe_target(name: str) -> Path | None:
    """Solo se restauran los archivos esperados y siempre dentro de la carpeta de datos (sin rutas peligrosas)."""
    if name == "COPIA.txt" or name.endswith("/"):
        return None
    parts = Path(name).parts
    if ".." in parts or Path(name).is_absolute() or not parts:
        return None
    if not (name in INCLUDE_FILES or parts[0] in INCLUDE_DIRS):
        return None
    target = (APP_DATA_DIR / name).resolve()
    if APP_DATA_DIR.resolve() not in target.parents and target != APP_DATA_DIR.resolve():
        return None
    return target


def restore_backup(path: str | os.PathLike) -> int:
    """Restaura la copia (guardando antes el estado actual). Devuelve cuántos archivos se restauraron."""
    if inspect_backup(path) is None:
        raise ValueError("Ese archivo no es una copia de seguridad de la aplicación.")
    create_backup(BACKUP_DIR / f"antes-de-restaurar-{datetime.now():%Y%m%d-%H%M%S}.zip")
    wanted = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            target = _safe_target(info.filename)
            if target is None:
                continue
            if info.file_size > MAX_RESTORE_BYTES:
                raise ValueError(f"«{info.filename}» es demasiado grande para ser de una copia de seguridad.")
            if info.filename.lower().endswith(".json"):       # un JSON estropeado no debe pisar uno bueno
                try:
                    json.loads(z.read(info).decode("utf-8"))
                except ValueError:
                    raise ValueError(f"La copia está dañada («{info.filename}»). No se ha restaurado nada.")
            wanted.append((info, target))
        count = 0
        for info, target in wanted:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(target) + ".restaurando")
            with z.open(info) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.replace(tmp, target)                              # atómico: o queda el viejo o queda el nuevo
            count += 1
    reset_settings_cache()                                       # los ajustes en memoria ya no valen
    return count


def auto_backup_if_due() -> Path | None:
    """Copia semanal automática (rápida: solo unos pocos archivos pequeños)."""
    try:
        settings = load_settings()
        last = float(settings.get("last_auto_backup", 0) or 0)
        if time.time() - last < AUTO_EVERY_DAYS * 86400 or not (APP_DATA_DIR / "playlists.json").exists():
            return None
        dest = BACKUP_DIR / f"auto-{datetime.now():%Y%m%d}.zip"
        create_backup(dest)
        settings["last_auto_backup"] = time.time()
        save_settings(settings)
        autos = sorted(BACKUP_DIR.glob("auto-*.zip"))
        for old in autos[:-AUTO_KEEP]:
            try:
                old.unlink()
            except OSError:
                pass
        return dest
    except Exception as e:
        logger.warning(f"No se pudo hacer la copia automática: {e}")
        return None
