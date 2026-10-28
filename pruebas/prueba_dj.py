"""Modo DJ: lectura de la carpeta general (todo, solo la carpeta, una subcarpeta), ajustes que se recuerdan, botón en la
barra superior y arranque de la sesión. Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_dj.py"""
import os
import sys
import tempfile
import time

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


from services import dj_service
from services.dj_service import SOURCE_ALL, SOURCE_ROOT

# Carpeta de mentira: 2 sueltas, Reguetón (con una subcarpeta dentro), Drill, una vacía y archivos que no son audio
root = tempfile.mkdtemp(prefix="dj_prueba_")
files = ["suelta1.mp3", "suelta2.mp4", "notas.txt",
         os.path.join("Reguetón", "a.mp3"), os.path.join("Reguetón", "b.m4a"), os.path.join("Reguetón", "Viejo", "c.mp3"),
         os.path.join("Drill", "d.wav"), os.path.join("Drill", "portada.jpg")]
for rel in files:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")
os.makedirs(os.path.join(root, "Vacía"))

summary = dj_service.scan(root)
check("se leen los archivos sueltos (mp3 y mp4)", len(summary["loose"]) == 2)
check("cada subcarpeta cuenta lo que tiene dentro, también sus subcarpetas", len(summary["folders"].get("Reguetón", [])) == 3)
check("lo que no es audio no cuenta", len(summary["folders"].get("Drill", [])) == 1)
check("las subcarpetas vacías no aparecen", "Vacía" not in summary["folders"])
check("toda la carpeta: 6 canciones", dj_service.count_all(summary) == 6)
check("solo la carpeta general: las 2 sueltas", len(dj_service.tracks_for(summary, SOURCE_ROOT)) == 2)
check("una subcarpeta: solo lo suyo", sorted(os.path.basename(p) for p in dj_service.tracks_for(summary, "Drill")) == ["d.wav"])
check("una subcarpeta que ya no existe: suena todo", len(dj_service.tracks_for(summary, "Borrada")) == 6)
check("sin resumen no hay canciones", dj_service.tracks_for(None, SOURCE_ALL) == [])
no_loose = dict(summary, loose=[])
check("«solo la carpeta general» sin archivos sueltos pasa a toda la carpeta",
      dj_service.effective_source(no_loose, SOURCE_ROOT) == SOURCE_ALL and len(dj_service.tracks_for(no_loose, SOURCE_ROOT)) == 4)
check("una subcarpeta borrada pasa a toda la carpeta", dj_service.effective_source(summary, "Borrada") == SOURCE_ALL)
check("una carpeta general que ya no existe se avisa", dj_service.scan(os.path.join(root, "no_existe"))["missing"])
check("una carpeta que no existe no da error", dj_service.count_all(dj_service.scan(os.path.join(root, "no_existe"))) == 0)

old_max = dj_service.MAX_FILES
dj_service.MAX_FILES = 3
small = dj_service.scan(root)
check("con una carpeta enorme se deja de buscar y se avisa", small["truncated"] and dj_service.count_all(small) <= 3)
dj_service.MAX_FILES = old_max

# Ajustes
check("por defecto la carpeta general es la de descargas", dj_service.get_root() == str(dj_service.get_download_dir()))
check("por defecto suena toda la carpeta", dj_service.get_source() == SOURCE_ALL)
dj_service.set_root(root)
dj_service.set_source("Drill")
check("se recuerda la carpeta general", dj_service.get_root() == root)
check("se recuerda qué suena", dj_service.get_source() == "Drill")
dj_service.set_root(root)
check("al cambiar de carpeta general vuelve a sonar todo", dj_service.get_source() == SOURCE_ALL)

# Canciones bloqueadas
everything = dj_service.tracks_for(summary, SOURCE_ALL)
check("sin bloqueadas no se quita nada", dj_service.without_blocked(everything) == everything)
dj_service.block(everything[0])
dj_service.block(everything[0])
check("bloquear la misma dos veces cuenta una", len(dj_service.get_blocked()) == 1)
check("la bloqueada no entra", everything[0] not in dj_service.without_blocked(everything)
      and len(dj_service.without_blocked(everything)) == 5)
check("aunque la ruta se escriba con otras mayúsculas", len(dj_service.without_blocked([everything[0].upper()])) == 0
      if os.name == "nt" else True)
dj_service.unblock_all()
check("desbloquear todas", not dj_service.get_blocked())

# Lectura en segundo plano
worker = dj_service.DjScanWorker(root)
got = []
worker.ready.connect(got.append)
worker.start()
t0 = time.time()
while not got and time.time() - t0 < 10:
    pump(0.05)
check("la carpeta se lee en segundo plano", bool(got) and dj_service.count_all(got[0]) == 6)

# Botón en la barra superior
from ui.topbar import TopBar
bar = TopBar()
pressed = []
bar.dj_clicked.connect(lambda: pressed.append(1))
bar.btn_dj.click()
check("la barra superior tiene el botón DJ y avisa al pulsarlo", pressed == [1] and bar.btn_dj.text().strip() == "DJ")

# Arranque de la sesión (con una ventana de mentira que solo apunta lo que se le pide)
from ui.dj_mixin import DJ_FADE_SECONDS, DjMixin


class FakeWindow(DjMixin):
    def __init__(self):
        self.init_dj_state()
        self._fade_ms = 0
        self._context, self.current_item_info = [], None
        self.context, self.played, self.notes = None, [], []

    def set_context(self, tracks):
        self._context = list(tracks)
        self.context = self._context

    def switch_to_page(self, index):
        pass

    def _local_track_info(self, path, meta=None):
        return {"local_path": path, "title": os.path.basename(path)}

    def set_fade_seconds(self, s):
        self._fade_ms = s * 1000

    def crossfade_ms(self):
        return 0

    def _play_entry(self, info, pixmap=None, crossfade_ms=0):
        self.played.append(info["local_path"])

    def notify(self, text):
        self.notes.append(text)


win = FakeWindow()
win._dj_summary = dj_service.scan(root)
dj_service.set_source("Reguetón")
win.start_dj_session()
check("la sesión usa solo la subcarpeta elegida", win.context is not None and len(win.context) == 3)
check("empieza a sonar la primera de la lista", win.played == [win.context[0]["local_path"]])
check("si el fundido estaba apagado, se enciende", win._fade_ms == DJ_FADE_SECONDS * 1000)
dj_service.set_source(SOURCE_ROOT)
win._dj_summary = {"root": root, "loose": [], "folders": {}, "truncated": False}
win.played.clear()
win.start_dj_session()
check("sin canciones no suena nada y se avisa", not win.played and "No hay canciones" in win.notes[-1])

print("FIN")
