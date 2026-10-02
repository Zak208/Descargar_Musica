"""Cuánto espacio ocupa cada cosa que guarda la aplicación y cómo liberarlo (sin tocar tus listas ni tu música)."""
import os
import shutil

from config import APP_DATA_DIR, FFMPEG_DIR, COVERS_DIR

# clave -> (nombre, ruta, ¿se puede borrar sin perder nada importante?, explicación)
def _categories() -> dict:
    return {
        "imagenes": ("Imágenes guardadas", APP_DATA_DIR / "img_cache", True,
                     "Portadas y fotos para que carguen al instante. Se vuelven a descargar si hacen falta."),
        "ecualizador": ("Copias del ecualizador", APP_DATA_DIR / "eq_cache", True,
                        "Copias temporales de la canción con el sonido ajustado."),
        "recomendaciones": ("Recomendaciones", APP_DATA_DIR / "recomendaciones.json", True,
                            "Se vuelven a calcular al abrir Inicio."),
        "biblioteca": ("Datos de tu biblioteca", APP_DATA_DIR / "biblioteca.sqlite", True,
                       "Títulos y duraciones leídos de tus canciones. Se vuelven a leer solos."),
        "reconocedor": ("Reconocedor de voz (para generar letras)", APP_DATA_DIR / "whisper", True,
                        "Se descarga otra vez si quieres volver a generar letras."),
        "ffmpeg": ("Componente de audio (FFmpeg)", FFMPEG_DIR, True,
                   "Si lo borras, la app lo descarga de nuevo cuando lo necesite."),
        "letras": ("Tus letras", APP_DATA_DIR / "letras", False, "Las que escribiste o generaste. No se borran desde aquí."),
        "portadas": ("Imágenes de tus listas y artistas", COVERS_DIR, False, "Forman parte de tus listas."),
    }


def _size(path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def usage() -> list:
    """[{'key', 'name', 'bytes', 'clearable', 'hint'}] ordenado de mayor a menor."""
    rows = []
    for key, (name, path, clearable, hint) in _categories().items():
        rows.append({"key": key, "name": name, "bytes": _size(path), "clearable": clearable, "hint": hint})
    return sorted(rows, key=lambda r: r["bytes"], reverse=True)


def clear(key: str) -> int:
    """Borra una categoría (solo las que se pueden borrar). Devuelve los bytes liberados."""
    cat = _categories().get(key)
    if not cat or not cat[2]:
        return 0
    path = cat[1]
    freed = _size(path)
    try:
        if key == "biblioteca":      # el índice SQLite se reconstruye leyendo las etiquetas otra vez
            from services import library_db
            library_db.delete_index()
            for suffix in ("-wal", "-shm"):
                try:
                    os.remove(str(path) + suffix)
                except OSError:
                    pass
            return freed
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 0
    return freed


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if n >= 100 or unit == "KB" else f"{n:.1f} {unit}".replace(".", ",")
    return f"{n} B"


def free_disk_bytes(path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 1 << 62
