"""Tipos de transición en la sesión del DJ (transition_types dentro de dj_engine.EngineSession): cada tipo (mezcla, corte en el
compás, eco de salida y filtro) sale con la longitud exacta y en su sitio, sin clic en las uniones; la cola del eco se SUMA al
principio del cuerpo de B (también con tempo estirado, después del empalme); `advanced` sale donde B empieza a dominar; la
posición, el seek y el replan siguen bien; solo A y B en memoria; y typed=False da la mezcla clásica. Sin sonido (cargador
falso). Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_tipos.py"""
import gc
import logging

import _banco_dj as bd
from _banco_dj import SR, TICK, Rig, check, max_jump

import numpy as np

from services import dj_dsp, transition_types
from services.deck_gain import deck_gain
from services.mix_types import KIND_BLEND, KIND_CUT

logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)
bd.DEFAULTS["entry_gain"] = False     # se compara muestra a muestra; la ganancia de entrada: prueba_motor_ganancia.py
T = transition_types


def song(dur, freq, bpm, **kw):
    return dict(dur=dur, freq=freq, bpm=bpm, **kw)


# (nombre, canciones, tipo esperado, tipo de plan)
CASES = [
    ("mezcla (todo encaja)", {"A": song(70, 220.0, 120.0), "B": song(70, 330.0, 120.0)}, T.TYPE_BLEND, KIND_BLEND),
    ("corte en el compás (rejilla poco fiable)", {"A": song(70, 220.0, 120.0, conf=0.2), "B": song(70, 330.0, 120.0)},
     T.TYPE_CUT_BAR, KIND_BLEND),
    ("eco de salida (final brusco)", {"A": song(70, 220.0, 120.0, outro=2), "B": song(70, 330.0, 120.0)}, T.TYPE_ECHO_OUT,
     KIND_BLEND),
    ("filtro (tonos que chocan)", {"A": song(70, 220.0, 120.0), "B": song(70, 330.0, 120.0, tone="2B")}, T.TYPE_FILTER, KIND_BLEND),
    ("eco de salida en un corte (tempos lejanos)", {"A": song(70, 220.0, 120.0), "B": song(70, 330.0, 150.0)}, T.TYPE_ECHO_OUT,
     KIND_CUT),
    ("eco de salida con B estirada (empalme y cola juntos)", {"A": song(70, 220.0, 120.0, outro=2), "B": song(70, 330.0, 124.0)},
     T.TYPE_ECHO_OUT, KIND_BLEND),
]

