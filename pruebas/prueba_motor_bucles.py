"""Bucles en la sesión del DJ (loops.needs_loop y extend_body dentro de dj_engine.EngineSession con loops=True): A repite los 4
compases de antes del punto de mezcla y la mezcla (la misma) llega más tarde; todo a la muestra, sin clic, con la posición, el
seek, el replan (bloqueado mientras el bucle suena), el truncado del trozo que suena en el principio del bucle y la memoria.
Sin sonido (cargador falso). Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_bucles.py"""
import logging

import _banco_dj as bd
from _banco_dj import SR, TICK, Rig, check, max_jump

import numpy as np

from services import dj_dsp, loops
from services.mix_types import BeatGrid

logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)
bd.DEFAULTS["entry_gain"] = False     # se compara muestra a muestra; la ganancia de entrada: prueba_motor_ganancia.py


def song(dur, freq, bpm, **kw):
    return dict(dur=dur, freq=freq, bpm=bpm, **kw)


# A: mezcla en un comienzo de frase (192 s) y B con una intro larga (52 s) que no llega a estar hecha al acabar la mezcla
SONGS = {"A": song(260, 220.0, 120.0, outro=68), "B": song(200, 330.0, 120.0, intro=52)}

r = Rig(SONGS, {"A": "B", "B": None}, loops=True, typed=False)
st = r.start()
plan = st["plan"]
with r.sess._lock:
    p = r.sess._pair
    L, M, reps, loop_bars = p.loop_start, p.a_mix, [len(x) for x in p.loop_segs], p.loop_bars
info_a, info_b = bd.info_of(SONGS, "A"), bd.info_of(SONGS, "B")
info_a["duration_s"], info_b["duration_s"], info_b["intro_s"] = 260.0, 200.0, 52.0     # needs_loop lee intro_s
want, why = loops.needs_loop(info_a, info_b, plan, BeatGrid(0.0, 120.0, confidence=0.9), BeatGrid(0.0, 120.0, confidence=0.9))
check(f"el motor pide el bucle que dice needs_loop ({loop_bars} compases; {why[:70]})", loop_bars == want == 8
      and st["loop_bars"] == 8 and "bucle de 8 compases" in plan.reason)
R = round(4 * 2.0 * SR)
check(f"bucle de 4 compases repetido 3 veces (la región y 2 repeticiones), justo antes del punto de mezcla ({L / SR:.1f} a {M / SR:.1f} s)",
      reps == [R, R, R] and M - L == R and abs(M / SR - plan.a_start_s) < 1e-6)
