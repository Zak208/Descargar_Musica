"""Punto de mezcla (fase 8, `mix_points`) y mezcla por frases (fase 13, `mix_planner`) con canciones de mentira: finales
largos y cortos, sin intro, tempos distintos, fuera de ±8 %, sin rejillas y datos que faltan.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_puntos_mezcla.py"""
import math
import os
import random
import sys

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from services import mix_planner, mix_points
from services.mix_types import BeatGrid


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def near(x, y, tol=1e-3):
    return x is not None and y is not None and abs(x - y) <= tol


def on_phrase(grid, t, multiple):
    """¿El instante `t` es un comienzo de frase de `multiple` compases? (con el redondeo a milisegundos del plan)."""
    bar = grid.bar_at(t)
    return abs(bar - round(bar)) < 1e-3 and round(bar) % multiple == 0


def song(dur, intro=0, outro=0, bpm=None, grid=None):
    """Como lo guarda `track_analysis` (en milisegundos)."""
    info = {"duration_ms": int(dur * 1000), "intro_ms": int(intro * 1000), "outro_ms": int(outro * 1000), "bpm": bpm}
    if grid is not None:
        info["beatgrid"] = grid
    return info


plan = mix_points.plan

# ---------------------------------------------------------------- fase 8: punto de mezcla
p = plan(song(200, outro=20), song(180, intro=30))
check(f"final de 20 s e intro de 30 s: la mezcla empieza al principio del final (180 s), dura 20 s y B entra en su "
      f"segundo 10 para que su cuerpo llegue cuando A acaba ({p.a_start_s}, {p.length_s}, {p.b_start_s})",
      p.kind == "blend" and near(p.a_start_s, 180) and near(p.length_s, 20) and near(p.b_start_s, 10))
check("el cuerpo de B (su intro) cae justo al final de la mezcla", near(p.b_start_s + p.length_s, 30))
p = plan(song(200, outro=40), song(180, intro=50))
check(f"un final de 40 s: empieza en 160 s y la mezcla se queda en 32 s como mucho ({p.a_start_s}, {p.length_s})",
      near(p.a_start_s, 160) and near(p.length_s, 32) and near(p.b_start_s, 18))
p = plan(song(200, outro=5), song(180, intro=10))
check(f"final corto (5 s, menos de 8): mezcla corta de 6 s que acaba con la canción ({p.a_start_s}, {p.length_s})",
      near(p.a_start_s, 194) and near(p.length_s, 6) and near(p.b_start_s, 4))
p = plan(song(200, outro=110), song(180, intro=10))
check("un final que empezaría antes de la mitad de la canción no se cree: mezcla corta al acabar",
      near(p.a_start_s, 194) and near(p.length_s, 6))
p = plan(song(200, outro=20), song(180, intro=4))
check(f"intro de B más corta que el final de A: B entra desde el principio y la mezcla dura su intro ({p.length_s} s)",
      near(p.a_start_s, 180) and near(p.length_s, 4) and near(p.b_start_s, 0))
p = plan(song(200, outro=20), song(180, intro=0))
check(f"B sin intro: entra desde el principio con una mezcla corta ({p.length_s} s) al principio del final de A",
      near(p.a_start_s, 180) and near(p.length_s, 6) and near(p.b_start_s, 0) and "intro clara" in p.reason)
p = plan(song(200, outro=20), song(180, intro=1.5))
check("una intro de menos de 2 s cuenta como sin intro", near(p.length_s, 6) and near(p.b_start_s, 0))
p = plan(song(200, outro=20), song(40, intro=30))
check("una intro de más de la mitad de B no se cree", near(p.b_start_s, 0) and p.length_s <= 6)
p = plan(song(200), None)
check("sin datos de B (aún sin analizar): mezcla corta al acabar A, B desde el principio",
      p.kind == "blend" and near(p.a_start_s, 194) and near(p.length_s, 6) and near(p.b_start_s, 0))
p = plan(song(30, outro=10), song(30, intro=10))
check(f"canciones cortas: la mezcla no pasa de un tercio de la canción ({p.length_s} s)", near(p.length_s, 10)
      and near(p.a_start_s, 20))
p = plan(song(5), song(180))
check("una canción de 5 s: corte limpio (la mezcla no llegaría a 2 s)", p.kind == "cut" and p.length_s == 0
      and near(p.a_start_s, 5) and "corta" in p.reason)
p = plan(song(200, outro=20), song(4.5, intro=0))
check("y si la corta es la que entra, también", p.kind == "cut")
for bad, label in ((None, "sin datos"), ({}, "vacío"), ({"duration_ms": "mucho"}, "un texto"),
                   ({"duration_ms": float("nan")}, "NaN"), ({"duration_ms": -5}, "negativa"), ({"duration_ms": True}, "True")):
    p = plan(bad, song(180, intro=10))
    check(f"A {label}: corte limpio con su motivo, sin fallar", p.kind == "cut" and "no se sabe" in p.reason)
