"""Limpieza de títulos: quitar las coletillas de YouTube entre paréntesis o corchetes («(Official Video)», «[Letra]»...).

Una sola definición para descargas, letras, arreglo de etiquetas y búsqueda de duplicados. Las palabras se buscan enteras:
«Eclipse» ya no se confunde con «clip» ni «Videodrome» con «video»."""
import re

JUNK_WORDS = (r"official|oficial|video|vídeo|audio|lyrics?|letra|visualizer|visualiser|remaster(?:ed)?|4k|1080p|hd|hq|"
              r"clip|videoclip|subtitulado|musical")
# palabras que, en los duplicados, también indican que el paréntesis es «adorno» (no cambia la canción)
EXTRA_WORDS = r"explicit|version|versión|feat|ft\.?|con"


def junk_group(extra: str = "") -> re.Pattern:
    words = JUNK_WORDS + (("|" + extra) if extra else "")
    return re.compile(r"[\(\[][^\)\]]*\b(?:" + words + r")(?!\w)[^\)\]]*[\)\]]", re.IGNORECASE)


JUNK = junk_group()
JUNK_WITH_EXTRA = junk_group(EXTRA_WORDS)
_WORD = re.compile(r"\b(?:" + JUNK_WORDS + r")(?!\w)", re.IGNORECASE)


def strip_junk(text: str, extra: bool = False) -> str:
    """Quita los grupos entre paréntesis o corchetes que contienen una coletilla de vídeo."""
    return (JUNK_WITH_EXTRA if extra else JUNK).sub("", text or "")


def has_junk(text: str) -> bool:
    return bool(_WORD.search(text or ""))
