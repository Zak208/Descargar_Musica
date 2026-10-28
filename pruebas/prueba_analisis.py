"""Análisis de canciones para el modo DJ: tempo y su fiabilidad, energía, intro y final; se guarda en el índice, no se
repite si el archivo no cambia y se hace en segundo plano con un archivo de audio de verdad.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_analisis.py"""
import math
import os
import random
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


from services import tempo, track_analysis
from services.ffmpeg_service import FFmpegService

random.seed(11)


def synth(bpm=124, intro_s=10, body_s=160, outro_s=20):
    """Envolvente de mentira: intro casi en silencio, cuerpo con un golpe en cada pulso y un final que se apaga."""
    frames = []
    period = 600 / bpm
    total = (intro_s + body_s + outro_s) * 10
    next_beat = intro_s * 10
    for i in range(total):
        if i < intro_s * 10:
            level = 0.05
        elif i < (intro_s + body_s) * 10:
            level = 1.0
        else:
            level = max(0.02, 1.0 - (i - (intro_s + body_s) * 10) / (outro_s * 10) * 1.5)
        low = random.randint(20, 60) * level
        mid = random.randint(40, 90) * level
        if i >= next_beat and level >= 0.5:
            low += 150 * level
            mid += 40 * level
            next_beat += period
        elif i >= next_beat:
            next_beat += period
        frames.append((min(255, int(low)), min(255, int(mid)), random.randint(0, 60)))
    return bytes(b for f in frames for b in f)


res = track_analysis.analyze_envelope(synth())
check(f"tempo de 124 detectado (da {res['bpm']})", res["bpm"] is not None and abs(res["bpm"] - 124) / 124 < 0.03)
check(f"con buena confianza ({res['confidence']:.2f})", res["confidence"] >= tempo.MIN_CONFIDENCE)
check(f"intro de unos 10 s (da {res['intro_ms'] / 1000:.1f} s)", 8000 <= res["intro_ms"] <= 13000)
check(f"final de unos 10-20 s (da {res['outro_ms'] / 1000:.1f} s)", 8000 <= res["outro_ms"] <= 23000)
check("duración de 190 s", res["duration_ms"] == 190_000)
check("energía entre 0 y 1", 0 < res["energy"] <= 1)

flat = track_analysis.analyze_envelope(bytes(random.randint(0, 255) for _ in range(3 * 1800)))
check("ruido sin pulso: sin tempo y con poca confianza", flat["bpm"] is None and flat["confidence"] < tempo.MIN_CONFIDENCE)
check("sin envolvente no se inventa nada", track_analysis.analyze_envelope(b"")["bpm"] is None
      and track_analysis.analyze_envelope(b"")["duration_ms"] == 0)
no_intro = track_analysis.analyze_envelope(synth(intro_s=0, outro_s=0))
check(f"canción que empieza fuerte: intro casi 0 (da {no_intro['intro_ms']} ms)", no_intro["intro_ms"] <= 1500)
check("estimate_bpm sigue dando lo mismo que antes", tempo.estimate_bpm(synth()) == res["bpm"])

# Guardar y leer
folder = tempfile.mkdtemp(prefix="analisis_")
dummy = os.path.join(folder, "nota.mp3")
with open(dummy, "wb") as fh:
    fh.write(b"x")
track_analysis.save(dummy, res)
check("lo guardado se lee igual", track_analysis.stored(dummy) == {k: res[k] for k in track_analysis.stored(dummy)})
os.utime(dummy, (time.time() + 100, time.time() + 100))
check("si el archivo cambia, se vuelve a analizar", track_analysis.stored(dummy) is None)

tempo.learn("x.mp3", 128.0)
tempo.learn("x.mp3", 90.0)
check("el tempo del análisis se aprovecha para el fundido (y no se pisa)", tempo.get("x.mp3") == 128.0)


# Con un audio de verdad: golpes secos a 120 BPM durante 75 s, con 8 s de silencio al principio
def make_beat_wav(path, bpm=120, seconds=75, silence=8):
    rate = 22050
    period = int(rate * 60 / bpm)
    samples = []
    for i in range(rate * seconds):
        if i < rate * silence:
            samples.append(0)
            continue
        t = (i - rate * silence) % period
        samples.append(int(20000 * math.exp(-t / 400) * math.sin(2 * math.pi * 80 * t / rate)) if t < 3000 else 0)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", s) for s in samples))


if not FFmpegService.get_ffmpeg_path():
    check("hay FFmpeg para analizar audio de verdad (no se encontró: se salta esta parte)", True)
else:
    beat = os.path.join(folder, "golpes.wav")
    make_beat_wav(beat)
    got, steps = {}, []
    worker = track_analysis.AnalysisWorker([beat, os.path.join(folder, "no_existe.mp3")])
    worker.result.connect(lambda p, r: got.__setitem__(p, r))
    worker.progress.connect(lambda d, t: steps.append((d, t)))
    worker.start()
    check("el análisis en segundo plano termina", wait(lambda: worker.isFinished(), 120))
    app.processEvents()
    found = got.get(beat)
    check(f"audio de verdad: 120 BPM (da {found and found['bpm']})", found is not None and found["bpm"] is not None
          and abs(found["bpm"] - 120) / 120 < 0.03)
    check(f"audio de verdad: intro de unos 8 s (da {found and found['intro_ms']} ms)",
          found is not None and 6000 <= found["intro_ms"] <= 11000)
    check("avisa del progreso (0 de 1 y 1 de 1)", steps == [(0, 1), (1, 1)])
    check("un archivo que no existe no se cuenta ni da error", len(got) == 1)

    again, steps2 = {}, []
    worker2 = track_analysis.AnalysisWorker([beat])
    worker2.result.connect(lambda p, r: again.__setitem__(p, r))
    worker2.progress.connect(lambda d, t: steps2.append((d, t)))
    t0 = time.time()
    worker2.start()
    wait(lambda: worker2.isFinished(), 30)
    app.processEvents()
    check(f"la segunda vez sale del índice al momento ({time.time() - t0:.2f} s)", again.get(beat) == found
          and steps2 == [(0, 0)])

    stopped = track_analysis.AnalysisWorker([os.path.join(folder, f"no{i}.wav") for i in range(3)])
    stopped.cancel()
    stopped.start()
    check("se puede parar (al cerrar el programa)", wait(lambda: stopped.isFinished(), 10))

print("FIN")
