"""Pruebas de las mejoras de calidad: listas M3U, limpieza de títulos con palabras enteras, modo privado, acceso a YouTube
configurable, páginas con nombre y el reconocedor de voz compartido.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_calidad.py"""
import os
import sys
import tempfile
import time
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


from config import load_settings, save_settings

# ---------------------------------------------------------------- limpieza de títulos
from services.title_clean import has_junk, strip_junk
from services.duplicates import normalize_title
from services.youtube_service import clean_youtube_title

check("quita las coletillas de vídeo", strip_junk("Tema [Official Video] (HD)").strip() == "Tema")
check("«Eclipse» no se confunde con «clip»", strip_junk("Tema (Eclipse)") == "Tema (Eclipse)")
check("«(Letra)» y «(Lyrics)» se quitan", strip_junk("A (Letra)").strip() == "A" and strip_junk("A (Lyrics)").strip() == "A")
check("dos canciones distintas ya no cuentan como duplicadas", normalize_title("Song (Eclipse)") != normalize_title("Song"))
check("y las que solo se diferencian en la coletilla, sí", normalize_title("Song (Official Audio)") == normalize_title("Song"))
check("se conservan los remix y colaboraciones", clean_youtube_title("Artista - Tema (Remix) [Official Video]") == ("Artista", "Tema (Remix)"))
check("has_junk", has_junk("Video oficial") and not has_junk("Eclipse total"))

# ---------------------------------------------------------------- M3U
from services import m3u_service
from services.playlist_service import PlaylistService as P

tmp = Path(tempfile.mkdtemp(prefix="descargador_m3u_"))
songs = []
for name in ("Uno.mp3", "Dos.mp3"):
    f = tmp / name
    f.write_bytes(b"\x00" * 64)
    songs.append(f)
pid = P.create_playlist("Mi lista")
P.add_track_to_playlist(pid, {"id": "m1", "title": "Uno", "uploader": "Yo", "local_path": str(songs[0]), "duration_secs": 61})
P.add_track_to_playlist(pid, {"id": "m2", "title": "Dos", "uploader": "Tu", "local_path": str(songs[1])})
P.add_track_to_playlist(pid, {"id": "m3", "title": "Sin descargar", "uploader": "Nadie"})
out = tmp / "salida"
res = m3u_service.export_all(str(out))
check("exporta una lista con sus canciones descargadas", res["listas"] == 1 and res["canciones"] == 2 and res["omitidas"] == 1)
file = out / "Mi lista.m3u8"
text = file.read_text(encoding="utf-8")
check("el archivo es un M3U con título, artista y duración", text.startswith("#EXTM3U") and "#EXTINF:61,Yo - Uno" in text)

(tmp / "relativa.m3u").write_text("#EXTM3U\n#EXTINF:10,Alguien - Tres\nUno.mp3\nhttps://ejemplo.com/radio.mp3\nNoExiste.mp3\nDos.mp3\n",
                                 encoding="utf-8")
check("lee rutas relativas, ignora direcciones de internet y archivos que no existen",
      [os.path.basename(p) for p, _t in m3u_service.parse_m3u(str(tmp / "relativa.m3u"))] == ["Uno.mp3", "Dos.mp3"])
before = len(P.get_playlists())
imp = m3u_service.import_files([str(file), str(tmp / "relativa.m3u")])
check("importa una lista nueva por archivo", imp["listas"] == 2 and imp["canciones"] == 4 and len(P.get_playlists()) == before + 2)

# ---------------------------------------------------------------- modo privado
from services import lyrics_service, network_service

s = load_settings()
s["private_mode"] = True
save_settings(s)
check("el modo privado se lee de los ajustes", network_service.private_mode())
called = []
real_fetch = lyrics_service.fetch_lyrics
lyrics_service.fetch_lyrics = lambda *a, **k: called.append(1)
errors, results = [], []
worker = lyrics_service.LyricsWorker("Titulo", "Artista", "clave-privada")
worker.lyrics_error.connect(errors.append)
worker.lyrics_ready.connect(results.append)
worker.start()
worker.wait(5000)
pump(0.2)
check("en modo privado no se buscan letras en internet", not called and errors and "privado" in errors[0].lower())
s = load_settings()
s["private_mode"] = False
save_settings(s)
lyrics_service.fetch_lyrics = real_fetch

# ---------------------------------------------------------------- acceso a YouTube
from services.youtube_service import yt_access_options

check("por defecto se usan los clientes android y web", yt_access_options()["extractor_args"]["youtube"]["player_client"] == ["android", "web"])
check("al reintentar se prueba justo lo contrario", "extractor_args" not in yt_access_options(alternate=True))
s = load_settings()
s["yt_client"] = "auto"
s["cookies_browser"] = "firefox"
save_settings(s)
check("en automático no se fuerza ningún cliente y se pueden usar las cookies",
      "extractor_args" not in yt_access_options() and yt_access_options()["cookiesfrombrowser"] == ("firefox",))
s["cookies_browser"] = "navegador-raro"
save_settings(s)
check("un navegador desconocido se ignora", "cookiesfrombrowser" not in yt_access_options())
s["yt_client"], s["cookies_browser"] = "android_web", ""
save_settings(s)

# ---------------------------------------------------------------- páginas con nombre
from ui.pages import Page

check("las páginas son enteros con nombre", Page.HOME == 0 and Page.RESULTS == 1 and Page.LIBRARY == 5 and int(Page.LIST) == 4)

# ---------------------------------------------------------------- reconocedor de voz compartido
from services import transcribe_service as T

class Dueno:
    is_cancelled = False
    _proc = None

work = tempfile.mkdtemp(prefix="descargador_voz_")
try:
    T.listen(str(songs[0]), work, "x", Dueno())
    ok = False
except T.SpeechError as e:
    ok = "reconocedor" in str(e).lower()
check("sin el reconocedor instalado, avisa con un mensaje claro", ok)

# ---------------------------------------------------------------- ventana: ajustes nuevos
from ui.main_window import MainWindow

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(1.2)
sd = w.settings_dialog
check("Ajustes tiene el modo privado, el acceso a YouTube y las listas M3U",
      sd.chk_private is not None and sd.yt_client_combo.count() == 2 and sd.cookies_combo.count() >= 4
      and "M3U" in sd.btn_export_m3u.text() and "M3U" in sd.btn_import_m3u.text())
sd.chk_private.setChecked(True)
pump(0.1)
check("al activar el modo privado se guarda", load_settings().get("private_mode") is True)
sd.chk_private.setChecked(False)
sd.yt_client_combo.setCurrentIndex(1)
check("y el modo de acceso a YouTube también", load_settings().get("yt_client") == "auto")
sd.yt_client_combo.setCurrentIndex(0)
check("la ventana principal se divide en mezclas por tema", all(hasattr(w, n) for n in (
    "check_updates", "generate_lyrics", "save_session", "set_high_contrast", "on_eq_changed", "toast_margin")))

print("FIN", flush=True)
os._exit(0)
