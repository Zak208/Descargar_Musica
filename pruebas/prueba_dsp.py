"""Ecualizador de 3 bandas y cambio de graves (fase 14) con señales sintéticas: reconstrucción perfecta, respuesta de cada banda,
cambio de graves sin solapamiento, ausencia de clics, volumen continuo en medios y agudos, casos límite y velocidad.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_dsp.py"""
import os
import sys
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import dj_dsp
from services.mix_types import KIND_CUT, SAMPLE_RATE, TransitionPlan

SR = SAMPLE_RATE


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def tone(freq, secs, amp=0.3, phase=0.0, ch=2):
    t = np.arange(int(secs * SR)) / SR
    y = (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)
    return np.stack([y] * ch, axis=1)


def rms(x):
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))


def db(ratio):
    return 20.0 * np.log10(max(ratio, 1e-12))


def middle(x, cut=0.3):
    """El trozo central de una señal (sin los bordes, donde el filtro todavía no se ha asentado)."""
    k = int(cut * SR)
    return x[k:len(x) - k]


def music(secs, seed=0):
    """Algo parecido a música: bombo y bajo (60 y 90 Hz), medios (1 kHz y 800 Hz), agudos (6 kHz) y un poco de ruido; los dos
    canales son distintos."""
    r = np.random.default_rng(seed)
    left = tone(60, secs, 0.3)[:, 0] + tone(1000, secs, 0.2)[:, 0] + tone(6000, secs, 0.1)[:, 0]
    right = tone(90, secs, 0.3, 1.0)[:, 0] + tone(800, secs, 0.2, 0.5)[:, 0] + tone(6500, secs, 0.1)[:, 0]
    x = np.stack([left, right], axis=1) + 0.05 * r.standard_normal((len(left), 2)).astype(np.float32)
    return x.astype(np.float32)


# ------------------------------------------------------------------ (a) reconstrucción perfecta
x = music(10)
lo, mi, hi = dj_dsp.split_bands(x)
err = float(np.max(np.abs(lo + mi + hi - x)))
check(f"reconstrucción perfecta en 10 s de estéreo con canales distintos (error máx {err:.2e} < 1e-5)", err < 1e-5)
check("las tres bandas son float32 y de la misma forma que la entrada",
      all(b.dtype == np.float32 and b.shape == x.shape for b in (lo, mi, hi)))
sweep_t = np.arange(int(8 * SR)) / SR
f0, f1, dur = 20.0, 16000.0, 8.0
k = np.log(f1 / f0)
phase = 2 * np.pi * f0 * dur / k * (np.exp(sweep_t / dur * k) - 1)
sweep = np.stack([0.5 * np.sin(phase), 0.5 * np.cos(phase)], axis=1).astype(np.float32)
lo, mi, hi = dj_dsp.split_bands(sweep)
err_sweep = float(np.max(np.abs(lo + mi + hi - sweep)))
check(f"reconstrucción perfecta con un barrido de 20 Hz a 16 kHz (error máx {err_sweep:.2e})", err_sweep < 1e-5)
mono = x[:, 0].copy()
ml, mm, mh = dj_dsp.split_bands(mono)
check("una entrada de una dimensión devuelve bandas de una dimensión que también suman la señal",
      ml.ndim == 1 and float(np.max(np.abs(ml + mm + mh - mono))) < 1e-5)
for n in (1, 2, 7, 1000, 44100 + 13):
    s = (np.random.default_rng(n).standard_normal((n, 2)) * 0.3).astype(np.float32)
    a_, b_, c_ = dj_dsp.split_bands(s)
    if float(np.max(np.abs(a_ + b_ + c_ - s))) >= 1e-5 or a_.shape != s.shape:
        check(f"reconstrucción con {n} fotogramas", False)
        break
else:
    check("reconstrucción perfecta también con trozos de 1, 2, 7, 1000 y 44113 fotogramas", True)
check("un trozo vacío no falla", dj_dsp.split_bands(np.zeros((0, 2), np.float32))[0].shape == (0, 2))
lo2, mi2, hi2 = dj_dsp.split_bands(x, 120.0, 4000.0)
check("con otras frecuencias de cruce (120 Hz y 4 kHz) también reconstruye",
      float(np.max(np.abs(lo2 + mi2 + hi2 - x))) < 1e-5)
try:
    dj_dsp.split_bands(x, 3000.0, 200.0)
    check("cruces al revés dan un error claro", False)
