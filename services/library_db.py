"""Índice de tu música en SQLite (un solo archivo, sin servidor): etiquetas de cada canción y recuento de reproducciones.

Frente al JSON anterior:
  * al cambiar una canción solo se escribe esa fila (no se reescribe todo el archivo);
  * se puede consultar sin recorrer listas enormes (búsqueda, «más escuchadas», listas automáticas...);
  * gasta menos memoria y CPU cuando la biblioteca tiene miles de canciones.
"""
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager

from config import APP_DATA_DIR

logger = logging.getLogger(__name__)

DB_FILE = APP_DATA_DIR / "biblioteca.sqlite"
OLD_JSON = APP_DATA_DIR / "biblioteca_cache.json"
TAG_VERSION = 2          # súbelo si se empiezan a leer más etiquetas: se vuelven a leer solas en segundo plano

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    title TEXT, artist TEXT, album TEXT,
    duration INTEGER DEFAULT 0,
    genre TEXT DEFAULT '', year INTEGER DEFAULT 0, track_no INTEGER DEFAULT 0,
    tagver INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plays (
    path TEXT PRIMARY KEY,
    count INTEGER DEFAULT 0,
    first_ts REAL DEFAULT 0,
    last_ts REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS loudness (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    lufs REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album);
"""


SCHEMA_VERSION = 1       # PRAGMA user_version: si cambia una tabla, súbelo y añade el paso en _migrate()
_ready = False
_ready_lock = threading.Lock()


def _migrate(con) -> None:
    """Crea las tablas (la primera vez en cada ejecución) y aplica los cambios de versiones anteriores."""
    current = con.execute("PRAGMA user_version").fetchone()[0]
    con.executescript(SCHEMA)
    # (aquí irán los pasos «si current < 2: ALTER TABLE ...» cuando alguna tabla cambie)
    if current < SCHEMA_VERSION:
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


@contextmanager
def connect():
    """Conexión corta (se abre y se cierra): se puede usar desde cualquier hilo. El esquema se comprueba una sola vez."""
    global _ready
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DB_FILE.exists():
        _ready = False              # la base se borró (copia restaurada, limpieza...): hay que crearla otra vez
    con = sqlite3.connect(str(DB_FILE), timeout=5)
    con.row_factory = sqlite3.Row
    try:
        if not _ready:
            with _ready_lock:
                if not _ready:
                    con.execute("PRAGMA journal_mode=WAL")
                    _migrate(con)
                    con.commit()
                    _ready = True
        con.execute("PRAGMA synchronous=NORMAL")
        yield con
        con.commit()
    finally:
        con.close()


def import_old_json() -> None:
    """Si existe el antiguo JSON de etiquetas, se aprovecha una sola vez (así no hay que volver a leer todo)."""
    if not OLD_JSON.exists():
        return
    try:
        with open(OLD_JSON, "r", encoding="utf-8") as f:
            old = json.load(f)
        with connect() as con:
            if con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0] == 0 and isinstance(old, dict):
                rows = [(p, e.get("mtime", 0), e.get("title", ""), e.get("artist", ""), e.get("album", ""),
                         int(e.get("duration", 0) or 0)) for p, e in old.items() if isinstance(e, dict)]
                con.executemany("INSERT OR IGNORE INTO tracks(path, mtime, title, artist, album, duration, tagver) "
                                "VALUES (?,?,?,?,?,?,1)", rows)
        OLD_JSON.rename(OLD_JSON.with_suffix(".json.importado"))
    except Exception as e:
        logger.warning(f"No se pudo importar la caché antigua: {e}")


def load_all() -> dict:
    """{ruta: fila} de todo el índice."""
    with connect() as con:
        return {r["path"]: dict(r) for r in con.execute("SELECT * FROM tracks")}


def apply_changes(upserts: list, removed: list) -> None:
    """upserts: [dict con path, mtime y etiquetas]; removed: [rutas que ya no existen]."""
    with connect() as con:
        con.executemany(
            "INSERT INTO tracks(path, mtime, title, artist, album, duration, genre, year, track_no, tagver) "
            "VALUES (:path,:mtime,:title,:artist,:album,:duration,:genre,:year,:track_no,:tagver) "
            "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, title=excluded.title, artist=excluded.artist, "
            "album=excluded.album, duration=excluded.duration, genre=excluded.genre, year=excluded.year, "
            "track_no=excluded.track_no, tagver=excluded.tagver", upserts)
        con.executemany("DELETE FROM tracks WHERE path=?", [(p,) for p in removed])


# ----------------------------------------------------------- reproducciones
def register_play(path: str) -> None:
    now = time.time()
    try:
        with connect() as con:
            con.execute("INSERT INTO plays(path, count, first_ts, last_ts) VALUES (?,1,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET count=count+1, last_ts=excluded.last_ts", (path, now, now))
    except Exception as e:
        logger.warning(f"No se pudo apuntar la reproducción: {e}")


def play_stats() -> dict:
    """{ruta: (veces, última vez)}"""
    try:
        with connect() as con:
            return {r["path"]: (r["count"], r["last_ts"]) for r in con.execute("SELECT * FROM plays")}
    except Exception:
        return {}


def top_played(limit: int = 30) -> list:
    try:
        with connect() as con:
            return [r["path"] for r in con.execute(
                "SELECT path FROM plays WHERE count>0 ORDER BY count DESC, last_ts DESC LIMIT ?", (limit,))]
    except Exception:
        return []


def get_loudness(path: str, mtime: float):
    """Volumen (LUFS) ya medido de una canción, o None si no se midió o el archivo cambió."""
    try:
        with connect() as con:
            row = con.execute("SELECT mtime, lufs FROM loudness WHERE path=?", (path,)).fetchone()
        return float(row["lufs"]) if row and abs(row["mtime"] - mtime) < 1 else None
    except Exception:
        return None


def set_loudness(path: str, mtime: float, lufs: float) -> None:
    try:
        with connect() as con:
            con.execute("INSERT INTO loudness(path, mtime, lufs) VALUES (?,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, lufs=excluded.lufs", (path, mtime, lufs))
    except Exception as e:
        logger.warning(f"No se pudo guardar el volumen medido: {e}")


def clear_plays() -> None:
    with connect() as con:
        con.execute("DELETE FROM plays")


def delete_index() -> None:
    """Borra el índice (se reconstruye solo leyendo las etiquetas otra vez). Las reproducciones se conservan."""
    try:
        with connect() as con:
            con.execute("DELETE FROM tracks")
    except Exception:
        pass
