"""Formato de duraciones sin dependencias de la interfaz (lo usan los servicios)."""


def format_duration(seconds, blank_zero: bool = True) -> str:
    """«m:ss» a partir de segundos. Con 0 o sin dato devuelve «» (o «0:00» si blank_zero es False)."""
    secs = int(seconds or 0)
    if not secs and blank_zero:
        return ""
    return f"{secs // 60}:{secs % 60:02d}"
