"""Pruebas de robustez: escrituras de JSON a la vez, archivos estropeados, favoritos con el mismo título, copias de
seguridad dañadas, rutas y enlaces peligrosos, escaneo de la biblioteca, descargas que fallan al empezar, instancia única
y cancelación. Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_robustez.py"""
import json
import os
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtWidgets import QApplication

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.01)


import config
from config import APP_DATA_DIR, atomic_write_json, read_json

tmp = Path(tempfile.mkdtemp(prefix="descargador_robusto_"))

# ---------------------------------------------------------------- JSON
target = tmp / "datos.json"
errors = []


def writer(n):
    try:
        for i in range(40):
            atomic_write_json(target, {"n": n, "i": i, "x": "á" * 200})
    except Exception as e:                       # noqa: BLE001
        errors.append(e)


threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
[t.start() for t in threads]
[t.join() for t in threads]
check("seis hilos escribiendo el mismo JSON a la vez no se pisan ni fallan", not errors and read_json(target)["x"] == "á" * 200)
check("no quedan archivos temporales sueltos", not [p for p in tmp.iterdir() if p.suffix == ".tmp"])
check("se guarda una copia .bak del anterior", (tmp / "datos.json.bak").exists())

target.write_text("{esto no es json", encoding="utf-8")
value = read_json(target, {"vacio": True})
check("un JSON estropeado se recupera de la copia .bak", isinstance(value, dict) and "x" in value)
check("y el estropeado se aparta, no se pierde", any(".corrupto-" in p.name for p in tmp.iterdir()))
(tmp / "solo.json").write_text("[[[", encoding="utf-8")
check("sin copia buena se devuelve el valor por defecto", read_json(tmp / "solo.json", {"v": 1}) == {"v": 1})

# ---------------------------------------------------------------- favoritos y listas
from services.playlist_service import PlaylistService as P

cancion_a = {"id": "a1", "title": "Intro", "uploader": "Artista Uno"}
cancion_b = {"id": "b1", "title": "Intro", "uploader": "Artista Dos"}
check("marcar una canción como favorita", P.toggle_favorite(cancion_a) is True)
check("otra con el mismo título pero de otro artista NO está marcada", not P.is_favorite("b1", "Intro", "Artista Dos"))
check("y se puede marcar también", P.toggle_favorite(cancion_b) is True and len(P.get_favorites()) == 2)
check("la misma canción por identificador sigue reconociéndose", P.is_favorite("a1", "otro título", ""))
check("misma canción sin artista conocido se reconoce por el título", P.is_favorite("zz", "Intro", ""))
pid = P.create_playlist("Prueba")
check("las dos caben en una lista", P.add_track_to_playlist(pid, cancion_a) and P.add_track_to_playlist(pid, cancion_b))
check("pero no la misma dos veces", not P.add_track_to_playlist(pid, dict(cancion_a, id="otro")))
check("lists_containing usa la caché y es correcto", P.lists_containing(cancion_a) == {"favorites", pid})

before = P._cache[str(config.FAVORITES_FILE)][1]
P.lists_containing(cancion_b)
check("consultar no relee el archivo (misma copia en memoria)", P._cache[str(config.FAVORITES_FILE)][1] is before)
copia = P.get_favorites()
copia.append({"id": "x"})
check("lo que devuelve get_favorites se puede modificar sin estropear la caché", len(P.get_favorites()) == 2)
data = json.loads(config.FAVORITES_FILE.read_text(encoding="utf-8"))
data.append({"id": "z9", "title": "Fuera del programa", "uploader": "X"})
time.sleep(0.02)
config.FAVORITES_FILE.write_text(json.dumps(data), encoding="utf-8")
check("si el archivo cambia por fuera, la caché se entera", P.is_favorite("z9", ""))

# rutas de archivos que cambian
real = tmp / "cancion.mp3"
real.write_text("x")
P.add_track_to_playlist(pid, {"id": "l1", "title": "Local", "uploader": "Yo", "local_path": str(real)})
check("renombrar el archivo actualiza las listas", P.relocate(str(real), str(tmp / "nueva.mp3")) == 1
      and any(t.get("local_path") == str(tmp / "nueva.mp3") for t in P.get_playlists()[pid]["tracks"]))
check("borrar el archivo quita la ruta pero deja la canción", P.relocate(str(tmp / "nueva.mp3")) == 1
      and not any(t.get("local_path") for t in P.get_playlists()[pid]["tracks"] if t["id"] == "l1"))

# ---------------------------------------------------------------- ajustes
from config import load_settings, save_settings, reset_settings_cache

s = load_settings()
s["prueba"] = 1
save_settings(s)
reset_settings_cache()
check("los ajustes guardados se leen otra vez desde el disco", load_settings().get("prueba") == 1)

# ---------------------------------------------------------------- copia de seguridad dañada
from services import backup_service

good = tmp / "buena.zip"
backup_service.create_backup(good)
bad = tmp / "mala.zip"
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("COPIA.txt", "x")
    z.writestr("playlists.json", "{roto")
before_pl = config.PLAYLISTS_FILE.read_text(encoding="utf-8")
try:
    backup_service.restore_backup(bad)
    ok = False
except ValueError:
    ok = True
check("una copia con un JSON estropeado se rechaza", ok)
check("y no toca las listas actuales", config.PLAYLISTS_FILE.read_text(encoding="utf-8") == before_pl)
check("una copia buena se restaura", backup_service.restore_backup(good) >= 1)