except ValueError:
    check("cruces al revés dan un error claro", True)

# ------------------------------------------------------------------ (b) respuesta de cada banda
resp = {}
for f in (60, 250, 1000, 2500, 6000):
    s = tone(f, 2.0, 0.5)
    bands = dj_dsp.split_bands(s)
    resp[f] = [db(rms(middle(b)) / rms(middle(s))) for b in bands]
show = "; ".join(f"{f} Hz: graves {r[0]:.1f}, medios {r[1]:.1f}, agudos {r[2]:.1f} dB" for f, r in resp.items())
print("     respuesta medida:", show, flush=True)
check(f"la banda grave deja pasar 60 Hz ({resp[60][0]:.2f} dB) y atenúa 6 kHz ({resp[6000][0]:.0f} dB, más de 30)",
      abs(resp[60][0]) < 0.1 and resp[6000][0] < -30)
check(f"la banda aguda deja pasar 6 kHz ({resp[6000][2]:.2f} dB) y atenúa 60 Hz ({resp[60][2]:.0f} dB, más de 30)",
      abs(resp[6000][2]) < 0.1 and resp[60][2] < -30)
check(f"los medios dejan pasar 1 kHz ({resp[1000][1]:.2f} dB) y atenúan 60 Hz ({resp[60][1]:.0f} dB) y 6 kHz ({resp[6000][1]:.0f} dB)",
      abs(resp[1000][1]) < 0.5 and resp[60][1] < -30 and resp[6000][1] < -30)
check(f"en el cruce de 250 Hz graves y medios están a -6 dB ({resp[250][0]:.2f} y {resp[250][1]:.2f})",
      abs(resp[250][0] + 6.02) < 0.15 and abs(resp[250][1] + 6.02) < 0.15)
check(f"en el cruce de 2,5 kHz medios y agudos están a -6 dB ({resp[2500][1]:.2f} y {resp[2500][2]:.2f})",
      abs(resp[2500][1] + 6.02) < 0.15 and abs(resp[2500][2] + 6.02) < 0.15)
for f in (250, 2500):
    s = tone(f, 2.0, 0.5)
    lo, mi, hi = dj_dsp.split_bands(s)
    total = db(rms(middle(lo + mi)) / rms(middle(s))) if f == 250 else db(rms(middle(mi + hi)) / rms(middle(s)))
    check(f"las bandas contiguas suman 0 dB en el cruce de {f} Hz ({total:.3f} dB)", abs(total) < 0.05)
# Barrido: en cada zona del barrido manda la banda que toca
inst = f0 * np.exp(sweep_t / dur * k)
lo, mi, hi = dj_dsp.split_bands(sweep)
win = int(0.1 * SR)


def share(band, lo_hz, hi_hz):
    sel = np.where((inst > lo_hz) & (inst < hi_hz))[0]
    sel = sel[(sel > win) & (sel < len(inst) - win)]
    e = [float(np.sum(b[sel].astype(np.float64) ** 2)) for b in (lo, mi, hi)]
    return e[band] / sum(e)


s_lo, s_mi, s_hi = share(0, 20, 100), share(1, 600, 1500), share(2, 6000, 12000)
check(f"en el barrido, por debajo de 100 Hz casi toda la energía va a graves ({s_lo:.4f}), en 600 a 1500 Hz a medios ({s_mi:.3f}) "
      f"y por encima de 6 kHz a agudos ({s_hi:.4f})", s_lo > 0.99 and s_mi > 0.9 and s_hi > 0.99)

