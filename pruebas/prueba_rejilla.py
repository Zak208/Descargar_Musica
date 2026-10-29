"""Rejilla de golpes (fase 11): tempo exacto, primer golpe y golpe fuerte del compás con audio sintético (80 a 160 BPM, con
decimales, con intros largas sin golpes, hi-hats y ruido), un tempo que deriva, ruido sin pulso, sin numpy, velocidad, y las
canciones reales de la carpeta de música (solo lectura, informativo: no hay referencia, así que no hacen fallar la prueba
salvo que den una excepción). Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_rejilla.py
Con REJILLA_SIN_REALES=1 se salta el apartado de las canciones reales (que es el más lento)."""
import glob
import os
import sys
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import beatgrid, envelope, key_detect, tempo
from services.mix_types import BeatGrid

SR = beatgrid.SAMPLE_RATE
MUSIC = r"C:\Users\juego\Music\Canciones_YouTube"


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


# ------------------------------------------------------------------ audio sintético
def kick(amp):
    t = np.arange(int(0.3 * SR)) / SR
    freq = 50 + 90 * np.exp(-t * 30)                                       # bombo: barrido de 140 a 50 Hz que se apaga
    return (amp * np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 11)).astype(np.float32)


def burst(amp, dur, rng, highpass=True):
    n = int(dur * SR)
    x = rng.standard_normal(n).astype(np.float32)
    if highpass:
        x = np.diff(x, prepend=0).astype(np.float32)
    return amp * x * np.exp(-np.arange(n) / SR / (dur / 4))


def song(bpm, first_beat, seconds, rng, drift=0.0, intro="silence", hats=True, snare=True, noise=0.02, soft=0.6):
    """Canción 4x4: bombo fuerte (1,0) en el primer golpe de cada compás y más flojo (`soft`) en los otros tres, caja en el 2 y
    el 4, hi-hats a contratiempo y ruido de fondo. Con `drift` el tempo oscila ese tanto por uno (un ciclo en toda la canción).
    Devuelve (audio, instantes verdaderos de los golpes). Los golpes empiezan en `first_beat`; antes hay silencio, una nota
    larga ("pad") o ruido flojo ("noise")."""
    n = int(seconds * SR)
    y = np.zeros(n + SR, dtype=np.float32)
    beats = []
    t, k = first_beat, 0
    while t < seconds - 0.4:
        beats.append(t)
        i = int(round(t * SR))
        ev = kick(1.0 if k % 4 == 0 else soft)
        y[i:i + len(ev)] += ev
        if snare and k % 4 in (1, 3):
            ev = burst(0.35, 0.12, rng, highpass=False)
            y[i:i + len(ev)] += ev
        if hats:
            j = int(round((t + 30.0 / bpm) * SR))
            ev = burst(0.25, 0.05, rng)
            y[j:j + len(ev)] += ev
        t += 60.0 / (bpm * (1 + drift * np.sin(2 * np.pi * (t - first_beat) / (seconds - first_beat))))
        k += 1
    m = int(first_beat * SR)
    if intro == "pad":
        tt = np.arange(m) / SR
        y[:m] += (0.15 * np.sin(2 * np.pi * 220 * tt) + 0.1 * np.sin(2 * np.pi * 330.5 * tt)).astype(np.float32)
    elif intro == "noise":
        y[:m] += 0.05 * rng.standard_normal(m).astype(np.float32)
    y = y[:n] + noise * rng.standard_normal(n).astype(np.float32)
    return y.astype(np.float32), np.array(beats)


def distance_to(times, t):
    """Distancia (s) de t al instante más cercano de `times`."""
    return float(np.min(np.abs(np.asarray(times) - t)))