p = plan({"duration_s": 200.0, "outro_s": 20.0}, {"duration_s": 180.0, "intro_s": 30.0})
check("la ficha en segundos (`mix_types`) da lo mismo que el análisis en milisegundos",
      near(p.a_start_s, 180) and near(p.length_s, 20) and near(p.b_start_s, 10))
p = plan(song(200, outro=20), song(180, intro=30), a_duration_s=203.4)
check("la duración real del reproductor manda sobre la del análisis", near(p.a_start_s, 183.4))
p = plan({"outro_ms": 20000}, song(180), a_duration_s=200.0)
check("y vale aunque el análisis no traiga la duración", p.kind == "blend" and near(p.a_start_s, 180))

rng = random.Random(8)
values = [None, -3, 0, 0.5, 1.9, 2, 5, 8, 12, 30, 45, 90, 200, float("nan"), float("inf"), "x"]
ok, count = True, 0
for _ in range(4000):
    a = {k: rng.choice(values) for k in ("duration_s", "intro_s", "outro_s")}
    b = {k: rng.choice(values) for k in ("duration_s", "intro_s", "outro_s")}
    try:
        p = plan(a, b)
    except Exception as e:              # noqa: BLE001 (la prueba es justo que no falle)
        ok = False
        print("   ", a, b, e)
        break
    if p.kind == "blend":
        count += 1
        a_dur = a["duration_s"]
        if not (2 - 1e-9 <= p.length_s <= 32 + 1e-9 and p.b_start_s >= 0 and p.a_start_s >= a_dur / 2 - 1e-9
                and p.a_start_s + p.length_s <= a_dur + 1e-9):
            ok = False
            print("   ", a, b, p)
            break
check(f"4000 canciones al azar (con datos raros): nunca falla y las mezclas ({count}) duran de 2 a 32 s, empiezan en "
      f"la segunda mitad de A y caben antes de que acabe", ok and count > 100)

# ---------------------------------------------------------------- fase 13: mezcla por frases
ratio = mix_planner.tempo_ratio
check("la mitad y el doble cuentan como el mismo ritmo (128 y 64, 70 y 140)", near(ratio(128, 64), 1.0)
      and near(ratio(70, 140), 1.0))
check("128 sobre 125: B un 2,4 % más rápida", near(ratio(128, 125), 1.024))
check("140 sobre 72 (el doble, 144): B un 2,8 % más lenta", near(ratio(140, 72), 140 / 144))
check("sin tempo de alguna no hay relación", ratio(None, 120) is None and ratio(120, 0) is None)

a, b = song(240, outro=40, bpm=128), song(200, intro=20, bpm=125)
p = mix_planner.plan_transition(a, b)
base = plan(a, b)
check(f"sin rejillas: el punto de la fase 8 y solo el tempo igualado ({p.tempo_ratio_b})", p.kind == "blend"
      and near(p.a_start_s, base.a_start_s) and near(p.length_s, base.length_s) and near(p.b_start_s, base.b_start_s)
      and near(p.tempo_ratio_b, 1.024) and "sin rejilla" in p.reason)
p = mix_planner.plan_transition(song(240, outro=40, bpm=128), song(200, intro=20, bpm=100))
check(f"tempos demasiado lejos (128 y 100, un 28 %): corte limpio con su motivo ({p.reason})", p.kind == "cut"
      and p.length_s == 0 and "demasiado lejos" in p.reason)
check("justo un 8 % se mezcla", mix_planner.plan_transition(song(240, 0, 40, 108), song(200, 20, 0, 100)).kind == "blend")
check("y un 9 % ya no", mix_planner.plan_transition(song(240, 0, 40, 109), song(200, 20, 0, 100)).kind == "cut")
p = mix_planner.plan_transition(song(240, outro=40), song(200, intro=20, bpm=100))
check("sin el tempo de una: se mezcla sin igualar el ritmo y lo dice", p.kind == "blend" and p.tempo_ratio_b == 1.0
      and "sin tempo" in p.reason)

ga = BeatGrid(first_beat_s=0.5, bpm=120.0)
gb = BeatGrid(first_beat_s=0.2, bpm=125.0)
a, b = song(240, outro=40, grid=ga), song(200, intro=40, grid=gb)
p = mix_planner.plan_transition(a, b)
check(f"con rejillas: la mezcla dura 16 compases de A (32 s a 120 BPM) ({p.length_s})", p.kind == "blend"
      and near(p.length_s, 32))
check(f"y empieza en un comienzo de frase de 16 compases de A, el más cercano al principio del final que cabe "
      f"({p.a_start_s} s)", near(p.a_start_s, 192.5) and on_phrase(ga, p.a_start_s, 16))
