"""Arreglos de la sesión del DJ encontrados por una revisión (fase 0 de la integración): redondeo del plan que pasaba del final
de A, canciones cortas cuyo primer trozo ya pasaba del punto de mezcla, B muy corta con mezcla por frases demasiado larga, carga
que se quedaba en «cargando» si fallaba el volumen y canciones truncadas por el tope del cargador. Cada caso falla sin su arreglo.
Sin sonido (cargador falso). Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_dj_arreglos.py"""
import logging

import _banco_dj as bd
from _banco_dj import SR, Rig, check, max_jump

from services import dj_engine, mix_planner, pcm_loader
from services.mix_types import KIND_BLEND, KIND_CUT, BeatGrid

logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)

# ---- (a) redondeo del plan: la mezcla se pasaba unas muestras del final de A y caía a corte --------------------------------
for dur, info_a, info_b, what in (
        (180.2799, {}, {}, "sin análisis"),
        (180.0176, {"outro_ms": 20000}, {"intro_ms": 25000}, "con final de 20 s")):
    songs = {"A": {"dur": dur, "freq": 220.0, "bpm": 120.0, "info": info_a},
             "B": {"dur": 90.0, "freq": 330.0, "bpm": 120.0, "info": info_b}}
    r = Rig(songs, {"A": "B"}, typed=False)
    st = r.start()
    plan = st["plan"] if st else None
    over = (plan.a_start_s + plan.length_s) * SR - round(dur * SR) if plan else 0
    check(f"(a) A de {dur} s {what}: el plan se pasa {over:.0f} muestras del final y aun así es una mezcla "
          f"({plan.kind if plan else None}: {plan.reason[:50] if plan else ''})", plan is not None and plan.kind == KIND_BLEND)
    if plan is not None and plan.kind == KIND_BLEND:
        r.pull(int((dur + 3) * SR))
        adv = [x["advanced"] for x in r.states if x["advanced"]]
        check("(a) y se pasa a B sin clic", adv == ["B"] and max_jump(r.audio()) < bd.CLICK)
    r.sess.stop()

