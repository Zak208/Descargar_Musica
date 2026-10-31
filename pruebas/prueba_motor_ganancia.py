"""Ganancia de entrada en la sesión del DJ (EngineSession(entry_gain=True), lo normal): como el mando de ganancia de un DJ, el
nivel de lo primero que suena de B se iguala al de lo último de A (B se sube o se baja y, si no basta, el final de A se lleva
hacia B en sus últimos 2 s) y la ganancia de B vuelve a 1,0 en 8 s sin escalón. Cortes, eco de salida y mezclas; B 12 dB más
floja y 12 dB más fuerte; seek, replan, memoria; A que ya calla; y la mezcla que se adelanta si A acaba en silencio. Cada caso
de nivel falla sin el arreglo (se comprueba también con entry_gain=False). Sin sonido (cargador falso).
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_ganancia.py"""
import gc
import logging

import _banco_dj as bd
from _banco_dj import SR, Rig, check, max_jump

import numpy as np

from services import dj_engine
from services.dj_engine import _gated_rms
from services.mix_types import KIND_CUT

logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)


def song(dur, freq, bpm, **kw):
    return dict(dur=dur, freq=freq, bpm=bpm, **kw)


def db(v):
    return 20.0 * np.log10(v) if v else -120.0


def cut_step(r, plan, k_from_pair):
    """Nivel (1 s, sin silencio) de lo que sale antes y después de que entre B, y su diferencia en dB."""
    out = r.audio()
    la, lb = _gated_rms(out[k_from_pair - SR:k_from_pair]), _gated_rms(out[k_from_pair:k_from_pair + SR])
    return db(la), db(lb), abs(db(la) - db(lb))


LOUD = dict(amp=0.5, bump=0.3)                          # unos -9 dBFS
SOFT = dict(amp=0.125, bump=0.075)                      # 12 dB más floja