check("con sitio para la mezcla entera antes de que A acabe", p.a_start_s + p.length_s <= 240)
check(f"B entra en un comienzo de frase suyo ({p.b_start_s} s, compás {gb.bar_at(p.b_start_s):.3f})",
      on_phrase(gb, p.b_start_s, 8) and p.b_start_s >= 0)
check("el más cercano a donde su cuerpo llega al acabar la mezcla (40 - 32 × 0,96 = 9,28 s)", near(p.b_start_s, 15.56))
check(f"tempo de A / tempo de B ({p.tempo_ratio_b})", near(p.tempo_ratio_b, 0.96))
swap_abs = p.a_start_s + p.bass_swap_at
check(f"el cambio de graves cae en un comienzo de compás, a la mitad ({p.bass_swap_at} s)", near(p.bass_swap_at, 16)
      and near(ga.bar_at(swap_abs), round(ga.bar_at(swap_abs))))
p8 = mix_planner.plan_transition(a, b, bars=8)
check(f"con 8 compases dura 16 s ({p8.length_s})", near(p8.length_s, 16) and near(p8.bass_swap_at, 8))
slow = BeatGrid(first_beat_s=0.0, bpm=90.0)
p = mix_planner.plan_transition(song(240, outro=40, grid=slow), song(200, intro=30, grid=BeatGrid(0.0, 90.0)))
check(f"a 90 BPM, 16 compases pasarían de 32 s: se queda en 8 compases ({p.length_s} s)", near(p.length_s, 8 * 4 * 60 / 90)
      and near(p.tempo_ratio_b, 1.0) and on_phrase(slow, p.a_start_s, 8))
p = mix_planner.plan_transition(song(240, outro=40, grid=ga), song(200, intro=20, grid=BeatGrid(0.1, 61.0)))
check(f"con B a la mitad de tempo (61 BPM contra 120) cuenta como el doble ({p.tempo_ratio_b})", p.kind == "blend"
      and near(p.tempo_ratio_b, 120 / 122))
p = mix_planner.plan_transition(song(20, outro=0, grid=ga), song(200, intro=10, grid=gb))
check(f"una canción corta donde no cabe una frase: punto de la fase 8 y lo dice ({p.length_s} s)", p.kind == "blend"
      and "no cabe una frase" in p.reason and p.length_s <= 20 / 3 + 1e-9)
p = mix_planner.plan_transition(song(240, outro=40, grid=ga), song(200, intro=20, bpm=121))
check("con rejilla solo en A: sin cuadrar compases, con el tempo igualado", "sin rejilla" in p.reason
      and near(p.tempo_ratio_b, 120 / 121))
p = mix_planner.plan_transition(song(240, outro=40, bpm=120, grid={"bpm": 120}), song(200, intro=20, grid=gb))
check("una rejilla que no es un BeatGrid cuenta como que no hay", "sin rejilla" in p.reason)
p = mix_planner.plan_transition(song(240, outro=40, grid=ga), song(200, intro=20, grid=BeatGrid(0.0, 160.0)))
check(f"con rejillas y tempos lejos (120 y 160): corte en un comienzo de compás de A ({p.a_start_s} s)", p.kind == "cut"
      and near(ga.bar_at(p.a_start_s), round(ga.bar_at(p.a_start_s))))
for a_, b_, label in ((None, song(200), "A"), (song(200), None, "B"), ("texto", 3, "las dos")):
    p = mix_planner.plan_transition(a_, b_)
    check(f"sin datos de {label}: corte limpio con su motivo", p.kind == "cut" and p.reason.startswith("corte limpio"))

ok = True
grids = [None, ga, gb, slow, BeatGrid(0.3, 174.0), BeatGrid(1.0, 0.0001), {"x": 1}]
for _ in range(3000):
    a = {k: rng.choice(values) for k in ("duration_s", "intro_s", "outro_s", "bpm")}
    b = {k: rng.choice(values) for k in ("duration_s", "intro_s", "outro_s", "bpm")}
    a["beatgrid"], b["beatgrid"] = rng.choice(grids), rng.choice(grids)
    try:
        p = mix_planner.plan_transition(a, b, bars=rng.choice((16, 8, 32, 0, 3)))
    except Exception as e:              # noqa: BLE001 (la prueba es justo que no falle)
        ok = False
        print("   ", a, b, e)
        break
    if p.kind == "blend" and not (p.length_s <= 32 + 1e-9 and p.b_start_s >= 0 and 0.92 - 1e-9 <= p.tempo_ratio_b <= 1.08 + 1e-9
                                  and math.isfinite(p.a_start_s)):
        ok = False
        print("   ", a, b, p)
        break
check("3000 parejas al azar con rejillas raras: nunca falla, nunca pasa de 32 s ni de ±8 %", ok)
print("FIN")