# ---- (b) canción de 20 s: el primer trozo de 15 s ya pasaba del punto de mezcla ---------------------------------------------
songs = {"A": {"dur": 20, "freq": 220.0, "bpm": 120.0}, "B": {"dur": 20, "freq": 330.0, "bpm": 120.0}}
r = Rig(songs, {"A": "B"}, typed=False)
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
r.pull(SR // 2)                                         # ya suena el primer trozo cuando llega el plan
st = r.wait(lambda x: x["plan"] is not None)
plan = st["plan"]
check(f"(b) A de 20 s con el primer trozo sonando: mezcla, no corte tardío ({plan.kind}: {plan.reason[:60]})",
      plan.kind == KIND_BLEND and "ya había pasado" not in plan.reason)
a_mix = round(plan.a_start_s * SR)
r.pull(30 * SR)
out = r.audio()
A = r.gained("A")
check("(b) A suena idéntica hasta el punto de mezcla y la mezcla empieza en esa muestra",
      bd.np.array_equal(out[bd.FADE:a_mix], A[bd.FADE:a_mix]) and not bd.np.array_equal(out[a_mix:a_mix + SR], A[a_mix:a_mix + SR]))
check(f"(b) sin clic al acortar el trozo que sonaba (salto máximo {max_jump(out):.4f})", max_jump(out) < bd.CLICK)
check("(b) y se pasa a B una sola vez", [x["advanced"] for x in r.states if x["advanced"]] == ["B"])
r.sess.stop()
# play(start_s) cerca del final, antes del punto de mezcla: el trozo empieza en 50 s y el punto (48 s de 70) no ha pasado
songs = {"A": {"dur": 70, "freq": 220.0, "bpm": 120.0}, "B": {"dur": 70, "freq": 330.0, "bpm": 120.0}}
r = Rig(songs, {"A": "B"}, typed=False)
r.sess.play("A", start_s=40.0)
r.wait(lambda x: x["state"] == "playing")
r.pull(SR)
st = r.wait(lambda x: x["plan"] is not None)
check(f"(b) play(start_s=40) con el punto de mezcla en el primer trozo: mezcla ({st['plan'].kind})", st["plan"].kind == KIND_BLEND)
r.sess.stop()

# ---- (c) B muy corta: la mezcla por frases no pasa de un tercio de B y deja cuerpo de B ------------------------------------
a = {"duration_s": 240.0, "outro_s": 32.0, "intro_s": 8.0, "bpm": 120.0, "beatgrid": BeatGrid(0.0, 120.0, confidence=0.9)}
b = {"duration_s": 25.0, "outro_s": 4.0, "intro_s": 8.0, "bpm": 120.0, "beatgrid": BeatGrid(0.0, 120.0, confidence=0.9)}
p = mix_planner.plan_transition(a, b)
check(f"(c) A de 240 s y B de 25 s: la mezcla cabe en B ({p.length_s} s desde {p.b_start_s} s; {p.reason[:50]})",
      p.kind == KIND_BLEND and p.length_s <= 25.0 / 3 + 1e-6 and p.b_start_s + p.length_s + 1.0 <= 25.0)
songs = {"A": {"dur": 240, "freq": 220.0, "bpm": 120.0, "outro": 32}, "B": {"dur": 25, "freq": 330.0, "bpm": 120.0, "outro": 4}}
r = Rig(songs, {"A": "B"}, typed=False)
st = r.start()
check(f"(c) y en la sesión: mezcla, no corte ({st['plan'].kind}: {st['plan'].reason[:50]})", st["plan"].kind == KIND_BLEND)
# si aun así la mezcla no se puede hacer, el corte va donde A se habría ido (no en el principio de la mezcla)
sess = r.sess
with sess._lock:
    a_tr = sess._a
orig = dj_engine.EngineSession._blend
dj_engine.EngineSession._blend = lambda self, *args: (None, "a propósito")
try:
    pair = sess._build_pair(a_tr, "B")
finally:
    dj_engine.EngineSession._blend = orig
plan_ok = st["plan"]
check(f"(c) corte por mezcla imposible: en el compás de donde acababa la mezcla ({pair.plan.a_start_s} s, la mezcla iba de "
      f"{plan_ok.a_start_s} a {plan_ok.a_start_s + plan_ok.length_s} s)", pair.plan.kind == KIND_CUT
      and plan_ok.a_start_s + plan_ok.length_s - 2.0 - 1e-6 <= pair.plan.a_start_s <= plan_ok.a_start_s + plan_ok.length_s + 1e-6)
r.sess.stop()

# ---- (d) si el volumen falla al cargar, no se queda «cargando» para siempre ---------------------------------------------------
songs = {"A": {"dur": 30, "freq": 220.0, "bpm": 120.0}}
r = Rig(songs, {})
orig_gain = dj_engine._gain_for
dj_engine._gain_for = lambda lufs, peak: 1 / 0
try:
    r.sess.play("A")
    st = r.wait(lambda x: x["state"] != "loading", timeout=5.0)
finally:
    dj_engine._gain_for = orig_gain
check(f"(d) fallo al calcular la ganancia de la que se pide: estado «stopped» con error ({st and st['error']})",
      st is not None and st["state"] == "stopped" and st["error"] and r.sess.current_path is None)
r.sess.play("A")
check("(d) y se puede volver a pedir", r.wait(lambda x: x["state"] == "playing") is not None)
r.sess.stop()

# ---- (e) canción truncada por el tope del cargador: corte al llegar al tope, no una mezcla sobre un final que no existe -----
old_max = pcm_loader.MAX_SECONDS
pcm_loader.MAX_SECONDS = 60                              # el tope real (480 s) gastaría 170 MB por canción en la prueba
try:
    songs = {"A": {"dur": 90, "cap": 60, "freq": 220.0, "bpm": 120.0, "outro": 20},
             "B": {"dur": 60, "freq": 330.0, "bpm": 120.0}}
    r = Rig(songs, {"A": "B"}, typed=False)
    st = r.start()
    plan = st["plan"]
    check(f"(e) A de 90 s cargada hasta el tope de 60 s: corte al llegar al tope ({plan.kind} en {plan.a_start_s} s: "
          f"{plan.reason[:60]})", plan.kind == KIND_CUT and 58.0 - 1e-6 <= plan.a_start_s <= 60.0 and "tope" in plan.reason)
    r.pull(63 * SR)
    check("(e) A suena hasta el corte y entra B sin clic", [x["advanced"] for x in r.states if x["advanced"]] == ["B"]
          and max_jump(r.audio()) < bd.CLICK)
    r.sess.stop()
    songs = {"A": {"dur": 60, "freq": 220.0, "bpm": 120.0, "outro": 20}, "B": {"dur": 60, "freq": 330.0, "bpm": 120.0}}
    r = Rig(songs, {"A": "B"}, typed=False)
    st = r.start()
    check(f"(e) una canción que de verdad dura lo que el tope no se toma por truncada ({st['plan'].kind})",
          st["plan"].kind == KIND_BLEND)
    r.sess.stop()
finally:
    pcm_loader.MAX_SECONDS = old_max

print("FIN", flush=True)
