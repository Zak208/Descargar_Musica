"""Letras guardadas en el equipo: las que escribe el usuario y las que genera el propio programa.

Cada letra es un archivo JSON en app_data/letras con su origen:
  * "user": la ha escrito o corregido el usuario (tiene prioridad sobre cualquier letra de internet)
  * "auto": generada por el sistema escuchando la canción (solo se usa si no hay letra en internet)
  * "online": copia de la letra que ya se encontró en internet (así funciona sin conexión y se abre al instante)

Además, en las canciones descargadas la letra viaja dentro del propio archivo (etiquetas ID3/MP4/FLAC).
"""
import hashlib
import os
import re

from config import APP_DATA_DIR, atomic_write_json, read_json

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
    data = read_json(_path(key), None, dict)
    return data if data and data.get("text") else None


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


# --------------------------------------------------------------- copia de internet
def save_online(key: str, result: dict) -> None:
    """Guarda una copia de la letra encontrada en internet (nunca pisa la del usuario ni la generada)."""
    existing = load(key)
    if existing and existing.get("source") in ("user", "auto"):
        if existing.get("source") == "user":
            return
    lines = result.get("synced_lines") if result.get("is_synced") else None
    if lines:
        text = "\n".join(f"{format_ms(ms)} {t}" for ms, t in lines)
    else:
        text = result.get("plain_text", "")
    if text.strip():
        save(key, text, "online")


# ------------------------------------------------------- letra dentro del archivo
def _lrc_text(result: dict) -> str:
    if result.get("is_synced") and result.get("synced_lines"):
        return "\n".join(f"{format_ms(ms)} {t}" for ms, t in result["synced_lines"])
    return ""


def write_embedded(path: str, result: dict) -> bool:
    """Guarda la letra dentro de las etiquetas del archivo (mp3, m4a o flac). Devuelve True si pudo."""
    plain = result.get("plain_text", "").strip()
    if not plain or not os.path.isfile(path):
        return False
    lrc = _lrc_text(result)
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3, ID3NoHeaderError, USLT, SYLT
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("USLT")
            tags.delall("SYLT")
            tags.add(USLT(encoding=3, lang="spa", desc="", text=plain))
            if result.get("is_synced") and result.get("synced_lines"):
                tags.add(SYLT(encoding=3, lang="spa", format=2, type=1, desc="",
                              text=[(t, int(ms)) for ms, t in result["synced_lines"]]))
            tags.save(path, v2_version=3)
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4, MP4FreeForm
            audio = MP4(path)
            audio["©lyr"] = [plain]
            if lrc:
                audio["----:com.descargador:LRC"] = [MP4FreeForm(lrc.encode("utf-8"))]
            audio.save()
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(path)
            audio["LYRICS"] = plain
            if lrc:
                audio["LRC"] = lrc
            audio.save()
        else:
            return False
        return True
    except Exception:
        return False


def read_embedded(path: str) -> dict | None:
    """Letra guardada dentro del archivo (formato de interfaz) o None."""
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    text = ""
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3
            tags = ID3(path)
            sylt = tags.getall("SYLT")
            if sylt and sylt[0].text:
                text = "\n".join(f"{format_ms(ms)} {t}" for t, ms in sorted(sylt[0].text, key=lambda x: x[1]))
            else:
                uslt = tags.getall("USLT")
                text = uslt[0].text if uslt else ""
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4
            audio = MP4(path)
            free = audio.get("----:com.descargador:LRC")
            if free:
                text = bytes(free[0]).decode("utf-8", "ignore")
            else:
                text = (audio.get("©lyr") or [""])[0]
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(path)
            text = (audio.get("LRC") or audio.get("LYRICS") or [""])[0]
    except Exception:
        return None
    text = (text or "").strip()
    if not text:
        return None
    return to_result({"text": text, "source": "online"})
