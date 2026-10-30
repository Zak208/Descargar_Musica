"""Cortes que no caen en un silencio (dj_engine.EngineSession): muchos mp3 acaban con segundos de silencio digital y empiezan con
un poco. Un corte limpio no debe cortar A cuando ya calla ni hacer entrar B donde aún calla, y el corte en el compás (o el eco)
de una mezcla se mueve a un compás en el que suenan las dos. Lo que sale no tiene huecos de silencio. Sin sonido (cargador falso).
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_silencios.py"""
import logging

import _banco_dj as bd
from _banco_dj import SR, Rig, check, max_jump

import numpy as np

from services import transition_scorer as ts
from services.mix_types import KIND_CUT

logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)


def song(dur, freq, bpm, **kw):
    return dict(dur=dur, freq=freq, bpm=bpm, **kw)


def longest_gap_ms(x):
    return ts._silence_gap_ms(np, x, SR)


# ---- corte limpio (tempos lejanos) con A acabada en silencio y B que empieza callada -------------------------------------------
SONGS = {"A": song(70, 220.0, 120.0, outro=16, silence=[(50.0, 70.0)]), "B": song(70, 330.0, 150.0, silence=[(0.0, 1.7)])}
for typed in (False, True):
    r = Rig(SONGS, {"A": "B"}, typed=typed)
    st = r.start()
    plan = st["plan"]
    c, bs = round(plan.a_start_s * SR), round(plan.b_start_s * SR)
    check(f"corte (typed={typed}): A se corta donde deja de sonar y B entra donde empieza a sonar "
          f"({plan.a_start_s} s y {plan.b_start_s} s; {plan.reason.split('; ')[-1][:70]})",
          plan.kind == KIND_CUT and 49.7 <= plan.a_start_s <= 50.0 and 1.68 <= plan.b_start_s <= 1.7 and "corte movido" in plan.reason)
    r.pull_to(c + 3 * SR)
    out = r.audio()
    gap = longest_gap_ms(out[c - 2 * SR:c + 2 * SR])
    check(f"y alrededor del corte no hay hueco de silencio (el más largo, {gap:.0f} ms) ni clic (salto {max_jump(out):.4f})",
          gap < 100 and max_jump(out) < bd.CLICK)
    r.sess.stop()

# ---- corte en el compás de una mezcla (rejilla poco fiable) con A que calla antes de la mitad de la mezcla ---------------------
SONGS = {"A": song(70, 220.0, 120.0, conf=0.2, silence=[(53.0, 70.0)]), "B": song(70, 330.0, 120.0)}
r = Rig(SONGS, {"A": "B"})
st = r.start()
plan = st["plan"]
a_mix, n = round(plan.a_start_s * SR), round(plan.length_s * SR)
swap = plan.bass_swap_at
check(f"corte en el compás: el corte se adelanta a un compás en que A aún suena (A calla en 53 s; mezcla desde "
      f"{plan.a_start_s} s, corte a los {swap} s)", st["transition_type"] == "cut_bar" and plan.a_start_s + swap <= 53.0 + 1e-6
      and abs((plan.a_start_s + swap) / 2.0 - round((plan.a_start_s + swap) / 2.0)) < 1e-3)
r.pull_to(a_mix + n + 2 * SR)
out = r.audio()
gap = longest_gap_ms(out[a_mix:a_mix + n])
check(f"y la mezcla no tiene huecos de silencio ({gap:.0f} ms) ni clics (salto {max_jump(out):.4f})", gap < 100 and max_jump(out) < bd.CLICK)
r.sess.stop()

# ---- B callada en toda la parte de la mezcla en que entraría sola: la mezcla tapa el silencio -----------------------------------
SONGS = {"A": song(70, 220.0, 120.0, conf=0.2), "B": song(70, 330.0, 120.0, silence=[(0.0, 50.0)])}
r = Rig(SONGS, {"A": "B"})
st = r.start()
with r.sess._lock:
    chk = dict(r.sess._pair.check)
print(f"INFO B callada durante toda la mezcla: tipo {st['transition_type']}, puntuador {chk}", flush=True)
plan = st["plan"]
if plan.kind != KIND_CUT:
    a_mix, n = round(plan.a_start_s * SR), round(plan.length_s * SR)
    r.pull_to(a_mix + n + SR)
    gap = longest_gap_ms(r.audio()[a_mix:a_mix + n])
    check(f"B callada en la parte de la mezcla: el corte en el compás se cambia por la mezcla (A tapa el silencio; hueco {gap:.0f} ms)",
          st["transition_type"] == "blend" and chk.get("swapped") == "cut_bar" and gap < 500)
r.sess.stop()

print("FIN", flush=True)
