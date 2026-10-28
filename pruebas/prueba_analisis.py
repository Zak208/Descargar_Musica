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

# Bordes limpios: 20 s de silencio, 260 s de música, 20 s de silencio (el suavizado no debe retrasar la intro ni adelantar el final)
edge = bytes(b for i in range(3000) for b in ((0, 0, 0) if i < 200 or i >= 2800 else (200, 200, 50)))
er = track_analysis.analyze_envelope(edge)
check(f"intro con bordes limpios: 20 s ±0,6 (da {er['intro_ms'] / 1000:.1f})", abs(er["intro_ms"] - 20000) <= 600)
check(f"final con bordes limpios: 20 s ±0,6 (da {er['outro_ms'] / 1000:.1f})", abs(er["outro_ms"] - 20000) <= 600)

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

# Un fallo al leer el audio no se guarda para siempre: se reintenta
from services import envelope
good_path = os.path.join(folder, "falla.mp3")
with open(good_path, "wb") as fh:
    fh.write(b"x")
real_compute, real_path = envelope.compute, FFmpegService.get_ffmpeg_path
FFmpegService.get_ffmpeg_path = staticmethod(lambda: "ffmpeg")
envelope.compute = lambda path, timeout=240: None
check("si FFmpeg no consigue leer la canción, no hay análisis", track_analysis.analyze(good_path) is None)
check("y no se guarda nada (se reintentará)", track_analysis.stored(good_path) is None)
envelope.compute = real_compute
FFmpegService.get_ffmpeg_path = real_path

tempo.set_bpm("x.mp3", 128.0)
check("el tempo del análisis se aprovecha para el fundido", tempo.get("x.mp3") == 128.0 and tempo.known("x.mp3"))
tempo.remember("x.mp3", synth(100))
check("lo calculado después no pisa lo que ya se decidió", tempo.get("x.mp3") == 128.0)
tempo.set_bpm("x.mp3", 90.0)
check("una corrección a mano sí pisa lo anterior", tempo.get("x.mp3") == 90.0)

# Regla de ventana por género: los tempos se confunden por octavas
check("ventana de reguetón: 180 pasa a 90", tempo.fold_for_genre(180.0, "Reggaeton") == 90.0)
check("ventana de reguetón: 70 pasa a 140 y 95 se queda", tempo.fold_for_genre(70.0, "Urbano latino") == 140.0
      and tempo.fold_for_genre(95.0, "Reguetón") == 95.0)
check("ventana de trap y drill: 75 pasa a 150", tempo.fold_for_genre(75.0, "Trap") == 150.0
      and tempo.fold_for_genre(72.0, "UK Drill") == 144.0 and tempo.fold_for_genre(140.0, "Drill") == 140.0)
check("un género que no se conoce no se toca", tempo.fold_for_genre(75.0, "Pop") == 75.0 and tempo.fold_for_genre(75.0, "") == 75.0)
check("sin tempo no se inventa nada", tempo.fold_for_genre(None, "Trap") is None)
check("«Reggaetón» con tilde y doble g también cuenta", tempo.fold_for_genre(180.0, "Reggaetón") == 90.0
      and tempo.fold_for_genre(70.0, "REGGAETON") == 140.0)
check("«Música urbana» y «Urbano latino» cuentan, «Urban» (inglés) no", tempo.fold_for_genre(70.0, "Música urbana") == 140.0
      and tempo.fold_for_genre(70.0, "Urbano latino") == 140.0 and tempo.fold_for_genre(70.0, "Urban") == 70.0)
check("«trap» solo como palabra entera: «Contrapunto» o «Strap» no", tempo.fold_for_genre(75.0, "Contrapunto") == 75.0
      and tempo.fold_for_genre(75.0, "Strap") == 75.0 and tempo.fold_for_genre(75.0, "Hip-Hop/Trap") == 150.0)
check("un género que no es texto no da error", tempo.fold_for_genre(75.0, 123) == 75.0 and tempo.fold_for_genre(75.0, None) == 75.0)
check("tempos que no son números finitos vuelven tal cual (y no se cuelga)", tempo.fold_bpm(float("inf"), 80, 160) == float("inf")
      and tempo.fold_bpm(float("nan"), 80, 160) != tempo.fold_bpm(float("nan"), 80, 160) and tempo.fold_bpm(-5.0, 80, 160) == -5.0)
tempo.set_bpm("olvidar.mp3", 100.0)
tempo.forget("olvidar.mp3")
tempo.forget("olvidar.mp3")
check("olvidar un tempo (también si ya no estaba): el fundido lo calculará", not tempo.known("olvidar.mp3"))
check("una ventana de menos del doble no se aplica (no habría un solo sitio)", tempo.fold_bpm(70.0, 100.0, 150.0) == 70.0)
check("toda la gama de 70 a 180 cae dentro de cada ventana", all(
    80 <= tempo.fold_for_genre(b / 2, "reggaeton") < 160 and 100 <= tempo.fold_for_genre(b / 2, "trap") < 200
    for b in range(140, 361)))
fast = synth(bpm=180)
slow = track_analysis.analyze_envelope(fast)
check(f"sin género, un tempo de 180 se queda como está (da {slow['bpm']})", slow["bpm"] is not None and abs(slow["bpm"] - 180) / 180 < 0.03)
reg = track_analysis.analyze_envelope(fast, "Reggaeton")
check(f"con género reguetón, el 180 pasa a 90 (da {reg['bpm']})", reg["bpm"] is not None and abs(reg["bpm"] - 90) / 90 < 0.03)
check("el género no cambia la confianza", reg["confidence"] == slow["confidence"])


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
    from services import key_detect
    check("el análisis completo trae el tono (los golpes secos no tienen armonía: «» o un tono dudoso)",
          found is not None and (found["tone"] is not None if key_detect.available() else True))
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
