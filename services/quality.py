"""Calidades de descarga explicadas en lenguaje sencillo, con lo que ocupa una canción de unos 4 minutos."""

# clave, nombre, tamaño aproximado de una canción de 4 min, códec, calidad, extensión final
QUALITIES = (
    ("320", "Alta calidad (recomendado)", 9.4, "mp3", "320", "mp3"),
    ("192", "Calidad normal", 5.6, "mp3", "192", "mp3"),
    ("128", "Ahorrar espacio", 3.8, "mp3", "128", "mp3"),
    ("m4a", "Fidelidad original (sin recomprimir)", 4.5, "m4a", None, "m4a"),
    ("flac", "Sin pérdida · FLAC (ocupa mucho)", 28.0, "flac", None, "flac"),
    ("wav", "Estudio · WAV (ocupa muchísimo)", 40.0, "wav", None, "wav"),
)
DEFAULT = "320"


def _row(code: str):
    for row in QUALITIES:
        if row[0] == (code or DEFAULT).lower():
            return row
    return QUALITIES[0]


def label(code: str) -> str:
    key, name, mb, *_ = _row(code)
    return f"{name} · ≈ {mb:.0f} MB por canción"


def encoder(code: str) -> tuple:
    """(códec, calidad, extensión) para yt-dlp."""
    _key, _name, _mb, codec, quality, ext = _row(code)
    return codec, quality, ext


def postprocessor(code: str) -> dict:
    codec, quality, _ext = encoder(code)
    pp = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
    if quality:
        pp["preferredquality"] = quality
    return pp


def estimate_mb(code: str, seconds: float) -> float:
    return _row(code)[2] * (seconds / 240.0)
