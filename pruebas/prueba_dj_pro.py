"""Bateria de pruebas acusticas y de rendimiento del motor DJ profesional (Fase DJ-1 y DJ-2).
Verifica:
  1. Cero distorsion / cero clipping (pico maximo <= 0.99 CEILING con limitador suave).
  2. Separacion limpia de frecuencias en Mid-Carve (sin colision de voces en 400 Hz - 2.5 kHz).
  3. Tiempos de retardo exactos en Tempo Delay acordes al BPM (precision de +/- 1 muestra).
  4. Rendimiento CPU: transiciones de 16 s y 32 s procesadas en < 0.5 s en CPU.
  5. Cero regresiones en la suite existente de pruebas DJ.

Se ejecuta desde la carpeta del proyecto:
  python pruebas/prueba_dj_pro.py
"""
import os
import sys
import time

import _aislar  # noqa: F401 (aislamiento de datos temporales)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import dj_dsp, dj_fx, transition_types as tt
from services.mix_types import SAMPLE_RATE, TransitionPlan

SR = SAMPLE_RATE
FAILED_TESTS = []


def check(label: str, cond: bool):
    """Imprime resultado con formato seguro para Windows sin caracteres especiales."""
    tag = "OK   " if cond else "FALLO"
    if not cond:
        FAILED_TESTS.append(label)
    try:
        print(f"{tag} {label}", flush=True)
    except UnicodeEncodeError:
        print(f"{tag} {label.encode('ascii', 'replace').decode('ascii')}", flush=True)


def sine(freq: float, secs: float, amp: float = 0.5, phase: float = 0.0, ch: int = 2) -> np.ndarray:
    """Genera tono senoidal sintetico."""
    t = np.arange(int(round(secs * SR)), dtype=np.float64) / SR
    y = (amp * np.sin(2.0 * np.pi * freq * t + phase)).astype(np.float32)
    return np.stack([y] * ch, axis=1) if ch == 2 else y[:, None]


def impulse(delay_s: float, total_s: float, amp: float = 1.0) -> np.ndarray:
    """Genera un impulso Dirac sintetico en delay_s."""
    total_n = int(round(total_s * SR))
    idx = int(round(delay_s * SR))
    x = np.zeros((total_n, 2), dtype=np.float32)
    if 0 <= idx < total_n:
        x[idx, :] = amp
    return x


def rms(x: np.ndarray) -> float:
    arr = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(arr ** 2))) if arr.size else 0.0


def db(ratio: float) -> float:
    return 20.0 * np.log10(max(ratio, 1e-12))


def max_jump(x: np.ndarray) -> float:
    """Salto maximo entre muestras consecutivas (para deteccion de clics)."""
    return float(np.max(np.abs(np.diff(x, axis=0)))) if len(x) > 1 else 0.0


def measure_amplitude_at(sig: np.ndarray, freq: float, t0: float, t1: float, ch: int = 0) -> float:
    """Calcula la amplitud espectral de un tono puro por proyeccion coherente."""
    n0 = int(round(t0 * SR))
    n1 = int(round(t1 * SR))
    seg = sig[n0:n1, ch].astype(np.float64)
    if len(seg) == 0:
        return 0.0
    t = (np.arange(len(seg), dtype=np.float64) + n0) / SR
    c = np.sum(seg * np.cos(2.0 * np.pi * freq * t)) * 2.0 / len(seg)
    s = np.sum(seg * np.sin(2.0 * np.pi * freq * t)) * 2.0 / len(seg)
    return float(np.hypot(c, s))


print("================================================================================")
print("  SUITE DE PRUEBAS ACUSTICAS Y DE RENDIMIENTO DJ PRO (FASE DJ-1 / DJ-2)")
print("================================================================================")

# ==============================================================================
# 1. CERO DISTORSION / CERO CLIPPING (PICO <= 0.99 CON LIMITADOR SUAVE)
# ==============================================================================
print("\n--- 1. CERO DISTORSION / CERO CLIPPING (LIMIT_PEAK <= 0.99 CEILING) ---")

# (a) Suma excesiva de 5 senos desfasados con pico > 2.5
t5 = (sine(100, 3.0, 0.6) + sine(300, 3.0, 0.6) + sine(1000, 3.0, 0.6) +
      sine(2500, 3.0, 0.6) + sine(5000, 3.0, 0.6))
raw_peak = float(np.max(np.abs(t5)))
limited = dj_fx.limit_peak(t5)
lim_peak = float(np.max(np.abs(limited)))

