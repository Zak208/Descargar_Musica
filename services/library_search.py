"""Búsqueda dentro de tu música descargada (sin internet): ignora mayúsculas y acentos y acepta varias palabras."""
import re
import unicodedata


def fold(text: str) -> str:
    """Minúsculas y sin acentos: «Canción» → «cancion»."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def tokens(query: str) -> list:
    return [t for t in re.split(r"\W+", fold(query)) if t]


def search_items(items: list, query: str, limit: int = 150) -> list:
    """Canciones cuyo título, artista, álbum o género contienen TODAS las palabras buscadas (las que empiezan
    por la búsqueda en el título salen primero)."""
    words = tokens(query)
    if not words:
        return []
    scored = []
    for it in items:
        haystack = fold(f"{it.get('title', '')} {it.get('uploader', '')} {it.get('album', '')} {it.get('genre', '')}")
        if all(w in haystack for w in words):
            title = fold(it.get("title", ""))
            rank = 0 if title.startswith(words[0]) else (1 if words[0] in title else 2)
            scored.append((rank, it))
    scored.sort(key=lambda x: x[0])
    return [it for _r, it in scored[:limit]]