for name, songs, want, want_plan in CASES:
    r = Rig(songs, {"A": "B", "B": None})
    st = r.start()
    plan, kind = st["plan"], st["transition_type"]
    check(f"{name}: tipo {kind} con plan {plan.kind} ({plan.reason.split('tipo: ')[-1][:60]})", kind == want and plan.kind == want_plan)
    sess = r.sess
    with sess._lock:
        pair = sess._pair
        a_mix, b_body_after = pair.a_mix, pair.b_body
    ratio = float(plan.tempo_ratio_b or 1.0)
    A, B = r.gained("A"), r.gained("B")
    full_b = r.fake.full("B")
    gb = deck_gain(bd.LUFS["B"], max(float(full_b.max()), -float(full_b.min())))
    if plan.kind == KIND_CUT:
        c, bs = round(plan.a_start_s * SR), round(plan.b_start_s * SR)
        piece = round(0.5 * SR)
        x, tail = T.render_typed_parts(A[c - piece:c], B[bs:bs + piece], plan, kind, bpm=120.0)
        mix_at, n, b_body = c - piece, len(x), bs + piece
        split = piece
    else:
        n = round(plan.length_s * SR)
        bs = round(plan.b_start_s * SR)
        b_body = round((plan.b_start_s + plan.length_s * ratio) * SR)
        if abs(ratio - 1.0) < 1e-6:
            bpart = B[bs:bs + n]
        else:
            bpart = r.fake("B", tempo_ratio=ratio, start_s=plan.b_start_s, duration_s=plan.length_s * ratio)
            bpart *= np.float32(gb)
        x, tail = T.render_typed_parts(A[a_mix:a_mix + n], bpart, plan, kind, bpm=120.0)
        mix_at = a_mix
        split = n // 2 if kind in (T.TYPE_BLEND, T.TYPE_FILTER) else T._cut_point(plan, n, SR)
    check(f"{name}: la mezcla mide exactamente lo que dice el plan ({len(x)} muestras) y la cola es "
          f"{'de eco' if kind == T.TYPE_ECHO_OUT else 'vacía'} ({len(tail)})",
          len(x) == (n if plan.kind != KIND_CUT else 2 * round(0.5 * SR))
          and (len(tail) > SR if kind == T.TYPE_ECHO_OUT and plan.kind == KIND_CUT else kind == T.TYPE_ECHO_OUT or not len(tail)))
    r.pull_to(mix_at + n + len(tail) + 3 * SR)
    out = r.audio()
    check(f"{name}: A idéntica hasta el punto de mezcla", np.array_equal(out[bd.FADE:mix_at], A[bd.FADE:mix_at]))
    check(f"{name}: la mezcla en su sitio, muestra a muestra", np.allclose(out[mix_at:mix_at + n], x, atol=2e-6))
    if len(tail):
        body_start = b_body + (round((plan.length_s + 0.020) * SR) - n if abs(ratio - 1.0) > 1e-6 and plan.kind != KIND_CUT else 0)
        k0 = body_start - b_body                                # empalme del tramo estirado (antes de él no se compara)
        got = out[mix_at + n + k0:mix_at + n + len(tail)]
        want_tail = B[b_body + k0:b_body + len(tail)] + tail[k0:]
        check(f"{name}: la cola del eco se SUMA al principio del cuerpo de B (desde su primera muestra tras el empalme)",
              np.allclose(got, want_tail, atol=2e-6) and np.abs(tail[k0:]).max() > 0.01)
        check(f"{name}: tras la cola, el cuerpo de B tal cual", np.array_equal(out[mix_at + n + len(tail):mix_at + n + len(tail) + SR],
                                                                            B[b_body + len(tail):b_body + len(tail) + SR]))
    else:
        k0 = round((plan.length_s + 0.020) * SR) - n if abs(ratio - 1.0) > 1e-6 else 0
        check(f"{name}: después, el cuerpo de B desde b_start + length * ratio",
              np.array_equal(out[mix_at + n + k0:mix_at + n + k0 + 2 * SR], B[b_body + k0:b_body + k0 + 2 * SR]))
    region = out[mix_at - SR:mix_at + n + len(tail) + SR]
    check(f"{name}: sin clic en ninguna unión (salto máximo {max_jump(region):.4f})", max_jump(region) < bd.CLICK)
    adv = r.first("advanced")
    check(f"{name}: advanced cuando B empieza a dominar (muestra {mix_at + split})",
          adv is not None and mix_at + split <= adv["_frames"] < mix_at + split + TICK + 1024)
    st_after = next((s_ for s_ in r.states if s_["path"] == "B" and s_["_frames"] >= mix_at + n + len(tail) + 2 * SR), None)
    if st_after is not None:
        exp = (b_body + (st_after["_frames"] - mix_at - n)) / SR
        check(f"{name}: la posición en el cuerpo de B va en su tiempo original ({st_after['position_s']:.3f} s)",
              abs(st_after["position_s"] - exp) < 0.03)
    check(f"{name}: memoria, nunca más de 2 canciones (visto {r.max_alive})", r.max_alive <= 2)
    r.sess.stop()

    # seek dentro de la mezcla y replan con este mismo tipo
    r = Rig(songs, {"A": "B", "B": None})
    st = r.start()
    with r.sess._lock:
        b_body_after = r.sess._pair.b_body
    loads = len(r.fake.calls)
    r.sess.replan(force=True)
    st = r.wait(lambda x: len(r.fake.calls) > loads and x["plan"] is not None)
    check(f"{name}: replan(force) rehace la misma transición con el mismo tipo", st is not None and st["transition_type"] == want)
    with r.sess._lock:
        b_body_after = r.sess._pair.b_body
        a_mix = r.sess._pair.a_mix
    r.sess.seek(a_mix / SR + 0.3)
    st = r.tick()
    check(f"{name}: seek dentro de la mezcla salta al cuerpo de B tras la cola ({st['position_s']:.3f} s)",
          st["path"] == "B" and abs(st["position_s"] - b_body_after / SR) < 1e-6)
    mark = r.frames
    r.pull(SR)
    B = r.gained("B")
    check(f"{name}: y suena B desde ahí, sin clic", np.array_equal(r.audio()[mark + bd.FADE:mark + SR], B[b_body_after + bd.FADE:b_body_after + SR])
          and max_jump(r.audio()[mark - 500:]) < bd.CLICK)
    r.sess.stop()