# ------------------------------------------------------------------ band_gains y eq_apply
g = dj_dsp.band_gains(SR * 2, [(0.5, 1.0), (1.0, 0.0), (1.5, 0.5)])
check("band_gains: mantiene el valor antes del primer punto y después del último, y pasa por los puntos",
      g.dtype == np.float32 and len(g) == SR * 2 and abs(g[0] - 1) < 1e-6 and abs(g[SR // 2 - 1] - 1) < 1e-3
      and abs(g[SR] ) < 1e-3 and abs(g[-1] - 0.5) < 1e-6 and abs(g[int(1.5 * SR)] - 0.5) < 1e-3)
check("band_gains: está entre los dos valores (sin pasarse) y no tiene escalones",
      float(np.max(g)) <= 1.0 + 1e-6 and float(np.min(g)) >= -1e-6 and float(np.max(np.abs(np.diff(g)))) < 2.0 / (0.5 * SR) * 1.6)
step = dj_dsp.band_gains(SR, [(0.4, 1.0), (0.44, 0.0)])
check(f"band_gains: un paso de 40 ms baja de 1 a 0 sin clic (salto máx entre muestras {np.max(np.abs(np.diff(step))):.4f})",
      step[int(0.39 * SR)] == 1.0 and step[int(0.45 * SR)] == 0.0 and float(np.max(np.abs(np.diff(step)))) < 1.6 / (0.04 * SR))
inst_step = dj_dsp.band_gains(SR, [(0.5, 1.0), (0.5, 0.0)])
check(f"band_gains: dos puntos en el mismo instante se separan 2 ms (salto máx {np.max(np.abs(np.diff(inst_step))):.3f})",
      float(np.max(np.abs(np.diff(inst_step)))) < 0.05)
check("band_gains: sin puntos vale 1, con uno vale ese valor, desordenados se ordenan y n=0 da un array vacío",
      np.all(dj_dsp.band_gains(100, []) == 1.0) and np.all(dj_dsp.band_gains(100, [(0, 0.3)]) == np.float32(0.3))
      and np.allclose(dj_dsp.band_gains(SR, [(0.6, 0.0), (0.2, 1.0)]), dj_dsp.band_gains(SR, [(0.2, 1.0), (0.6, 0.0)]))
      and len(dj_dsp.band_gains(0, [(0, 1)])) == 0)

x = music(4)
same = dj_dsp.eq_apply(x)
check("eq_apply con todo a 1.0 devuelve la señal igual", float(np.max(np.abs(same - x))) == 0.0)
check("eq_apply con todo a 1.0 e ignorando el redondeo (por las bandas) reconstruye igual",
      float(np.max(np.abs(dj_dsp.eq_apply(x, 1.0, 1.0, 1.000001) - x))) < 1e-4)
nolow = dj_dsp.kill_low(x)
before = dj_dsp.split_bands(x)[0]
after = dj_dsp.split_bands(nolow)[0]
att = db(rms(middle(after)) / rms(middle(before)))
check(f"kill_low quita los graves (la banda grave baja {att:.0f} dB, más de 40)", att < -40)
mid_keep = db(rms(middle(dj_dsp.split_bands(nolow)[1])) / rms(middle(dj_dsp.split_bands(x)[1])))
check(f"kill_low deja los medios como estaban ({mid_keep:.3f} dB)", abs(mid_keep) < 0.05)
boost = dj_dsp.eq_apply(tone(60, 2.0, 0.2), low_gain=2.0)
check("eq_apply con graves a 2.0 sube 6 dB un seno de 60 Hz", abs(db(rms(middle(boost)) / rms(middle(tone(60, 2.0, 0.2)))) - 6.0) < 0.1)
curve = dj_dsp.band_gains(len(x), [(0.0, 1.0), (2.0, 0.0)])
ramped = dj_dsp.eq_apply(x, low_gain=curve)
check("eq_apply admite una curva de ganancia por banda (los graves se apagan poco a poco)",
      rms(dj_dsp.split_bands(ramped[:SR // 2])[0]) > 4 * rms(dj_dsp.split_bands(ramped[-SR // 2:])[0]))
check("eq_apply de una dimensión devuelve una dimensión", dj_dsp.eq_apply(x[:, 0], 0.0).shape == (len(x),))


# ------------------------------------------------------------------ (c) cambio de graves en render_transition
def mix_a(secs):
    return (tone(60, secs, 0.4) + tone(1000, secs, 0.2) + tone(6000, secs, 0.1)).astype(np.float32)


def mix_b(secs):
    return (tone(55, secs, 0.4, 0.7) + tone(1300, secs, 0.2, 0.3) + tone(7000, secs, 0.1, 1.1)).astype(np.float32)


LEN, SWAP = 16.0, 6.0
plan = TransitionPlan(a_start_s=0.0, b_start_s=0.0, length_s=LEN, bass_swap_s=SWAP)
a_seg, b_seg = mix_a(LEN + 4), mix_b(LEN)         # A trae más audio que la mezcla (se usa solo lo que cabe)
out = dj_dsp.render_transition(a_seg, b_seg, plan)
check(f"render_transition devuelve (length_s * 44100, 2) float32: {out.shape} {out.dtype}",
      out.shape == (int(LEN * SR), 2) and out.dtype == np.float32)
check("el primer fotograma es el de A y el último el de B (sin saltos con lo de antes y después)",
      float(np.max(np.abs(out[0] - a_seg[0]))) < 1e-4 and float(np.max(np.abs(out[-1] - b_seg[-1]))) < 1e-4)

low_out = dj_dsp.split_bands(out)[0]


def proj(sig, freq, t0, t1):
    """Amplitud de un seno de frecuencia `freq` dentro de sig[t0:t1] (segundos), por proyección."""
    seg = sig[int(t0 * SR):int(t1 * SR), 0].astype(np.float64)
    t = np.arange(len(seg)) / SR
    c = np.sum(seg * np.cos(2 * np.pi * freq * t)) * 2 / len(seg)
    s = np.sum(seg * np.sin(2 * np.pi * freq * t)) * 2 / len(seg)
    return float(np.hypot(c, s))


# ventanas de un número entero de segundos: 60 Hz y 55 Hz caben en ellas en ciclos enteros y no se cuelan una en la otra
a_before, b_before = proj(out, 60, 1.0, 5.0), proj(out, 55, 1.0, 5.0)
a_after, b_after = proj(out, 60, 7.0, 15.0), proj(out, 55, 7.0, 15.0)
check(f"antes del cambio A tiene todos sus graves ({a_before:.3f} de 0,4) y B no tiene ({b_before:.4f}, {db(b_before / 0.4):.0f} dB)",
      abs(a_before - 0.4 * 0.997) < 0.01 and b_before < 0.002)
check(f"después del cambio B tiene todos sus graves ({b_after:.3f}) y A no tiene ({a_after:.4f}, {db(a_after / 0.4):.0f} dB)",
      b_after > 0.4 * 0.99 and a_after < 0.002)
# Ganancias de graves medidas en la salida real: la mezcla es lineal, así que A sola y B sola dan cada curva
pure_a = np.concatenate([tone(60, LEN, 0.5)], axis=0)
pure_b = tone(60, LEN, 0.5)
only_a = dj_dsp.render_transition(pure_a, np.zeros_like(pure_b), plan)
only_b = dj_dsp.render_transition(np.zeros_like(pure_a), pure_b, plan)
env_sel = np.where(np.abs(pure_a[:, 0]) > 0.45)[0]
gain_a = np.zeros(len(pure_a))
gain_b = np.zeros(len(pure_a))
gain_a[env_sel] = only_a[env_sel, 0] / pure_a[env_sel, 0]
gain_b[env_sel] = only_b[env_sel, 0] / pure_b[env_sel, 0]
ga, gb = gain_a[env_sel], gain_b[env_sel]
both = (ga > 0.02) & (gb > 0.02)
overlap_ms = float((env_sel[both].max() - env_sel[both].min()) / SR * 1000) if both.any() else 0.0
first_b = env_sel[gb > 0.02].min() / SR
last_a = env_sel[ga > 0.02].max() / SR
print(f"     paso de graves medido: B entra en {first_b:.3f} s, A se va en {last_a:.3f} s, solapamiento {overlap_ms:.0f} ms", flush=True)
check(f"cambio de graves: solapamiento medido de {overlap_ms:.0f} ms (máximo 60 ms) y centrado en {SWAP} s",
      overlap_ms <= 60 and abs((first_b + last_a) / 2 - SWAP) < 0.01)
check(f"cambio de graves: la suma de las dos ganancias se queda entre {np.min(ga + gb):.3f} y {np.max(ga + gb):.3f} (la mezcla de graves no se hunde ni sube)",
      float(np.min(ga + gb)) > 0.97 and float(np.max(ga + gb)) < 1.03)
check("cambio de graves: antes del paso A pasa entero y B nada, después al revés",
      float(np.min(ga[env_sel < (SWAP - 0.05) * SR])) > 0.98 and float(np.max(gb[env_sel < (SWAP - 0.05) * SR])) < 0.02
      and float(np.max(ga[env_sel > (SWAP + 0.05) * SR])) < 0.02 and float(np.min(gb[env_sel > (SWAP + 0.05) * SR])) > 0.98)
# La energía de graves de la mezcla (en ventanas de 50 ms) nunca supera la mayor de las dos
W = int(0.05 * SR)
nwin = len(out) // W
e_out = np.array([rms(low_out[i * W:(i + 1) * W]) for i in range(nwin)])
la, lb = dj_dsp.split_bands(a_seg[:len(out)])[0], dj_dsp.split_bands(b_seg)[0]
e_a = np.array([rms(la[i * W:(i + 1) * W]) for i in range(nwin)])
e_b = np.array([rms(lb[i * W:(i + 1) * W]) for i in range(nwin)])
limit = np.maximum(e_a, e_b)
ratio = float(np.max(e_out / limit))
check(f"energía de graves de la mezcla: nunca supera la mayor de las dos (razón máx {ratio:.3f} <= 1,05, también en el paso)", ratio <= 1.05)
swap_w = slice(int((SWAP - 0.1) / 0.05), int((SWAP + 0.1) / 0.05) + 1)
check(f"y en el paso de 40 ms la energía de graves se queda en {float(np.min(e_out[swap_w] / limit[swap_w])):.2f} a "
      f"{float(np.max(e_out[swap_w] / limit[swap_w])):.2f} de la mayor (sin hueco)", float(np.min(e_out[swap_w] / limit[swap_w])) > 0.6)
# El mismo resultado que con las tres bandas y curvas de ganancia explícitas
n = len(out)
fa_ = np.cos((np.arange(n) + 0.5) / n * np.pi / 2)[:, None]
fb_ = np.sin((np.arange(n) + 0.5) / n * np.pi / 2)[:, None]
swap_curve = dj_dsp.band_gains(n, [(SWAP - 0.02, 0.0), (SWAP + 0.02, 1.0)])[:, None].astype(np.float64)
a3, b3 = dj_dsp.split_bands(a_seg[:n]), dj_dsp.split_bands(b_seg)
ref = (a3[0] * (1 - swap_curve) + b3[0] * swap_curve + (a3[1] + a3[2]) * fa_ + (b3[1] + b3[2]) * fb_)
check(f"coincide con el cálculo explícito por tres bandas con band_gains (diferencia máx {float(np.max(np.abs(ref - out))):.1e})",
      float(np.max(np.abs(ref - out))) < 1e-4)

# ------------------------------------------------------------------ (d) ausencia de clics
natural = float(np.max(np.abs(np.diff(a_seg[:n], axis=0)))) + float(np.max(np.abs(np.diff(b_seg, axis=0))))
jump = float(np.max(np.abs(np.diff(out, axis=0))))
check(f"sin clics en la mezcla completa: salto máx entre muestras {jump:.4f} <= suma de los saltos naturales de A y B ({natural:.4f})",
      jump <= natural)
bass_a, bass_b = tone(60, LEN + 2, 0.8), tone(60, LEN, 0.8, 2.0)         # graves a tope y en fases distintas: el peor caso del paso
out_bass = dj_dsp.render_transition(bass_a, bass_b, plan)
nat_bass = max(float(np.max(np.abs(np.diff(bass_a, axis=0)))), float(np.max(np.abs(np.diff(bass_b, axis=0)))))
j_bass = float(np.max(np.abs(np.diff(out_bass, axis=0))))
check(f"sin clics en el cambio de graves, con graves a tope y desfasados: salto {j_bass:.4f} vs natural {nat_bass:.4f} "
      f"(umbral: 2 veces lo natural)", j_bass <= 2.0 * nat_bass)
cut_plan = TransitionPlan(a_start_s=0.0, b_start_s=0.0, length_s=0.0, kind=KIND_CUT)
ca, cb = tone(1000, 1.0, 0.5), tone(1000, 1.0, 0.5, 2.5)
cut = dj_dsp.render_transition(ca, cb, cut_plan)
nat_cut = max(float(np.max(np.abs(np.diff(ca, axis=0)))), float(np.max(np.abs(np.diff(cb, axis=0)))))
check(f"corte limpio: salto máx {np.max(np.abs(np.diff(cut, axis=0))):.4f} <= 1,3 veces el natural ({nat_cut:.4f}), "
      f"mientras que pegado a pelo daría {float(np.max(np.abs(cb[0] - ca[-1]))):.2f}",
      float(np.max(np.abs(np.diff(cut, axis=0)))) <= 1.3 * nat_cut)

# ------------------------------------------------------------------ (e) volumen continuo en medios y agudos
def mid_high(sig):
    lo, mi, hi = dj_dsp.split_bands(sig)
    return mi + hi


p_a = rms(mid_high(a_seg[:n])[int(1 * SR):-int(1 * SR)])
p_b = rms(mid_high(b_seg)[int(1 * SR):-int(1 * SR)])
mh_out = mid_high(out)
W2 = int(0.5 * SR)
total_pow = np.array([rms(mh_out[i * W2:(i + 1) * W2]) ** 2 for i in range(int(LEN / 0.5))])
mid_idx = len(total_pow) // 2
spread = db(np.sqrt(total_pow.max() / total_pow.min()))
center_vs_ends = db(np.sqrt(total_pow[mid_idx] / np.mean([total_pow[1], total_pow[-2]])))
print(f"     potencia de medios y agudos: A {db(p_a):.1f} dB, B {db(p_b):.1f} dB; del centro frente a los extremos {center_vs_ends:+.2f} dB; "
      f"variación total {spread:.2f} dB", flush=True)
check(f"volumen de medios y agudos continuo: el centro de la mezcla frente a los extremos {center_vs_ends:+.2f} dB (dentro de 1,5 dB)",
      abs(center_vs_ends) < 1.5)
check(f"y en toda la mezcla la potencia de medios y agudos varía {spread:.2f} dB (menos de 3 dB, con A y B de nivel parecido)", spread < 3.0)

# ------------------------------------------------------------------ (f) casos límite
short_a, short_b = mix_a(2.0), mix_b(3.0)
res = dj_dsp.render_transition(short_a, short_b, TransitionPlan(0.0, 0.0, 6.0, bass_swap_s=3.0))
tail = res[int(3.2 * SR):]
check(f"trozos más cortos que la mezcla: devuelve length_s completo ({res.shape}) sin fallar, con silencio al final",
      res.shape == (int(6.0 * SR), 2) and float(np.max(np.abs(tail))) < 1e-6 and res.dtype == np.float32 and np.isfinite(res).all())
check(f"y sin clic donde se acaba el trozo corto (salto máx {float(np.max(np.abs(np.diff(res, axis=0)))):.4f})",
      float(np.max(np.abs(np.diff(res, axis=0)))) < 0.8)
res = dj_dsp.render_transition(np.zeros((0, 2), np.float32), np.zeros((0, 2), np.float32), TransitionPlan(0.0, 0.0, 1.0))
check("trozos vacíos: un segundo de silencio", res.shape == (SR, 2) and float(np.max(np.abs(res))) == 0.0)
res = dj_dsp.render_transition(mix_a(1.0), np.zeros((0, 2), np.float32), TransitionPlan(0.0, 0.0, 1.0))
check("B vacía: suena A fundiéndose a silencio, sin fallar", res.shape == (SR, 2) and np.isfinite(res).all() and abs(res[0, 0] - mix_a(1.0)[0, 0]) < 1e-3)
tiny = dj_dsp.render_transition(mix_a(0.03), mix_b(0.03), TransitionPlan(0.0, 0.0, 0.03))
check(f"una mezcla de 30 ms (más corta que el paso de graves) funciona ({tiny.shape})", tiny.shape == (int(0.03 * SR), 2) and np.isfinite(tiny).all())
swap_out = dj_dsp.render_transition(mix_a(4.0), mix_b(4.0), TransitionPlan(0.0, 0.0, 4.0, bass_swap_s=99.0))
check("un cambio de graves fuera de la mezcla se limita al final sin fallar", swap_out.shape == (4 * SR, 2) and np.isfinite(swap_out).all())
default_swap = dj_dsp.render_transition(mix_a(4.0), mix_b(4.0), TransitionPlan(0.0, 0.0, 4.0))
check("sin bass_swap_s el cambio de graves cae a la mitad: a 1 s tiene A y a 3 s tiene B",
      proj(default_swap, 60, 0.5, 1.5) > 0.3 and proj(default_swap, 55, 0.5, 1.5) < 0.01
      and proj(default_swap, 55, 2.5, 3.5) > 0.3 and proj(default_swap, 60, 2.5, 3.5) < 0.01)
cut_kind = dj_dsp.render_transition(ca, cb, TransitionPlan(0.0, 0.0, 5.0, kind=KIND_CUT))
check("kind 'cut' da un corte limpio (A entera y B entera) aunque length_s no sea 0", cut_kind.shape == (len(ca) + len(cb), 2))
check(f"corte: A hasta el final y B desde su inicio, con rampa de 5 ms ({cut.shape}); lo del medio queda intacto",
      cut.shape == (len(ca) + len(cb), 2) and float(np.max(np.abs(cut[SR // 2 - 100:SR // 2] - ca[SR // 2 - 100:SR // 2]))) == 0.0
      and abs(float(cut[len(ca) - 1, 0])) < 1e-6 and abs(float(cut[len(ca), 0])) < 1e-6
      and float(np.max(np.abs(cut[len(ca) + SR // 2:len(ca) + SR // 2 + 100] - cb[SR // 2:SR // 2 + 100]))) == 0.0)
blend_zero = dj_dsp.render_transition(ca, cb, TransitionPlan(0.0, 0.0, 0.0))
check("length_s 0 es un corte aunque el tipo sea mezcla", blend_zero.shape == cut.shape and np.allclose(blend_zero, cut))
ca_in, cb_in = ca.copy(), cb.copy()
dj_dsp.render_transition(ca, cb, cut_plan)
dj_dsp.render_transition(a_seg, b_seg, plan)
check("render_transition no modifica los arrays de entrada", np.array_equal(ca, ca_in) and np.array_equal(cb, cb_in))
# Estéreo con canales distintos: cada canal sigue su camino
la = np.stack([tone(440, 8.0, 0.4)[:, 0], np.zeros(8 * SR, np.float32)], axis=1)
res = dj_dsp.render_transition(la, np.zeros_like(la), TransitionPlan(0.0, 0.0, 8.0, bass_swap_s=4.0))
check(f"estéreo con canales distintos: el canal derecho de A (silencio) sigue en silencio ({float(np.max(np.abs(res[:, 1]))):.1e}) "
      f"y el izquierdo suena", float(np.max(np.abs(res[:, 1]))) < 1e-6 and float(np.max(np.abs(res[:SR, 0]))) > 0.3)
chan_a = np.stack([tone(1000, 8.0, 0.3)[:, 0], tone(2000, 8.0, 0.3)[:, 0]], axis=1)
chan_b = np.stack([tone(1500, 8.0, 0.3)[:, 0], tone(3000, 8.0, 0.3)[:, 0]], axis=1)
res = dj_dsp.render_transition(chan_a, chan_b, TransitionPlan(0.0, 0.0, 8.0))
mid_l, mid_r = proj(res, 1000, 0.0, 1.0), proj(res[:, ::-1], 2000, 0.0, 1.0)
check(f"estéreo con canales distintos en una mezcla: izquierda con 1 kHz de A ({mid_l:.2f}) y derecha con 2 kHz de A ({mid_r:.2f}), sin mezclarse",
      mid_l > 0.25 and mid_r > 0.25 and proj(res, 2000, 0.0, 1.0) < 0.01 and proj(res[:, ::-1], 1000, 0.0, 1.0) < 0.01)
res = dj_dsp.render_transition(mono, mono, TransitionPlan(0.0, 0.0, 2.0))
check("una entrada mono (n,) se duplica en estéreo", res.shape == (2 * SR, 2) and np.array_equal(res[:, 0], res[:, 1]))

# ------------------------------------------------------------------ (g) velocidad
long_a = music(35, 1)
long_b = music(30, 2)
t0 = time.perf_counter()
res = dj_dsp.render_transition(long_a, long_b, TransitionPlan(0.0, 0.0, 30.0, bass_swap_s=15.0))
t_render = time.perf_counter() - t0
check(f"render_transition de 30 s de estéreo tarda {t_render:.2f} s (umbral holgado: 8 s)", t_render < 8.0 and res.shape == (30 * SR, 2))
long60 = music(60, 3)
t0 = time.perf_counter()
bands = dj_dsp.split_bands(long60)
t_split = time.perf_counter() - t0
err60 = float(np.max(np.abs(bands[0] + bands[1] + bands[2] - long60)))
check(f"split_bands de 60 s de estéreo tarda {t_split:.2f} s (umbral holgado: 8 s) y reconstruye con error {err60:.1e}",
      t_split < 8.0 and err60 < 1e-5)
t0 = time.perf_counter()
dj_dsp.eq_apply(long60, 0.0, 1.0, 1.0)
t_eq = time.perf_counter() - t0
check(f"eq_apply de 60 s tarda {t_eq:.2f} s (umbral: 8 s)", t_eq < 8.0)
print("FIN", flush=True)
