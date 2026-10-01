import os
import sys
import json
from pathlib import Path

# Directorio raíz del proyecto o del ejecutable compilado
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    APP_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent
    APP_DIR = BASE_DIR

# Directorio predeterminado de descargas (Carpeta Música del sistema de Windows)
DEFAULT_MUSIC_DIR = Path(os.path.expanduser("~")) / "Music" / "Canciones_YouTube"
DEFAULT_MUSIC_DIR.mkdir(parents=True, exist_ok=True)

# Directorio de datos de la app (historial, configuración, ffmpeg portátil)
APP_DATA_DIR = APP_DIR / "app_data"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

COVERS_DIR = APP_DATA_DIR / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_DIR = APP_DATA_DIR / "ffmpeg"
FFMPEG_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_FILE = APP_DATA_DIR / "historial_descargas.json"
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
FAVORITES_FILE = APP_DATA_DIR / "favoritos.json"
PLAYLISTS_FILE = APP_DATA_DIR / "playlists.json"
EQUALIZER_FILE = APP_DATA_DIR / "equalizer.json"
ARTISTS_FILE = APP_DATA_DIR / "artistas_seguidos.json"
RECOMMENDATIONS_FILE = APP_DATA_DIR / "recomendaciones.json"


_settings_cache: dict | None = None


def atomic_write_json(path: Path, data) -> None:
    """Escribe JSON a un archivo temporal y lo renombra, para no dejar el archivo corrupto si la app se cierra a mitad."""
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_settings() -> dict:
    """Carga los ajustes del usuario (se leen del disco una sola vez y se guardan en memoria)."""
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = {}
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    _settings_cache = loaded
            except Exception:
                _settings_cache = {}
    return dict(_settings_cache)


def save_settings(settings: dict):
    """Guarda los ajustes del usuario en settings.json."""
    global _settings_cache
    _settings_cache = dict(settings)
    try:
        atomic_write_json(SETTINGS_FILE, settings)
    except Exception as e:
        print(f"Error guardando settings: {e}")


def get_download_dir() -> Path:
    """Obtiene el directorio de descargas configurado o el predeterminado."""
    settings = load_settings()
    custom_dir = settings.get("download_dir")
    if custom_dir and os.path.isdir(custom_dir):
        return Path(custom_dir)
    return DEFAULT_MUSIC_DIR


def set_download_dir(new_dir: str):
    """Establece un nuevo directorio personalizado de descargas."""
    settings = load_settings()
    resolved_path = Path(new_dir).resolve()
    resolved_path.mkdir(parents=True, exist_ok=True)
    settings["download_dir"] = str(resolved_path)
    save_settings(settings)


def get_audio_quality() -> str:
    """Obtiene la calidad de audio configurada ('320', '192', 'm4a', 'flac', 'wav')."""
    settings = load_settings()
    return settings.get("quality", "320")


def set_audio_quality(quality: str):
    """Guarda la calidad de audio seleccionada."""
    settings = load_settings()
    settings["quality"] = quality
    save_settings(settings)


def get_theme() -> str:
    """Obtiene el tema visual ('spotify', 'midnight', 'cyberpunk', 'emerald')."""
    settings = load_settings()
    return settings.get("theme", "spotify")


def set_theme(theme_name: str):
    """Guarda el tema visual activo."""
    settings = load_settings()
    settings["theme"] = theme_name
    save_settings(settings)


def get_parallel_downloads() -> int:
    """Obtiene el número de descargas simultáneas en paralelo (por defecto 3)."""
    settings = load_settings()
    return int(settings.get("parallel_downloads", 3))