# ---- corte (tempos lejanos): B 12 dB más floja y 12 dB más fuerte, con corte limpio y con eco --------------------------------
for name, a_kw, b_kw in (("B 12 dB más floja", LOUD, SOFT), ("B 12 dB más fuerte", SOFT, LOUD)):
    for typed in (False, True):
        steps = {}
        for eg in (False, True):
            songs = {"P": song(70, 220.0, 120.0, **a_kw), "Q": song(70, 330.0, 150.0, **b_kw)}
            r = Rig(songs, {"P": "Q", "Q": None}, typed=typed, entry_gain=eg)
            st = r.start("P")
            plan = st["plan"]
            with r.sess._lock:
                p = r.sess._pair
                b_in = p.a_mix + (len(p.x1) if p.x1 is not None else 0)
                chk, b_body = dict(p.check), p.b_body
            r.pull_to(b_in + 12 * SR)
            la, lb, step = cut_step(r, plan, b_in)
            steps[eg] = step
            if eg:
                kind = st["transition_type"]
                check(f"corte ({name}, {kind}): A {la:.1f} dB y B {lb:.1f} dB a cada lado del corte, salto de {step:.1f} dB "
                      f"(sin la ganancia, {steps[False]:.1f} dB); ganancias {chk}",
                      plan.kind == KIND_CUT and step < 3.0 and steps[False] > 10.0)
                out = r.audio()
                check(f"corte ({name}, {kind}): sin clic (salto máximo {max_jump(out):.4f}) y sin pasar de 1,0",
                      max_jump(out) < bd.CLICK and np.abs(out).max() <= 1.0)
                full_b = r.fake.full("Q")
                body_out = b_in + (b_body - p.b_cut)
                check(f"corte ({name}, {kind}): pasada la rampa (8 s), el cuerpo de B tal cual, a su nivel de siempre",
                      np.array_equal(out[body_out:body_out + SR], full_b[b_body:b_body + SR])
                      and body_out - b_in >= int(dj_engine.TRIM_RAMP_S * SR) - 1)
                lvl = [db(_gated_rms(out[b_in + j * SR // 2:b_in + (j + 1) * SR // 2])) for j in range(20)]
                check(f"corte ({name}, {kind}): la vuelta de B a su nivel es suave (mayor cambio entre medios segundos "
                      f"{max(abs(np.diff(lvl))):.2f} dB)", max(abs(np.diff(lvl))) < 2.0)
            r.sess.stop()

# ---- mezcla larga con B 12 dB más floja: B se sube (en una mezcla solo se sube) ---------------------------------------------
songs = {"P": song(70, 220.0, 120.0, **LOUD), "Q": song(70, 330.0, 120.0, **SOFT)}
r = Rig(songs, {"P": "Q", "Q": None})
st = r.start("P")
with r.sess._lock:
    chk = dict(r.sess._pair.check)
check(f"mezcla ({st['transition_type']}) con B 12 dB más floja: B se sube hasta 6 dB ({chk.get('entry_gain_db')}) y A no se toca",
      st["plan"].kind != KIND_CUT and 5.9 <= chk.get("entry_gain_db", 0) <= 6.01 and "a_end_gain_db" not in chk)
plan = st["plan"]
a_mix, n = round(plan.a_start_s * SR), round(plan.length_s * SR)
r.pull_to(a_mix + n + 10 * SR)
check(f"y sin clic (salto máximo {max_jump(r.audio()):.4f})", max_jump(r.audio()) < bd.CLICK)
check(f"memoria: nunca más de 2 canciones (visto {r.max_alive})", r.max_alive <= 2)
r.sess.stop()
songs = {"P": song(70, 220.0, 120.0, **SOFT), "Q": song(70, 330.0, 120.0, **LOUD)}
r = Rig(songs, {"P": "Q"})
st = r.start("P")
with r.sess._lock:
    chk = dict(r.sess._pair.check)
check(f"mezcla con B 12 dB más fuerte: no se baja B (destaparía el final de A) ({chk})", "entry_gain_db" not in chk)
r.sess.stop()

# ---- seek dentro de la transición y replan: la ganancia no se queda pegada ---------------------------------------------------
songs = {"P": song(70, 220.0, 120.0, **LOUD), "Q": song(70, 330.0, 150.0, **SOFT)}
r = Rig(songs, {"P": "Q"})
st = r.start("P")
loads = len(r.fake.calls)
r.sess.replan(force=True)
st = r.wait(lambda x: len(r.fake.calls) > loads and x["plan"] is not None)
with r.sess._lock:
    chk, b_body = dict(r.sess._pair.check), r.sess._pair.b_body
check(f"replan(force): la misma ganancia de entrada ({chk})", "entry_gain_db" in chk)
r.sess.seek(st["plan"].a_start_s + 0.2)
st = r.tick()
mark = r.frames
r.pull(SR)
check("seek dentro de la transición: al cuerpo de B tras la rampa, a su nivel de siempre",
      st["path"] == "Q" and np.array_equal(r.audio()[mark + bd.FADE:mark + SR], r.fake.full("Q")[b_body + bd.FADE:b_body + SR]))
r.sess.stop()

# ---- A que ya calla (silencio digital al final): no se iguala con un silencio ----------------------------------------------
songs = {"P": song(70, 220.0, 120.0, silence=[(40.0, 70.0)], **LOUD), "Q": song(70, 330.0, 150.0, **SOFT)}
r = Rig(songs, {"P": "Q"}, typed=False)
st = r.start("P")
with r.sess._lock:
    chk = dict(r.sess._pair.check)
check(f"A en silencio digital antes del corte: el corte va donde A deja de sonar y se iguala con lo que sonaba "
      f"({st['plan'].a_start_s} s; {chk})", st["plan"].a_start_s <= 40.0 + 1e-6)
r.sess.stop()

# ---- mezcla que pisaría el silencio final de A: se adelanta ----------------------------------------------------------------
songs = {"P": song(70, 220.0, 120.0, silence=[(60.0, 70.0)]), "Q": song(70, 330.0, 120.0)}
r = Rig(songs, {"P": "Q"})
st = r.start("P")
plan = st["plan"]
check(f"A calla desde 60 s: la mezcla se adelanta para acabar donde A deja de sonar ({plan.a_start_s} a "
      f"{plan.a_start_s + plan.length_s} s; {plan.reason.split('; ')[-2][:60] if 'adelantada' in plan.reason else plan.reason[-60:]})",
      plan.kind != KIND_CUT and plan.a_start_s + plan.length_s <= 60.0 + 1e-6 and "adelantada" in plan.reason)
r.sess.stop()

gc.collect()
print("FIN", flush=True)
