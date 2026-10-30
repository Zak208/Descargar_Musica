"""Tipos de transición del modo DJ (fase 16, `services/transition_types.py`) con señales sintéticas: «blend» es exactamente
`dj_dsp.render_transition`, longitudes exactas en cada tipo, corte en el compás con el golpe de B entero, eco de salida al
tempo y sin graves (con su cola por separado y sin salto al sumarla al cuerpo de B), filtro que quita lo que debe sin dos
graves a la vez, continuidad con lo de antes y lo de después, entradas vacías, mono y cortas, la regla de elección
(`choose_type`) y velocidad. No abre ningún flujo de sonido.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_tipos_transicion.py"""
import os
import sys
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import dj_dsp, transition_types as tt
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid, TransitionPlan

SR = SAMPLE_RATE


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def tone(freq, secs, amp=0.3, phase=0.0):
    t = np.arange(int(round(secs * SR))) / SR
    y = (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)
    return np.stack([y, y], axis=1)


def proj(sig, freq, t0, t1, ch=0):
    """Amplitud de un seno de frecuencia `freq` dentro de sig[t0:t1] (segundos), por proyección."""
    seg = sig[int(t0 * SR):int(t1 * SR), ch].astype(np.float64)
    t = (np.arange(len(seg)) + int(t0 * SR)) / SR
    c = np.sum(seg * np.cos(2 * np.pi * freq * t)) * 2 / len(seg)
    s = np.sum(seg * np.sin(2 * np.pi * freq * t)) * 2 / len(seg)
    return float(np.hypot(c, s))


def max_jump(x):
    return float(np.max(np.abs(np.diff(x, axis=0)))) if len(x) > 1 else 0.0


def ok_array(y, n=None):
    return y.dtype == np.float32 and y.ndim == 2 and y.shape[1] == 2 and bool(np.isfinite(y).all()) and (n is None or len(y) == n)


def song_a(secs):
    return (tone(60, secs, 0.4) + tone(1000, secs, 0.2)).astype(np.float32)


def song_b(secs):
    return (tone(55, secs, 0.4, 0.7) + tone(1300, secs, 0.2, 0.3)).astype(np.float32)


LEN, SWAP, BPM = 16.0, 8.0, 120.0          # a 120 BPM un compás son 2 s: el cambio de graves (8 s) cae en un compás
N = int(LEN * SR)
plan = TransitionPlan(a_start_s=0.0, b_start_s=0.0, length_s=LEN, bass_swap_s=SWAP)
A = song_a(LEN + 4)                         # A trae más audio que la mezcla
B_FULL = song_b(LEN + 10)                   # B entera desde donde entra: la mezcla usa los primeros 16 s y el cuerpo sigue
B = B_FULL[:N]
natural = max_jump(A) + max_jump(B_FULL)

# ------------------------------------------------------------------ blend = render_transition
ref = dj_dsp.render_transition(A, B, plan)
check("blend: exactamente lo mismo que dj_dsp.render_transition",
      np.array_equal(tt.render_typed(A, B, plan, tt.TYPE_BLEND, BPM), ref))
mix, tail = tt.render_typed_parts(A, B, plan, tt.TYPE_BLEND, BPM)
check("blend con render_typed_parts: la misma mezcla y cola vacía", np.array_equal(mix, ref) and tail.shape == (0, 2))
for kind in tt.TYPES:
    out = tt.render_typed(A, B, plan, kind, BPM)
    if not ok_array(out, N):
        check(f"{kind}: longitud exacta round(length_s * 44100)", False)
        break
else:
    check(f"los cuatro tipos devuelven exactamente round(length_s * 44100) = {N} fotogramas float32 estéreo sin NaN", True)
odd = TransitionPlan(0.0, 0.0, 3.33337, bass_swap_s=1.5)
check("con una duración que no cae en muestra entera, también exacta (round) en los cuatro tipos",
      all(len(tt.render_typed(A, B_FULL, odd, k, BPM)) == round(3.33337 * SR) for k in tt.TYPES))
