"""Letras guardadas en el equipo: las que escribe el usuario y las que genera el propio programa.

Cada letra es un archivo JSON en app_data/letras con su origen:
  * "user": la ha escrito o corregido el usuario (tiene prioridad sobre cualquier letra de internet)
  * "auto": generada por el sistema escuchando la canción (solo se usa si no hay letra en internet)
"""
import hashlib
import os
import re

from config import APP_DATA_DIR, atomic_write_json

LYRICS_DIR = APP_DATA_DIR / "letras"
_TS = re.compile(r"^\s*\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$")


def key_for(title: str, artist: str, local_path: str = "") -> str:
    """Identificador estable de la canción: su archivo si está descargada, o el título y el artista."""
    base = os.path.normcase(os.path.abspath(local_path)) if local_path else \
        re.sub(r"\W+", "", f"{title}|{artist}".lower())
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:16]


def _path(key: str):
    return LYRICS_DIR / f"{key}.json"


def load(key: str) -> dict | None:
    try:
        import json
        with open(_path(key), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("text") else None
    except (OSError, ValueError):
        return None


def save(key: str, text: str, source: str) -> dict:
    """Guarda el texto (con o sin tiempos «[mm:ss.xx]») y devuelve la letra ya procesada."""
    LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    data = {"source": source, "text": text.strip()}
    atomic_write_json(_path(key), data)
    return data


def delete(key: str, source: str | None = None) -> None:
    """Borra la letra guardada (si se indica `source`, solo si es de ese origen)."""
    stored = load(key)
    if stored and (source is None or stored.get("source") == source):
        try:
            os.remove(_path(key))
        except OSError:
            pass


def parse_text(text: str) -> tuple[list, bool]:
    """Convierte el texto en líneas [(ms, texto)]. Devuelve (líneas, tiene_tiempos).
    Las líneas sin tiempo dentro de una letra con tiempos heredan el de la línea anterior."""
    lines, last_ms, synced = [], 0, False
    for raw in text.splitlines():
        m = _TS.match(raw)
        if m:
            synced = True
            last_ms = int((int(m.group(1)) * 60 + float(m.group(2))) * 1000)
            body = m.group(3).strip()
        else:
            body = raw.strip()
        if body:
            lines.append((last_ms, body))
    return (sorted(lines, key=lambda x: x[0]) if synced else lines), synced


def to_result(data: dict, title: str = "", artist: str = "") -> dict:
    """Formato que entiende la interfaz de letras (el mismo que el de internet) más el origen."""
    lines, synced = parse_text(data["text"])
    return {
        "title": title, "artist": artist,
        "is_synced": synced,
        "synced_lines": lines if synced else [],
        "plain_text": "\n".join(t for _ms, t in lines),
        "source": data.get("source", "user"),
    }


def format_ms(ms: int) -> str:
    total = max(0, ms) / 1000
    return f"[{int(total // 60):02d}:{total % 60:05.2f}]"
