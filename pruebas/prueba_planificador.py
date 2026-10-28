"""Orden inteligente (planificador) y medidas de energía del audio: la curva de fiesta, el ritmo, el tono, el género, el artista,
que salgan todas una vez, que sea mejor que el azar, que sea rápido y que las medidas de volumen, brillo y golpes midan lo que dicen.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_planificador.py"""
import math
import os
import random
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


from services import audio_features, dj_planner as dp, key_detect

T = dp.Track

# ------------------------------------------------------------------ la curva de energía
check("la curva empieza tranquila y termina arriba", dp.target_energy(0.0) == 0.30 and dp.target_energy(1.0) == 0.95)
check("interpola entre los puntos (a mitad de 0,0 y 0,12: 0,375)", abs(dp.target_energy(0.06) - 0.375) < 1e-9)
check("tiene un pico y un respiro: sube a 0,92 hacia la mitad, baja a 0,60 y vuelve a subir",
      dp.target_energy(0.55) == 0.92 and dp.target_energy(0.70) == 0.60 and dp.target_energy(0.82) == 0.85)
check("fuera de 0 a 1 no se sale de la curva", dp.target_energy(-1) == 0.30 and dp.target_energy(2) == 0.95)
check("una sesión de hasta 120 canciones recorre la curva entera", dp.curve_progress(0, 100) == 0.0 and dp.curve_progress(99, 100) == 1.0)
check("una sesión larga repite la curva cada 80 canciones",
      dp.curve_progress(0, 500) == 0.0 and dp.curve_progress(79, 500) == 1.0 and dp.curve_progress(80, 500) == 0.0)