check("base_length: la de la mezcla, o len(a) + len(b) en un corte",
      tt.base_length(A, B, plan) == N and tt.base_length(A[:100], B[:50], TransitionPlan(0, 0, 0.0, kind=KIND_CUT)) == 150)

# ------------------------------------------------------------------ cut_bar
c = int(SWAP * SR)
cb = tt.render_typed(A, B, plan, tt.TYPE_CUT_BAR, BPM)
ra = int(round(tt.CUT_A_RAMP_S * SR))
rb = int(round(tt.CUT_B_RAMP_S * SR))
check("cut_bar: A sin tocar hasta 5 ms antes del corte", np.array_equal(cb[:c - ra], A[:c - ra]))
check("cut_bar: desde el corte, B sin tocar (el golpe del primer tiempo entra entero, sin rampa encima)",
      np.array_equal(cb[c:], B[c:]))
only_a_ramp = A[c - ra:c - rb].astype(np.float64) * dj_dsp._ramp(ra, True)[:ra - rb, None]
check("cut_bar: las dos solo suenan juntas los 2 ms de la rampa de B (antes de ella, en la rampa de A, no hay nada de B)",
      float(np.max(np.abs(cb[c - ra:c - rb] - only_a_ramp))) < 1e-6)
check(f"cut_bar sin clics (salto máx {max_jump(cb):.4f} <= natural {natural:.4f})", max_jump(cb) <= natural)
check("cut_bar: primer fotograma = A y último = B (sin salto con lo de antes ni con el cuerpo de B)",
      np.array_equal(cb[0], A[0]) and np.array_equal(cb[-1], B[-1]))
