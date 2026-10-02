"""Formato de fechas y duraciones en español."""
import time
from datetime import datetime

MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def format_date(ts) -> str:
    """'12 oct 2026' a partir de una marca de tiempo (vacío si no se conoce)."""
    if not ts:
        return ""
    try:
        d = datetime.fromtimestamp(float(ts))
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    except (ValueError, OSError, OverflowError):
        return ""


def format_added(ts) -> str:
    """Cuánto hace que se añadió: '5 min', '2 h', '3 días', '2 semanas' y, pasado un tiempo, la fecha ('31 ago 2026')."""
    if not ts:
        return ""
    try:
        elapsed = max(0.0, time.time() - float(ts))
    except (TypeError, ValueError):
        return ""
    minutes = int(elapsed // 60)
    if minutes < 1:
        return "Ahora"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h"
    days = hours // 24
    if days < 7:
        return "1 día" if days == 1 else f"{days} días"
    weeks = days // 7
    if weeks < 4:
        return "1 semana" if weeks == 1 else f"{weeks} semanas"
    return format_date(ts)


def format_total(seconds: int) -> str:
    """'1 h 23 min' / '45 min' a partir de segundos (vacío si no hay duración)."""
    if not seconds:
        return ""
    minutes = round(seconds / 60)
    if minutes >= 60:
        return f"{minutes // 60} h {minutes % 60:02d} min"
    return f"{max(minutes, 1)} min"


def parse_added(item: dict) -> float:
    """Marca de tiempo en la que se añadió una canción a una lista (0 si no se sabe)."""
    ts = item.get("added_ts")
    if ts:
        try:
            return float(ts)
        except (TypeError, ValueError):
            pass
    text = item.get("added_at", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except (ValueError, TypeError):
            continue
    return 0.0


from services.artist_names import split_artists  # noqa: E402,F401  (se usa desde varias pantallas)
