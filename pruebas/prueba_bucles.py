"""Bucles del modo DJ (fase 21) con audio sintético de golpes en una rejilla conocida: región de compases enteros que empieza en un
comienzo de compás, repetición sin clics y con longitud exacta, extensión del cuerpo con el nuevo inicio de mezcla en su sitio
(y múltiplo de la frase), la regla `needs_loop` en casos construidos a mano y entradas vacías o cortas sin excepciones.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_bucles.py"""
import os
import sys

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import loops
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid, TransitionPlan

SR = SAMPLE_RATE
BPM = 120.0
FIRST = 0.3                         # el primer golpe cae a 0,3 s
GRID = BeatGrid(first_beat_s=FIRST, bpm=BPM, beats_per_bar=4, downbeat_offset=0, confidence=0.9)
BAR = GRID.bar_s                    # 2 s
BAR_N = round(BAR * SR)


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def kicks(secs, seed=0):
    """Golpes de bombo (55 Hz con caída) en cada golpe de la rejilla, un tono de 503 Hz (no encaja en un número entero de ciclos
    por compás: el final de un compás no engancha con su principio) y un poco de ruido. Los dos canales son distintos."""
    n = int(secs * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    k = 0
    while GRID.beat_time(k) < secs:
        t0 = GRID.beat_time(k)
        if t0 >= 0:
            i0 = int(round(t0 * SR))
            m = min(n - i0, int(0.4 * SR))
            tt = np.arange(m) / SR
            out[i0:i0 + m] += (0.7 if k % 4 == 0 else 0.45) * np.sin(2 * np.pi * 55 * tt) * np.exp(-tt / 0.08)
        k += 1
    r = np.random.default_rng(seed)
    left = out + 0.15 * np.sin(2 * np.pi * 503 * t) + 0.01 * r.standard_normal(n)
    right = out + 0.15 * np.sin(2 * np.pi * 503 * t + 1.0) + 0.01 * r.standard_normal(n)
    return np.stack([left, right], axis=1).astype(np.float32)


def max_jump(x):
    return float(np.max(np.abs(np.diff(x, axis=0)))) if len(x) > 1 else 0.0


DATA = kicks(60.0)                  # 30 compases
NATURAL = max_jump(DATA)

# ------------------------------------------------------------------ (a) loop_region
reg, s, e = loops.loop_region(DATA, GRID, GRID.bar_time(5) + 0.3, 4)
check(f"loop_region: {len(reg)} muestras = 4 compases exactos ({4 * BAR_N}) y end - start = longitud",
      len(reg) == 4 * BAR_N and e - s == len(reg) and reg.dtype == np.float32 and reg.shape[1] == 2)
check("loop_region: el array son las muestras del original entre start_frame y end_frame", np.array_equal(reg, DATA[s:e]))
d_ms = abs(s - round(GRID.bar_time(5) * SR)) / SR * 1000
check(f"loop_region: empieza en el comienzo del compás 5 (a {d_ms:.2f} ms, dentro de los 2 ms del cruce por cero)", d_ms <= 2.0 + 1e-9)
_, s2, _ = loops.loop_region(DATA, GRID, GRID.bar_time(5) + 1.2, 4)
check("loop_region: elige el comienzo de compás más cercano (1,2 s después del 5 es el 6)",
      abs(s2 - round(GRID.bar_time(6) * SR)) <= round(0.002 * SR))
reg3, s3, e3 = loops.loop_region(DATA, GRID, GRID.bar_time(8), 8)
check(f"loop_region: 8 compases desde el compás 8 ({len(reg3)} muestras)", len(reg3) == 8 * BAR_N and e3 - s3 == len(reg3))
sig = DATA.mean(axis=1)
c_val = abs(float(sig[s]))
check(f"loop_region: el comienzo mueve la muestra a un valor cercano a 0 ({c_val:.4f}, no peor que el del compás exacto "
      f"{abs(float(sig[round(GRID.bar_time(5) * SR)])):.4f})", c_val <= abs(float(sig[round(GRID.bar_time(5) * SR)])) + 1e-9)
_, sn, en = loops.loop_region(DATA, GRID, 59.0, 4)
check(f"loop_region: con start_s al final la región cabe en el audio ({en} <= {len(DATA)}) y sigue siendo de 4 compases",
      en <= len(DATA) and en - sn == 4 * BAR_N)
_, s0, e0 = loops.loop_region(DATA, GRID, -5.0, 4)
check(f"loop_region: con start_s negativo empieza en el primer compás que cabe ({s0 / SR:.3f} s >= 0)", s0 >= 0 and e0 - s0 == 4 * BAR_N)
check("loop_region: sin sitio para la región (audio de 3 s, 4 compases) devuelve vacío",
      len(loops.loop_region(DATA[:3 * SR], GRID, 1.0, 4)[0]) == 0)
check("loop_region: entradas malas (sin audio, vacío, sin rejilla, bars 0, start_s NaN, bpm 0) devuelven vacío sin excepciones",
      all(len(loops.loop_region(*args)[0]) == 0 for args in (
          (None, GRID, 1.0, 4), (np.zeros((0, 2), np.float32), GRID, 1.0, 4), (DATA, None, 1.0, 4), (DATA, GRID, 1.0, 0),
          (DATA, GRID, float("nan"), 4), (DATA, BeatGrid(0.0, 0.0), 1.0, 4), (DATA, "no", 1.0, 4), (DATA, GRID, None, 4),
          (DATA[:5], GRID, 0.0, 1))))
mono_reg = loops.loop_region(DATA[:, 0].copy(), GRID, 4.0, 2)[0]
check("loop_region: un audio de una dimensión también vale", mono_reg.ndim == 1 and len(mono_reg) == 2 * BAR_N)

# ------------------------------------------------------------------ (b) repeat
R0 = round((GRID.bar_time(6) + 0.0045) * SR)                  # empieza dentro de un bombo y acaba en mitad de otro: no engancha
region = DATA[R0:R0 + BAR_N + BAR_N // 3]                       # un compás y un tercio, sin ajustar nada
rep = loops.repeat(region, 4)
n = len(region)
check(f"repeat: la longitud es exactamente times * len(region) ({len(rep)} = {4 * n}), float32 y estéreo",
      len(rep) == 4 * n and rep.dtype == np.float32 and rep.shape[1] == 2)
check("repeat: el principio y el final del resultado son los de la región, sin tocar (empalman con el audio de alrededor)",
      np.array_equal(rep[:50], region[:50]) and np.array_equal(rep[-50:], region[-50:]))
h = round(0.003 * SR) // 2
guard = h + 2
same = all(np.array_equal(rep[k * n + guard:(k + 1) * n - guard], region[guard:n - guard]) for k in range(4))
check("repeat: lejos de las uniones cada repetición es idéntica a la región (periodo exacto del compás)", same)
seams = [k * n for k in (1, 2, 3)]
changed = [int(np.sum(np.any(rep[s - h - 5:s + h + 5] != np.tile(region, (4, 1))[s - h - 5:s + h + 5], axis=1))) for s in seams]
check(f"repeat: solo cambian los ~{2 * h} fotogramas que rodean cada unión ({changed})", all(0 < c <= 2 * h for c in changed))
j = max_jump(rep)
raw_tile = np.tile(region, (4, 1))
check(f"repeat: sin clics, salto máx {j:.4f} <= 1,5 veces el natural del audio ({NATURAL:.4f}); a pelo daría {max_jump(raw_tile):.4f}",
      j <= 1.5 * NATURAL and max_jump(raw_tile) > 1.5 * NATURAL)
cs = loops.repeat(region, 3, 0.0)
check("repeat: con crossfade_ms = 0 es una repetición a pelo (longitud exacta, mismas muestras)", np.array_equal(cs, np.tile(region, (3, 1))))
one = loops.repeat(region, 1)
check("repeat: una sola vez devuelve una copia igual (no una vista)", np.array_equal(one, region) and not np.shares_memory(one, region))
check("repeat: times 0, negativo o no entero y región vacía dan un array vacío sin excepciones",
      all(len(loops.repeat(region, t)) == 0 for t in (0, -2, 2.5, None)) and len(loops.repeat(np.zeros((0, 2), np.float32), 3)) == 0
      and len(loops.repeat(None, 3)) == 0)
for m in (1, 2, 5, 40, 300):
    tiny = loops.repeat(DATA[1000:1000 + m], 3)
    if len(tiny) != 3 * m or not np.isfinite(tiny).all():
        check(f"repeat: región corta de {m} muestras", False)
        break
else:
    check("repeat: regiones de 1, 2, 5, 40 y 300 muestras (más cortas que el fundido) dan la longitud exacta y finita", True)
check("repeat: un audio de una dimensión devuelve una dimensión y longitud exacta",
      loops.repeat(region[:, 0].copy(), 3).shape == (3 * n,))
sine = np.stack([np.sin(2 * np.pi * 440 * np.arange(BAR_N) / SR)] * 2, axis=1).astype(np.float32)       # 440 Hz: 1760 ciclos por compás
pr = loops.repeat(sine, 3)
check(f"repeat: un seno que engancha consigo mismo no cambia de nivel en las uniones (salto máx {max_jump(pr):.4f} vs {max_jump(sine):.4f})",
      max_jump(pr) <= 1.5 * max_jump(sine))
seam_rms = float(np.sqrt(np.mean(pr[BAR_N - h:BAR_N + h].astype(np.float64) ** 2)))
check(f"repeat: la potencia en la unión es la del resto ({seam_rms:.3f} frente a 0,707)", abs(seam_rms - 0.7071) < 0.1)

# ------------------------------------------------------------------ (c) extend_body
MIX = GRID.bar_time(12)                      # compás 12: no es múltiplo de 8 (es 8 + 4)
segs, new_mix = loops.extend_body(DATA, GRID, MIX, 4, 4)
m_frame = round(MIX * SR)
check(f"extend_body: el nuevo inicio de mezcla cae exactamente 4 compases después ({new_mix:.4f} = {MIX + 4 * BAR:.4f})",
      abs(new_mix - (MIX + 4 * BAR)) < 1e-9)
check(f"extend_body: el nuevo inicio es el compás {GRID.bar_at(new_mix):.3f}, múltiplo de la frase de 8", abs(GRID.bar_at(new_mix) - 16) < 1e-9
      and round(GRID.bar_at(new_mix)) % 8 == 0)
total = sum(len(x) for x in segs)
check(f"extend_body: 4 + 4 compases en 2 segmentos de 4 compases ({len(segs)} segmentos, {total} muestras = {8 * BAR_N})",
      len(segs) == 2 and total == 8 * BAR_N and all(len(x) == 4 * BAR_N and x.shape[1] == 2 and x.dtype == np.float32 for x in segs))
seq = np.concatenate(segs, axis=0)
check("extend_body: la primera muestra es la de L (empalma con el cuerpo) y la última la de M - 1 (empalma con la mezcla)",
      np.array_equal(seq[:50], DATA[m_frame - 4 * BAR_N:m_frame - 4 * BAR_N + 50]) and np.array_equal(seq[-50:], DATA[m_frame - 50:m_frame]))
full = np.concatenate([DATA[:m_frame - 4 * BAR_N], seq, DATA[m_frame:m_frame + 5 * SR]], axis=0)
check(f"extend_body: el cuerpo, los segmentos y el principio de la mezcla seguidos no tienen clics (salto máx {max_jump(full):.4f} "
      f"<= 1,5 veces el natural {NATURAL:.4f})", max_jump(full) <= 1.5 * NATURAL)
MIX_B = GRID.bar_time(12)
mb = round(MIX_B * SR)
tt = (np.arange(len(DATA)) - (mb - 2 * BAR_N)) / SR                     # un cambio lento de nivel (0 a 0,4) a mitad de la región:
DATA_B = (DATA + (0.2 * (1 + np.tanh(tt * 3)))[:, None]).astype(np.float32)      # el final no engancha con el principio (escalón de 0,4)
NAT_B = max_jump(DATA_B)
segs_b, _ = loops.extend_body(DATA_B, GRID, MIX_B, 4, 4)
seq_b = np.concatenate(segs_b, axis=0)
full_b = np.concatenate([DATA_B[:mb - 4 * BAR_N], seq_b, DATA_B[mb:mb + 5 * SR]], axis=0)
raw_b = np.concatenate([DATA_B[:mb - 4 * BAR_N], np.tile(DATA_B[mb - 4 * BAR_N:mb], (2, 1)), DATA_B[mb:mb + 5 * SR]], axis=0)
check(f"extend_body: con una región que no engancha, sin clics en las uniones (salto máx {max_jump(full_b):.4f} <= 1,5 veces el "
      f"natural; a pelo daría {max_jump(raw_b):.4f})", max_jump(full_b) <= 1.5 * NAT_B and max_jump(raw_b) > 1.5 * NAT_B)
period_ok = np.array_equal(seq[guard:4 * BAR_N - guard], seq[4 * BAR_N + guard:8 * BAR_N - guard])
check("extend_body: el audio alargado es periódico con el periodo de la región (4 compases)", period_ok)
segs8, new8 = loops.extend_body(DATA, GRID, GRID.bar_time(16), 8, 4)
check(f"extend_body: 8 compases extra con región de 4: 3 segmentos y la mezcla 8 compases después (compás {GRID.bar_at(new8):.1f})",
      len(segs8) == 3 and abs(GRID.bar_at(new8) - 24) < 1e-9 and sum(len(x) for x in segs8) == 12 * BAR_N)
segs2, new2 = loops.extend_body(DATA, GRID, GRID.bar_time(12), 6, 4)
check(f"extend_body: 6 compases extra con región de 4 usa el mayor divisor (3 compases): {len(segs2)} segmentos de {len(segs2[0]) / BAR_N:.0f} "
      f"compases, nuevo inicio en el compás {GRID.bar_at(new2):.0f}",
      len(segs2) == 3 and all(len(x) == 3 * round(BAR * SR) for x in segs2) and abs(GRID.bar_at(new2) - 18) < 1e-9)
segs_s, _ = loops.extend_body(DATA, GRID, GRID.bar_time(2), 8, 4)
check(f"extend_body: con la mezcla en el compás 2 la región de 4 compases no cabe antes y se acorta a lo que cabe (2 compases): "
      f"{len(segs_s)} segmentos", len(segs_s) == 5 and all(len(x) == 2 * BAR_N for x in segs_s))
bad = [
    (None, GRID, MIX, 4), (np.zeros((0, 2), np.float32), GRID, MIX, 4), (DATA, None, MIX, 4), (DATA, GRID, MIX, 0), (DATA, GRID, MIX, -4),
    (DATA, GRID, MIX, 2.5), (DATA, GRID, float("nan"), 4), (DATA, GRID, 500.0, 4), (DATA, GRID, -1.0, 4), (DATA, GRID, 0.5, 4),
    (DATA[:SR], GRID, 0.9, 4), (DATA, GRID, MIX, True),
]
res = [loops.extend_body(*args) for args in bad]
check("extend_body: datos malos (sin audio, sin rejilla, extra 0 o negativo, mezcla fuera o sin sitio) dan ([], mix_start_s) sin excepciones",
      all(r[0] == [] for r in res) and res[0][1] == MIX and res[7][1] == 500.0)
check("extend_body: loop_bars no válido (0, -1, 2.5) no lanza excepciones",
      all(loops.extend_body(DATA, GRID, MIX, 4, lb)[0] == [] for lb in (0, -1, 2.5)))

# ------------------------------------------------------------------ (d) needs_loop
A_INFO = {"duration_s": 60.0}
B_INFO = {"duration_s": 200.0, "intro_s": 0.0}


def plan_at(bar, length_bars=8, b_start=0.0, ratio=1.0, kind="blend"):
    return TransitionPlan(a_start_s=GRID.bar_time(bar), b_start_s=b_start, length_s=length_bars * BAR, tempo_ratio_b=ratio, kind=kind)


def reason_ok(r):
    return isinstance(r, tuple) and len(r) == 2 and r[0] in (0, 4, 8) and isinstance(r[1], str) and len(r[1]) > 5 and "—" not in r[1]


r = loops.needs_loop(A_INFO, B_INFO, plan_at(16), GRID, GRID)
check(f"needs_loop: mezcla en un comienzo de frase y B lista: 0 ({r[1]})", reason_ok(r) and r[0] == 0)
r = loops.needs_loop(A_INFO, B_INFO, plan_at(12), GRID, GRID)
check(f"needs_loop: mezcla en el compás 12 (fuera de frase) con sitio: 4 ({r[1]})", reason_ok(r) and r[0] == 4)
r = loops.needs_loop(A_INFO, B_INFO, plan_at(14), GRID, GRID)
check(f"needs_loop: mezcla en el compás 14: ni 4 ni 8 compases la dejan en una frase: 0 ({r[1]})", reason_ok(r) and r[0] == 0)
r = loops.needs_loop(A_INFO, B_INFO, plan_at(13), GRID, GRID)
check(f"needs_loop: mezcla en el compás 13: 0 ({r[1]})", reason_ok(r) and r[0] == 0)
low = BeatGrid(FIRST, BPM, 4, 0, 0.39)
r = loops.needs_loop(A_INFO, B_INFO, plan_at(12), low, GRID)
r2 = loops.needs_loop(A_INFO, B_INFO, plan_at(12), GRID, low)
check(f"needs_loop: rejilla poco fiable (confianza 0,39) en A o en B: 0 ({r[1]})", reason_ok(r) and r[0] == 0 and reason_ok(r2) and r2[0] == 0)
r = loops.needs_loop(A_INFO, B_INFO, plan_at(12), BeatGrid(FIRST, BPM, 4, 0, 0.4), GRID)
check("needs_loop: confianza justo 0,4 ya es fiable", r[0] == 4)
r = loops.needs_loop(A_INFO, B_INFO, plan_at(12), None, GRID)
r2 = loops.needs_loop(A_INFO, B_INFO, plan_at(12), GRID, None)
check(f"needs_loop: sin rejilla de A o de B: 0 ({r[1]})", reason_ok(r) and r[0] == 0 and reason_ok(r2) and r2[0] == 0)
poco = {"duration_s": GRID.bar_time(12) + 8 * BAR + 3 * BAR}            # tras la mezcla (8 compases) no caben 4 compases extra
r = loops.needs_loop(poco, B_INFO, plan_at(12), GRID, GRID)
check(f"needs_loop: con poco margen hasta el final de A (la mezcla más 4 compases no caben): 0 ({r[1]})", reason_ok(r) and r[0] == 0)
justo = {"duration_s": GRID.bar_time(12) + 4 * BAR + 8 * BAR}
r = loops.needs_loop(justo, B_INFO, plan_at(12), GRID, GRID)
check(f"needs_loop: cabe justo (4 compases extra y la mezcla acaban con la canción): 4 ({r[1]})", reason_ok(r) and r[0] == 4)
# intro de B: llega a su cuerpo (b_start + length * ratio) antes de que acabe su intro
b_intro = {"duration_s": 200.0, "intro_s": 24.0}
r = loops.needs_loop({"duration_s": 90.0}, b_intro, plan_at(16, 8, b_start=0.0), GRID, GRID)    # 16 s de mezcla: le faltan 8 s = 4 compases de B
check(f"needs_loop: la intro de B no está lista (faltan 8 s) y A está en una frase: 8, que la mantienen ({r[1]})", reason_ok(r) and r[0] == 8)
r = loops.needs_loop(A_INFO, b_intro, plan_at(12, 8, b_start=0.0), GRID, GRID)
check(f"needs_loop: intro pendiente y A a 4 compases de una frase: 4 sirve a las dos cosas ({r[1]})", reason_ok(r) and r[0] == 4)
r = loops.needs_loop(A_INFO, {"duration_s": 200.0, "intro_s": 40.0}, plan_at(12, 8), GRID, GRID)
check(f"needs_loop: intro pendiente de 24 s (12 compases): 8 ({r[1]})", reason_ok(r) and r[0] == 8)
r = loops.needs_loop(A_INFO, {"duration_s": 200.0, "intro_s": 16.5}, plan_at(16, 8), GRID, GRID)
check(f"needs_loop: a B le falta menos de un compás de intro (0,5 s): 0 ({r[1]})", reason_ok(r) and r[0] == 0)
r = loops.needs_loop(A_INFO, {"duration_s": 200.0, "intro_s": 24.0}, plan_at(16, 8, b_start=8.0), GRID, GRID)
check(f"needs_loop: B entra por 8 s y su intro ya está hecha al acabar la mezcla: 0 ({r[1]})", reason_ok(r) and r[0] == 0)
r = loops.needs_loop({"duration_s": GRID.bar_time(16) + 8 * BAR + 2 * BAR}, b_intro, plan_at(16, 8), GRID, GRID)
check(f"needs_loop: intro pendiente pero A no tiene margen para 8 ni para 4 compases: 0 ({r[1]})", reason_ok(r) and r[0] == 0)
r = loops.needs_loop({"duration_s": GRID.bar_time(16) + 8 * BAR + 5 * BAR}, b_intro, plan_at(16, 8), GRID, GRID)
check(f"needs_loop: intro pendiente de 4 compases, A tiene sitio para 4 pero no para 8: 4 ({r[1]})", reason_ok(r) and r[0] == 4)
r = loops.needs_loop(A_INFO, b_intro, plan_at(16, 8, kind=KIND_CUT), GRID, GRID)
check(f"needs_loop: un corte limpio no lleva bucle: 0 ({r[1]})", reason_ok(r) and r[0] == 0)
off_bar = TransitionPlan(a_start_s=GRID.bar_time(12) + 0.7, b_start_s=0.0, length_s=16.0)
r = loops.needs_loop(A_INFO, B_INFO, off_bar, GRID, GRID)
check(f"needs_loop: mezcla que no empieza en un comienzo de compás: 0 ({r[1]})", reason_ok(r) and r[0] == 0)
weird = [
    (None, B_INFO, plan_at(12), GRID, GRID), (A_INFO, None, plan_at(12), GRID, GRID), (A_INFO, B_INFO, None, GRID, GRID),
    ({}, B_INFO, plan_at(12), GRID, GRID), (A_INFO, {}, plan_at(12), GRID, GRID), ("x", 3, "y", 4, 5),
    ({"duration_s": float("nan")}, B_INFO, plan_at(12), GRID, GRID), ({"duration_s": -3}, B_INFO, plan_at(12), GRID, GRID),
    (A_INFO, {"intro_s": float("inf")}, plan_at(12), GRID, GRID), (A_INFO, {"intro_s": "mucho"}, plan_at(12), GRID, GRID),
    (A_INFO, B_INFO, TransitionPlan(float("nan"), 0.0, 16.0), GRID, GRID), (A_INFO, B_INFO, TransitionPlan(0.0, 0.0, 0.0), GRID, GRID),
    (A_INFO, B_INFO, plan_at(12, ratio=None), GRID, GRID), (A_INFO, B_INFO, plan_at(12), BeatGrid(FIRST, 0.0, 4, 0, 1.0), GRID),
]
out = [loops.needs_loop(*args) for args in weird]
check("needs_loop: entradas vacías, absurdas o con NaN dan una tupla (0 o más, motivo) sin excepciones", all(reason_ok(o) for o in out))
check("needs_loop: sin duración de A o con duración inválida: 0", all(o[0] == 0 for o in out[3:4] + out[6:8]))

# ------------------------------------------------------------------ integración: lo que haría el motor
bars_extra, why = loops.needs_loop(A_INFO, B_INFO, plan_at(12), GRID, GRID)
segs, new_mix = loops.extend_body(DATA, GRID, GRID.bar_time(12), bars_extra, 4)
check(f"integración: needs_loop pide {bars_extra} y extend_body deja la mezcla en el compás {GRID.bar_at(new_mix):.0f} (múltiplo de 8)",
      bars_extra == 4 and round(GRID.bar_at(new_mix)) % 8 == 0 and sum(len(x) for x in segs) == (4 + bars_extra) * BAR_N)
print("FIN", flush=True)
