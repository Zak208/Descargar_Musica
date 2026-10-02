"""Canciones repetidas en tu música: busca las que son la misma (aunque el nombre del archivo cambie un poco) y
propone quedarse con la de mejor calidad."""
import os
import re
from collections import defaultdict

from services.library_search import fold

_JUNK = re.compile(r"[\(\[][^\)\]]*(official|oficial|video|vídeo|audio|lyric|letra|visualizer|remaster|hd|hq|clip|"
                   r"explicit|version|versión|feat|ft\.?|con )[^\)\]]*[\)\]]", re.IGNORECASE)
_FEAT = re.compile(r"\s+(feat|ft)\.?\s+.*$", re.IGNORECASE)


def normalize_title(title: str) -> str:
    text = _JUNK.sub("", title or "")
    text = _FEAT.sub("", text)
    return re.sub(r"\W+", "", fold(text))


def primary_artist(artist: str) -> str:
    first = re.split(r"\s*(?:&|,|;|/|\bfeat\.?|\bft\.?|\by\b|\band\b|\bx\b)\s*", artist or "", maxsplit=1)[0]
    return re.sub(r"\W+", "", fold(first))


def _audio_info(path: str) -> dict:
    info = {"size": 0, "bitrate": 0, "duration": 0}
    try:
        info["size"] = os.path.getsize(path)
        import mutagen
        audio = mutagen.File(path)
        if audio is not None and audio.info is not None:
            info["duration"] = float(getattr(audio.info, "length", 0) or 0)
            info["bitrate"] = int(getattr(audio.info, "bitrate", 0) or 0) // 1000
        if not info["bitrate"] and info["duration"]:
            info["bitrate"] = int(info["size"] * 8 / info["duration"] / 1000)
    except Exception:
        pass
    return info


def find_duplicates(items: list) -> list:
    """Grupos de canciones repetidas. Cada grupo es una lista [{item, size, bitrate, duration, keep}] con la mejor
    primero (keep=True) y el resto propuestas para quitar. Solo grupos de 2 o más."""
    buckets = defaultdict(list)
    for it in items:
        key = normalize_title(it.get("title", ""))
        if len(key) >= 3:
            buckets[key].append(it)
    groups = []
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        # mismo artista principal (o artista desconocido en alguna de las dos)
        by_artist = defaultdict(list)
        for it in members:
            artist = primary_artist(it.get("uploader", ""))
            if artist in ("", "musicalocal"):
                artist = "?"
            by_artist[artist].append(it)
        unknown = by_artist.pop("?", [])
        for artist, same in by_artist.items():
            pool = same + unknown if len(by_artist) == 1 else same
            if len(pool) >= 2:
                groups.append(pool)
        if not by_artist and len(unknown) >= 2:
            groups.append(unknown)
    result = []
    for group in groups:
        entries = []
        for it in group:
            info = _audio_info(it["local_path"])
            entries.append({"item": it, **info})
        # mayor calidad primero; a igualdad, el más grande y el más antiguo
        entries.sort(key=lambda e: (-e["bitrate"], -e["size"], e["item"].get("added_ts", 0)))
        durations = [e["duration"] for e in entries if e["duration"]]
        if durations and max(durations) - min(durations) > 15:
            continue        # duraciones muy distintas: no es la misma grabación (directo, remix...)
        for i, e in enumerate(entries):
            e["keep"] = i == 0
        result.append(entries)
    result.sort(key=lambda g: g[0]["item"].get("title", "").lower())
    return result
