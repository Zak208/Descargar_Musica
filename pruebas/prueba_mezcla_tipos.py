"""Tipos compartidos del motor de mezcla: la rejilla de golpes (compases, frases) y el plan de una transición.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_mezcla_tipos.py"""
import os
import sys

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from services.mix_types import BeatGrid, TransitionPlan


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


g = BeatGrid(first_beat_s=0.5, bpm=120.0)
check("a 120 BPM un golpe dura 0,5 s y un compás 2 s", g.beat_s == 0.5 and g.bar_s == 2.0)
check("el golpe 4 cae en 2,5 s y el -2 en -0,5 s", g.beat_time(4) == 2.5 and g.beat_time(-2) == -0.5)
check("del instante 1,2 s, el golpe más cercano es el de 1,0 s, y de 1,3 s el de 1,5 s",
      abs(g.nearest_beat_time(1.2) - 1.0) < 1e-9 and abs(g.nearest_beat_time(1.3) - 1.5) < 1e-9)
check("el número de golpe de un instante tiene decimales", abs(g.beat_at(1.25) - 1.5) < 1e-9)
check("el compás 0 empieza en el primer golpe y el 3 seis segundos después", g.bar_time(0) == 0.5 and g.bar_time(3) == 6.5)
check("el siguiente comienzo de compás igual o posterior: de 0,5 s es 0,5 s; de 0,51 s es 2,5 s",
      abs(g.next_bar_time(0.5) - 0.5) < 1e-9 and abs(g.next_bar_time(0.51) - 2.5) < 1e-9)
check("de un instante anterior al primer golpe se llega al primer compás", abs(g.next_bar_time(0.0) - 0.5) < 1e-9)
check("frases de 4 compases: de 2,6 s el siguiente comienzo de frase es 8,5 s (compás 4)", abs(g.next_bar_time(2.6, 4) - 8.5) < 1e-9)
check("y si ya está en un comienzo de frase, se queda ahí", abs(g.next_bar_time(8.5, 4) - 8.5) < 1e-9)
check("frases de 16 compases: el siguiente desde 10 s es el compás 16 (32,5 s)", abs(g.next_bar_time(10.0, 16) - 32.5) < 1e-9)
d = BeatGrid(first_beat_s=0.0, bpm=100.0, downbeat_offset=2)
check("con el compás abriendo en el tercer golpe, el compás 0 empieza dos golpes después", abs(d.bar_time(0) - 1.2) < 1e-9)
check("y el siguiente comienzo de compás desde 0 s es el de 1,2 s", abs(d.next_bar_time(0.0) - 1.2) < 1e-9)
check("también hacia atrás: los compases son 2,4 s", abs(d.bar_time(-1) - (-1.2)) < 1e-9)
check("el compás de un instante, con decimales", abs(d.bar_at(2.4) - 0.5) < 1e-9)
three = BeatGrid(0.0, 90.0, beats_per_bar=3)
check("compases de 3 golpes (vals)", abs(three.bar_s - 2.0) < 1e-9 and abs(three.bar_time(2) - 4.0) < 1e-9)

plan = TransitionPlan(a_start_s=150.0, b_start_s=0.0, length_s=16.0)
check("el cambio de graves por defecto cae a la mitad de la mezcla", plan.bass_swap_at == 8.0 and plan.kind == "blend"
      and plan.tempo_ratio_b == 1.0)
check("y se puede fijar a mano", TransitionPlan(0, 0, 16.0, bass_swap_s=4.0).bass_swap_at == 4.0)
check("un corte no tiene duración", TransitionPlan(150.0, 0.0, 0.0, kind="cut").bass_swap_at == 0.0)
print("FIN")
