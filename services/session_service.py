"""Recuerda cómo dejaste la aplicación (volumen, canción y punto en que iba, cola, ventana...) para seguir donde lo dejaste."""
import json
import logging

from config import APP_DATA_DIR, atomic_write_json

SESSION_FILE = APP_DATA_DIR / "sesion.json"
MAX_CONTEXT = 500
MAX_QUEUE = 100
logger = logging.getLogger(__name__)


def load() -> dict:
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    try:
        atomic_write_json(SESSION_FILE, data)
    except Exception as e:
        logger.warning(f"No se pudo guardar la sesión: {e}")


def local_paths(items: list, limit: int) -> list:
    """Solo se recuerdan las canciones descargadas (las de internet necesitan conexión para volver a sonar)."""
    return [i["local_path"] for i in items if i.get("local_path")][:limit]
