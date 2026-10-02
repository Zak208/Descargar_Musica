"""Importar y exportar listas en M3U/M3U8, el formato que entienden casi todos los reproductores.

Exportar escribe, por cada lista, un `.m3u8` con las canciones que están descargadas (con su artista, título y duración).
Importar lee uno o varios `.m3u`/`.m3u8` y crea una lista por archivo con las canciones que existen en tu equipo (las rutas
pueden ser absolutas o relativas al propio archivo)."""
import os
import re

from services import library_service
from services.playlist_service import PlaylistService
from services.youtube_service import sanitize_filename

_EXTINF = re.compile(r"#EXTINF:\s*(-?\d+)\s*(?:[^,]*),(.*)", re.IGNORECASE)
AUDIO_EXTS = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".wma", ".aac", ".opus")


def export_playlist(playlist: dict, dest: str) -> tuple[int, int]:
    """Escribe una lista en `dest` (.m3u8). Devuelve (canciones escritas, canciones sin descargar que se omiten)."""
    written = skipped = 0
    lines = ["#EXTM3U", f"#PLAYLIST:{playlist.get('name', '')}"]
    for track in playlist.get("tracks", []):
        path = track.get("local_path")
        if not path or not os.path.isfile(path):
            skipped += 1
            continue
        secs = int(track.get("duration_secs") or 0) or -1
        artist, title = (track.get("uploader") or "").strip(), (track.get("title") or "").strip()
        lines.append(f"#EXTINF:{secs},{artist + ' - ' if artist else ''}{title}")
        lines.append(os.path.normpath(path))
        written += 1
    with open(dest, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return written, skipped


def export_all(folder: str) -> dict:
    """Exporta todas tus listas a una carpeta. Devuelve {'listas': n, 'canciones': n, 'omitidas': n}."""
    os.makedirs(folder, exist_ok=True)
    total = {"listas": 0, "canciones": 0, "omitidas": 0}
    used = set()
    for playlist in PlaylistService.get_playlists().values():
        name = sanitize_filename(playlist.get("name") or "Lista")
        base, n = name, 2
        while name.lower() in used:
            name, n = f"{base} ({n})", n + 1
        used.add(name.lower())
        written, skipped = export_playlist(playlist, os.path.join(folder, name + ".m3u8"))
        total["listas"] += 1
        total["canciones"] += written
        total["omitidas"] += skipped
    return total


def parse_m3u(path: str) -> list:
    """[(ruta existente, título o '')] de un archivo M3U. Se ignoran las rutas que no existen o no son de audio."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            raw = f.read().splitlines()
    except OSError:
        return []
    base = os.path.dirname(os.path.abspath(path))
    entries, pending = [], ""
    for line in raw:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = _EXTINF.match(line)
            if m:
                pending = m.group(2).strip()
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*://", line, re.IGNORECASE):
            pending = ""
            continue                                       # direcciones de internet: no se importan
        full = line if os.path.isabs(line) else os.path.join(base, line)
        full = os.path.normpath(full)
        if full.lower().endswith(AUDIO_EXTS) and os.path.isfile(full):
            entries.append((full, pending))
        pending = ""
    return entries


def import_files(paths: list) -> dict:
    """Crea una lista por cada archivo M3U. Devuelve {'listas': n, 'canciones': n, 'omitidas': n}."""
    total = {"listas": 0, "canciones": 0, "omitidas": 0}
    for m3u in paths:
        entries = parse_m3u(m3u)
        if not entries:
            continue
        name = os.path.splitext(os.path.basename(m3u))[0] or "Lista importada"
        playlist_id = PlaylistService.create_playlist(name)
        total["listas"] += 1
        for path, label in entries:
            tags = library_service.read_basic_tags(path)
            item = library_service.build_item(path, os.path.getmtime(path), tags)
            if label and not tags.get("title"):
                artist, _sep, title = label.partition(" - ")
                item["uploader"], item["title"] = (artist, title) if title else (item["uploader"], label)
            if PlaylistService.add_track_to_playlist(playlist_id, item):
                total["canciones"] += 1
            else:
                total["omitidas"] += 1
    return total
