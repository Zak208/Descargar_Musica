"""Convierte errores técnicos en mensajes cortos y comprensibles."""


def friendly_error(raw) -> str:
    """Devuelve una explicación sencilla del problema, sin jerga técnica."""
    text = str(raw or "").lower()

    if any(k in text for k in ("getaddrinfo", "urlopen", "connection", "timed out", "timeout",
                               "network", "name or service", "temporary failure", "unreachable",
                               "max retries", "ssl")):
        try:
            from services import network_service
            network_service.note_failure()      # comprueba si de verdad se perdió la conexión
        except Exception:
            pass
        return "No hay conexión a internet. Revisa tu conexión e inténtalo de nuevo."
    if any(k in text for k in ("private video", "unavailable", "removed", "not available",
                               "copyright", "blocked", "no longer available", "terminated")):
        return "Esta canción no está disponible. Prueba con otra versión."
    if any(k in text for k in ("age-restricted", "age restricted", "sign in", "confirm your age", "log in", "login required")):
        return "Esta canción requiere iniciar sesión y no se puede descargar."
    if "ffmpeg" in text or "ffprobe" in text:
        return "Falta un componente de audio. Cierra y vuelve a abrir la aplicación."
    if any(k in text for k in ("permission", "access is denied", "denegado", "read-only")):
        return "No se puede guardar en esa carpeta. Elige otra en Ajustes."
    if any(k in text for k in ("no space", "disk full", "espacio")):
        return "No hay espacio suficiente en el disco."
    if "http error 429" in text or "too many requests" in text:
        return "Demasiadas peticiones seguidas. Espera un momento e inténtalo otra vez."
    return "Algo no ha ido bien. Inténtalo de nuevo en unos segundos."