nobpm = tt.render_typed(A, B, TransitionPlan(0.0, 0.0, LEN), tt.TYPE_CUT_BAR)
check("cut_bar sin bass_swap_s: corta a la mitad", np.array_equal(nobpm[N // 2:], B[N // 2:]) and np.array_equal(nobpm[:N // 2 - ra], A[:N // 2 - ra]))

# ------------------------------------------------------------------ echo_out
beat = 60.0 / BPM
eo_mix, eo_tail = tt.render_typed_parts(A, B, plan, tt.TYPE_ECHO_OUT, BPM)
send0 = c - int(round(beat * SR))
first_rep = send0 + int(round(0.75 * beat * SR))
check(f"echo_out: mezcla de {len(eo_mix)} fotogramas y sin cola (el eco se apaga dentro: el corte está a 8 s del final)",
      ok_array(eo_mix, N) and eo_tail.shape == (0, 2))
check("echo_out: A sin tocar hasta que llega la primera repetición del eco", np.array_equal(eo_mix[:first_rep], A[:first_rep]))
wet = eo_mix.astype(np.float64) - B
wet[:c] = 0.0
check(f"echo_out: tras el corte suena el eco de A por encima de B (1 kHz a {proj(wet, 1000, SWAP, SWAP + 1):.3f})",
      proj(wet, 1000, SWAP, SWAP + 1) > 0.03)
check(f"echo_out: el eco no lleva graves de A (60 Hz tras el corte a {proj(wet, 60, SWAP, SWAP + 2):.5f}, más de 50 dB por debajo)",
      proj(wet, 60, SWAP, SWAP + 2) < 0.4 * 10 ** (-50 / 20))
check(f"echo_out: los graves de A se cortan en el golpe de entrada de B (60 Hz en la salida tras el corte: {proj(eo_mix, 60, SWAP, SWAP + 2):.5f})",
      proj(eo_mix, 60, SWAP, SWAP + 2) < 0.002 and proj(eo_mix, 55, SWAP + 1, SWAP + 3) > 0.39)
check("echo_out: B desde el corte con su golpe entero (lo que hay es B + eco, sin rampa en B)",
      float(np.max(np.abs(eo_mix[c:] - B[c:] - wet[c:]))) < 1e-6)
# Distancia entre repeticiones: un golpecito de 1 kHz medio golpe antes del corte y B en silencio
click_a = np.zeros((N, 2), np.float32)
pos = c - int(0.5 * beat * SR)
click_a[pos:pos + int(0.01 * SR)] = tone(1000, 0.01, 0.8)
e_mix = tt.render_typed(click_a, np.zeros((N, 2), np.float32), plan, tt.TYPE_ECHO_OUT, BPM)
env = np.abs(e_mix[:, 0])
step = int(round(0.75 * beat * SR))
reps = [float(env[pos + k * step:pos + k * step + int(0.01 * SR)].max()) for k in range(1, 5)]
gaps = [float(env[pos + k * step + int(0.03 * SR):pos + (k + 1) * step - int(0.03 * SR)].max()) for k in range(1, 4)]
print("     repeticiones del eco (cada 3/4 de golpe):", ", ".join(f"{v:.3f}" for v in reps), "; entre medias:",
      ", ".join(f"{v:.1e}" for v in gaps), flush=True)
check("echo_out: el eco repite cada 3/4 de golpe exactos, cada vez más bajo (realimentación 0,45) y en silencio entre medias",
      all(r > 0.05 for r in reps[:3]) and all(b < a for a, b in zip(reps, reps[1:]))
      and abs(reps[1] / reps[0] - tt.ECHO_FEEDBACK) < 0.05 and max(gaps) < 1e-3)
check(f"echo_out sin clics (salto máx {max_jump(eo_mix):.4f} <= natural {natural:.4f})", max_jump(eo_mix) <= natural)
# Corte cerca del final: el eco no cabe y sale cola
late = TransitionPlan(0.0, 0.0, LEN, bass_swap_s=LEN - 0.5)
l_mix, l_tail = tt.render_typed_parts(A, B, late, tt.TYPE_ECHO_OUT, BPM)
check(f"echo_out con el corte 0,5 s antes del final: mezcla exacta ({len(l_mix)}) y cola aparte ({len(l_tail) / SR:.2f} s) que acaba en 0",
      ok_array(l_mix, N) and len(l_tail) > SR and float(np.max(np.abs(l_tail[-1]))) < 1e-6)
stream = np.concatenate([l_mix, B_FULL[N:N + len(l_tail)] + l_tail, B_FULL[N + len(l_tail):]], axis=0)
check(f"echo_out: la cola SUMADA al cuerpo de B no hace saltos (salto máx {max_jump(stream):.4f} <= natural {natural:.4f})",
      max_jump(stream) <= natural)
check("echo_out: la cola sin graves (60 Hz)", proj(l_tail, 60, 0, 1) < 0.001)
s_mix, s_tail = tt.render_typed_parts(A, B, late, tt.TYPE_ECHO_OUT, BPM, tail_s=1.0)
check(f"echo_out con tail_s=1: cola de como mucho 1 s ({len(s_tail)}) y acaba en 0",
      len(s_tail) <= SR and float(np.max(np.abs(s_tail[-1]))) < 1e-6 and np.array_equal(s_mix, l_mix))
folded = tt.render_typed(A, B, late, tt.TYPE_ECHO_OUT, BPM)
check("render_typed de echo_out: solo la mezcla, con el eco bajado a cero al final (los últimos 250 ms) y sin clic",
      ok_array(folded, N) and np.array_equal(folded[:N - int(0.25 * SR)], l_mix[:N - int(0.25 * SR)])
      and float(np.max(np.abs(folded[-1] - B[-1]))) < 1e-6 and max_jump(folded) <= natural)

# ------------------------------------------------------------------ filter
fl = tt.render_typed(A, B, plan, tt.TYPE_FILTER, BPM)
check(f"filter: primer fotograma ≈ A ({float(np.max(np.abs(fl[0] - A[0]))):.1e}) y último ≈ B ({float(np.max(np.abs(fl[-1] - B[-1]))):.1e})",
      float(np.max(np.abs(fl[0] - A[0]))) < 2e-3 and float(np.max(np.abs(fl[-1] - B[-1]))) < 2e-3)
a_low = [proj(fl, 60, s, s + 1) for s in (0, 3, 6)]
check(f"filter: el paso alto va quitando los graves de A ({', '.join(f'{v:.3f}' for v in a_low)} a 0, 3 y 6 s)",
      a_low[0] > 0.38 and a_low[0] > a_low[1] > a_low[2])
a_mid = [proj(fl, 1000, s, s + 1) for s in (1, 12, 14)]
check(f"filter: y luego el cuerpo (1 kHz de A: {', '.join(f'{v:.3f}' for v in a_mid)} a 1, 12 y 14 s)",
      a_mid[0] > 0.18 and a_mid[2] < 0.01)
b_mid = [proj(fl, 1300, s, s + 1) for s in (1, 6, 14)]
check(f"filter: B entra apagada (1,3 kHz a {b_mid[0]:.4f} al principio) y el paso bajo se abre ({b_mid[2]:.3f} al final)",
      b_mid[0] < 0.005 and b_mid[1] > b_mid[0] and b_mid[2] > 0.18)
# ventanas de segundos enteros: 55 y 60 Hz caben en ciclos enteros y no se cuelan una en la otra
check(f"filter: nunca dos graves a la vez: B sin graves antes del cambio ({proj(fl, 55, 6, 7):.4f}) y A sin graves después "
      f"({proj(fl, 60, 9, 10):.4f})", proj(fl, 55, 6, 7) < 0.002 and proj(fl, 60, 9, 10) < 0.002)
check(f"filter: los graves de B llegan enteros tras el cambio ({proj(fl, 55, 12, 15):.3f})", proj(fl, 55, 12, 15) > 0.38)
check(f"filter sin clics (salto máx {max_jump(fl):.4f} <= natural {natural:.4f})", max_jump(fl) <= natural)

# ------------------------------------------------------------------ planes de corte
cut_plan = TransitionPlan(a_start_s=0.0, b_start_s=0.0, length_s=0.0, kind=KIND_CUT)
ca, cbb = song_a(1.0), song_b(1.0)
ref_cut = dj_dsp.render_transition(ca, cbb, cut_plan)
check("plan de corte: blend, cut_bar y filter dan el corte limpio de render_transition (len(a) + len(b))",
      all(np.array_equal(tt.render_typed(ca, cbb, cut_plan, k, BPM), ref_cut) for k in (tt.TYPE_BLEND, tt.TYPE_CUT_BAR, tt.TYPE_FILTER)))
c_mix, c_tail = tt.render_typed_parts(ca, cbb, cut_plan, tt.TYPE_ECHO_OUT, BPM)
c_wet = c_mix.astype(np.float64) - ref_cut
first = len(ca) - int(round(beat * SR)) + int(round(0.75 * beat * SR))
check(f"plan de corte con echo_out: la mezcla mide len(a) + len(b) ({len(c_mix)}), es el corte limpio más el eco, y la cola "
      f"({len(c_tail) / SR:.2f} s) sigue tras B", len(c_mix) == len(ca) + len(cbb) and float(np.max(np.abs(c_wet[:first]))) < 1e-7
      and proj(c_wet, 1000, 1.0, 2.0) > 0.03 and len(c_tail) > SR and float(np.max(np.abs(c_tail[-1]))) < 1e-6)
check("plan de corte con echo_out: el eco no lleva graves", proj(np.concatenate([c_wet, c_tail]), 60, 1.0, 3.0) < 0.001)
zero_len = TransitionPlan(0.0, 0.0, 0.0)
check("length_s 0 es un corte aunque el plan diga mezcla", np.array_equal(tt.render_typed(ca, cbb, zero_len, tt.TYPE_FILTER), ref_cut))

# ------------------------------------------------------------------ casos límite
empty = np.zeros((0, 2), np.float32)
check("trozos vacíos: un segundo de silencio en los cuatro tipos (y cola vacía)",
      all(np.array_equal(tt.render_typed(empty, empty, TransitionPlan(0, 0, 1.0), k, BPM), np.zeros((SR, 2), np.float32))
          for k in tt.TYPES) and len(tt.render_typed_parts(empty, empty, TransitionPlan(0, 0, 1.0), tt.TYPE_ECHO_OUT, BPM)[1]) == 0)
short = [tt.render_typed(song_a(2.0), song_b(3.0), TransitionPlan(0, 0, 6.0, bass_swap_s=3.0), k, BPM) for k in tt.TYPES]
check("trozos más cortos que la mezcla: longitud completa, sin NaN y con silencio al final en los cuatro tipos",
      all(ok_array(o, 6 * SR) and float(np.max(np.abs(o[int(3.2 * SR):]))) < 1e-6 for o in short))
mono_a, mono_b = A[:, 0].copy(), B[:, 0].copy()
check("entradas mono (n,): salen estéreo con los dos canales iguales en los cuatro tipos",
      all((lambda o: ok_array(o, N) and np.array_equal(o[:, 0], o[:, 1]))(tt.render_typed(mono_a, mono_b, plan, k, BPM)) for k in tt.TYPES))
tiny = tt.render_typed(song_a(0.03), song_b(0.03), TransitionPlan(0, 0, 0.03), tt.TYPE_FILTER, BPM)
check("una mezcla de 30 ms funciona en los cuatro tipos",
      ok_array(tiny, round(0.03 * SR)) and all(ok_array(tt.render_typed(song_a(0.03), song_b(0.03), TransitionPlan(0, 0, 0.03), k), round(0.03 * SR))
                                               for k in tt.TYPES))
check("echo_out sin bpm: no falla (supone 120)", ok_array(tt.render_typed(A, B, plan, tt.TYPE_ECHO_OUT), N))
try:
    tt.render_typed(A, B, plan, "scratch")
    check("un tipo desconocido da ValueError", False)
except ValueError:
    check("un tipo desconocido da ValueError", True)
a_in, b_in = A.copy(), B.copy()
for k in tt.TYPES:
    tt.render_typed_parts(A, B, late, k, BPM)
check("ningún tipo modifica los arrays de entrada", np.array_equal(A, a_in) and np.array_equal(B, b_in))

# ------------------------------------------------------------------ choose_type
good = BeatGrid(0.5, 128.0, confidence=0.8)


def info(**kw):
    base = {"duration_s": 240.0, "intro_s": 16.0, "outro_s": 30.0, "bpm": 128.0, "beatgrid": good, "tone": "8A", "energy": 0.6}
    base.update(kw)
    return base


long_plan = TransitionPlan(200.0, 0.0, 30.0, bass_swap_s=15.0)
short_plan = TransitionPlan(230.0, 0.0, 6.0)
cases = [
    ("rejillas fiables, mismo tempo y tonos compatibles", info(), info(tone="9A"), long_plan, None, tt.TYPE_BLEND),
    ("sin rejilla en la que entra, mezcla larga", info(), info(beatgrid=None), long_plan, None, tt.TYPE_CUT_BAR),
    ("sin rejilla, mezcla corta", info(beatgrid=None), info(), short_plan, None, tt.TYPE_BLEND),
    ("rejilla con confianza 0,3", info(beatgrid=BeatGrid(0.5, 128.0, confidence=0.3)), info(), long_plan, None, tt.TYPE_CUT_BAR),
    ("rejilla sin confianza (0 por defecto)", info(), info(beatgrid=BeatGrid(0.5, 128.0)), long_plan, None, tt.TYPE_CUT_BAR),
    ("cambio de tempo del 6 %", info(), info(bpm=120.5, beatgrid=BeatGrid(0.5, 120.5, confidence=0.9)), long_plan, None, tt.TYPE_CUT_BAR),
    ("cambio de tempo del 4 %", info(), info(bpm=123.0, beatgrid=BeatGrid(0.5, 123.0, confidence=0.9), tone="8B"), long_plan, None,
     tt.TYPE_BLEND),
    ("tonos que chocan (8A y 2B), tempo igual", info(), info(tone="2B"), long_plan, None, tt.TYPE_FILTER),
    ("final brusco de A", info(outro_ms=1000, outro_s=None), info(), long_plan, None, tt.TYPE_ECHO_OUT),
    ("plan de corte por tempos lejanos", info(), info(bpm=100.0, beatgrid=BeatGrid(0.5, 100.0, confidence=0.9)),
     TransitionPlan(220.0, 0.0, 0.0, kind=KIND_CUT), None, tt.TYPE_ECHO_OUT),
    ("plan de corte sin tempo de A", info(bpm=None, beatgrid=None), info(bpm=100.0), TransitionPlan(220.0, 0.0, 0.0, kind=KIND_CUT),
     None, tt.TYPE_CUT_BAR),
    ("plan de corte, tempos cercanos y final normal", info(), info(), TransitionPlan(220.0, 0.0, 0.0, kind=KIND_CUT), None, tt.TYPE_CUT_BAR),
    ("tono desconocido y mezcla larga", info(tone=None), info(), long_plan, None, tt.TYPE_FILTER),
    ("tono desconocido y mezcla de 12 s", info(tone=None), info(), TransitionPlan(200.0, 0.0, 12.0), None, tt.TYPE_BLEND),
    ("tonos a dos pasos (8A y 10A) y mezcla larga", info(), info(tone="10A"), long_plan, None, tt.TYPE_FILTER),
    ("bpm_a dado a mano que deja el cambio en más del 5 %", info(), info(), long_plan, 140.0, tt.TYPE_CUT_BAR),
    ("fichas que no son dicts", None, "x", long_plan, None, tt.TYPE_CUT_BAR),
    ("análisis en milisegundos (track_analysis)", {"duration_ms": 240000, "outro_ms": 30000, "bpm": 128.0, "beatgrid": good, "tone": "8A"},
     {"duration_ms": 200000, "intro_ms": 16000, "bpm": 128.0, "beatgrid": good, "tone": "8A"}, long_plan, None, tt.TYPE_BLEND),
]
bad = []
for label, ia, ib, pl, bpm_a, want in cases:
    got, why = tt.choose_type(ia, ib, pl, bpm_a)
    print(f"     {label}: {got} ({why})", flush=True)
    if got != want or not isinstance(why, str) or len(why) < 10:
        bad.append(f"{label}: {got} en vez de {want}")
check(f"choose_type: los {len(cases)} casos eligen lo esperado y dan un motivo" + (f" ({'; '.join(bad)})" if bad else ""), not bad)
check("choose_type: con plan None no falla (corte)", tt.choose_type(info(), info(), None)[0] == tt.TYPE_CUT_BAR)

# ------------------------------------------------------------------ velocidad
rng = np.random.default_rng(3)
la = (song_a(32.0) + 0.05 * rng.standard_normal((32 * SR, 2))).astype(np.float32)
lb = (song_b(30.0) + 0.05 * rng.standard_normal((30 * SR, 2))).astype(np.float32)
lp = TransitionPlan(0.0, 0.0, 30.0, bass_swap_s=16.0)
times = {}
for k in tt.TYPES:
    t0 = time.perf_counter()
    o = tt.render_typed_parts(la, lb, lp, k, BPM)[0]
    times[k] = time.perf_counter() - t0
    if not ok_array(o, 30 * SR):
        check(f"{k} de 30 s: salida válida", False)
print("     tiempos con 30 s de estéreo:", "; ".join(f"{k} {v:.2f} s" for k, v in times.items()), flush=True)
check(f"cada tipo prepara 30 s de transición en menos de 3 s (el más lento: {max(times.values()):.2f} s)", max(times.values()) < 3.0)
print("FIN", flush=True)