n = round(plan.length_s * SR)
out_mix = L + 3 * R                                        # en la salida, la mezcla empieza tras el bucle
r.pull_to(L + R + R // 2)
st = r.tick()
check(f"durante la 2.ª vuelta del bucle la posición vuelve a estar en la región ({st['position_s']:.3f} s)",
      st["path"] == "A" and abs(st["position_s"] - (L + R // 2) / SR) < 1e-6)
loads = len(r.fake.calls)
r.order["A"] = None
r.sess.replan()
r.tick()
r.tick()
st = r.tick()
check("con el bucle sonando, replan no cambia nada (va derecho a la mezcla)", st["next_path"] == "B" and st["plan"] is not None
      and len(r.fake.calls) == loads)
r.pull_to(out_mix + n + 3 * SR)
out = r.audio()
A, B = r.gained("A"), r.gained("B")
check("A idéntica hasta el principio del bucle", np.array_equal(out[bd.FADE:L], A[bd.FADE:L]))
tile = loops.repeat(A[L:M], 3)
check("el bucle suena tal cual (la región, repetida sin clic) y empalma con A por delante",
      np.array_equal(out[L:out_mix], tile) and np.array_equal(out[L:L + R - 200], A[L:M - 200]))
bs = round(plan.b_start_s * SR)
x = dj_dsp.render_transition(A[M:M + n], B[bs:bs + n], plan)
check("la mezcla (la misma de siempre, desde la misma muestra de A) empieza justo tras el bucle", np.allclose(out[out_mix:out_mix + n], x, atol=1e-6))
b_body = round((plan.b_start_s + plan.length_s) * SR)
check("y después el cuerpo de B", np.array_equal(out[out_mix + n:out_mix + n + 2 * SR], B[b_body:b_body + 2 * SR]))
check(f"sin clic en todo (salto máximo {max_jump(out):.4f}; en las uniones del bucle "
      f"{max(max_jump(out[L + k * R - 300:L + k * R + 300]) for k in range(4)):.4f})", max_jump(out) < bd.CLICK)
adv = r.first("advanced")
check("advanced en la segunda mitad de la mezcla (tras el bucle)", adv is not None and out_mix + n // 2 <= adv["_frames"] < out_mix + n // 2 + TICK + 1024)
check(f"memoria: nunca más de 2 canciones (visto {r.max_alive})", r.max_alive <= 2)
r.sess.stop()

# ---- seek dentro de la región del bucle: suena desde ahí, luego las repeticiones y la mezcla ---------------------------------
r = Rig(SONGS, {"A": "B"}, loops=True, typed=False)
st = r.start()
with r.sess._lock:
    L, M = r.sess._pair.loop_start, r.sess._pair.a_mix
f = L + R // 3
r.sess.seek(f / SR)
st = r.tick()
check("seek dentro de la región del bucle: la posición es esa", abs(st["position_s"] - f / SR) < 1e-9 and st["path"] == "A")
mark = r.frames
r.pull((M - f) + 2 * R + n + SR)
out = r.audio()
A = r.gained("A")
seg = out[mark:]
check("y suena el resto de la región, las 2 repeticiones y la mezcla, sin clic",
      np.array_equal(seg[bd.FADE:M - f - 200], A[f + bd.FADE:M - 200]) and max_jump(out[mark - 500:]) < bd.CLICK
      and np.allclose(seg[M - f + 2 * R:M - f + 2 * R + n], x, atol=1e-6))
r.sess.stop()

# ---- seek antes del bucle y replan antes de que empiece: se rehace con su bucle ------------------------------------------------
r = Rig(SONGS, {"A": "B"}, loops=True, typed=False)
st = r.start()
r.sess.seek(150.0)
r.tick()
loads = len(r.fake.calls)
r.sess.replan(force=True)
st = r.wait(lambda x_: len(r.fake.calls) > loads and x_["plan"] is not None)
check("replan antes de que suene el bucle: se rehace (con su bucle)", st is not None and st["loop_bars"] == 8)
with r.sess._lock:
    L = r.sess._pair.loop_start
mark = r.frames
r.pull(L - 150 * SR + 3 * R + SR)
out = r.audio()
check("y el bucle llega en su sitio tras el seek, sin clic", np.array_equal(out[mark + bd.FADE + L - 150 * SR:mark + L - 150 * SR + 3 * R],
                                                                         tile[bd.FADE:]) and max_jump(out[mark - 500:]) < bd.CLICK)
r.sess.stop()

# ---- el plan llega con el trozo que contiene el principio del bucle ya sonando: se acorta en él ----------------------------------
r = Rig(SONGS, {"A": "B"}, loops=True, typed=False)
r.fake.delay["B"] = 0.4
r.sess.play("A", start_s=176.0)                                 # trozo de 176 a 191 s; el bucle empieza en 184 s
r.wait(lambda x_: x_["state"] == "playing")
r.pull(SR)
st = r.wait(lambda x_: x_["plan"] is not None)
with r.sess._lock:
    L = r.sess._pair.loop_start
check(f"plan con el trozo del bucle ya sonando: hay bucle igual ({st['loop_bars']} compases, empieza en {L / SR:.0f} s)",
      st["loop_bars"] == 8 and "ya había pasado" not in st["plan"].reason)
r.pull_to(L - 176 * SR + 3 * R + n)
out = r.audio()
k = L - 176 * SR
check("y el bucle suena desde su principio, sin clic", np.allclose(out[k + bd.FADE:k + 3 * R], tile[bd.FADE:], atol=0)
      and max_jump(out) < bd.CLICK)
r.sess.stop()

# ---- carrera con la llamada de audio: bucles, tipos, replan y seek a la vez ---------------------------------------------------
import threading  # noqa: E402
import time  # noqa: E402

RACE = {"A": song(260, 220.0, 120.0, outro=68, intro=52), "B": song(260, 330.0, 120.0, outro=68, intro=52),
        "C": song(260, 440.0, 120.0, outro=68, intro=52)}
r = Rig(RACE, {"A": "B", "B": "C", "C": "A"}, loops=True)
r.sess.play("A", start_s=150.0)
r.wait(lambda x_: x_["state"] == "playing")
outs, halt = [], threading.Event()


def audio_thread():
    while not halt.is_set():
        outs.append(r.eng.pull(1024))      # muy por encima del tiempo real
        time.sleep(0.0003)


th = threading.Thread(target=audio_thread)
th.start()
t0, last, k, advs, seen_loop = time.monotonic(), 0.0, 0, 0, 0
while time.monotonic() - t0 < 40.0 and advs < 3:
    st = r.tick()
    advs += bool(st["advanced"])
    seen_loop = max(seen_loop, st.get("loop_bars", 0))
    now = time.monotonic() - t0
    if now - last > 0.4:
        last, k = now, k + 1
        r.sess.replan(force=(k % 3 == 0))
        if k % 4 == 0:
            cur = r.sess.current_path
            r.sess.seek(150.0 + (k % 5) * 9.0 if cur else 150.0)
    time.sleep(0.01)
halt.set()
th.join()
out = np.concatenate(outs)
errs = [x_["error"] for x_ in r.states if x_["error"]]
check(f"con la llamada de audio corriendo a la vez ({k} replan, {advs} pasos, bucles vistos: {seen_loop} compases, "
      f"{len(out) / SR:.0f} s de audio): sin clics (salto máximo {max_jump(out):.4f}) ni errores ({errs[:1]})",
      max_jump(out) < bd.CLICK and advs >= 2 and not errs and seen_loop == 8)
check(f"y nunca más de 2 canciones enteras vivas (máximo visto {r.max_alive})", r.max_alive <= 2)
r.sess.stop()

# ---- con loops=False (lo normal) no hay bucle -------------------------------------------------------------------------------
r = Rig(SONGS, {"A": "B"}, typed=False)
st = r.start()
check("loops=False: sin bucle (como antes)", st["loop_bars"] == 0 and "bucle" not in st["plan"].reason)
r.sess.stop()

print("FIN", flush=True)
