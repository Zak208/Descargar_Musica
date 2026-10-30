"""Efectos del modo DJ (fase 20, `services/dj_fx.py`) con señales sintéticas: el eco repite a la distancia pedida y con la
realimentación pedida, el filtro con barrido quita lo que debe a medida que se mueve, la reverberación y el riser tienen la
forma esperada, el stutter repite sin clics, la ganancia segura no deja pasar de ±1, longitudes exactas, entradas vacías y
mono, sin NaN, y velocidad (30 s de estéreo en menos de 1 s). No abre ningún flujo de sonido.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_efectos.py"""
import os
import sys
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import dj_fx
from services.mix_types import SAMPLE_RATE

SR = SAMPLE_RATE


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def tone(freq, secs, amp=0.3, phase=0.0):
    t = np.arange(int(round(secs * SR))) / SR
    y = (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)
    return np.stack([y, y], axis=1)


def rms(x):
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0


def db(ratio):
    return 20.0 * np.log10(max(ratio, 1e-12))


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


# ------------------------------------------------------------------ eco
imp = np.zeros((2 * SR, 2), np.float32)
imp[int(0.1 * SR)] = 0.5
D, FB, MIX = 0.25, 0.5, 0.8
e = dj_fx.echo(imp, D, FB, MIX)
check(f"echo sin cola: misma longitud ({e.shape}), float32 estéreo", ok_array(e, len(imp)))
d = int(round(D * SR))
peaks = [int(0.1 * SR) + k * d for k in range(1, 7)]
amps = [float(e[p, 0]) for p in peaks]
want = [0.5 * MIX * FB ** (k - 1) for k in range(1, 7)]
check(f"echo: las repeticiones caen cada {D} s exactos y valen mix*fb^(k-1) ({', '.join(f'{v:.4f}' for v in amps)})",
      all(abs(a - w) < 1e-6 for a, w in zip(amps, want)))