# ---------------------------------------------------------------- enlaces y nombres
from services.youtube_service import is_youtube_url, sanitize_filename
from services.spotify_service import is_spotify_url

check("enlaces de YouTube normales", all(is_youtube_url(u) for u in (
    "https://www.youtube.com/watch?v=abc", "https://music.youtube.com/watch?v=a", "youtu.be/abc", "https://youtu.be/abc?t=3")))
check("un enlace que solo menciona youtube.com NO vale", not is_youtube_url("http://192.168.1.5/?x=youtube.com/")
      and not is_youtube_url("https://youtube.com.malo.es/watch?v=1") and not is_youtube_url("mira youtube.com/"))
check("enlaces de Spotify", is_spotify_url("https://open.spotify.com/track/abc") and not is_spotify_url("http://x/?open.spotify.com/"))
check("nombres reservados de Windows", sanitize_filename("CON") != "CON" and sanitize_filename("nul.mp3") != "nul.mp3")
check("nombres demasiado largos se acortan", len(sanitize_filename("a" * 400)) <= 120)
check("el porcentaje no se pierde en el nombre", "100%" in sanitize_filename("100% Pure Love"))

# ---------------------------------------------------------------- biblioteca
from services.library_service import _inside, load_items_sync
from services import library_db

check("«Music2» no está dentro de «Music»", _inside("C:/Music/a.mp3", "C:/Music") and not _inside("C:/Music2/a.mp3", "C:/Music"))
music = tmp / "musica"
music.mkdir()
with library_db.connect() as con:
    con.execute("INSERT INTO tracks(path, mtime, title, artist, album, duration, tagver) VALUES (?,?,?,?,?,?,?)",
                (str(music / "fantasma.mp3"), 1.0, "F", "A", "", 10, library_db.TAG_VERSION))
    con.execute("INSERT INTO plays(path, count, first_ts, last_ts) VALUES (?,5,1,1)", (str(music / "fantasma.mp3"),))
load_items_sync(str(music))
known = library_db.load_all()
check("si la carpeta está vacía no se borra todo el índice", str(music / "fantasma.mp3") in known)
check("las reproducciones se conservan", library_db.play_stats().get(str(music / "fantasma.mp3"), (0,))[0] == 5)
with library_db.connect() as con:
    check("la base de datos lleva su versión de esquema", con.execute("PRAGMA user_version").fetchone()[0] == library_db.SCHEMA_VERSION)

# ---------------------------------------------------------------- descargas
from services.youtube_service import DownloadWorker

class RutaImposible(DownloadWorker):
    def target_dir(self, artist, album):
        raise PermissionError("sin permisos")

res = []
w = RutaImposible({"id": "v1", "url": "ytsearch1:x", "title": "T", "uploader": "A"}, str(tmp), "320")
w.finished_signal.connect(res.append)
w.start()
w.wait(5000)
pump(0.2)
check("una descarga que falla al empezar avisa igualmente (la cola no se atasca)", len(res) == 1 and res[0]["success"] is False)

from ui.downloads_panel import DownloadsTracker

class Falso:
    def __init__(self):
        from PySide6.QtCore import QObject, Signal
        class S(QObject):
            progress_signal = Signal(dict)
            finished_signal = Signal(dict)
        self.s = S()
        self.progress_signal, self.finished_signal = self.s.progress_signal, self.s.finished_signal
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

tracker = DownloadsTracker()
fw = Falso()
tracker.track(fw, {"title": "T", "uploader": "A", "id": "q"})
key = next(iter(tracker.entries))
tracker.cancel(key)
check("cancelar una descarga en curso llega al proceso", fw.cancelled and tracker.entries[key]["cancelled"])
fw.finished_signal.emit({"success": False, "error": "Descarga cancelada por el usuario"})
check("y queda como cancelada, no como error raro", tracker.entries[key]["error"] == "Descarga cancelada.")
check("las fallidas se pueden reintentar", len(tracker.failed()) == 1 and tracker.entries[key]["info"]["id"] == "q")

# ---------------------------------------------------------------- carriles de tareas pesadas
from services.heavy import heavy_task

order = []
def slow():
    with heavy_task("slow"):
        order.append("slow-in")
        time.sleep(0.6)
        order.append("slow-out")

t = threading.Thread(target=slow)
t.start()
time.sleep(0.15)
t0 = time.time()
with heavy_task():
    waited = time.time() - t0
t.join()
check("una tarea lenta (voz) no bloquea las rápidas (biblioteca)", waited < 0.3)

# ---------------------------------------------------------------- una sola copia
from ui.single_instance import SingleInstance

first = SingleInstance()
second = SingleInstance()
shown = []
first.activated.connect(lambda: shown.append(1))
check("la primera copia se queda con el bloqueo", first.acquire())
check("la segunda no puede abrirse", not second.acquire())
pump(0.6)
check("y avisa a la primera para que se muestre", shown == [1])
first.release()
third = SingleInstance()
check("al cerrar la primera, otra puede abrirse", third.acquire())
third.release()

# ---------------------------------------------------------------- red
from services import network_service
check("los errores de red se reconocen", network_service.is_network_error("getaddrinfo failed"))

print("FIN", flush=True)
os._exit(0)