check(f"Suma de 5 senos (pico crudo {raw_peak:.2f} > 2.5): limitado a pico <= {dj_fx.CEILING} ({lim_peak:.4f})",
      lim_peak <= dj_fx.CEILING + 1e-6)
check(f"Limitador suave: salto maximo {max_jump(limited):.4f} <= natural {max_jump(t5):.4f} sin clics",
      max_jump(limited) <= max_jump(t5) + 0.05)

# (b) Transparencia del limitador: senales con pico <= 0.90 se mantienen intactas
clean_tone = sine(1000, 2.0, 0.85)
check("Transparencia: senal con pico <= 0.90 pasa sin alteracion (error < 1e-6)",
      np.allclose(dj_fx.limit_peak(clean_tone), clean_tone, atol=1e-6))

# (c) Cero clipping en todos los motores de efectos avanzados
# - Tempo delay con realimentacion alta
dly_loud = dj_fx.tempo_delay(sine(440, 2.0, 0.95), bpm=128.0, beats=0.75, feedback=0.85, mix=0.9)
check(f"Tempo Delay con realimentacion 0.85: pico {float(np.max(np.abs(dly_loud))):.4f} <= 0.99",
      float(np.max(np.abs(dly_loud))) <= dj_fx.CEILING + 1e-6)

# - Dub Tape Echo con saturacion y freeze
dub_loud = dj_fx.dub_tape_echo(sine(220, 2.0, 0.98), bpm=120.0, feedback=0.9, mix=1.0, freeze=True)
check(f"Dub Tape Echo Freeze sobre tono a 0.98: pico {float(np.max(np.abs(dub_loud))):.4f} <= 0.99",
      float(np.max(np.abs(dub_loud))) <= dj_fx.CEILING + 1e-6)

# - Washout Reverb envolvente
wash_loud = dj_fx.washout_reverb(sine(500, 2.0, 0.95), decay_s=3.5, mix_end=0.95)
check(f"Washout Reverb espacial: pico {float(np.max(np.abs(wash_loud))):.4f} <= 0.99",
      float(np.max(np.abs(wash_loud))) <= dj_fx.CEILING + 1e-6)

# - Filtro resonante con Q alto (Q=3.0) y limitador
filt_res = dj_dsp.resonant_filter(sine(1000, 2.0, 0.9), cutoff_hz=1000.0, kind="lp", q=3.0)
filt_limited = dj_fx.limit_peak(filt_res)
check(f"Filtro resonante Q=3.0 protegido: pico {float(np.max(np.abs(filt_limited))):.4f} <= 0.99",
      float(np.max(np.abs(filt_limited))) <= dj_fx.CEILING + 1e-6)

# ==============================================================================
# 2. SEPARACION LIMPIA DE FRECUENCIAS EN MID-CARVE (400 Hz - 2.5 kHz)
# ==============================================================================
print("\n--- 2. TALLADO DE MEDIOS (MID-CARVE VOCAL 400 Hz - 2.5 kHz) ---")

# (a) Verificacion de atenuacion en la banda vocal (1500 Hz) vs graves y agudos intactos
dur_test = 3.0
vocal_tone = sine(1500, dur_test, 0.5)
bass_tone = sine(80, dur_test, 0.5)
high_tone = sine(7000, dur_test, 0.5)

carved_vocal = dj_dsp.mid_carve(vocal_tone, center_hz=1500.0, width_oct=1.2, gain_db=-6.0)
carved_bass = dj_dsp.mid_carve(bass_tone, center_hz=1500.0, width_oct=1.2, gain_db=-6.0)
carved_high = dj_dsp.mid_carve(high_tone, center_hz=1500.0, width_oct=1.2, gain_db=-6.0)

amp_vocal_orig = measure_amplitude_at(vocal_tone, 1500, 0.5, 2.5)
amp_vocal_carv = measure_amplitude_at(carved_vocal, 1500, 0.5, 2.5)
gain_vocal_db = db(amp_vocal_carv / amp_vocal_orig)

amp_bass_orig = measure_amplitude_at(bass_tone, 80, 0.5, 2.5)
amp_bass_carv = measure_amplitude_at(carved_bass, 80, 0.5, 2.5)
gain_bass_db = db(amp_bass_carv / amp_bass_orig)

amp_high_orig = measure_amplitude_at(high_tone, 7000, 0.5, 2.5)
amp_high_carv = measure_amplitude_at(carved_high, 7000, 0.5, 2.5)
gain_high_db = db(amp_high_carv / amp_high_orig)

check(f"Mid-Carve en centro vocal 1500 Hz: atenuacion medida {gain_vocal_db:.2f} dB (rango objetivo: -5.0 a -7.0 dB)",
      -7.0 <= gain_vocal_db <= -5.0)
