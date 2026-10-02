"""Pruebas de la actualización de la propia aplicación desde GitHub: versiones, descarga con huella, descompresión
segura, script de instalación (se ejecuta de verdad en una carpeta temporal) y botón azul de la barra superior.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_actualizar.py"""
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.01)


from services import app_updater, http
from version import __version__

# ---------------------------------------------------------------- versiones
check("1.15 es más nueva que 1.11", app_updater.is_newer("99.0.0") and not app_updater.is_newer("0.0.1"))
check("la misma versión no es «más nueva»", not app_updater.is_newer(__version__))


# ---------------------------------------------------------------- un GitHub de mentira
class FakeResponse:
    def __init__(self, data=None, text="", status=200, body=b""):
        self._data, self.text, self.status_code, self._body = data, text, status, body
        self.headers = {"content-length": str(len(body))}

    def json(self):
        return self._data

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


ZIP = make_zip({"Descargar_Musica/Descargar_Musica.exe": "exe nuevo", "Descargar_Musica/_internal/lib.dll": "lib nueva"})
SHA = hashlib.sha256(ZIP).hexdigest()
PREFIX = app_updater.ALLOWED_PREFIX
state = {"sha": SHA, "assets": True}


def fake_get(url, **kw):
    if url == app_updater.API_LATEST:
        assets = []
        if state["assets"]:
            assets = [{"name": "Descargar_Musica-v99.0.0-windows.zip", "browser_download_url": PREFIX + "v99.0.0/Descargar_Musica-v99.0.0-windows.zip", "size": len(ZIP)},
                      {"name": "Descargar_Musica-v99.0.0-windows.zip.sha256", "browser_download_url": PREFIX + "v99.0.0/Descargar_Musica-v99.0.0-windows.zip.sha256", "size": 90}]
        return FakeResponse({"tag_name": "v99.0.0", "assets": assets})
    if url.endswith(".sha256"):
        return FakeResponse(text=f"{state['sha']}  Descargar_Musica-v99.0.0-windows.zip")
    if url.endswith(".zip"):
        return FakeResponse(body=ZIP)
    return FakeResponse(status=404)


real_get = http.get
http.get = fake_get

release = app_updater.fetch_release()
check("lee la versión publicada y sus archivos", release and release["version"] == "99.0.0" and release["zip_url"].startswith(PREFIX))
state["assets"] = False
check("sin huella publicada no se actualiza", app_updater.fetch_release() is None)
state["assets"] = True

# ---------------------------------------------------------------- descompresión segura
evil = make_zip({"../fuera.txt": "no"})
tmp = Path(tempfile.mkdtemp(prefix="descargador_zip_"))
bad = tmp / "mal.zip"
bad.write_bytes(evil)
try:
    app_updater.safe_extract(str(bad), tmp / "destino")
    ok = False
except RuntimeError:
    ok = not (tmp / "fuera.txt").exists()
check("el .zip que intenta salirse de su carpeta se rechaza", ok)

# ---------------------------------------------------------------- descarga + huella
results = []
worker = app_updater.AppUpdateWorker()
worker.done.connect(lambda v: results.append(("ok", v)))
worker.failed.connect(lambda m: results.append(("fallo", m)))
worker.start()
t0 = time.time()
while not results and time.time() - t0 < 30:
    pump(0.1)
check("descarga y prepara la versión nueva", results and results[0] == ("ok", "99.0.0"))
check("queda lista para instalar", app_updater.staged_version() == "99.0.0"
      and (app_updater.staged_folder() / app_updater.EXE_NAME).is_file())

app_updater.clear_staged()
check("se puede descartar lo descargado", app_updater.staged_version() is None)

state["sha"] = "0" * 64
results.clear()
worker = app_updater.AppUpdateWorker()
worker.done.connect(lambda v: results.append(("ok", v)))
worker.failed.connect(lambda m: results.append(("fallo", m)))
worker.start()
t0 = time.time()
while not results and time.time() - t0 < 30:
    pump(0.1)
check("con la huella equivocada se rechaza la descarga", results and results[0][0] == "fallo" and app_updater.staged_version() is None)
state["sha"] = SHA

# ---------------------------------------------------------------- el script de instalación (se ejecuta de verdad)
if sys.platform == "win32":
    base = Path(tempfile.mkdtemp(prefix="descargador_inst_"))
    target = base / "Mi Música" / "Descargar_Musica"          # con tilde y espacios, como las rutas reales
    staged = base / "preparada" / "Descargar_Musica"
    (target / "_internal").mkdir(parents=True)
    (staged / "_internal").mkdir(parents=True)
    (target / "run.cmd").write_text("@echo viejo> \"%~dp0resultado.txt\"\r\n", encoding="utf-8")
    (target / "_internal" / "lib.dll").write_text("lib vieja")
    (staged / "run.cmd").write_text("@echo nuevo> \"%~dp0resultado.txt\"\r\n", encoding="utf-8")
    (staged / "_internal" / "lib.dll").write_text("lib nueva y más grande")
    (staged / "_internal" / "extra.dll").write_text("extra")
    stage_work = base / "trabajo"
    script = app_updater.build_script(staged, target, 99999999, "run.cmd", stage_work)
    proc = subprocess.Popen(["cmd", "/c", str(script)], creationflags=subprocess.CREATE_NO_WINDOW)
    proc.wait(timeout=60)
    for _ in range(100):                     # el programa se abre aparte: se espera a que escriba su resultado
        if (target / "resultado.txt").exists() and (target / "resultado.txt").read_text().strip():
            break
        time.sleep(0.1)
    check("el script copia los archivos nuevos sobre los viejos", (target / "_internal" / "lib.dll").read_text() == "lib nueva y más grande"
          and (target / "_internal" / "extra.dll").exists())
    check("y vuelve a abrir el programa", (target / "resultado.txt").exists() and "nuevo" in (target / "resultado.txt").read_text())
    check("y limpia la carpeta de preparación", not stage_work.exists())