# ---- typed=False: la mezcla clásica aunque el tipo elegido fuera otro --------------------------------------------------------
songs = CASES[2][1]
r = Rig(songs, {"A": "B"}, typed=False)
st = r.start()
check("typed=False: mezcla larga (o corte limpio) sin tipo en el motivo", st["transition_type"] == T.TYPE_BLEND
      and "tipo:" not in st["plan"].reason)
plan = st["plan"]
a_mix, n = round(plan.a_start_s * SR), round(plan.length_s * SR)
r.pull_to(a_mix + n + SR)
A, B = r.gained("A"), r.gained("B")
bs = round(plan.b_start_s * SR)
check("typed=False: idéntica a render_transition", np.allclose(r.audio()[a_mix:a_mix + n],
                                                              dj_dsp.render_transition(A[a_mix:a_mix + n], B[bs:bs + n], plan), atol=1e-6))
r.sess.stop()

# ---- plan tardío con tempos lejanos: corte con eco, sin clic ----------------------------------------------------------------
songs = {"A": song(70, 220.0, 120.0), "B": song(70, 330.0, 150.0)}
r = Rig(songs, {"A": "B"})
r.fake.delay["B"] = 2.0
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
r.wait(lambda x: x["next_path"] == "B")
r.pull(int(56.3 * SR))                                          # el corte por tempos lejanos iba en 54 s
st = r.wait(lambda x: x["plan"] is not None)
plan = st["plan"]
check(f"plan tardío con tempos lejanos: corte con eco de salida ({st['transition_type']}, {plan.reason[:40]}...)",
      plan.kind == KIND_CUT and "ya había pasado" in plan.reason and st["transition_type"] == T.TYPE_ECHO_OUT)
r.pull(20 * SR)
c = round(plan.a_start_s * SR)
out = r.audio()
check(f"y suena sin clic, con A entera hasta medio segundo antes del corte (salto máximo {max_jump(out):.4f})",
      max_jump(out) < bd.CLICK and np.array_equal(out[bd.FADE:c - SR // 2], r.gained("A")[bd.FADE:c - SR // 2]))
check("y se pasa a B una vez", [x["advanced"] for x in r.states if x["advanced"]] == ["B"])
r.sess.stop()

# ---- la cola del eco con el empalme del tramo estirado (no lo da la regla de elección, pero el código debe hacerlo bien) -------
r = Rig({"A": song(70, 220.0, 120.0), "B": song(70, 330.0, 124.0)}, {})
r.sess.play("B")
r.wait(lambda x: x["state"] == "playing")
with r.sess._lock:
    b_tr = r.sess._a
rng = np.random.default_rng(5)
join = rng.uniform(-0.1, 0.1, (882, 2)).astype(np.float32)
tail = rng.uniform(-0.2, 0.2, (SR, 2)).astype(np.float32)
before = b_tr.data.copy()
more, nb = r.sess._tail_entry(b_tr, 10 * SR, join, tail, 10.0, 0.97)
post = more[0][0] if more else None
check("cola con empalme: un trozo que empieza con el empalme, sigue con el cuerpo de B y lleva la cola sumada desde el principio",
      len(more) == 1 and len(post) == SR and nb == 11 * SR and np.allclose(post[:882], join + tail[:882], atol=1e-6)
      and np.allclose(post[882:], b_tr.data[10 * SR + 882:11 * SR] + tail[882:], atol=1e-6))
check("y el cuerpo de B no se ha tocado (la cola va en una copia)", np.array_equal(before, b_tr.data))
more, nb = r.sess._tail_entry(b_tr, b_tr.frames - 1000, None, tail, 0.0, 1.0)
check("si B se acaba antes que la cola, se corta con rampa al final de B (sin clic)", nb == b_tr.frames
      and len(more[0][0]) == 1000 and abs(float(more[0][0][-1, 0] - b_tr.data[-1, 0])) < 1e-3)
more, nb = r.sess._tail_entry(b_tr, 5 * SR, join, tail[:0], 5.0, 0.97)
check("sin cola, solo el empalme (como antes)", len(more) == 1 and more[0][0] is join and nb == 5 * SR + 882)
r.sess.stop()

# ---- la regla de seguridad manda: datos malos nunca dan una mezcla larga -----------------------------------------------------
songs = {"A": song(70, 220.0, 120.0, conf=0.1), "B": song(70, 330.0, 120.0, conf=0.1)}
r = Rig(songs, {"A": "B"})
st = r.start()
check(f"rejillas poco fiables: no hay mezcla larga de graves ({st['transition_type']})", st["transition_type"] == T.TYPE_CUT_BAR)
r.sess.stop()
gc.collect()
print("FIN", flush=True)