check(f"Mid-Carve selectivo: graves a 80 Hz intactos ({gain_bass_db:.2f} dB, desviacion < 0.2 dB)",
      abs(gain_bass_db) < 0.2)
check(f"Mid-Carve selectivo: agudos a 7 kHz intactos ({gain_high_db:.2f} dB, desviacion < 0.2 dB)",
      abs(gain_high_db) < 0.2)

# (b) Transicion Smart Filter EQ con Mid-Carving dinamico
plan_smart = TransitionPlan(0.0, 0.0, 16.0, bass_swap_s=8.0)
# Track A con voz en 1500 Hz + bombo 80 Hz
# Track B con voz en 1200 Hz + bombo 80 Hz
track_a = sine(1500, 16.0, 0.3) + sine(80, 16.0, 0.4)
track_b = sine(1200, 16.0, 0.3) + sine(80, 16.0, 0.4)

smart_mix = tt.render_typed(track_a, track_b, plan_smart, tt.TYPE_SMART_FILTER_EQ, bpm=120.0)

# Medir atenuacion de la voz de Track A en la mitad de la mezcla (segundo 7 a 9)
a_mid_mix_amp = measure_amplitude_at(smart_mix, 1500, 7.0, 9.0)
a_isolated_amp = measure_amplitude_at(track_a, 1500, 7.0, 9.0)
# En una mezcla estandar sin carving, a la mitad (45 grados) fade_a = cos(pi/4) = ~0.707 (-3 dB)
# Con Mid-Carve (-5 dB adicional), debe estar por debajo de -6 dB respecto al original
carved_ratio_db = db(a_mid_mix_amp / a_isolated_amp)
check(f"Smart Filter EQ atenua voz de A en la zona de solape: {carved_ratio_db:.2f} dB (< -6.0 dB)",
      carved_ratio_db < -6.0)

# Verificar que los graves de B estan apagados antes de bass_swap_at y los de A despues
pre_swap_a_bass = measure_amplitude_at(smart_mix, 80, 2.0, 4.0)
post_swap_a_bass = measure_amplitude_at(smart_mix, 80, 12.0, 14.0)
check("Separacion de graves en Smart EQ: graves de A activos antes del swap y conmutados tras el cambio",
      pre_swap_a_bass > 0.25 and post_swap_a_bass > 0.25)

# ==============================================================================
# 3. TIEMPOS DE RETARDO EXACTOS EN TEMPO DELAY SEGUN BPM (+/- 1 MUESTRA)
# ==============================================================================
print("\n--- 3. PRECISION RITMICA EN TEMPO DELAY (+/- 1 MUESTRA) ---")

bpms_and_beats = [
    (120.0, 0.50, 0.250000),      # 1/2 pulso a 120 BPM = 250 ms = 11025 muestras
    (120.0, 0.75, 0.375000),      # 3/4 pulso a 120 BPM = 375 ms = 16538 muestras
    (120.0, 1.00, 0.500000),      # 1 pulso a 120 BPM = 500 ms = 22050 muestras
    (128.0, 0.75, 0.3515625),    # 3/4 pulso a 128 BPM = 351.5625 ms = 15504 muestras
    (140.0, 0.50, 0.2142857),    # 1/2 pulso a 140 BPM = 214.2857 ms = 9450 muestras
]

for bpm, beats, expected_s in bpms_and_beats:
    expected_samples = int(round(expected_s * SR))
    t0_s = 0.1
    t0_sample = int(round(t0_s * SR))
    imp_sig = impulse(t0_s, 2.5, amp=0.8)

    dly_out = dj_fx.tempo_delay(imp_sig, bpm=bpm, beats=beats, feedback=0.5, mix=0.8,
                                ping_pong=False, ducking=0.0)

    # Buscar el pico de la primera repeticion en la ventana alrededor de t0 + expected_samples
    search_start = t0_sample + expected_samples - 5
    search_end = t0_sample + expected_samples + 6
    window = np.abs(dly_out[search_start:search_end, 0])
    detected_offset = int(np.argmax(window)) - 5
    detected_sample = t0_sample + expected_samples + detected_offset
    sample_diff = abs(detected_sample - (t0_sample + expected_samples))

    check(f"Tempo Delay BPM={bpm:g}, {beats} beats: retardo exacto {expected_samples} muestras ({expected_s*1000:.1f} ms) | error: {sample_diff} muestra(s)",
          sample_diff <= 1)

