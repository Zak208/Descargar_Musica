"""Pruebas de las descargas: elegir la versión correcta, comprobar el archivo, reintentos, carpetas, cola con pausa,
espacio en disco y actualización del motor de descargas.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_descargas.py"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

app = QApplication([])
from services import storage_service, update_service, youtube_service, ytdlp_loader
from services.ffmpeg_service import FFmpegService
from services.youtube_service import DownloadWorker, rank_candidates, verify_download


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


good_src = sorted(glob.glob(os.path.expanduser("~/Music/Canciones_YouTube/*.mp3")))[1]
import mutagen
good_len = int(mutagen.File(good_src).info.length)
tmp = Path(tempfile.mkdtemp(prefix="desc_"))
clip = str(tmp / "clip.mp3")
subprocess.run([FFmpegService.get_ffmpeg_path(), "-y", "-v", "error", "-i", good_src, "-t", "12", "-c", "copy", clip], check=True)
clip_len = int(mutagen.File(clip).info.length)

# ---- elegir candidatos
entries = [{"id": "a", "duration": 400}, {"id": "b", "duration": 215}, {"id": "c", "duration": 205}, {"id": "d"}]
ranked = rank_candidates(entries, 210)
check("candidatos: primero los de duración parecida, en el orden de YouTube", ranked[0].endswith("=b") and ranked[1].endswith("=c"))
check("candidatos: los que no se parecen van detrás", ranked[-1].endswith("=a") or ranked[-1].endswith("=d"))

# ---- comprobar el archivo
check("comprobación: archivo correcto", verify_download(good_src, good_len)[0])
ok, why = verify_download(good_src, good_len + 120)
check("comprobación: duración muy distinta se rechaza", not ok and "esperaban" in why)
check("comprobación: sin duración esperada se acepta", verify_download(good_src, 0)[0])
empty = tmp / "vacio.mp3"
empty.write_bytes(b"x" * 100)
check("comprobación: archivo vacío se rechaza", not verify_download(str(empty), 0)[0])
check("comprobación: archivo inexistente se rechaza", not verify_download(str(tmp / "no.mp3"), 0)[0])


# ---- descarga completa con un yt-dlp simulado
class FakeYDL:
    plan = []            # [("ok", archivo) | ("error", texto)] por intento de descarga
    searched = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=True):
        if not download:
            FakeYDL.searched.append(url)
            return {"entries": [{"id": "malo", "duration": clip_len}, {"id": "bueno", "duration": good_len}]}
        kind, value = FakeYDL.plan.pop(0)
        FakeYDL.downloaded = getattr(FakeYDL, "downloaded", []) + [url]
        if kind == "error":
            raise RuntimeError(value)
        out = self.opts["outtmpl"].replace("%(ext)s", "mp3")
        shutil.copy(value, out)
        return {"id": "x", "ext": "mp3"}

    def prepare_filename(self, info):
        return self.opts["outtmpl"].replace("%(ext)s", "webm")


class FakeModule:
    YoutubeDL = FakeYDL


real_get = ytdlp_loader.get
ytdlp_loader.get = lambda: FakeModule
DownloadWorker._embed_lyrics = staticmethod(lambda *a: None)


def run_worker(item, **kw):
    results = []
    out = tmp / f"salida_{len(os.listdir(tmp))}"
    w = DownloadWorker(item, str(out), "320", **kw)
    w.finished_signal.connect(results.append)
    w.run()
    return results[0], out


item = {"id": "t1", "title": "Tema", "uploader": "Artista", "album": "Disco", "url": "ytsearch1:Artista Tema",
        "duration_secs": good_len, "thumbnail": ""}
FakeYDL.plan = [("ok", good_src)]
FakeYDL.searched = []
FakeYDL.downloaded = []
res, out = run_worker(item)
check("descarga: se comparan versiones y se baja la que dura lo esperado", res["success"] and FakeYDL.searched
      and FakeYDL.downloaded[0].endswith("bueno") and not res["warning"])
check("descarga: queda como «Artista - Tema.mp3» en la carpeta principal", (out / "Artista - Tema.mp3").is_file())

FakeYDL.plan = [("ok", clip), ("ok", good_src)]
FakeYDL.downloaded = []
bad_first = dict(item, id="t2", title="Tema 2")
orig_cands = DownloadWorker._candidates
DownloadWorker._candidates = lambda self, url, exp: ["https://y/malo", "https://y/bueno"]
res, out = run_worker(bad_first)
check("reintento: si la primera versión no dura lo esperado, prueba otra", res["success"] and not res["warning"]
      and FakeYDL.downloaded == ["https://y/malo", "https://y/bueno"] and verify_download(res["mp3_path"], good_len)[0])
check("reintento: no queda ningún archivo sobrante", [f.name for f in out.iterdir()] == ["Artista - Tema 2.mp3"])

FakeYDL.plan = [("ok", clip), ("ok", clip), ("ok", clip)]
FakeYDL.downloaded = []
DownloadWorker._candidates = lambda self, url, exp: ["https://y/1", "https://y/2", "https://y/3"]
res, out = run_worker(dict(item, id="t3", title="Tema 3"))
check("ninguna coincide: se queda la menos mala, con aviso", res["success"] and "esperaban" in res["warning"]
      and len(list(out.iterdir())) == 1)

FakeYDL.plan = [("error", "ERROR: Video unavailable"), ("ok", good_src)]
FakeYDL.downloaded = []
res, out = run_worker(dict(item, id="t4", title="Tema 4"))
check("reintento: si una versión no está disponible, prueba otra", res["success"] and len(FakeYDL.downloaded) == 2)

FakeYDL.plan = [("error", "getaddrinfo failed")]
FakeYDL.downloaded = []
res, out = run_worker(dict(item, id="t5", title="Tema 5"))
check("sin internet no se reintenta", not res["success"] and len(FakeYDL.downloaded) == 1)

DownloadWorker._candidates = orig_cands
w_art = DownloadWorker(dict(item), str(tmp / "base"), "320", organize="artist")
w_alb = DownloadWorker(dict(item), str(tmp / "base"), "320", organize="artist_album")
w_flat = DownloadWorker(dict(item), str(tmp / "base"), "320", organize="flat")
check("carpetas: todas juntas por defecto", w_flat.target_dir("A", "B") == tmp / "base")
check("carpetas: por artista (el principal)", w_art.target_dir("Bizarrap & Quevedo", "X") == tmp / "base" / "Bizarrap")
check("carpetas: artista y álbum (sin álbum → «Sin álbum»)", w_alb.target_dir("Dib", "") == tmp / "base" / "Dib" / "Sin álbum")
ytdlp_loader.get = real_get

# ---- cola con pausa y espacio en disco
from ui import downloads_mixin
from ui.main_window import MainWindow


class FakeWorker(QObject):
    finished_signal = Signal(dict)
    progress_signal = Signal(dict)
    started = []

    def __init__(self, item, *a, **k):
        super().__init__()
        self.item_info = item

    def start(self):
        FakeWorker.started.append(self.item_info["id"])

    def isRunning(self):
        return False


w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(2.0)
downloads_mixin.DownloadWorker = FakeWorker
w.network.set_forced_offline(False)
storage_free = storage_service.free_disk_bytes
storage_service.free_disk_bytes = lambda p: 500 * 1024 ** 3
items = [dict(item, id=f"q{i}", title=f"Cola {i}", url=f"ytsearch1:q{i}") for i in range(6)]
w.start_batch_download(items)
expected_parallel = w.max_parallel_workers
check("cola: arrancan tantas como permite el equipo", len(FakeWorker.started) == expected_parallel and len(w.batch_queue) == 6 - expected_parallel)
w.pause_batch()
first = list(w._batch_workers)
first[0].finished_signal.emit({"success": True, "mp3_path": "x"})
pump(0.2)
check("pausa: al terminar una no arranca otra", len(FakeWorker.started) == expected_parallel and w.batch_paused)
w.resume_batch()
check("reanudar: vuelve a llenar los huecos", len(FakeWorker.started) > expected_parallel)
total_before = w.batch_total
w.start_batch_download([dict(w.batch_queue[0]), dict(item, id="extra", title="Extra", url="ytsearch1:e")])
check("cola: lo ya encolado no se repite y lo nuevo se suma", w.batch_total == total_before + 1 and "extra" in
      [i["id"] for i in w.batch_queue] + FakeWorker.started + [x.item_info["id"] for x in w._batch_workers])
w.cancel_batch_queue()
check("cancelar la cola vacía lo que esperaba", not w.batch_queue)
for wk in list(w._batch_workers):
    wk.finished_signal.emit({"success": True, "mp3_path": "x"})
pump(0.3)
check("al terminar todas la cola queda libre", not w._batch_workers and not w.batch_queue)

# poco espacio → pregunta antes de empezar
FakeWorker.started.clear()
storage_service.free_disk_bytes = lambda p: 100 * 1024 * 1024
asked = []
downloads_mixin.ask_confirm = lambda *a, **k: asked.append(a[2]) or False
w.start_batch_download([dict(item, id=f"s{i}", title=f"Poco {i}", url=f"ytsearch1:s{i}") for i in range(3)])
check("poco espacio: avisa y respeta el «no»", asked and "libres" in asked[0] and not FakeWorker.started)
downloads_mixin.ask_confirm = lambda *a, **k: True
w.start_batch_download([dict(item, id=f"s{i}", title=f"Poco {i}", url=f"ytsearch1:s{i}") for i in range(3)])
check("poco espacio: con «sí» descarga", len(FakeWorker.started) >= 1)
storage_service.free_disk_bytes = storage_free

# ---- actualización del motor de descargas
check("versiones se comparan bien", ytdlp_loader.parse_version("2026.08.19") > ytdlp_loader.parse_version("2026.03.31")
      and ytdlp_loader.parse_version("2026.10.01") > ytdlp_loader.parse_version("2026.09.30"))
from version import BUNDLED_YTDLP
import yt_dlp
check("la versión de yt-dlp incluida está anotada", BUNDLED_YTDLP == yt_dlp.version.__version__)
fake_zip = tmp / "yt_dlp_falso"
with zipfile.ZipFile(fake_zip, "w") as z:
    z.writestr("yt_dlp/version.py", "__version__ = '2099.01.01'\n")
real_updated = ytdlp_loader.UPDATED
ytdlp_loader.UPDATED = fake_zip
check("se lee la versión de dentro del archivo descargado", ytdlp_loader.updated_version() == "2099.01.01"
      and ytdlp_loader.active_version() in ("2099.01.01", yt_dlp.version.__version__))
ytdlp_loader.UPDATED = real_updated
try:
    tag = update_service.latest_ytdlp_tag()
    check(f"GitHub informa de la última versión de yt-dlp ({tag})", bool(tag) and ytdlp_loader.parse_version(tag) >= ytdlp_loader.parse_version(BUNDLED_YTDLP))
    results = []
    uw = update_service.YtdlpUpdateWorker(tag)
    uw.done.connect(lambda v: results.append(("ok", v)))
    uw.failed.connect(lambda m: results.append(("fallo", m)))
    uw.run()
    check("descarga del motor: se verifica la huella y se guarda", results and results[0] == ("ok", tag)
          and ytdlp_loader.updated_version() == tag)
    ytdlp_loader.remove_updated()
    app_new = update_service.latest_app_version()
    check(f"GitHub informa de la versión de la aplicación ({app_new})", app_new is not None)
except Exception as e:
    print("(sin internet: se omiten las pruebas de actualización)", type(e).__name__)
shutil.rmtree(tmp, ignore_errors=True)
print("FIN")