# ------------------------------------------------------------------ las piezas de la puntuación
rank = dp.energy_ranker([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
check("la energía pasa a posición: la más baja ~0, la más alta ~1, la del medio ~0,5",
      rank(0.1) < 0.1 and rank(1.0) > 0.9 and abs(rank(0.55) - 0.5) < 0.1 and rank(None) is None)
flat = dp.energy_ranker([0.6, 0.6, 0.6, 0.6, 0.6, 0.6])
check("si todas valen lo mismo, todas quedan en el medio", abs(flat(0.6) - 0.5) < 1e-9)
check("con menos de 5 valores no hay posiciones: se deja la energía como está", dp.energy_ranker([0.2, 0.9])(0.2) == 0.2)
check("ritmo: casi igual vale 1, la mitad y el doble cuentan como igual, lejos vale 0, sin dato 0,5",
      dp.bpm_fit(120, 121) == 1.0 and dp.bpm_fit(95, 190) == 1.0 and dp.bpm_fit(120, 60) == 1.0 and dp.bpm_fit(120, 150) == 0.0
      and dp.bpm_fit(None, 120) == 0.5 and dp.bpm_fit(120, 0) == 0.5)
check("ritmo: a un 7 % queda entre medias", 0.2 < dp.bpm_fit(120, 128.4) < 0.8)
a, b = T(1, 120, "8A", 0.9, 0.5, "", ""), T(2, 120, "9A", 0.9, 0.5, "", "")
check("tono compatible (un paso por la rueda) puntúa 0,8", abs(dp.key_fit(a, b) - 0.8) < 1e-9)
check("tono que choca puntúa 0", dp.key_fit(a, T(3, 120, "2A", 0.9, 0.5, "", "")) == 0.0)
check("un tono poco fiable pesa menos (se acerca a 0,5)", 0.5 < dp.key_fit(a, T(3, 120, "9A", 0.3, 0.5, "", "")) < 0.8)
check("sin tono, neutro", dp.key_fit(a, T(3, 120, None, 0.0, 0.5, "", "")) == 0.5)
check("género: igual 1, distinto 0,3, desconocido 0,5, y solo cuenta el primero de la lista",
      dp.genre_fit("Reggaeton", "reggaeton") == 1.0 and dp.genre_fit("Trap", "House") == 0.3 and dp.genre_fit("", "House") == 0.5
      and dp.genre_fit("Pop/Rock", "pop") == 1.0)

# ------------------------------------------------------------------ el planificador
rng = random.Random(7)
TONES = [f"{n}{letter}" for n in range(1, 13) for letter in "AB"]
GENRES = ["reggaeton", "trap", "house", "pop", "drill"]


def library(n, artists=None):
    return [T(i, rng.choice([90, 95, 100, 124, 128, 140, 150]) * rng.uniform(0.97, 1.03), rng.choice(TONES), rng.uniform(0.4, 0.9),
              rng.random(), rng.choice(GENRES), f"artista{rng.randrange(artists or max(3, n // 6))}") for i in range(n)]


songs = library(100)
ordered = dp.plan(songs, rng=random.Random(1))
check("salen todas, una vez cada una", sorted(t.ref for t in ordered) == list(range(100)))
check("con la misma semilla sale el mismo orden", [t.ref for t in ordered] == [t.ref for t in dp.plan(songs, rng=random.Random(1))])
check("con otra semilla, otro orden", [t.ref for t in ordered] != [t.ref for t in dp.plan(songs, rng=random.Random(2))])
check("no toca la lista que se le da", [t.ref for t in songs] == list(range(100)))
check("lista vacía: vacía", dp.plan([]) == [])
check("una sola canción: esa", [t.ref for t in dp.plan(songs[:1])] == [0])
shuffled = songs[:]
random.Random(3).shuffle(shuffled)
q_plan, q_rand = dp.transition_quality(ordered), dp.transition_quality(shuffled)
check(f"mejora el encaje de ritmo ({q_rand['bpm']:.2f} al azar, {q_plan['bpm']:.2f} ordenado)", q_plan["bpm"] > q_rand["bpm"] + 0.3)
check(f"mejora el encaje de tono ({q_rand['key']:.2f} al azar, {q_plan['key']:.2f} ordenado)", q_plan["key"] > q_rand["key"] + 0.15)
check(f"y no empeora el de género ({q_rand['genre']:.2f} frente a {q_plan['genre']:.2f})", q_plan["genre"] >= q_rand["genre"] - 0.02)

# la energía sigue la curva
pool = [t.energy for t in songs]
ranker = dp.energy_ranker(pool)
chosen = [ranker(t.energy) for t in ordered]
targets = [dp.target_energy(dp.curve_progress(i, 100)) for i in range(100)]
mean_c, mean_t = sum(chosen) / 100, sum(targets) / 100
corr = (sum((c - mean_c) * (g - mean_t) for c, g in zip(chosen, targets))
        / math.sqrt(sum((c - mean_c) ** 2 for c in chosen) * sum((g - mean_t) ** 2 for g in targets)))
check(f"la energía de las canciones sigue la curva de fiesta (correlación {corr:.2f})", corr > 0.5)
starts = [ranker(dp.plan(songs, rng=random.Random(s))[0].energy) for s in range(20)]
check(f"la primera canción arranca tranquila (energía media {sum(starts) / 20:.2f} de 0 a 1)", sum(starts) / 20 < 0.45)

# el principio y el final de la sesión: no se queda con sobras (si cada paso gasta lo que le conviene, al final solo quedarían
# las canciones que no encajaban en ningún sitio) y arranca tranquila
def media_extremos(n, semillas=12):
    inicio, final = [], []
    for semilla in range(semillas):
        canciones = library(n)
        rk = dp.energy_ranker([t.energy for t in canciones])
        orden = dp.plan(canciones, rng=random.Random(semilla))
        inicio.append(sum(rk(t.energy) for t in orden[:3]) / 3)
        final.append(sum(rk(t.energy) for t in orden[-3:]) / 3)
    return sum(inicio) / semillas, sum(final) / semillas


for n in (22, 40, 100):
    ini, fin = media_extremos(n)
    check(f"con {n} canciones, las 3 primeras son suaves ({ini:.2f}) y las 3 últimas fuertes ({fin:.2f}), no sobras", ini < 0.3 and fin > 0.7)

# una biblioteca casi toda de un artista: la energía pesa más que no repetir
dominada = [T(i, 100.0, "8A", 0.9, random.Random(i).random(), "urbano", "Quevedo" if i % 10 else "Otro") for i in range(40)]
orden_dominada = dp.plan(dominada, rng=random.Random(2))
rk_dom = dp.energy_ranker([t.energy for t in dominada])
mc = [rk_dom(t.energy) for t in orden_dominada]
mt = [dp.target_energy(dp.curve_progress(i, 40)) for i in range(40)]
ma, mb = sum(mc) / 40, sum(mt) / 40
corr_dom = sum((c - ma) * (g - mb) for c, g in zip(mc, mt)) / math.sqrt(sum((c - ma) ** 2 for c in mc) * sum((g - mb) ** 2 for g in mt))
check(f"con 36 de 40 canciones del mismo artista, la energía sigue la curva igualmente (correlación {corr_dom:.2f})",
      corr_dom > 0.7 and sorted(t.ref for t in orden_dominada) == list(range(40)))

# artistas
cinco = library(60, artists=5)
orden_cinco = dp.plan(cinco, rng=random.Random(4))
mezcla = cinco[:]
random.Random(5).shuffle(mezcla)
repetidos = lambda lista: sum(1 for x, y in zip(lista, lista[1:]) if x.artist == y.artist)
check(f"no repite artista seguido ({repetidos(orden_cinco)} veces frente a {repetidos(mezcla)} al azar)",
      repetidos(orden_cinco) <= 4 and repetidos(orden_cinco) * 3 < repetidos(mezcla))
check("con el artista de la que suena ya, la primera nueva no es de ese artista",
      all(dp.plan(library(30, artists=3), previous=T("x", 120, "8A", 0.9, 0.5, "pop", "artista0"), rng=random.Random(s))[0].artist != "artista0"
          for s in range(10)))

# sin datos
vacias = [T(i, None, None, 0.0, None, "", "") for i in range(30)]
check("sin ningún dato de las canciones, sale igualmente completo", sorted(t.ref for t in dp.plan(vacias)) == list(range(30)))
mixtas = [T(i, 120.0 if i % 2 else None, "8A" if i % 3 else None, 0.8, 0.5 if i % 4 else None, "pop", "") for i in range(40)]
check("con datos a medias también", sorted(t.ref for t in dp.plan(mixtas)) == list(range(40)))

# continuar una sesión a medias
actual = T("ahora", 124.0, "8A", 0.9, 0.5, "house", "dj")
resto = library(40)
nuevo = dp.plan(resto, previous=actual, start_index=21, total=61, energy_pool=resto + [actual])
check("replanificar lo que queda: salen todas las que quedaban", sorted(t.ref for t in nuevo) == list(range(40)))

# valores estropeados (no deberían llegar de la aplicación, pero no deben romper nada)
raras = [T(i, bpm, "8A", 0.8, energia, "pop", "x") for i, (bpm, energia) in enumerate(
    [(float("nan"), 0.5), (float("inf"), 0.2), (0.0, float("nan")), (-5.0, 0.9), (120.0, float("inf")), (120.0, 0.4), (None, None),
     (128.0, 0.6), (128.0, 0.7), (90.0, 0.1)])]
check("tempos o energías que no son números finitos no rompen el orden: salen todas", sorted(t.ref for t in dp.plan(raras)) == list(range(10)))
check("curva con una sesión de 0 o 1 canciones no divide por cero", dp.curve_progress(5, 0) == 0.0 and dp.curve_progress(0, 1) == 0.0)
sin_artista = [T(i, 120.0, "8A", 0.9, i / 20, "pop", "" if i % 2 else "Mismo") for i in range(20)]
check("las de artista desconocido no cuentan como repetidas entre sí", sorted(t.ref for t in dp.plan(sin_artista)) == list(range(20)))

# límite y rapidez
grande = library(20000)
t0 = time.time()
out = dp.plan(grande, rng=random.Random(9))
dt = time.time() - t0
check(f"20.000 canciones se ordenan en {dt:.2f} s (menos de 1 s: se hace en el hilo de la interfaz)", dt < 1.0)
check("y salen todas (las 400 primeras ordenadas, el resto detrás)", len(out) == 20000 and len({t.ref for t in out}) == 20000)
check("limit=10: se ordenan 10 y las demás van detrás", sorted(t.ref for t in dp.plan(songs, limit=10)) == list(range(100)))

# ------------------------------------------------------------------ medidas de energía del audio
SR = key_detect.SAMPLE_RATE


def clicks(rate_per_s, seconds=40, frequency=80.0, amplitude=0.6, bright=False):
    """Golpes secos (un seno que se apaga) a `rate_per_s` por segundo sobre un colchón continuo grave (como en música real, donde
    entre golpe y golpe suena algo); con `bright`, los golpes llevan mucho agudo."""
    t = np.arange(SR * seconds) / SR
    signal = 0.05 * np.sin(2 * np.pi * 60.0 * t)
    period = 1.0 / rate_per_s
    n = np.arange(int(0.1 * SR)) / SR
    burst = np.exp(-n * 40) * np.sin(2 * np.pi * frequency * n)
    if bright:
        burst = burst + np.exp(-n * 60) * np.random.default_rng(1).normal(0, 0.6, len(n)) * 0.5
    for start in np.arange(0, seconds - 0.2, period):
        i = int(start * SR)
        signal[i:i + len(burst)] += burst * 0.5
    return (signal / max(1e-9, np.abs(signal).max()) * amplitude).astype(np.float32)


suave = audio_features.compute(clicks(2.0, amplitude=0.05))
fuerte = audio_features.compute(clicks(2.0, amplitude=0.6))
check(f"el volumen mide la fuerza: 20 dB menos de amplitud, unos 20 dB menos ({suave['loudness_db']} y {fuerte['loudness_db']})",
      18 < fuerte["loudness_db"] - suave["loudness_db"] < 22)
def estable(parciales, seconds=40):
    t = np.arange(SR * seconds) / SR
    return (sum(np.sin(2 * np.pi * 200.0 * k * t) / k for k in parciales) * 0.2).astype(np.float32)


oscuro = audio_features.compute(estable([1]))
brillante = audio_features.compute(estable([1, 3, 5, 7, 9, 11, 13]))
check(f"el brillo sube con los agudos ({oscuro['brightness_hz']:.0f} Hz y {brillante['brightness_hz']:.0f} Hz)",
      brillante["brightness_hz"] > oscuro["brightness_hz"] + 500)
lento = audio_features.compute(clicks(1.5))
rapido = audio_features.compute(clicks(3.0))
fondo = audio_features.compute(clicks(0.05))                   # casi sin golpes: lo que aporta el colchón del propio test
check(f"la actividad sube con la cantidad de golpes ({fondo['flux']} casi sin golpes, {lento['flux']} con 1,5 y {rapido['flux']} con 3 por segundo)",
      fondo["flux"] < lento["flux"] < rapido["flux"] and 1.3 < (rapido["flux"] - fondo["flux"]) / (lento["flux"] - fondo["flux"]) < 2.6)
callado = audio_features.compute(clicks(2.0, amplitude=0.02))
estruendo = audio_features.compute(clicks(2.0, amplitude=0.9))
check(f"la actividad no depende del volumen de la grabación (45 dB de diferencia: {callado['flux']} y {estruendo['flux']})",
      abs(callado["flux"] - estruendo["flux"]) / estruendo["flux"] < 0.1)
e_baja = audio_features.energy_score({"loudness_db": -12.0, "brightness_hz": 800.0, "flux": 0.11})
e_alta = audio_features.energy_score({"loudness_db": -5.0, "brightness_hz": 1700.0, "flux": 0.19})
check(f"más fuerte, más brillante y más activa = más energía ({e_baja} frente a {e_alta})", e_alta > e_baja + 0.5 and 0 <= e_baja < e_alta <= 1)
check("silencio: no hay medidas", audio_features.compute(np.zeros(SR * 40, dtype=np.float32)) is None)
check("menos de 20 s: no hay medidas", audio_features.compute(clicks(2.0, seconds=10)) is None)
check("sin audio: no hay medidas", audio_features.compute(None) is None)
check("lo que no se pudo medir no da energía", audio_features.energy_score({"loudness_db": audio_features.NOT_MEASURED,
      "brightness_hz": 0.0, "flux": 0.0}) is None and audio_features.energy_score(None) is None
      and audio_features.energy_score({"loudness_db": -7.0}) is None)
check("la energía siempre queda entre 0 y 1", all(0.0 <= audio_features.energy_score(
    {"loudness_db": l, "brightness_hz": b, "flux": r}) <= 1.0 for l in (-60, -7, 0) for b in (0, 1500, 9000) for r in (0, 0.3, 5)))
print("FIN")