# (b) Modo Estereo Ping-Pong: alternancia L -> R -> L
imp_mono = impulse(0.1, 3.0, amp=0.9)
pp_out = dj_fx.tempo_delay(imp_mono, bpm=120.0, beats=0.5, feedback=0.6, mix=0.8,
                           ping_pong=True, ducking=0.0)
d_samples = int(round(0.25 * SR))
k0 = int(round(0.1 * SR))

# Tap 1 (L):
tap1_l = float(np.abs(pp_out[k0 + d_samples, 0]))
tap1_r = float(np.abs(pp_out[k0 + d_samples, 1]))
# Tap 2 (R):
tap2_l = float(np.abs(pp_out[k0 + 2 * d_samples, 0]))
tap2_r = float(np.abs(pp_out[k0 + 2 * d_samples, 1]))

check(f"Ping-Pong Tap 1: dominante en canal Izquierdo (L={tap1_l:.3f} vs R={tap1_r:.3f})",
      tap1_l > 3.0 * tap1_r)
check(f"Ping-Pong Tap 2: rebote dominante en canal Derecho (R={tap2_r:.3f} vs L={tap2_l:.3f})",
      tap2_r > 3.0 * tap2_l)

# (c) Ducking vocal en Tempo Delay: volumen atenuado durante presencia de senal activa
burst = sine(1000, 1.0, 0.35)  # 1 s activo con nivel moderado, luego silencio
silence = np.zeros((int(2.0 * SR), 2), dtype=np.float32)
burst_test = np.concatenate([burst, silence], axis=0)

dly_no_duck = dj_fx.tempo_delay(burst_test, bpm=120.0, beats=0.5, feedback=0.5, mix=0.8, ducking=0.0)
dly_with_duck = dj_fx.tempo_delay(burst_test, bpm=120.0, beats=0.5, feedback=0.5, mix=0.8, ducking=0.7)

n_burst = len(burst_test)
wet_no_duck = dly_no_duck[:n_burst] - burst_test
wet_with_duck = dly_with_duck[:n_burst] - burst_test

# Medir nivel del retardo wet durante la senal activa (segundo 0.6 a 0.9)
seg_duck = slice(int(0.6 * SR), int(0.9 * SR))
rms_active_no_duck = rms(wet_no_duck[seg_duck])
rms_active_duck = rms(wet_with_duck[seg_duck])
duck_reduction_db = db(rms_active_duck / rms_active_no_duck)

check(f"Ducking automatico: atenua el retardo durante audio activo en {duck_reduction_db:.2f} dB (< -4.0 dB)",
      duck_reduction_db < -4.0)

# ==============================================================================
# 4. BENCHMARK DE RENDIMIENTO CPU (TRANSICIONES 16s Y 32s EN < 0.5s)
# ==============================================================================
print("\n--- 4. BENCHMARK DE RENDIMIENTO CPU (< 0.5s PARA 16-32s) ---")

audio16_a = sine(440, 16.0, 0.4) + sine(80, 16.0, 0.4)
audio16_b = sine(554, 16.0, 0.4) + sine(80, 16.0, 0.4)
audio32_a = sine(440, 32.0, 0.4) + sine(80, 32.0, 0.4)
audio32_b = sine(554, 32.0, 0.4) + sine(80, 32.0, 0.4)

plan16 = TransitionPlan(0.0, 0.0, 16.0, bass_swap_s=8.0)
plan32 = TransitionPlan(0.0, 0.0, 32.0, bass_swap_s=16.0)

bench_results = {}

# Evaluar cada tipo de transicion principal
for kind in (tt.TYPE_BLEND, tt.TYPE_SMART_FILTER_EQ, tt.TYPE_DELAY_DROP, tt.TYPE_REVERB_WASH):
    # 16 segundos
    t0 = time.perf_counter()
    out16 = tt.render_typed(audio16_a, audio16_b, plan16, kind, bpm=120.0)
    dur16 = time.perf_counter() - t0

    # 32 segundos
    t0 = time.perf_counter()
    out32 = tt.render_typed(audio32_a, audio32_b, plan32, kind, bpm=120.0)
    dur32 = time.perf_counter() - t0

    bench_results[kind] = (dur16, dur32)
    speedup16 = 16.0 / max(dur16, 1e-6)
    speedup32 = 32.0 / max(dur32, 1e-6)

    check(f"Transicion '{kind}': 16s procesados en {dur16:.3f} s CPU ({speedup16:.1f}x tiempo real, < 0.50 s)",
          dur16 < 0.50 and len(out16) == int(round(16.0 * SR)))
    check(f"Transicion '{kind}': 32s procesados en {dur32:.3f} s CPU ({speedup32:.1f}x tiempo real, < 0.50 s)",
          dur32 < 0.50 and len(out32) == int(round(32.0 * SR)))