all_peaks = [int(0.1 * SR) + k * d for k in range(0, (len(imp) - int(0.1 * SR) - 1) // d + 1)]
others = np.delete(np.abs(e[:, 0]), all_peaks)
check(f"echo: fuera de las repeticiones no hay nada (máx {float(others.max()):.1e})", float(others.max()) < 1e-7)
check("echo: el impulso original sale tal cual (seca intacta)", abs(float(e[int(0.1 * SR), 0]) - 0.5) < 1e-7)
x = tone(440, 3.0, 0.4, 0.3)
e = dj_fx.echo(x, 0.3, 0.4, 0.5)
check("echo: los primeros delay_s de la salida son exactamente la entrada (sin salto con lo anterior)",
      np.array_equal(e[:int(0.3 * SR)], x[:int(0.3 * SR)]))
e = dj_fx.echo(x, 0.3, 0.4, 0.5, tail_s=1.5)
check(f"echo con tail_s=1,5: n + 1,5 s ({len(e)} = {len(x) + int(1.5 * SR)})", ok_array(e, len(x) + int(1.5 * SR)))
check(f"echo: la cola sigue sonando tras el final de la entrada ({rms(e[len(x):len(x) + SR // 2]):.3f}) y acaba en 0 ({abs(float(e[-1, 0])):.1e})",
      rms(e[len(x):len(x) + SR // 2]) > 0.02 and float(np.max(np.abs(e[-1]))) < 1e-6)
e = dj_fx.echo(x, 0.0, 2.0, 7.0)
check("echo: parámetros fuera de rango (retardo 0, realimentación 2, mix 7) se recortan sin fallar", ok_array(e, len(x)))
loud = tone(200, 4.0, 0.98)
e = dj_fx.echo(loud, 0.1, 0.9, 1.0, tail_s=2.0)
check(f"echo con realimentación 0,9 sobre un seno a 0,98: ganancia segura (pico {float(np.max(np.abs(e))):.4f} <= 0,99)",
      float(np.max(np.abs(e))) <= dj_fx.CEILING + 1e-6 and ok_array(e))
check(f"y sin clics por el limitador (salto máx {max_jump(e):.4f}, natural del seno {max_jump(loud):.4f})", max_jump(e) < 3 * max_jump(loud))
eb = dj_fx.echo_beats(imp, 128.0)
d128 = int(round(0.75 * 60 / 128 * SR))
check(f"echo_beats: a 128 BPM la primera repetición cae a 3/4 de golpe ({d128} muestras) con mix 0,5",
      abs(float(eb[int(0.1 * SR) + d128, 0]) - 0.25) < 1e-6)
tail_auto = dj_fx.echo_tail_s(0.75 * 60 / 128, 0.45)
check(f"echo_beats: cola automática hasta -60 dB ({tail_auto:.2f} s) y la salida la incluye",
      len(eb) == len(imp) + int(round(tail_auto * SR)) and 3.0 < tail_auto < 5.0)
eb2 = dj_fx.echo_beats(imp, 128.0, beats=1.0, tail_s=0.0)
check("echo_beats con beats=1 y sin cola: repetición a un golpe exacto y misma longitud",
      len(eb2) == len(imp) and abs(float(eb2[int(0.1 * SR) + int(round(60 / 128 * SR)), 0]) - 0.25) < 1e-6)
for bad in (0, -5, float("nan")):
    try:
        dj_fx.echo_beats(imp, bad)
        check(f"echo_beats con bpm {bad} da ValueError", False)
    except ValueError:
        pass
check("echo_beats con bpm 0, negativo o NaN da ValueError", True)

# ------------------------------------------------------------------ filtro con barrido
mixsig = (tone(60, 10.0, 0.3) + tone(3000, 10.0, 0.2, 1.0)).astype(np.float32)
hp = dj_fx.filter_sweep(mixsig, "hp", 20.0, 2000.0)
check("filter_sweep: misma longitud, float32 estéreo, sin NaN", ok_array(hp, len(mixsig)))
low_track = [proj(hp, 60, s, s + 1) for s in range(0, 10)]
print("     60 Hz por segundos con el paso alto subiendo de 20 Hz a 2 kHz:", " ".join(f"{db(v / 0.3):.0f}" for v in low_track), "dB", flush=True)
check(f"hp que sube: el grave está casi entero al principio ({db(low_track[0] / 0.3):.2f} dB) y desaparece al final "
      f"({db(low_track[-1] / 0.3):.0f} dB, menos de -60)", db(low_track[0] / 0.3) > -1.0 and db(low_track[-1] / 0.3) < -60)
check("hp que sube: el grave baja segundo a segundo (monótono hasta el ruido de redondeo de float32, -80 dB)",
      all(b <= a * 1.001 or db(b / 0.3) < -80 for a, b in zip(low_track, low_track[1:])))
hi_end = proj(hp, 3000, 9, 10)
check(f"hp que sube: los 3 kHz siguen al final ({db(hi_end / 0.2):.2f} dB)", db(hi_end / 0.2) > -1.0)
lp = dj_fx.filter_sweep(mixsig, "lp", 20000.0, 200.0)
hi_track = [proj(lp, 3000, s, s + 1) for s in range(0, 10)]
check(f"lp que baja de 20 kHz a 200 Hz: los 3 kHz pasan al principio ({db(hi_track[0] / 0.2):.2f} dB) y se van al final "
      f"({db(hi_track[-1] / 0.2):.0f} dB)", db(hi_track[0] / 0.2) > -0.5 and db(hi_track[-1] / 0.2) < -40)
check(f"lp que baja: los 60 Hz se quedan ({db(proj(lp, 60, 9, 10) / 0.3):.2f} dB al final)", db(proj(lp, 60, 9, 10) / 0.3) > -0.5)
lp_open = dj_fx.filter_sweep(mixsig, "lp", 300.0, 20000.0, end_at=0.5)
check(f"lp que se abre con end_at=0,5: en la segunda mitad ya está abierto y quieto (3 kHz a {db(proj(lp_open, 3000, 6, 9) / 0.2):.2f} dB) "
      f"y al principio cerrado ({db(proj(lp_open, 3000, 0, 1) / 0.2):.0f} dB)",
      db(proj(lp_open, 3000, 6, 9) / 0.2) > -0.3 and db(proj(lp_open, 3000, 0, 1) / 0.2) < -30)
# Respuesta con el corte quieto: -3 dB en el corte y 24 dB por octava
resp = {}
for f in (250, 500, 1000, 2000, 4000):
    s = tone(f, 2.0, 0.5)
    resp[f] = db(proj(dj_fx.filter_sweep(s, "hp", 1000.0, 1000.0), f, 0.5, 1.5) / 0.5)
print("     paso alto quieto en 1 kHz:", "; ".join(f"{f} Hz {v:.1f} dB" for f, v in resp.items()), flush=True)
check(f"corte quieto en 1 kHz: -3 dB en el corte ({resp[1000]:.2f}), unos -24 dB una octava por debajo ({resp[500]:.1f}) "
      f"y casi nada dos por encima ({resp[4000]:.2f})",
      abs(resp[1000] + 3.01) < 0.2 and -25.5 < resp[500] < -22.5 and resp[4000] > -0.1)
open_lp = dj_fx.filter_sweep(tone(1000, 2.0, 0.5), "lp", 21000.0, 21000.0)
err = float(np.max(np.abs(open_lp[1000:-1000] - tone(1000, 2.0, 0.5)[1000:-1000])))
check(f"un paso bajo abierto del todo deja el audio igual (error máx {err:.1e}): los bloques se reconstruyen sin costuras", err < 1e-4)
nat = max_jump(mixsig)
check(f"filter_sweep sin clics por los cambios de corte (salto máx hp {max_jump(hp):.4f}, lp {max_jump(lp):.4f}, natural {nat:.4f})",
      max_jump(hp) <= 1.1 * nat and max_jump(lp) <= 1.1 * nat)
res = dj_fx.filter_sweep(tone(1000, 2.0, 0.9), "lp", 1000.0, 1000.0, resonance=1.0)
check(f"resonancia: sube el nivel cerca del corte ({db(proj(res, 1000, 0.5, 1.5) / 0.9):+.1f} dB) sin pasar de 0,99 "
      f"(pico {float(np.max(np.abs(res))):.3f})", float(np.max(np.abs(res))) <= dj_fx.CEILING + 1e-6 and proj(res, 1000, 0.5, 1.5) > 0.9 * 0.707)
for args in (("bp", 100, 200), ("hp", 0, 200), ("lp", 100, 30000)):
    try:
        dj_fx.filter_sweep(mixsig[:1000], *args)
        check(f"filter_sweep{args} da ValueError", False)
    except ValueError:
        pass
check("filter_sweep con tipo desconocido o frecuencias fuera de rango da ValueError", True)

# ------------------------------------------------------------------ reverberación
burst = np.zeros((SR, 2), np.float32)
burst[int(0.1 * SR):int(0.15 * SR)] = tone(1000, 0.05, 0.5)
rv = dj_fx.reverb_tail(burst, decay_s=1.5, mix=0.4)
check(f"reverb_tail: n + decay_s de cola ({len(rv)} = {len(burst) + int(1.5 * SR)}), sin NaN", ok_array(rv, len(burst) + int(1.5 * SR)))
pre_n = int(0.1 * SR) + int(0.02 * SR)
check(f"reverb_tail: antes del sonido y en el pre-retardo la salida es la entrada (diferencia máx "
      f"{float(np.max(np.abs(rv[:pre_n] - burst[:pre_n]))):.1e}, redondeo de la FFT)",
      float(np.max(np.abs(rv[:pre_n] - burst[:pre_n]))) < 1e-7)
early, late = rms(rv[int(0.2 * SR):int(0.4 * SR)]), rms(rv[int(1.9 * SR):int(2.1 * SR)])
check(f"reverb_tail: la cola decae (de {db(early):.0f} dB a {db(late):.0f} dB en 1,7 s, más de 40 dB) y acaba en 0",
      db(early) - db(late) > 40 and float(np.max(np.abs(rv[-1]))) < 1e-6)
rv_mono = dj_fx.reverb_tail(burst[:, 0], decay_s=1.0)
diff_lr = rms(rv_mono[int(0.3 * SR):, 0] - rv_mono[int(0.3 * SR):, 1])
check(f"reverb_tail de una entrada mono: sale estéreo y los dos canales de la cola son distintos (diferencia {diff_lr:.4f})",
      rv_mono.shape[1] == 2 and diff_lr > 1e-3)
check("reverb_tail: con la misma semilla sale igual", np.array_equal(rv, dj_fx.reverb_tail(burst, decay_s=1.5, mix=0.4)))
lowcut = dj_fx.reverb_tail(tone(50, 2.0, 0.5), mix=1.0, tail_s=0.0) - tone(50, 2.0, 0.5)
check(f"reverb_tail: la reverberación casi no lleva graves (50 Hz en el efecto a {db(proj(lowcut, 50, 0.5, 1.9) / 0.5):.0f} dB)",
      db(proj(lowcut, 50, 0.5, 1.9) / 0.5) < -12)
rv_loud = dj_fx.reverb_tail(tone(500, 3.0, 0.95), mix=1.0)
check(f"reverb_tail con mix 1 sobre un seno fuerte: ganancia segura (pico {float(np.max(np.abs(rv_loud))):.3f})",
      float(np.max(np.abs(rv_loud))) <= dj_fx.CEILING + 1e-6)

# ------------------------------------------------------------------ riser
rs = dj_fx.riser(4.0, 300.0, 6000.0, 0.4)
check(f"riser: {rs.shape}, float32 estéreo, pico {float(np.max(np.abs(rs))):.3f} = level", ok_array(rs, 4 * SR) and abs(float(np.max(np.abs(rs))) - 0.4) < 1e-5)
check(f"riser: crece (último cuarto {db(rms(rs[3 * SR:])):.0f} dB frente al primero {db(rms(rs[:SR])):.0f} dB, más de 20 dB)",
      db(rms(rs[3 * SR:])) - db(rms(rs[:SR])) > 20)


def centroid(sig):
    spec = np.abs(np.fft.rfft(sig[:, 0].astype(np.float64)))
    f = np.fft.rfftfreq(len(sig), 1 / SR)
    return float(np.sum(f * spec) / np.sum(spec))


c0, c1 = centroid(rs[int(0.5 * SR):int(1.0 * SR)]), centroid(rs[int(3.4 * SR):int(3.9 * SR)])
check(f"riser: el tono sube (centro del espectro de {c0:.0f} Hz a {c1:.0f} Hz)", c1 > 4 * c0)
check("riser: empieza y acaba en silencio (sin clic al entrar ni al cortarse en el golpe)",
      float(np.max(np.abs(rs[:10]))) < 1e-3 and float(np.max(np.abs(rs[-1]))) < 1e-6)
check(f"riser: los dos canales son distintos (anchura estéreo; correlación {np.corrcoef(rs[:, 0], rs[:, 1])[0, 1]:.2f})",
      abs(np.corrcoef(rs[:, 0], rs[:, 1])[0, 1]) < 0.5)
check("riser de 0 s: vacío", dj_fx.riser(0.0).shape == (0, 2))

# ------------------------------------------------------------------ stutter
BPM = 120.0
sx = (tone(220, 4.0, 0.4) + tone(1700, 4.0, 0.1, 0.4)).astype(np.float32)
st = dj_fx.stutter(sx, BPM, division=16, repeats=4)
piece = int(round(60 / BPM * 4 / 16 * SR))
ramp = int(round(0.002 * SR))
check(f"stutter: misma longitud ({st.shape})", ok_array(st, len(sx)))
same = all(np.allclose(st[k * piece + ramp:(k + 1) * piece - ramp], sx[ramp:piece - ramp]) for k in range(4))
check(f"stutter: las 4 primeras figuras (de {piece} muestras, 1/16) son el mismo trozo inicial", same)
check("stutter: después sigue la canción en su sitio (como si no se hubiera repetido nada)",
      np.array_equal(st[4 * piece + ramp:], sx[4 * piece + ramp:]))
check("stutter: la primera figura empieza sin rampa (continúa lo que sonaba)", np.array_equal(st[:piece - ramp], sx[:piece - ramp]))
check(f"stutter sin clics en las uniones (salto máx {max_jump(st):.4f}, natural {max_jump(sx):.4f})", max_jump(st) <= 1.5 * max_jump(sx))
check("stutter con repeats=1 o un trozo demasiado corto devuelve el audio igual",
      np.array_equal(dj_fx.stutter(sx, BPM, 16, 1), sx) and np.array_equal(dj_fx.stutter(sx, 9000.0, 64, 4), sx))
check("stutter con más repeticiones de las que caben: no falla y conserva la longitud",
      ok_array(dj_fx.stutter(sx[:piece * 2 + 10], BPM, 16, 8), piece * 2 + 10))

# ------------------------------------------------------------------ ganancia
big = tone(100, 2.0, 1.6)
lim = dj_fx.limit_peak(big)
check(f"limit_peak: una señal a 1,6 queda en {float(np.max(np.abs(lim))):.3f} (<= 0,99) sin clics (salto {max_jump(lim):.4f})",
      float(np.max(np.abs(lim))) <= dj_fx.CEILING + 1e-6 and max_jump(lim) <= 1.2 * max_jump(big))
quiet = tone(100, 1.0, 0.5)
check("limit_peak: una señal que no se pasa sale exactamente igual", np.array_equal(dj_fx.limit_peak(quiet), quiet))
gr = dj_fx.gain_ramp(quiet, 1.0, 0.0)
check("gain_ramp: el primer fotograma igual, el último a 0, misma longitud",
      ok_array(gr, len(quiet)) and gr[0, 0] == quiet[0, 0] and gr[-1, 0] == 0.0)
cf = dj_fx.crossfade_equal_power(tone(300, 1.0, 0.5), tone(700, 2.0, 0.5))
check("crossfade_equal_power: longitud de la más larga, empieza en A y acaba en B",
      ok_array(cf, 2 * SR) and abs(float(cf[0, 0]) - 0.0) < 1e-3 and proj(cf, 700, 1.9, 2.0) > 0.45)

# ------------------------------------------------------------------ entradas vacías y mono
empty = np.zeros((0, 2), np.float32)
ok_empty = (dj_fx.echo(empty, 0.2, 0.5, 0.5).shape == (0, 2) and dj_fx.echo(empty, 0.2, 0.5, 0.5, tail_s=1.0).shape == (SR, 2)
            and dj_fx.echo_beats(empty, 128).shape[1] == 2 and dj_fx.filter_sweep(empty, "hp", 20, 200).shape == (0, 2)
            and dj_fx.reverb_tail(empty, tail_s=0.5).shape == (SR // 2, 2) and dj_fx.stutter(empty, 128).shape == (0, 2)
            and dj_fx.limit_peak(empty).shape == (0, 2) and dj_fx.gain_ramp(empty, 1, 0).shape == (0, 2)
            and dj_fx.crossfade_equal_power(empty, empty).shape == (0, 2))
check("entradas vacías: ninguna función falla; sin cola salen vacías y con cola, silencio de la cola", ok_empty)
mono = tone(500, 1.0, 0.3)[:, 0].copy()
outs = [dj_fx.echo(mono, 0.1, 0.3, 0.5), dj_fx.filter_sweep(mono, "lp", 2000, 200), dj_fx.reverb_tail(mono),
        dj_fx.stutter(mono, 128), dj_fx.gain_ramp(mono, 1, 0), dj_fx.limit_peak(mono), dj_fx.echo_beats(mono.reshape(-1, 1), 100)]
check("entradas mono (n,) y (n, 1): todas salen estéreo (m, 2) float32 sin NaN", all(ok_array(o) for o in outs))
inp = sx.copy()
for fn in (lambda: dj_fx.echo(sx, 0.1, 0.5, 0.5, 1.0), lambda: dj_fx.filter_sweep(sx, "hp", 20, 2000),
           lambda: dj_fx.reverb_tail(sx), lambda: dj_fx.stutter(sx, 128), lambda: dj_fx.limit_peak(sx * 3)):
    fn()
check("ninguna función modifica su entrada", np.array_equal(sx, inp))
tiny = np.full((3, 2), 0.2, np.float32)
check("trozos de 1 a 3 fotogramas: sin fallar",
      all(ok_array(o) for o in (dj_fx.echo(tiny, 0.001, 0.5, 0.5, 0.01), dj_fx.filter_sweep(tiny[:1], "hp", 100, 1000),
                                dj_fx.reverb_tail(tiny[:1], 0.2), dj_fx.stutter(tiny, 128), dj_fx.gain_ramp(tiny[:1], 1, 0))))

# ------------------------------------------------------------------ velocidad (30 s de estéreo)
rng = np.random.default_rng(1)
long = (tone(60, 30.0, 0.3) + tone(1000, 30.0, 0.2) + 0.05 * rng.standard_normal((30 * SR, 2))).astype(np.float32)
times = {}
for name, fn in (("echo_beats", lambda: dj_fx.echo_beats(long, 128.0)),
                 ("echo 1 ms", lambda: dj_fx.echo(long, 0.001, 0.5, 0.3)),
                 ("filter_sweep", lambda: dj_fx.filter_sweep(long, "hp", 20.0, 2000.0, resonance=0.5)),
                 ("reverb_tail", lambda: dj_fx.reverb_tail(long, 2.0)),
                 ("riser", lambda: dj_fx.riser(30.0)),
                 ("stutter", lambda: dj_fx.stutter(long, 128.0, 16, 64)),
                 ("limit_peak", lambda: dj_fx.limit_peak(long * 4))):
    t0 = time.perf_counter()
    out = fn()
    times[name] = time.perf_counter() - t0
    if not ok_array(out):
        check(f"{name} de 30 s: salida válida", False)
print("     tiempos con 30 s de estéreo:", "; ".join(f"{k} {v:.3f} s" for k, v in times.items()), flush=True)
check(f"cada efecto procesa 30 s de estéreo en menos de 1 s (el más lento: {max(times.values()):.2f} s)", max(times.values()) < 1.0)
print("FIN", flush=True)
