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

# Directorio de datos de la app (listas, ajustes, letras, cachés...).
#   * Programa compilado (.exe): %APPDATA%\Descargador de Música  → actualizar o mover el .exe nunca borra tus datos.
#   * Desde el código: la carpeta app_data del proyecto (como siempre).
#   * La variable DESCARGADOR_DATA_DIR lo cambia (las pruebas automáticas la usan para no tocar tus datos).
LEGACY_DATA_DIR = APP_DIR / "app_data"
DATA_DIR_NAME = "Descargador de Música"


def _resolve_data_dir() -> Path:
    custom = os.environ.get("DESCARGADOR_DATA_DIR")
    if custom:
        return Path(custom)
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get("APPDATA") or Path.home()) / DATA_DIR_NAME
    return LEGACY_DATA_DIR


def _migrate_legacy_data(new_dir: Path) -> None:
    """Versiones anteriores guardaban los datos junto al .exe. La primera vez se pasan a la carpeta nueva
    (lo pequeño se copia, lo pesado se mueve) y la carpeta antigua queda intacta."""
    import shutil
    old = LEGACY_DATA_DIR
    if new_dir == old or not old.is_dir() or (new_dir / ".migrado").exists():
        return
    if any((new_dir / n).exists() for n in ("settings.json", "playlists.json", "favoritos.json")):
        return
    new_dir.mkdir(parents=True, exist_ok=True)
    for child in old.iterdir():
        target = new_dir / child.name
        if target.exists():
            continue
        try:
            if child.is_dir():
                if child.name in ("whisper", "ffmpeg", "img_cache", "eq_cache"):
                    shutil.move(str(child), str(target))
                else:
                    shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)
        except Exception:
            pass
    try:
        (new_dir / ".migrado").write_text("Datos traídos de la carpeta del programa.", encoding="utf-8")
    except OSError:
        pass


APP_DATA_DIR = _resolve_data_dir()
try:
    _migrate_legacy_data(APP_DATA_DIR)
except Exception:
    pass
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
    if "parallel_downloads" in settings:
        return int(settings["parallel_downloads"])
    from ui.perf import default_parallel_downloads      # equipo modesto: de una en una
    return default_parallel_downloads()


