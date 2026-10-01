"""Modo ahorro de recursos: menos animaciones y menos memoria para equipos modestos."""
from config import load_settings, save_settings

_eco = None


def eco() -> bool:
    """True si el modo ahorro está activado (por defecto lo está)."""
    global _eco
    if _eco is None:
        _eco = bool(load_settings().get("eco_mode", True))
    return _eco


def set_eco(enabled: bool) -> None:
    global _eco
    _eco = bool(enabled)
    settings = load_settings()
    settings["eco_mode"] = _eco
    save_settings(settings)


def image_scale() -> int:
    """Factor de resolución de las imágenes en memoria: 1 en modo ahorro, 2 para máxima nitidez."""
    return 1 if eco() else 2
