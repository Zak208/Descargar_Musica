"""Recomendaciones al estilo Spotify a partir de la música que tienes descargada, tus favoritas y los artistas que sigues.

Usa las APIs públicas de Deezer (artistas relacionados, canciones populares, listas de éxitos) y de iTunes (novedades).
No hace falta ninguna cuenta ni clave.
"""
import hashlib
import json
import logging
import re
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests
from PySide6.QtCore import QThread, Signal

from config import RECOMMENDATIONS_FILE, atomic_write_json

logger = logging.getLogger(__name__)

DEEZER = "https://api.deezer.com"
ITUNES = "https://itunes.apple.com"
CACHE_HOURS = 8


# ------------------------------------------------------------------ utilidades
def norm(text: str) -> str:
    """Texto en minúsculas, sin acentos ni símbolos (para comparar nombres)."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", "", folded.lower())


def primary_artist(name: str) -> str:
    """'Milo j & Yahritza Y Su Esencia' -> 'Milo j'; 'A feat. B' -> 'A'."""
    name = re.split(r"\s+(?:&|y|x|feat\.?|ft\.?|con|with)\s+|,|;|/", name or "", maxsplit=1, flags=re.IGNORECASE)[0]
    return name.strip()


def _get(url: str, **params) -> dict:
    try:
        r = requests.get(url, params=params, timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.debug(f"Petición fallida {url}: {e}")
    return {}


def _track(item: dict) -> dict | None:
    try:
        title = item["title"]
        artist = item["artist"]["name"]
        album = item.get("album", {})
        secs = int(item.get("duration", 0))
        return {
            "title": title,
            "uploader": artist,
            "album": album.get("title", ""),
            "duration_secs": secs,
            "duration_str": f"{secs // 60}:{secs % 60:02d}",
            "thumbnail": album.get("cover_big") or album.get("cover_medium") or "",
            "url": f"ytsearch1:{artist} {title}",
            "id": f"dz{item['id']}",
        }
    except (KeyError, TypeError):
        return None


# ------------------------------------------------------------- perfil de gustos
def build_taste_profile(library_items: list, favorites: list, followed: list) -> dict:
    """Analiza tu música: artistas más escuchados, con más peso los que sigues, los que te gustan y los recientes."""
    weights = defaultdict(float)
    names = {}

    def add(raw_artist: str, points: float):
        artist = primary_artist(raw_artist)
        key = norm(artist)
        if not key or key in ("artistadesconocido", "musicalocal", "artista"):
            return
        weights[key] += points
        names.setdefault(key, artist)

    for i, it in enumerate(library_items):
        add(it.get("uploader", ""), 1.0 + (0.6 if i < 10 else 0.0))   # las añadidas hace poco pesan más
    for it in favorites:
        add(it.get("uploader", ""), 2.0)
    for a in followed:
        add(a.get("name", ""), 3.0)

    ordered = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    seeds = [(names[k], w) for k, w in ordered[:8]]
    known = set(weights.keys())
    titles = {norm(it.get("title", "")) for it in library_items} | {norm(it.get("title", "")) for it in favorites}
    return {"seeds": seeds, "known": known, "titles": titles}


def signature(seeds: list, followed_ids: list) -> str:
    raw = "|".join(n for n, _ in seeds) + "#" + ",".join(sorted(str(i) for i in followed_ids))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_cache(sig: str) -> dict | None:
    """Recomendaciones guardadas, si son recientes y corresponden a los mismos gustos."""
    try:
        if RECOMMENDATIONS_FILE.exists():
            with open(RECOMMENDATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            fresh = time.time() - data.get("generated_at", 0) < CACHE_HOURS * 3600
            if fresh and data.get("signature") == sig:
                return data
    except Exception:
        pass
    return None


def load_stale_cache() -> dict | None:
    """Última recomendación guardada aunque sea antigua (para mostrar algo al instante sin conexión)."""
    try:
        if RECOMMENDATIONS_FILE.exists():
            with open(RECOMMENDATIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------- trabajo
class RecommendationWorker(QThread):
    ready = Signal(dict)

    def __init__(self, profile: dict, followed: list, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.followed = followed
        self.is_cancelled = False

    # -- consultas
    @staticmethod
    def _find_artist(name: str) -> dict | None:
        data = _get(f"{DEEZER}/search/artist", q=name, limit=5).get("data", [])
        if not data:
            return None
        for cand in data:
            if norm(cand.get("name", "")) == norm(name):
                return cand
        return max(data, key=lambda c: c.get("nb_fan", 0))

    @staticmethod
    def _related(artist_id) -> list:
        return _get(f"{DEEZER}/artist/{artist_id}/related", limit=14).get("data", [])

    @staticmethod
    def _top(artist_id, limit: int = 6) -> list:
        out = []
        for item in _get(f"{DEEZER}/artist/{artist_id}/top", limit=limit).get("data", []):
            t = _track(item)
            if t:
                out.append(t)
        return out

    def run(self):
        try:
            seeds = self.profile["seeds"]
            known = self.profile["known"]
            lib_titles = self.profile["titles"]
            result = {"generated_at": time.time(), "signature": signature(seeds, [a["id"] for a in self.followed]),
                      "artists": [], "tracks": [], "because": [], "mixes": [], "releases": [], "charts": [],
                      "genres": []}

            with ThreadPoolExecutor(max_workers=6) as pool:
                # 1) cada artista base -> su artista de Deezer y los parecidos
                found = list(pool.map(lambda s: self._find_artist(s[0]), seeds))
                related_lists = list(pool.map(lambda f: self._related(f["id"]) if f else [], found))
                if self.is_cancelled:
                    return

                scores = {}
                for (name, weight), rel in zip(seeds, related_lists):
                    for rank, art in enumerate(rel):
                        key = norm(art.get("name", ""))
                        if not key or key in known or key == norm(name):
                            continue
                        entry = scores.setdefault(key, {"id": art["id"], "name": art["name"],
                                                       "picture": art.get("picture_medium") or art.get("picture", ""),
                                                       "score": 0.0})
                        entry["score"] += weight * (1.0 - rank / max(len(rel), 1))
                ranked = sorted(scores.values(), key=lambda e: e["score"], reverse=True)

                result["artists"] = [{"id": f"dz{a['id']}", "name": a["name"], "picture": a["picture"]} for a in ranked[:14]]

                # 2) canciones de los artistas parecidos (que aún no tienes)
                top_related = ranked[:8]
                tops = list(pool.map(lambda a: self._top(a["id"], 6), top_related))
                interleaved, i = [], 0
                while len(interleaved) < 24 and any(len(t) > i for t in tops):
                    for t in tops:
                        if len(t) > i and norm(t[i]["title"]) not in lib_titles:
                            interleaved.append(t[i])
                    i += 1
                seen = set()
                for t in interleaved:
                    k = (norm(t["title"]), norm(t["uploader"]))
                    if k not in seen:
                        seen.add(k)
                        result["tracks"].append(t)
                result["tracks"] = result["tracks"][:24]

                # 3) "Porque escuchas a X": lo más popular de tus artistas que aún no tienes
                for (name, _w), f in list(zip(seeds, found))[:2]:
                    if not f:
                        continue
                    tracks = [t for t in self._top(f["id"], 12) if norm(t["title"]) not in lib_titles][:10]
                    if tracks:
                        result["because"].append({"artist": name, "tracks": tracks})

                # 4) Mixes: un artista base + sus parecidos
                for idx in range(min(6, len(seeds))):
                    rel = [r for r in related_lists[idx] if norm(r.get("name", "")) != norm(seeds[idx][0])][:3]
                    members = [(seeds[idx][0], found[idx])] + [(r["name"], r) for r in rel]
                    member_tops = list(pool.map(lambda m: self._top(m[1]["id"], 7) if m[1] else [], members))
                    mix_tracks, j = [], 0
                    while len(mix_tracks) < 25 and any(len(t) > j for t in member_tops):
                        for t in member_tops:
                            if len(t) > j:
                                mix_tracks.append(t[j])
                        j += 1
                    if mix_tracks:
                        result["mixes"].append({"name": f"Mix {idx + 1}", "artists": [m[0] for m in members],
                                                "tracks": mix_tracks})

                # 5) novedades de los artistas que sigues (iTunes, último año)
                def releases(artist):
                    data = _get(f"{ITUNES}/lookup", id=artist["id"], entity="album", limit=8, sort="recent")
                    out = []
                    limit_date = datetime.now() - timedelta(days=400)
                    for item in data.get("results", []):
                        if item.get("wrapperType") != "collection":
                            continue
                        try:
                            date = datetime.strptime(item.get("releaseDate", "")[:10], "%Y-%m-%d")
                        except ValueError:
                            continue
                        if date < limit_date:
                            continue
                        out.append({
                            "id": item.get("collectionId"),
                            "name": item.get("collectionName", ""),
                            "artist": item.get("artistName", artist["name"]),
                            "year": item.get("releaseDate", "")[:4],
                            "release_date": item.get("releaseDate", "")[:10],
                            "track_count": item.get("trackCount", 0),
                            "cover": item.get("artworkUrl100", "").replace("100x100bb", "600x600bb"),
                        })
                    return out

                if self.followed:
                    all_rel = []
                    for chunk in pool.map(releases, self.followed[:12]):
                        all_rel.extend(chunk)
                    all_rel.sort(key=lambda a: a["release_date"], reverse=True)
                    result["releases"] = all_rel[:12]

                # 6) éxitos del momento
                for item in _get(f"{DEEZER}/chart/0/tracks", limit=20).get("data", []):
                    t = _track(item)
                    if t:
                        result["charts"].append(t)

            # Los mixes de artistas se numeran seguidos (Mix 1, Mix 2...) aunque alguno no haya tenido canciones
            for number, mix in enumerate(result["mixes"], start=1):
                mix["name"] = f"Mix {number}"

            # Mixes especiales: lo nuevo para ti y los éxitos del momento
            if result["tracks"]:
                names = [a["name"] for a in result["artists"][:6]]
                result["mixes"].append({"name": "Descubrimiento semanal", "artists": names,
                                        "tracks": result["tracks"][:30]})
            if result["charts"]:
                result["mixes"].append({"name": "Éxitos del momento",
                                        "artists": [t["uploader"] for t in result["charts"][:4]],
                                        "tracks": result["charts"]})

            # Géneros para explorar
            for g in _get(f"{DEEZER}/genre").get("data", []):
                if g.get("id") and g.get("name") and g["id"] != 0:
                    result["genres"].append({"id": g["id"], "name": g["name"]})
            result["genres"] = result["genres"][:14]

            if self.is_cancelled:
                return
            try:
                atomic_write_json(RECOMMENDATIONS_FILE, result)
            except Exception as e:
                logger.warning(f"No se pudieron guardar las recomendaciones: {e}")
            self.ready.emit(result)
        except Exception as e:
            logger.warning(f"Error generando recomendaciones: {e}")


class RelatedArtistsWorker(QThread):
    """Artistas parecidos a uno dado ('Los fans también escuchan')."""
    ready = Signal(list)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name

    def run(self):
        found = RecommendationWorker._find_artist(self.name)
        if not found:
            self.ready.emit([])
            return
        out = []
        for art in RecommendationWorker._related(found["id"])[:12]:
            out.append({"id": f"dz{art['id']}", "name": art.get("name", ""),
                        "picture": art.get("picture_medium") or art.get("picture", "")})
        self.ready.emit(out)


class ArtistResolver(QThread):
    """Busca en iTunes el artista por su nombre para poder abrir su perfil completo."""
    found = Signal(dict)
    failed = Signal()

    def __init__(self, name: str, picture: str = "", parent=None):
        super().__init__(parent)
        self.name = name
        self.picture = picture

    def run(self):
        data = _get(f"{ITUNES}/search", term=self.name, entity="musicArtist", limit=5).get("results", [])
        best = None
        for item in data:
            if norm(item.get("artistName", "")) == norm(self.name):
                best = item
                break
        best = best or (data[0] if data else None)
        if not best:
            self.failed.emit()
            return
        self.found.emit({"id": best["artistId"], "name": best.get("artistName", self.name), "avatar": self.picture})


class GenreTracksWorker(QThread):
    """Las canciones más escuchadas de un género."""
    ready = Signal(list)

    def __init__(self, genre_id: int, parent=None):
        super().__init__(parent)
        self.genre_id = genre_id

    def run(self):
        tracks = []
        for item in _get(f"{DEEZER}/chart/{self.genre_id}/tracks", limit=40).get("data", []):
            t = _track(item)
            if t:
                tracks.append(t)
        self.ready.emit(tracks)