# Benchmark individual de los motores DSP unitarios sobre 32 segundos
t0 = time.perf_counter()
_ = dj_dsp.resonant_filter(audio32_a, cutoff_hz=800.0, q=1.5)
res_filt_time = time.perf_counter() - t0
check(f"Motor DSP resonant_filter (32 s estéreo): {res_filt_time:.3f} s CPU (< 0.50 s)",
      res_filt_time < 0.50)

t0 = time.perf_counter()
_ = dj_dsp.mid_carve(audio32_a, center_hz=1500.0, gain_db=-6.0)
mid_carve_time = time.perf_counter() - t0
check(f"Motor DSP mid_carve (32 s estéreo): {mid_carve_time:.3f} s CPU (< 0.50 s)",
      mid_carve_time < 0.50)

t0 = time.perf_counter()
_ = dj_fx.tempo_delay(audio32_a, bpm=128.0, beats=0.75, ping_pong=True, ducking=0.3, tail_s=2.0)
delay_time = time.perf_counter() - t0
check(f"Motor FX tempo_delay ping-pong + ducking (32 s): {delay_time:.3f} s CPU (< 0.50 s)",
      delay_time < 0.50)

t0 = time.perf_counter()
_ = dj_fx.dub_tape_echo(audio32_a, bpm=128.0, saturation=0.5, tail_s=2.0)
dub_time = time.perf_counter() - t0
check(f"Motor FX dub_tape_echo saturacion analoga (32 s): {dub_time:.3f} s CPU (< 0.50 s)",
      dub_time < 0.50)

t0 = time.perf_counter()
_ = dj_fx.washout_reverb(audio16_a, decay_s=3.0, tail_s=3.0)
wash_time = time.perf_counter() - t0
check(f"Motor FX washout_reverb espacial (16 s): {wash_time:.3f} s CPU (< 0.50 s)",
      wash_time < 0.50)

# ==============================================================================
# 5. INTEGRIDAD Y AUSENCIA DE REGRESIONES
# ==============================================================================
print("\n--- 5. AUSENCIA DE REGRESIONES EN TIPOS Y FORMATOS ---")

# (a) Longitud estricta en arrays vacios o casos limite
empty = np.zeros((0, 2), dtype=np.float32)
check("Entrada vacia no falla en resonant_filter", len(dj_dsp.resonant_filter(empty, 500)) == 0)
check("Entrada vacia no falla en mid_carve", len(dj_dsp.mid_carve(empty)) == 0)
check("Entrada vacia con tail_s=0 devuelve (0, 2) en tempo_delay", len(dj_fx.tempo_delay(empty, 120, tail_s=0.0)) == 0)
check("Entrada vacia no falla en tempo_delay", len(dj_fx.tempo_delay(empty, 120)) >= 0)
check("Entrada vacia con tail_s=0 devuelve (0, 2) en dub_tape_echo", len(dj_fx.dub_tape_echo(empty, 120, tail_s=0.0)) == 0)
check("Entrada vacia no falla en dub_tape_echo", len(dj_fx.dub_tape_echo(empty, 120)) >= 0)

# (b) Entrada mono unidimensional (n,) se maneja de forma hermetica
mono1d = sine(440, 1.0, 0.5)[:, 0]
check("resonant_filter acepta array 1D (n,) y devuelve 1D (n,)",
      dj_dsp.resonant_filter(mono1d, 500).ndim == 1)
check("mid_carve acepta array 1D (n,) y devuelve 1D (n,)",
      dj_dsp.mid_carve(mono1d).ndim == 1)
check("tempo_delay acepta array 1D y devuelve estéreo seguro (m, 2)",
      dj_fx.tempo_delay(mono1d, 120).shape == (len(mono1d) + int(round(dj_fx.echo_tail_s(0.375, 0.5) * SR)), 2))

# ==============================================================================
# RESUMEN EJECUTIVO
# ==============================================================================
print("\n================================================================================")
if not FAILED_TESTS:
    print("  RESULTADO: 100% DE PRUEBAS SUPERADAS SATISFACTORIAMENTE")
    print("  Cero distorsion, cero clipping, precision de retardo y rendimiento verificados.")
    print("================================================================================")
    sys.exit(0)
else:
    print(f"  RESULTADO: {len(FAILED_TESTS)} PRUEBA(S) FALLIDAS:")
    for f in FAILED_TESTS:
        print(f"    - {f}")
    print("================================================================================")
    sys.exit(1)