def judge(grid, beats, true_bpm):
    """(error de tempo en %, error del primer golpe en ms respecto al golpe más cercano, error del compás en ms respecto al
    comienzo de compás más cercano, lo lejos que cae el primer golpe del verdadero en golpes)."""
    bar_error = distance_to(beats[::4], grid.bar_time(0))
    return ((grid.bpm / true_bpm - 1.0) * 100.0, distance_to(beats, grid.first_beat_s) * 1000.0, bar_error * 1000.0,
            abs(grid.first_beat_s - beats[0]) / (60.0 / true_bpm))


# ------------------------------------------------------------------ (a) tempos, desfases, compás
check("sin audio, o con muy poco, no hay rejilla (ni excepción)", beatgrid.compute(None) is None
      and beatgrid.compute(np.zeros(1000, dtype=np.float32)) is None and beatgrid.compute(np.zeros(SR * 40, dtype=np.float32)) is None)

rng = np.random.default_rng(20260429)
cases = []
tempos = (80.0, 87.3, 92.0, 98.4, 104.0, 110.5, 117.0, 120.0, 124.5, 127.6, 133.3, 138.0, 140.3, 146.0, 150.2, 155.0, 160.0)
intros = ("silence", "pad", "noise", "silence", "pad")
starts = (0.3, 2.1, 7.7, 12.4, 20.0, 0.8, 4.4, 10.0, 16.5)
for n, bpm in enumerate(tempos):
    cases.append(dict(bpm=bpm, first=starts[n % len(starts)], intro=intros[n % len(intros)], hats=n % 5 != 3, snare=n % 4 != 2,
                      noise=(0.02, 0.04, 0.03)[n % 3], hint=bpm * (1.0 + (0.012, -0.015, 0.0, 0.008)[n % 4]) if n % 3 != 2 else None))
tempo_ok = first_ok = bar_ok = intro_ok = align_ok = 0
worst_tempo = worst_first = 0.0
t_total = 0.0
for case in cases:
    seconds = case["first"] + 55.0
    y, beats = song(case["bpm"], case["first"], seconds, rng, intro=case["intro"], hats=case["hats"], snare=case["snare"],
                    noise=case["noise"])
    t = time.time()
    found = beatgrid.compute(y, case["hint"], SR)
    t_total += time.time() - t
    label = f"{case['bpm']} BPM, primer golpe a {case['first']} s ({case['intro']}), pista {case['hint'] and round(case['hint'], 1)}"
    if found is None:
        print("FALLO", label, ": sin rejilla", flush=True)
        continue
    d_tempo, d_first, d_bar, d_far = judge(found, beats, case["bpm"])
    tempo_ok += abs(d_tempo) < 0.3
    first_ok += d_first < 30
    bar_ok += d_bar < 30
    intro_ok += d_far < 1.5
    align_ok += (beatgrid.alignment(y, found, SR) or 0.0) >= 0.9
    worst_tempo, worst_first = max(worst_tempo, abs(d_tempo)), max(worst_first, d_first)
    print(f"     {label}: tempo {found.bpm:.3f} ({d_tempo:+.3f} %), primer golpe {found.first_beat_s:.3f} (error {d_first:.1f} ms, a "
          f"{d_far:.1f} golpes del verdadero), compás {d_bar:.1f} ms, confianza {found.confidence:.2f}", flush=True)
count = len(cases)
check(f"sintético: tempo con error menor del 0,3 % en {tempo_ok} de {count} (peor {worst_tempo:.3f} %)", tempo_ok == count)
check(f"sintético: primer golpe a menos de 30 ms de un golpe verdadero en {first_ok} de {count} (peor {worst_first:.1f} ms)",
      first_ok == count)
check(f"sintético: el primer golpe es el de verdad, no uno de la intro (a menos de 1,5 golpes), en {intro_ok} de {count}",
      intro_ok >= count - 1)
check(f"sintético: el golpe de compás es el correcto (a menos de 30 ms) en {bar_ok} de {count} ({100.0 * bar_ok / count:.0f} %)",
      bar_ok >= 0.85 * count)
