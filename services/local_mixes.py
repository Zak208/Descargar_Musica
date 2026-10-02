"""Mixes y listas automáticas hechos solo con tu música descargada (no necesitan internet ni cuestan nada).

Se calculan a partir de las etiquetas que ya están en el índice: artista, álbum, género, año y fecha de descarga.
"""
import datetime
import random
from collections import Counter, defaultdict

MIN_ARTIST_TRACKS = 3
MIN_ALBUM_TRACKS = 4
MIN_GENRE_TRACKS = 5
MIN_DECADE_TRACKS = 6
MAX_MIX_SIZE = 60


def _artists_label(tracks: list) -> list:
    counts = Counter(t.get("uploader", "") for t in tracks if t.get("uploader") and t.get("uploader") != "Música local")
    return [name for name, _n in counts.most_common(3)]


def _mix(name: str, tracks: list, kind: str) -> dict:
    tracks = tracks[:MAX_MIX_SIZE]
    return {"name": name, "tracks": tracks, "artists": _artists_label(tracks), "kind": kind, "local": True}


def build_local_mixes(items: list, today: datetime.date | None = None, limit: int = 12) -> list:
    """Devuelve hasta `limit` mixes, de los más interesantes a los menos."""
    if not items:
        return []
    today = today or datetime.date.today()
    mixes = []

    # Lo último que descargaste
    recent = sorted(items, key=lambda i: i.get("added_ts", 0), reverse=True)[:30]
    if len(recent) >= 5:
        mixes.append(_mix("Lo último que descargaste", recent, "recent"))

    # Un mix por cada artista con varias canciones
    by_artist = defaultdict(list)
    for it in items:
        artist = it.get("uploader", "")
        if artist and artist != "Música local":
            by_artist[artist].append(it)
    for artist, tracks in sorted(by_artist.items(), key=lambda kv: len(kv[1]), reverse=True):
        if len(tracks) >= MIN_ARTIST_TRACKS:
            mixes.append(_mix(f"Lo mejor de {artist}", tracks, "artist"))
        if len([m for m in mixes if m["kind"] == "artist"]) >= 4:
            break

    # Géneros y décadas (solo si las etiquetas los traen)
    by_genre = defaultdict(list)
    by_decade = defaultdict(list)
    for it in items:
        genre = (it.get("genre") or "").strip()
        if genre:
            by_genre[genre.title()].append(it)
        year = int(it.get("year") or 0)
        if 1950 <= year <= today.year:
            by_decade[year // 10 * 10].append(it)
    for genre, tracks in sorted(by_genre.items(), key=lambda kv: len(kv[1]), reverse=True)[:2]:
        if len(tracks) >= MIN_GENRE_TRACKS:
            mixes.append(_mix(f"{genre}", tracks, "genre"))
    for decade, tracks in sorted(by_decade.items(), key=lambda kv: len(kv[1]), reverse=True)[:2]:
        if len(tracks) >= MIN_DECADE_TRACKS:
            mixes.append(_mix(f"Música de los {decade}", tracks, "decade"))

    # Álbumes completos
    by_album = defaultdict(list)
    for it in items:
        if it.get("album"):
            by_album[(it["album"], it.get("uploader", ""))].append(it)
    for (album, _artist), tracks in sorted(by_album.items(), key=lambda kv: len(kv[1]), reverse=True)[:2]:
        if len(tracks) >= MIN_ALBUM_TRACKS:
            ordered = sorted(tracks, key=lambda t: (t.get("track_no") or 999, t.get("title", "")))
            mixes.append(_mix(f"Álbum: {album}", ordered, "album"))

    # Un mix aleatorio que cambia cada día (siempre el mismo durante ese día)
    if len(items) >= 8:
        rng = random.Random(today.toordinal())
        shuffled = items[:]
        rng.shuffle(shuffled)
        mixes.append(_mix("Sorpresa del día", shuffled, "random"))
    return mixes[:limit]


def rediscover(items: list, stats: dict, limit: int = 30, quiet_days: int = 30, now: float | None = None) -> list:
    """Canciones que llevas tiempo sin escuchar (o nunca): «Redescubre»."""
    import time
    now = now or time.time()
    cutoff = now - quiet_days * 86400
    old = []
    for it in items:
        count, last = stats.get(it.get("local_path"), (0, 0))
        if last < cutoff and it.get("added_ts", now) < cutoff:
            old.append(it)
    random.Random(int(now // 86400)).shuffle(old)
    return old[:limit]


def smart_lists(items: list, stats: dict, now: float | None = None) -> list:
    """Listas automáticas útiles: [(clave, nombre, canciones)] (solo las que tienen canciones)."""
    import time
    now = now or time.time()
    week = now - 7 * 86400
    out = []
    recent = [i for i in items if i.get("added_ts", 0) >= week]
    if recent:
        out.append(("week", "Añadidas esta semana", recent))
    no_cover_tags = [i for i in items if i.get("uploader") in ("", "Música local") or not i.get("album")]
    if no_cover_tags:
        out.append(("untagged", "Sin artista o álbum", no_cover_tags))
    longest = sorted([i for i in items if int(i.get("duration_secs", 0) or 0) >= 360],
                     key=lambda i: int(i.get("duration_secs", 0)), reverse=True)
    if longest:
        out.append(("long", "Canciones largas (6 min o más)", longest))
    top = sorted((i for i in items if stats.get(i.get("local_path"), (0, 0))[0] > 0),
                 key=lambda i: stats[i["local_path"]][0], reverse=True)[:50]
    if top:
        out.append(("top", "Lo más escuchado", top))
    never = [i for i in items if stats.get(i.get("local_path"), (0, 0))[0] == 0]
    if never and len(never) < len(items):
        out.append(("never", "Aún sin escuchar", never))
    return out
