"""Fundido entre canciones: el tempo se calcula de la envolvente, el ritmo de la canción que entra se acerca al de la que
sale, y el volumen nunca cae a un hueco. Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_ritmo.py"""
import os
import random
import sys
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


from services import tempo

random.seed(7)


def synth(bpm, secs=200):
    """Envolvente de mentira (graves, medios, agudos cada 0,1 s) con un golpe fuerte en cada pulso."""
    n = int(secs * 10)
    period = 600 / bpm
    low = [random.randint(10, 60) for _ in range(n)]
    mid = [random.randint(20, 90) for _ in range(n)]
    t = 0.0
    while t < n - 1:
        i = int(round(t + random.uniform(-0.3, 0.3)))
        if 0 <= i < n:
            low[i] = min(255, low[i] + random.randint(140, 200))
            mid[i] = min(255, mid[i] + 50)
        t += period
    return bytes(b for i in range(n) for b in (low[i], mid[i], random.randint(0, 80)))


for bpm in (84, 100, 120, 128):
    est = tempo.estimate_bpm(synth(bpm))
    check(f"se detecta un tempo de {bpm} ppm (da {est})", est is not None and abs(est - bpm) / bpm < 0.03)
check("la música sin pulso no da tempo (no se toca nada)", tempo.estimate_bpm(bytes(random.randint(0, 255) for _ in range(7200))) is None)
check("una canción muy corta tampoco", tempo.estimate_bpm(synth(120, secs=30)) is None)

check("120 → 124 ppm: la que entra se frena un poco", abs(tempo.match_rate(120, 124) - 120 / 124) < 1e-6)
check("a 60 ppm (mitad) se entiende como el mismo ritmo y no se toca", tempo.match_rate(120, 60) is None)
check("a 64 ppm (casi la mitad de 126) se ajusta con el doble", tempo.match_rate(126, 61) is not None
      and abs(tempo.match_rate(126, 61) * 61 * 2 - 126) < 1e-6)
check("con más de un 10 % de diferencia no se toca", tempo.match_rate(120, 100) is None and tempo.match_rate(120, 140) is None)
check("si ya son iguales, tampoco", tempo.match_rate(120, 120.5) is None)
check("sin tempo conocido, nada", tempo.match_rate(None, 120) is None and tempo.match_rate(120, None) is None)

# ---------------------------------------------------------------- volumen del fundido
from ui.playback_options import crossfade_levels

samples = [crossfade_levels(i / 50) for i in range(51)]
check("empieza con la canción que sale a todo volumen y la que entra en silencio", samples[0] == (0.0, 1.0))
check("termina con la que entra a todo volumen y la que sale en silencio", abs(samples[-1][0] - 1.0) < 1e-9 and samples[-1][1] < 1e-9)
check("en ningún momento las dos juntas suenan bajo (no hay hueco de volumen)", all(max(i, o) >= 0.58 for i, o in samples))
check("las dos suenan altas a la vez durante el cruce", all(min(i, o) >= 0.55 for i, o in samples[17:36]))
check("la mezcla nunca se pasa de fuerte", all((i * i + o * o) ** 0.5 <= 1.121 for i, o in samples))
check("el volumen de la que entra solo sube y el de la que sale solo baja",
      all(b[0] >= a[0] - 1e-9 and b[1] <= a[1] + 1e-9 for a, b in zip(samples, samples[1:])))

# ---------------------------------------------------------------- en la ventana
from ui import motion
from ui.main_window import MainWindow

motion.set_level(motion.NONE)
w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(1.0)
w.current_item_info = {"local_path": "C:/a.mp3", "title": "A", "uploader": "X"}
tempo._cache["C:/a.mp3"] = 120.0
tempo._cache["C:/b.mp3"] = 124.0
w._begin_crossfade(2000, "C:/b.mp3")
check("al empezar el fundido la canción que entra se frena para llevar el ritmo", abs(w.player.playbackRate() - 120 / 124) < 1e-6)
w._finish_crossfade()
pump(0.3)
check("al terminar vuelve poco a poco a su velocidad", w._rate_back.state().name == "Running" if hasattr(w._rate_back.state(), "name")
      else w._rate_back.state() == w._rate_back.State.Running)
w.set_playback_rate(1.0)
check("si eliges tú la velocidad, el ajuste automático se cancela", not w._xf_matched and w.player.playbackRate() == 1.0)
tempo._cache["C:/c.mp3"] = None
w._finish_crossfade()
w._begin_crossfade(2000, "C:/c.mp3")
check("sin tempo conocido la velocidad no se toca", w.player.playbackRate() == 1.0 and not w._xf_matched)
w._finish_crossfade()

print("FIN", flush=True)
os._exit(0)
