import re
import time
import logging
import requests
from services import http
from services.title_clean import strip_junk
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


def parse_lrc(lrc_text: str) -> list[tuple[int, str]]:
    """Parsea texto LRC sincronizado a una lista de tuplas (milisegundos, texto)."""
    lines = []
    pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
    for line in lrc_text.splitlines():
        m = pattern.match(line.strip())
        if m:
            mins = int(m.group(1))
            secs = float(m.group(2))
            ms = int((mins * 60 + secs) * 1000)
            text = m.group(3).strip()
            if text:
                lines.append((ms, text))
    return sorted(lines, key=lambda x: x[0])


HEADERS = {"User-Agent": "DescargadorMusicaApp/2.0"}


def _clean(text: str) -> str:
    text = strip_junk(text or "")
    text = re.sub(r"\s+", " ", text).strip(" -|_")
    return text


def _strip_featuring(text: str) -> str:
    text = re.sub(r"[\(\[]\s*(feat|ft|con|with)\.?[^\)\]]*[\)\]]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(feat|ft)\.?\s+.*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" -|_")


def _candidates(title: str, artist: str) -> list[tuple[str, str]]:
    """Combinaciones (artista, canción) a probar, de más a menos probable."""
    artist = "" if artist in ("Artista Desconocido", "Artista", "Música Local", "Música local") else (artist or "")
    title = _clean(title)
    artist = _clean(artist)
    pairs = []

    def add(a, t):
        a, t = (a or "").strip(), (t or "").strip()
        if t and (a, t) not in pairs:
            pairs.append((a, t))

    # Títulos tipo "Artista - Canción"
    if " - " in title:
        left, right = [x.strip() for x in title.split(" - ", 1)]
        add(left, right)
        add(artist, right)
    add(artist, title)
    add(artist, _strip_featuring(title))
    add(_strip_featuring(artist), _strip_featuring(title))
    add("", title)
    if " - " in title:
        add("", title.split(" - ", 1)[1])
    return pairs


def _build_result(data: dict, title: str, artist: str) -> dict | None:
    synced_raw = data.get("syncedLyrics")
    plain_raw = data.get("plainLyrics")
    synced_lines = parse_lrc(synced_raw) if synced_raw else []
    if not synced_lines and not plain_raw:
        return None
    return {
        "title": data.get("trackName", title),
        "artist": data.get("artistName", artist),
        "is_synced": bool(synced_lines),
        "synced_lines": synced_lines,
        "plain_text": plain_raw or "\n".join(line[1] for line in synced_lines),
    }


def _lrclib_get(artist: str, title: str) -> dict | None:
    params = {"track_name": title}
    if artist:
        params["artist_name"] = artist
    r = http.get("https://lrclib.net/api/get", params=params, headers=HEADERS, timeout=6)
    if r.status_code == 200:
        return _build_result(r.json(), title, artist)
    return None


def _lrclib_search(query: str, title: str, artist: str) -> dict | None:
    r = http.get("https://lrclib.net/api/search", params={"q": query}, headers=HEADERS, timeout=8)
    if r.status_code != 200:
        return None
    results = r.json()
    if not isinstance(results, list):
        return None
    # Preferir resultados con letra sincronizada y con el título parecido
    wanted = re.sub(r"\W+", "", title.lower())

    def score(item):
        name = re.sub(r"\W+", "", (item.get("trackName") or "").lower())
        art = re.sub(r"\W+", "", (item.get("artistName") or "").lower())
        pts = 0
        if wanted and (wanted in name or name in wanted):
            pts += 4
        if artist and re.sub(r"\W+", "", artist.lower()) in art:
            pts += 3
        if item.get("syncedLyrics"):
            pts += 2
        if item.get("plainLyrics"):
            pts += 1
        return pts

    for item in sorted(results, key=score, reverse=True):
        if score(item) >= 3:
            built = _build_result(item, title, artist)
            if built:
                return built
    return None


def _lyrics_ovh(artist: str, title: str) -> dict | None:
    if not artist:
        return None
    r = http.get(
        f"https://api.lyrics.ovh/v1/{requests.utils.quote(artist, safe='')}/{requests.utils.quote(title, safe='')}",
        headers=HEADERS, timeout=8,
    )
    if r.status_code == 200:
        text = (r.json().get("lyrics") or "").strip()
        if text:
            return {"title": title, "artist": artist, "is_synced": False, "synced_lines": [], "plain_text": text}
    return None


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", (text or "").lower())


def _artist_parts(text: str) -> set:
    parts = re.split(r"\s*(?:&|,|;|/|\bfeat\.?|\bft\.?|\by\b|\band\b|\bx\b)\s*", (text or "").lower())
    return {_norm(p) for p in parts if _norm(p)}


def _same_artist(wanted: str, found: str) -> bool:
    """¿La letra encontrada es del artista pedido? Sin esto, una canción con el mismo título de otro artista colaba su letra."""
    w, f = _artist_parts(wanted), _artist_parts(found)
    if not w or not f:
        return True
    return any(x in y or y in x for x in w for y in f)


def fetch_lyrics(title: str, artist: str = "", max_seconds: float | None = None) -> dict | None:
    """Busca la letra probando varias combinaciones y varias fuentes (LRCLIB y lyrics.ovh).
    Solo se acepta si el artista de la letra coincide con el de la canción."""
    known = "" if artist in ("Artista Desconocido", "Artista", "Música Local", "Música local") else _clean(artist)
    pairs = _candidates(title, artist)
    attempts = []
    for art, tit in pairs:
        attempts.append(lambda a=art, t=tit: _lrclib_get(a, t))
    for art, tit in pairs[:4]:
        attempts.append(lambda a=art, t=tit: _lrclib_search(f"{a} {t}".strip(), t, a))
    for art, tit in pairs:
        attempts.append(lambda a=art, t=tit: _lyrics_ovh(a, t))

    allowed = {_norm(known)} | {_norm(a) for a, _t in pairs if a}
    allowed.discard("")
    started = time.time()
    for attempt in attempts:
        if max_seconds is not None and time.time() - started > max_seconds:
            break
        try:
            result = attempt()
            if result and (not allowed or any(_same_artist(a, result.get("artist", "")) for a in allowed)):
                return result
        except Exception as e:
            logger.warning(f"Intento de letra fallido ({title} - {artist}): {e}")
    return None


class LyricsWorker(QThread):
    """Busca la letra. Orden: la que escribió el usuario, la copia ya guardada, la del propio archivo, internet
    (si hay conexión) y, por último, la generada por el sistema."""
    lyrics_ready = Signal(dict)
    lyrics_error = Signal(str)

    def __init__(self, title: str, artist: str = "", store_key: str = "", local_path: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.artist = artist
        self.store_key = store_key
        self.local_path = local_path
        self.is_cancelled = False

    def run(self):
        from services import lyrics_store, network_service
        stored = lyrics_store.load(self.store_key) if self.store_key else None
        source = stored.get("source") if stored else None
        if stored and source in ("user", "online"):
            self.lyrics_ready.emit(lyrics_store.to_result(stored, self.title, self.artist))
            return
        embedded = lyrics_store.read_embedded(self.local_path) if self.local_path else None
        if embedded:
            embedded["title"], embedded["artist"] = self.title, self.artist
            self.lyrics_ready.emit(embedded)
            return
        result = fetch_lyrics(self.title, self.artist) if (network_service.is_online() and not network_service.private_mode()) else None
        if self.is_cancelled:
            return
        if result:
            result["source"] = "online"
            if self.store_key:
                try:
                    lyrics_store.save_online(self.store_key, result)
                except Exception:
                    pass
            if self.local_path:
                lyrics_store.write_embedded(self.local_path, result)
            self.lyrics_ready.emit(result)
        elif stored:
            self.lyrics_ready.emit(lyrics_store.to_result(stored, self.title, self.artist))
        else:
            offline = not network_service.is_online()
            if network_service.private_mode():
                self.lyrics_error.emit("Modo privado: no se busca la letra en internet. Puedes escribirla tú o generarla con el sistema.")
                return
            self.lyrics_error.emit("Sin conexión: esta canción no tiene letra guardada todavía." if offline
                                   else "No hemos encontrado la letra de esta canción.")
