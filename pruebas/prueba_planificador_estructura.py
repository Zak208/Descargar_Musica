"""Estructura en el planificador de mezclas (mix_planner con `structure` en la ficha): dos drops a la vez acortan la mezcla o la
cambian por un corte; el drop de B al final de la mezcla se usa solo si no empeora el cuadre con la frase; las voces solapadas
(peso bajo) solo prueban una frase más corta; y sin estructura todo es como antes. Puro, sin audio.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_planificador_estructura.py"""
import os
import sys

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from services import mix_planner, structure  # noqa: E402
from services.mix_types import KIND_BLEND, KIND_CUT, BeatGrid  # noqa: E402


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


GRID = BeatGrid(0.0, 120.0, confidence=0.9)                     # compás de 2 s


def fichas(ev_a=None, ev_b=None, voc_a=None, voc_b=None, with_structure=True):
    a = {"duration_s": 240.0, "outro_s": 48.0, "intro_s": 8.0, "bpm": 120.0, "beatgrid": GRID}
    b = {"duration_s": 200.0, "outro_s": 16.0, "intro_s": 40.0, "bpm": 120.0, "beatgrid": GRID}
    if with_structure:
        a["structure"] = {"events": ev_a or [], "vocal": voc_a or [], "energy": [], "bass": [], "sections": []}
        b["structure"] = {"events": ev_b or [], "vocal": voc_b or [], "energy": [], "bass": [], "sections": []}
    return a, b


def drop(t):
    return {"t": float(t), "type": "drop", "end": None, "strength": 1.0}


base = mix_planner.plan_transition(*fichas(with_structure=False))
check(f"punto de partida: mezcla de 16 compases desde 192 s, B desde 16 s ({base.a_start_s}, {base.b_start_s}, {base.length_s})",
      base.kind == KIND_BLEND and (base.a_start_s, base.b_start_s, base.length_s) == (192.0, 16.0, 32.0))
same = mix_planner.plan_transition(*fichas())
check("con estructura vacía, el mismo plan", same == base)
a, b = fichas(with_structure=False)
a["structure"], b["structure"] = None, "texto sin leer"
check("con structure None o sin leer (texto), el mismo plan", mix_planner.plan_transition(a, b) == base)

# ---- dos drops a la vez -------------------------------------------------------------------------------------------------------
p = mix_planner.plan_transition(*fichas(ev_a=[drop(212.0)], ev_b=[drop(22.0)]))
check(f"drop de A a los 20 s de la mezcla y de B a los 6 s: se acorta a 8 compases y ya no coinciden ({p.length_s} s; {p.reason[-50:]})",
      p.kind == KIND_BLEND and p.length_s == 16.0 and "no coincidan los drops" in p.reason
      and not structure.drops_overlap(p.a_start_s, p.length_s, p.tempo_ratio_b, p.b_start_s, [drop(212.0)], [drop(22.0)]))
p = mix_planner.plan_transition(*fichas(ev_a=[drop(196.0)], ev_b=[drop(36.0)]))
check(f"drops que coinciden con cualquier frase: corte limpio al empezar la frase de A ({p.kind} en {p.a_start_s} s: {p.reason[:60]})",
      p.kind == KIND_CUT and p.a_start_s == 192.0 and "drops" in p.reason)

# ---- drop de B al final de la mezcla ------------------------------------------------------------------------------------------
p = mix_planner.plan_transition(*fichas(ev_b=[drop(64.0)]))
check(f"drop de B en 64 s: entra desde 32 s (comienzo de frase de 8) para que caiga al final de la mezcla ({p.b_start_s}; {p.reason[:90]})",
      p.b_start_s == 32.0 and p.length_s == 32.0 and "drop al final" in p.reason)
p = mix_planner.plan_transition(*fichas(ev_b=[drop(58.0)]))
check(f"drop de B en 58 s: la entrada que lo alinearía (26 s) cuadra peor con la frase: se queda en 16 s ({p.b_start_s})",
      p.b_start_s == 16.0 and "drop al final" not in p.reason)
p = mix_planner.plan_transition(*fichas(ev_b=[drop(190.0)]))
check(f"un drop de B que obligaría a entrar pasada su mitad no se usa ({p.b_start_s})", p.b_start_s == 16.0)

# ---- voces (peso bajo) ------------------------------------------------------------------------------------------------------
voc_a = [1.0] * 240
voc_b = [1.0 if 16 <= k < 40 else 0.0 for k in range(200)]
p = mix_planner.plan_transition(*fichas(voc_a=voc_a, voc_b=voc_b))
check(f"voces de las dos en el 75 % de la mezcla larga: se prueba la frase de la mitad y se queda si solapa menos ({p.length_s} s, "
      f"{structure.vocal_overlap(p.a_start_s, p.length_s, 1.0, p.b_start_s, voc_a, voc_b):.2f})",
      p.kind == KIND_BLEND and p.length_s == 16.0 and "menos voces" in p.reason)
p = mix_planner.plan_transition(*fichas(voc_a=voc_a, voc_b=[1.0] * 200))
check(f"voces de las dos en toda la mezcla y también en la corta: se queda la larga, nunca un corte ({p.kind}, {p.length_s} s)",
      p.kind == KIND_BLEND and p.length_s == 32.0)
voc_b = [1.0 if 16 <= k < 30 else 0.0 for k in range(200)]
p = mix_planner.plan_transition(*fichas(voc_a=voc_a, voc_b=voc_b))
check(f"voces solapadas en menos del 60 %: nada cambia ({p.length_s} s)", p.length_s == 32.0 and p.b_start_s == 16.0)

print("FIN", flush=True)
