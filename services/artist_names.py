"""Varios artistas en un solo texto: «Milo j & Yahritza Y Su Esencia», «A feat. B»... Una sola forma de separarlos para toda
la aplicación (duplicados, letras, recomendaciones, carpetas por artista y pantallas)."""
import re

_SYMBOLS = r"&|,|;|/"
_FEAT = r"feat\.?|ft\.?"
_WORDS = r"y|and|x|con|with"          # palabras sueltas que también unen a dos artistas

_SPLIT_BASIC = re.compile(rf"\s*(?:{_SYMBOLS})\s*|\s+(?:{_FEAT})\s+", re.IGNORECASE)
_SPLIT_WORDS = re.compile(rf"\s*(?:{_SYMBOLS})\s*|\s+(?:{_FEAT}|{_WORDS})\s+", re.IGNORECASE)


def split_artists(text: str, words: bool = False) -> list:
    """['Milo j', 'Yahritza Y Su Esencia'], sin repetidos. Con `words=True` también separa por «y», «and», «x», «con» y «with»
    (útil para comparar, pero puede partir nombres como «Simon y Garfunkel»)."""
    parts = (_SPLIT_WORDS if words else _SPLIT_BASIC).split(text or "")
    seen, out = set(), []
    for part in parts:
        part = part.strip()
        if part and part.lower() not in seen:
            seen.add(part.lower())
            out.append(part)
    return out


def first_artist(text: str, words: bool = False) -> str:
    """El artista principal: «Milo j & Yahritza» → «Milo j»."""
    parts = split_artists(text, words)
    return parts[0] if parts else (text or "").strip()