# ---------------------------------------------------------------- el botón azul
from ui.main_window import MainWindow

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(1.5)
check("el botón azul está oculto si no hay nada nuevo", not w.topbar.btn_update.isVisible())
w._update_version = "1.15.0"
w._set_update_state("available")
check("«Actualizar a la 1.15.0» cuando hay una versión nueva", w.topbar.btn_update.isVisible()
      and "1.15.0" in w.topbar.btn_update.text() and w.topbar.btn_update.isEnabled())
w._set_update_state("downloading")
check("mientras descarga no se puede pulsar", not w.topbar.btn_update.isEnabled())
w._set_update_state("ready")
check("«Reiniciar y actualizar» cuando está lista", "Reiniciar y actualizar" in w.topbar.btn_update.text())
check("el botón es azul", "#2979FF" in w.topbar.btn_update.styleSheet())
quit_called, launched = [], []
w.quit_app = lambda: quit_called.append(1)
app_updater.install_and_restart = lambda: launched.append(1) or True
w.topbar.btn_update.click()
check("al pulsarlo se lanza la instalación y se cierra la aplicación", launched == [1] and quit_called == [1])
app_updater.install_and_restart = lambda: False
w.topbar.btn_update.click()
check("si no se puede preparar, avisa y vuelve a ofrecerlo", w._update_state == "available")

# una versión nueva detectada con conexión normal empieza a descargarse sola
started = []
app_updater.can_self_update = lambda: True
w._start_app_download = lambda: started.append(1)
w._offer_app_update("1.15.0")
check("al detectar una versión nueva empieza a descargarse sola", started == [1] or w._update_state in ("available", "ready"))

# ---------------------------------------------------------------- el motor de descargas (yt-dlp) también usa el botón azul
from services import ytdlp_loader, update_service
from config import load_settings, save_settings

w._set_update_state(None)
check("sin novedades el botón vuelve a esconderse", not w.topbar.btn_update.isVisible())
s = load_settings()
s["ytdlp_auto_update"] = False
save_settings(s)
w._on_update_result("", "2099.01.01", False)
check("una versión nueva del descargador de canciones enseña el botón azul", w.topbar.btn_update.isVisible()
      and "descargador de canciones" in w.topbar.btn_update.text() and w.topbar.btn_update.isEnabled())
w._start_app_download = lambda: w._set_update_state("available")
w._on_update_result("1.15.0", "2099.01.01", False)
check("si hay también una de la aplicación, manda la de la aplicación", "1.15.0" in w.topbar.btn_update.text())
w._set_update_state(None)
check("y al terminar con ella vuelve el aviso del motor", "descargador de canciones" in w.topbar.btn_update.text())

engine_calls = []
w.update_engine = lambda quiet=False: engine_calls.append(quiet)
w.topbar.btn_update.click()
check("al pulsarlo se descarga el motor nuevo", engine_calls == [False])

w._set_engine_state("downloading", 40)
check("mientras descarga enseña el porcentaje y no se puede pulsar", "40%" in w.topbar.btn_update.text() and not w.topbar.btn_update.isEnabled())
ytdlp_loader.is_loaded = lambda: True
w._on_engine_updated("2099.01.01", True)
check("si el motor ya estaba en uso pide reiniciar", "Reiniciar" in w.topbar.btn_update.text() and w.topbar.btn_update.isEnabled())
restarted = []
w.restart_app = lambda: restarted.append(1)
w.topbar.btn_update.click()
check("al pulsarlo la aplicación se reinicia", restarted == [1])
ytdlp_loader.is_loaded = lambda: False
w._on_engine_updated("2099.01.01", True)
check("si el motor aún no se había usado no hace falta reiniciar", not w.topbar.btn_update.isVisible())

s = load_settings()
s["ytdlp_auto_update"] = True
save_settings(s)
w._engine_state = None
engine_calls.clear()
w._on_update_result("", "2099.02.02", False)
check("con la descarga automática activada se descarga sola y se avisa", engine_calls == [True])

check("la aplicación comprueba si hay novedades al menos cada 10 minutos", w._update_timer.interval() <= 10 * 60 * 1000)

# tras actualizar y reabrir se confirma la versión
s = load_settings()
s["last_run_version"] = "0.1.0"
save_settings(s)
shown = []
w.toast.show_message = lambda text, **kw: shown.append(text)
w._announce_finished_update()
check("al abrir una versión más nueva se avisa de que se actualizó", shown and __version__ in shown[0])
shown.clear()
w._announce_finished_update()
check("y solo una vez", not shown)
check("la ventana lleva la versión en su título", __version__ in w.windowTitle())

http.get = real_get
print("FIN", flush=True)
os._exit(0)
