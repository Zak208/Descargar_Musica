"""Mejorar etiquetas en lote: para las canciones con artista, álbum o portada pobres, se busca en iTunes la ficha más
parecida y se propone. El usuario revisa y aplica solo lo que quiere."""
import difflib
import logging
import os
import re
import time

from PySide6.QtCore import QThread, Signal

from services import http
from services.duplicates import normalize_title, primary_artist
from services.library_search import fold
from services.metadata_service import MetadataService

logger = logging.getLogger(__name__)

POOR_ARTISTS = ("", "música local", "musica local", "artista desconocido")
MIN_SCORE = 0.62
MAX_CANDIDATES = 120
_JUNK = re.compile(r"[\(\[][^\)\]]*(official|oficial|video|vídeo|audio|lyric|letra|visualizer|remaster|hd|hq|clip)[^\)\]]*[\)\]]",
                   re.IGNORECASE)


def needs_fixing(item: dict) -> bool:
    artist = (item.get("uploader") or "").strip().lower()
    return artist in POOR_ARTISTS or not (item.get("album") or "").strip()


def candidates(items: list) -> list:
    return [it for it in items if needs_fixing(it)][:MAX_CANDIDATES]


def guess_query(item: dict) -> tuple:
    """(artista, título) deducidos de las etiquetas o del nombre del archivo («Artista - Título»)."""
    stem = os.path.splitext(os.path.basename(item.get("local_path", "")))[0]
    title = _JUNK.sub("", item.get("title") or stem).strip()
    artist = "" if (item.get("uploader") or "").strip().lower() in POOR_ARTISTS else item["uploader"]
    if not artist and " - " in stem:
        left, right = [x.strip() for x in _JUNK.sub("", stem).split(" - ", 1)]
        artist, title = left, right
    return artist, title


def search_itunes(term: str, limit: int = 6) -> list:
    r = http.get("https://itunes.apple.com/search", params={"term": term, "entity": "song", "media": "music",
                                                            "limit": limit}, timeout=8)
    if r.status_code != 200:
        return []
    return r.json().get("results", [])


def hires_cover(url: str) -> str:
    return re.sub(r"/\d+x\d+bb\.", "/600x600bb.", url or "")


def best_match(artist: str, title: str, results: list):
    """(ficha, puntuación 0-1) de la mejor coincidencia, o (None, 0)."""
    want_title = normalize_title(title)
    want_artist = primary_artist(artist)
    best, best_score = None, 0.0
    for res in results:
        got_title = normalize_title(res.get("trackName", ""))
        if not got_title or not want_title:
            continue
        score = difflib.SequenceMatcher(None, want_title, got_title).ratio()
        if want_artist:
            got_artist = primary_artist(res.get("artistName", ""))
            if want_artist == got_artist or want_artist in got_artist or got_artist in want_artist:
                score = min(1.0, score + 0.15)
            else:
                score -= 0.35
        if score > best_score:
            best, best_score = res, score
    return (best, best_score) if best_score >= MIN_SCORE else (None, best_score)


def suggestion_for(item: dict):
    artist, title = guess_query(item)
    term = f"{artist} {title}".strip()
    if not term:
        return None
    match, score = best_match(artist, title, search_itunes(term))
    if not match:
        return None
    proposed = {
        "title": match.get("trackName", ""),
        "artist": match.get("artistName", ""),
        "album": match.get("collectionName", ""),
        "cover": hires_cover(match.get("artworkUrl100", "")),
        "year": (match.get("releaseDate") or "")[:4],
        "genre": match.get("primaryGenreName", ""),
    }
    current = {"title": item.get("title", ""), "artist": item.get("uploader", ""), "album": item.get("album", "")}
    if fold(proposed["title"]) == fold(current["title"]) and fold(proposed["artist"]) == fold(current["artist"]) \
            and fold(proposed["album"]) == fold(current["album"]):
        return None
    return {"path": item["local_path"], "current": current, "proposed": proposed, "score": round(score, 2)}


class TagSuggestWorker(QThread):
    """Busca propuestas una a una (con una pausa corta para no saturar el servicio)."""
    progress = Signal(int, int)
    suggestion = Signal(dict)
    finished_all = Signal(int)

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.items = items
        self.is_cancelled = False

    def run(self):
        self.setPriority(QThread.LowPriority)
        found = 0
        for i, item in enumerate(self.items, 1):
            if self.is_cancelled:
                break
            try:
                s = suggestion_for(item)
            except Exception as e:
                logger.info(f"Sin propuesta para {item.get('title')}: {e}")
                s = None
            if s:
                found += 1
                self.suggestion.emit(s)
            self.progress.emit(i, len(self.items))
            time.sleep(0.25)
        self.finished_all.emit(found)


def apply_suggestions(suggestions: list) -> int:
    """Escribe las etiquetas y la portada propuestas. Devuelve cuántas canciones se actualizaron."""
    done = 0
    for s in suggestions:
        p = s["proposed"]
        if MetadataService.embed_metadata(s["path"], p["title"], p["artist"], p["album"], p["cover"] or None):
            done += 1
    return done