check(f"sintético: la puntuación de alineación es de 0,9 o más en {align_ok} de {count}", align_ok >= count - 1)
print(f"     tiempo medio de cálculo de un audio de ~65 s: {t_total / count:.2f} s", flush=True)

# sin pista de tempo, en el rango en que cada tempo tiene un solo sitio posible (78 a 156)
free_ok, free_n = 0, 0
for bpm, first in ((90.0, 3.3), (101.7, 9.0), (115.0, 0.5), (128.2, 14.2), (141.0, 6.1)):
    y, beats = song(bpm, first, first + 50.0, rng, intro="pad")
    found = beatgrid.compute(y, None, SR)
    free_n += 1
    if found is not None and abs(found.bpm / bpm - 1.0) < 0.003 and distance_to(beats, found.first_beat_s) < 0.03:
        free_ok += 1
check(f"sintético sin pista: el tempo y el primer golpe salen bien en {free_ok} de {free_n}", free_ok == free_n)

# pista equivocada (informativo): el tempo de la pista manda; la mitad, el doble y el que saldría sin pista solo se prueban si
# en el de la pista no hay pulso (un 3:2 con pulso aparente, como el de los hi-hats, se acepta)
y, beats = song(124.0, 5.0, 60.0, rng)
for factor in (0.5, 2.0, 1.5):
    found = beatgrid.compute(y, 124.0 * factor, SR)
    shown = "None" if found is None else f"{found.bpm:.2f} BPM"
    print(f"     pista a x{factor} del tempo verdadero (124 BPM): sale {shown} (informativo)", flush=True)

# ------------------------------------------------------------------ (b) tempo que deriva
for bpm, first in ((100.0, 4.0), (124.5, 8.0), (140.0, 1.0)):
    y, beats = song(bpm, first, first + 70.0, rng, drift=0.01)
    found = beatgrid.compute(y, bpm * 1.01, SR)
    if found is None:
        check(f"deriva de ±1 %, {bpm} BPM: da rejilla", False)
        continue
    d_tempo, d_first, d_bar, _far = judge(found, beats, bpm)
    check(f"deriva de ±1 %, {bpm} BPM: tempo medio a menos del 1 % ({d_tempo:+.2f} %), primer golpe a menos de 40 ms "
          f"({d_first:.1f} ms), compás a menos de 40 ms ({d_bar:.1f} ms)", abs(d_tempo) < 1.0 and d_first < 40 and d_bar < 40)

# ------------------------------------------------------------------ (c) sin pulso
quiet = 0
for seed in range(4):
    noise = (0.1 * np.random.default_rng(seed).standard_normal(SR * 60)).astype(np.float32)
    found = beatgrid.compute(noise, (95.0, 120.0, None, 140.0)[seed], SR)
    quiet += found is None or found.confidence < 0.3
    print(f"     ruido blanco {seed}: {'None' if found is None else 'confianza %.2f' % found.confidence}", flush=True)
check(f"ruido sin pulso: None o confianza baja (menos de 0,3) en {quiet} de 4", quiet == 4)
swell = (np.sin(2 * np.pi * 0.05 * np.arange(SR * 60) / SR) * 0.1 * np.random.default_rng(9).standard_normal(SR * 60)).astype(np.float32)
found = beatgrid.compute(swell, 100.0, SR)
check("ruido con un volumen que sube y baja despacio: None o confianza baja", found is None or found.confidence < 0.3)
tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(SR * 40) / SR)).astype(np.float32)
check("un tono continuo sin golpes: None o confianza baja", beatgrid.compute(tone, 100.0, SR) is None
      or beatgrid.compute(tone, 100.0, SR).confidence < 0.3)

