"""Grabar la sesión DJ desde la ventana de verdad (con el reproductor de siempre, en silencio): se graba lo que queda de la sesión en
un archivo con su listado, en segundo plano, y se puede cancelar sin dejar nada a medias.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_grabar_mix_ventana.py"""
import math
import os
import struct
import sys
import tempfile
import time
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtWidgets import QApplication

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def wait(cond, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.03)
        if cond():
            return True
    return False


root = tempfile.mkdtemp(prefix="descargador_grabar_")
out_dir = tempfile.mkdtemp(prefix="descargador_salida_")


def make_wav(name, freq, seconds):
    path = os.path.join(root, name)
    rate = 22050
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(rate * seconds)))
    return path


paths = [make_wav(f"cancion{i}.wav", 330 + 55 * i, 36 + 6 * i) for i in range(3)]

from config import update_settings
from services import dj_service, ffmpeg_service
from ui.main_window import MainWindow

update_settings(dj_engine=False)       # la ventana toca con el reproductor de siempre; la grabación usa su propia sesión del motor
dj_service.set_root(root)
w = MainWindow()
w.audio_output.setVolume(0)
w.show()
wait(lambda: False, 1.0)
w.open_dj_page()
wait(lambda: w._dj_summary is not None)
wait(lambda: w._dj_an_worker is None, 120)
for i, p in enumerate(paths):
    w._dj_analysis[p] = {"bpm": 120.0, "intro_ms": 2000, "outro_ms": 12000, "duration_ms": (36 + 6 * i) * 1000, "energy": 0.5}

if not ffmpeg_service.FFmpegService.get_ffmpeg_path():
    check("no hay FFmpeg: se salta esta prueba", True)
    print("FIN")
    sys.exit(0)

w.dj_record_ask()
check("sin sesión DJ no se graba nada (solo se avisa)", not w.dj_recording())
w.start_dj_session()
check("empieza la sesión", wait(lambda: w.dj_session_active()))
tracks = w.dj_record_tracks()
check("se grabarían la canción de ahora y las que quedan, en orden", len(tracks) == 3 and tracks[0] == w.current_item_info["local_path"])

out = os.path.join(out_dir, "mix.wav")
check("empieza la grabación", w.dj_record_session(out) and w.dj_recording())
check("no se puede empezar otra a la vez", not w.dj_record_session(os.path.join(out_dir, "otra.wav")))
check("termina", wait(lambda: not w.dj_recording(), 120))
check("el archivo existe y dura más que la mayor de las canciones", os.path.isfile(out) and os.path.getsize(out) > 44100 * 2 * 60)
check("con su listado de canciones (txt) y su .cue", wait(lambda: os.path.isfile(os.path.join(out_dir, "mix.txt"))
                                                        and os.path.isfile(os.path.join(out_dir, "mix.cue")), 10))
text = open(os.path.join(out_dir, "mix.txt"), encoding="utf-8").read()
check("el listado nombra las 3 canciones", all(os.path.splitext(os.path.basename(p))[0] in text for p in paths))
check("sin archivo .part a medias", not any(f.endswith(".part") for f in os.listdir(out_dir)))

# cancelar
out2 = os.path.join(out_dir, "cancelado.wav")
w.dj_record_session(out2)
w.dj_record_cancel()
check("cancelar termina la grabación", wait(lambda: not w.dj_recording(), 60))
check("y no deja ni archivo ni .part", not os.path.exists(out2) and not any(f.endswith(".part") for f in os.listdir(out_dir)))
check("formato no admitido: se rechaza", not w.dj_record_session(os.path.join(out_dir, "x.ogg")))
w.player.pause()
w.shutdown_playback_options()
print("FIN")
