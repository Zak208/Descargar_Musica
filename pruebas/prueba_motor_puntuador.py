"""El puntuador (transition_scorer) dentro de la sesión del DJ: un plan que score_plan descarta pasa a corte limpio con su motivo;
una mezcla renderizada con clic, recorte, hueco o salto de volumen se cambia por un corte en el compás (sin tocarla); lo que
cuesta por transición; y audio_check=None no puntúa nada. Sin sonido (cargador falso).
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_puntuador.py"""
import logging

import _banco_dj as bd
from _banco_dj import SR, Rig, check, max_jump

import numpy as np

from services import dj_engine, transition_scorer, transition_types
from services.mix_types import KIND_BLEND, KIND_CUT

logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)
T = transition_types


def song(dur, freq, bpm, **kw):
    return dict(dur=dur, freq=freq, bpm=bpm, **kw)


GOOD = {"A": song(70, 220.0, 120.0), "B": song(70, 330.0, 120.0)}

# ---- una mezcla buena: se puntúa, no se toca, y lo que cuesta ------------------------------------------------------------
costs = []
LONG = {"A": song(180, 220.0, 120.0, outro=40), "B": song(180, 330.0, 120.0)}
for bars, songs in ((8, GOOD), (16, GOOD), (16, LONG)):
    r = Rig(songs, {"A": "B"}, bars=bars)
    st = r.start()
    with r.sess._lock:
        chk = dict(r.sess._pair.check)
    costs.append((st["plan"].length_s, chk.get("seconds")))
    check(f"mezcla buena de {st['plan'].length_s:.0f} s: el puntuador no pone pegas ({chk})", st["transition_type"] == T.TYPE_BLEND
          and chk.get("audio") == [] and chk.get("plan") in ("ok", "dudosa") and "swapped" not in chk)
    r.sess.stop()
print("INFO coste del puntuador ligero por mezcla: " + ", ".join(f"{L:.0f} s de mezcla: {c * 1000:.0f} ms" for L, c in costs), flush=True)
check("el puntuador ligero cuesta unos 0,1 s o menos por mezcla (hasta 32 s de mezcla)", all(c is not None and c < 0.15 for _, c in costs))

# ---- una mezcla que sale con clic: se cambia por un corte en el compás ------------------------------------------------------
orig_render = dj_engine.EngineSession._render


def broken_render(a_part, b_part, plan, kind, ctx):
    x, tail = orig_render(a_part, b_part, plan, kind, ctx)
    if kind == T.TYPE_BLEND and plan.kind != KIND_CUT:
        x = x.copy()
        x[len(x) // 3] += 0.6                                  # un clic en mitad de la mezcla (como un fallo del render)
    return x, tail


dj_engine.EngineSession._render = staticmethod(broken_render)
try:
    for mode in ("light", "full"):
        r = Rig(GOOD, {"A": "B"}, audio_check=mode)
        st = r.start()
        with r.sess._lock:
            chk = dict(r.sess._pair.check)
        plan = st["plan"]
        # el ligero solo mira las uniones: un clic en mitad de la mezcla solo lo ve el completo
        if mode == "full":
            check(f"puntuador completo: la mezcla con clic se cambia por corte en el compás ({plan.reason.split('tipo: ')[-1][:70]})",
                  st["transition_type"] == T.TYPE_CUT_BAR and chk.get("swapped") == T.TYPE_BLEND and "puntuador" in plan.reason)
            a_mix, n = round(plan.a_start_s * SR), round(plan.length_s * SR)
            r.pull_to(a_mix + n + SR)
            check(f"y lo que suena no tiene el clic (salto máximo {max_jump(r.audio()):.4f})", max_jump(r.audio()) < bd.CLICK)
        else:
            print(f"INFO puntuador ligero con un clic en mitad de la mezcla: {chk} (solo mira las uniones)", flush=True)
        r.sess.stop()
finally:
    dj_engine.EngineSession._render = staticmethod(orig_render)


# un clic en la unión con el cuerpo de B (lo que sí mira el ligero)
def broken_end(a_part, b_part, plan, kind, ctx):
    x, tail = orig_render(a_part, b_part, plan, kind, ctx)
    if kind == T.TYPE_BLEND and plan.kind != KIND_CUT:
        x = x.copy()
        x[-1] += 0.5
    return x, tail


dj_engine.EngineSession._render = staticmethod(broken_end)
try:
    r = Rig(GOOD, {"A": "B"})
    st = r.start()
    with r.sess._lock:
        chk = dict(r.sess._pair.check)
    check(f"puntuador ligero: un clic en la unión con B cambia la mezcla por corte en el compás ({chk.get('audio')})",
          st["transition_type"] == T.TYPE_CUT_BAR and chk.get("swapped") == T.TYPE_BLEND and any("clic" in m for m in chk["audio"]))
    r.sess.stop()
finally:
    dj_engine.EngineSession._render = staticmethod(orig_render)

# ---- recorte: dos canciones fuertes sumadas -----------------------------------------------------------------------------------
LOUD = {"P": song(70, 220.0, 120.0, amp=0.78), "Q": song(70, 330.0, 120.0, amp=0.78)}
r = Rig(LOUD, {"P": "Q"})
st = r.start("P")
with r.sess._lock:
    chk = dict(r.sess._pair.check)
check(f"dos canciones al límite sumadas: el recorte que añade la mezcla la cambia por corte en el compás ({chk.get('audio')})",
      st["transition_type"] == T.TYPE_CUT_BAR and any("recorte" in m for m in chk.get("audio", [])))
plan = st["plan"]
a_mix, n = round(plan.a_start_s * SR), round(plan.length_s * SR)
r.pull_to(a_mix + n + SR)
out = r.audio()
check(f"y no sale nada por encima de 1,0 (pico {np.abs(out).max():.3f}) ni hay clic (salto {max_jump(out):.4f})",
      np.abs(out).max() <= 1.0 and max_jump(out) < bd.CLICK)
r.sess.stop()

# ---- score_plan descarta: corte limpio con su motivo, sin renderizar la mezcla ------------------------------------------------
orig_score = transition_scorer.score_plan
transition_scorer.score_plan = lambda a, b, p: {"score": 0.1, "verdict": "descartar", "reasons": ["motivo de prueba"], "metrics": {}}
try:
    r = Rig(GOOD, {"A": "B"})
    st = r.start()
    plan = st["plan"]
    check(f"score_plan descarta: corte limpio con el motivo del puntuador ({plan.reason[:70]})",
          plan.kind == KIND_CUT and "puntuador descartó" in plan.reason and "motivo de prueba" in plan.reason)
    stretched = [c for c in r.fake.calls if c[0] == "B" and c[1] != 1.0]
    check("y no se estiró ni se renderizó ninguna mezcla", not stretched)
    r.pull(70 * SR)
    check("y se pasa a B sin clic", [x["advanced"] for x in r.states if x["advanced"]] == ["B"] and max_jump(r.audio()) < bd.CLICK)
    r.sess.stop()
finally:
    transition_scorer.score_plan = orig_score

# ---- audio_check=None: no se puntúa nada -----------------------------------------------------------------------------------
r = Rig(LOUD, {"P": "Q"}, audio_check=None)
st = r.start("P")
with r.sess._lock:
    chk = dict(r.sess._pair.check)
check(f"audio_check=None: no se puntúa y la mezcla se queda ({st['transition_type']})", chk == {} and st["plan"].kind == KIND_BLEND
      and st["transition_type"] == T.TYPE_BLEND)
r.sess.stop()

print("FIN", flush=True)
