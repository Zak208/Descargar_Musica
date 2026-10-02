"""Descargas pendientes: lo que no se pudo bajar por falta de internet (o porque pediste «descargar» sin conexión)
queda guardado y se reanuda solo cuando vuelve la conexión, incluso si cierras la aplicación."""
import logging

from config import APP_DATA_DIR, atomic_write_json, read_json

PENDING_FILE = APP_DATA_DIR / "descargas_pendientes.json"
MAX_PENDING = 500
logger = logging.getLogger(__name__)

_KEEP = ("id", "title", "uploader", "album", "url", "thumbnail", "duration_secs", "duration_str")


def _key(info: dict) -> str:
    return str(info.get("id") or info.get("url") or info.get("title"))


def load() -> list:
    return read_json(PENDING_FILE, [], list)


def _save(items: list) -> None:
    try:
        if items:
            atomic_write_json(PENDING_FILE, items[:MAX_PENDING])
        elif PENDING_FILE.exists():
            PENDING_FILE.unlink()
    except Exception as e:
        logger.warning(f"No se pudieron guardar las descargas pendientes: {e}")


def add(infos) -> int:
    """Añade una o varias canciones (sin repetir). Devuelve cuántas son nuevas."""
    infos = [infos] if isinstance(infos, dict) else list(infos)
    items = load()
    known = {_key(i) for i in items}
    added = 0
    for info in infos:
        if _key(info) in known or not info.get("url"):
            continue
        items.append({k: info[k] for k in _KEEP if k in info})
        known.add(_key(info))
        added += 1
    if added:
        _save(items)
    return added


def remove(info: dict) -> None:
    key = _key(info)
    items = [i for i in load() if _key(i) != key]
    _save(items)


def clear() -> None:
    _save([])


def count() -> int:
    return len(load())