# ------------------------------------------------------------------ (d) sin numpy
real_beatgrid, real_key = beatgrid._numpy, key_detect._numpy
beatgrid._numpy = key_detect._numpy = lambda: None
try:
    y_small, _b = song(120.0, 1.0, 30.0, np.random.default_rng(1))
    check("sin numpy: compute da None y available() da False", beatgrid.compute(y_small, 120.0, SR) is None
          and not beatgrid.available() and beatgrid.analyse(y_small, 120.0, SR) is None)
    check("sin numpy: detect da None sin excepción", beatgrid.detect(__file__, 120.0) is None)
    check("sin numpy: alignment da None", beatgrid.alignment(y_small, BeatGrid(1.0, 120.0), SR) is None)
finally:
    beatgrid._numpy, key_detect._numpy = real_beatgrid, real_key
check("con numpy otra vez disponible, available() da True", beatgrid.available())
check("un archivo que no existe da None sin excepción", beatgrid.detect(os.path.join(os.path.dirname(__file__), "no_existe.mp3"), 120.0) is None)

# ------------------------------------------------------------------ (e) velocidad (holgada: la máquina va cargada)
y, beats = song(126.0, 9.0, 240.0, rng, intro="pad")
t = time.time()
found = beatgrid.compute(y, 126.5, SR)
elapsed = time.time() - t
print(f"     canción de 4 minutos: {elapsed:.2f} s de cálculo (objetivo: menos de 1 s)", flush=True)
check("velocidad: 4 minutos de audio en menos de 4 s (con la máquina cargada)", elapsed < 4.0 and found is not None)
check("y la rejilla de la canción larga es buena (tempo, primer golpe y compás)", found is not None
      and abs(found.bpm / 126.0 - 1) < 0.003 and distance_to(beats, found.first_beat_s) < 0.03
      and distance_to(beats[::4], found.bar_time(0)) < 0.03)

# ------------------------------------------------------------------ (f) canciones reales (informativo)
files = sorted(glob.glob(os.path.join(MUSIC, "*.mp3")))
if os.environ.get("REJILLA_SIN_REALES") or not files:
    print("     (canciones reales: saltado)", flush=True)
else:
    print(f"     canciones reales ({len(files)}): tempo de la rejilla, tempo del análisis (tempo.estimate_bpm), alineación "
          f"(golpes sobre picos de novedad), acuerdo del golpe de compás entre la primera y la segunda mitad", flush=True)
    errors, done, aligned, agree_halves, times = 0, 0, [], [], []
    for path in files:
        name = os.path.basename(path)[:36]
        try:
            data = envelope.compute(path)
            hint = tempo.estimate_bpm(data) if data else None
            t = time.time()
            grid = beatgrid.detect(path, hint)
            times.append(time.time() - t)
            samples = key_detect.decode(path)
            info = beatgrid.analyse(samples, hint, SR)
            if grid is None or info is None:
                print(f"     {name:36s} analisis {hint}: sin rejilla", flush=True)
                continue
            done += 1
            score = beatgrid.alignment(samples, grid, SR)
            aligned.append(score)
            first_half, second_half = info["bar_halves"]
            same = int(np.argmax(first_half) == np.argmax(second_half))
            agree_halves.append(same)
            halves = f", compás {'coincide' if same else 'NO coincide'} entre mitades"
            print(f"     {name:36s} rejilla {grid.bpm:8.3f} | analisis {hint if hint is None else round(hint, 1)} | primer golpe "
                  f"{grid.first_beat_s:6.2f} s, golpe de compás {grid.downbeat_offset} | confianza {grid.confidence:.2f} | alineación "
                  f"{score:.2f}{halves}", flush=True)
        except Exception as e:
            errors += 1
            print(f"FALLO {name}: excepción {type(e).__name__}: {e}", flush=True)
    check("canciones reales: ninguna da excepción", errors == 0)
    if aligned:
        print(f"     reales con rejilla: {done} de {len(files)}; alineación media {np.mean(aligned):.2f} (mín. {min(aligned):.2f}); "
              f"compás coincidente entre mitades en {sum(agree_halves)} de {len(agree_halves)}; "
              f"tiempo de detect() medio {np.mean(times):.2f} s, máximo {max(times):.2f} s", flush=True)
print("FIN")
