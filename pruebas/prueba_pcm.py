"""Cargador de audio del motor de mezcla (fase 12) y volumen igualado (fase 15): estirar el tempo sin cambiar el tono
(duración, tono, posición de los golpes, `start_s`), casos que devuelven None, velocidad, una canción real, y `deck_gain` con
audio sintético medido con la misma medición de LUFS que usa la aplicación. Se ejecuta desde la carpeta del proyecto:
python pruebas/prueba_pcm.py"""
import glob
import os
import sys
import tempfile
import time
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import subprocess

import numpy as np

from services import deck_gain as dg
from services import library_db, loudness_service, pcm_loader
from services.ffmpeg_service import FFmpegService

SR = pcm_loader.SAMPLE_RATE
TMP = tempfile.mkdtemp(prefix="prueba_pcm_")
FF = FFmpegService.get_ffmpeg_path()


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def write_wav(path, x, rate=SR):
    x = np.asarray(x)
    if x.ndim == 1:
        x = x[:, None]
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def click_track(seconds=20.0, period=0.5, first=0.3):
    """Golpes secos de ruido de 6 ms cada medio segundo. Devuelve la matriz y los instantes de cada golpe."""
    x = np.zeros((int(seconds * SR), 2), dtype=np.float32)
    rng = np.random.default_rng(1)
    times = np.arange(first, seconds - 0.5, period)
    length = int(0.006 * SR)
    env = np.exp(-np.arange(length) / (0.0015 * SR))
    for t in times:
        i = int(round(t * SR))
        burst = (rng.standard_normal(length) * env * 0.8).astype(np.float32)
        x[i:i + length, 0] += burst
        x[i:i + length, 1] += burst
    return x, times


def centroids(x, expected, half=0.06):
    """Instante (centro de energía) de cada golpe, buscando en ±60 ms alrededor del instante esperado."""
    mono = x.mean(axis=1)
    found = []
    for t in expected:
        a, b = max(0, int((t - half) * SR)), min(len(mono), int((t + half) * SR))
        seg = mono[a:b] ** 2
        found.append(np.nan if seg.sum() < 1e-6 else (a + (np.arange(len(seg)) * seg).sum() / seg.sum()) / SR)
    return np.array(found)


def dominant_hz(x, lo, hi):
    """Frecuencia con más energía entre lo y hi (FFT con ventana, relleno de ceros e interpolación parabólica)."""
    seg = x * np.hanning(len(x))
    n = 8 * len(seg)
    spec = np.abs(np.fft.rfft(seg, n))
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    k = int(np.argmax(np.where((freqs >= lo) & (freqs <= hi), spec, 0)))
    a, b, c = np.log(spec[k - 1] + 1e-12), np.log(spec[k] + 1e-12), np.log(spec[k + 1] + 1e-12)
    return freqs[k] + (0.5 * (a - c) / (a - 2 * b + c)) * (freqs[1] - freqs[0])


def to_mp3(wav, mp3):
    subprocess.run([FF, "-y", "-nostdin", "-v", "error", "-i", wav, "-b:a", "192k", mp3], check=True)


# ------------------------------------------------------------------ archivos de prueba
clk, click_times = click_track()
CLICKS_WAV = os.path.join(TMP, "clicks.wav")
CLICKS_MP3 = os.path.join(TMP, "clicks.mp3")
write_wav(CLICKS_WAV, clk)
to_mp3(CLICKS_WAV, CLICKS_MP3)
tt = np.arange(10 * SR) / SR
tone = (0.4 * np.sin(2 * np.pi * 1000.0 * tt) + 0.3 * np.sin(2 * np.pi * 220.0 * tt)).astype(np.float32)
TONE_WAV = os.path.join(TMP, "tono.wav")
write_wav(TONE_WAV, np.stack([tone, tone], axis=1))

check("rubberband_available() dice que sí en esta compilación de FFmpeg", pcm_loader.rubberband_available() is True)
check("la consulta se guarda en caché (segunda llamada instantánea)", (lambda t0: (pcm_loader.rubberband_available(), time.time() - t0)[1] < 0.01)(time.time()))

# ------------------------------------------------------------------ (a) estirar: duración, tono, golpes, start_s
base = pcm_loader.load(CLICKS_WAV)
check("sin estirar: matriz (n, 2) float32 a 44,1 kHz de 20,000 s", base is not None and base.dtype == np.float32
      and base.ndim == 2 and base.shape[1] == 2 and abs(len(base) / SR - 20.0) < 0.005)
base_c = centroids(base, click_times)
for ratio in (0.92, 1.0, 1.08):
    for fmt, path in (("wav", CLICKS_WAV), ("mp3", CLICKS_MP3)):
        y = pcm_loader.load(path, tempo_ratio=ratio)
        if y is None:
            check(f"{fmt} ratio {ratio}: carga", False)
            continue
        dur_err = abs(len(y) / SR - 20.0 / ratio) / (20.0 / ratio) * 100
        check(f"{fmt} ratio {ratio}: duración {len(y) / SR:.3f} s (esperado {20.0 / ratio:.3f}), error {dur_err:.3f} % < 0,5 %", dur_err < 0.5)
        got = centroids(y, base_c / ratio)
        err_ms = (got - base_c / ratio) * 1000.0
        check(f"{fmt} ratio {ratio}: golpes en original/ratio, error medio {np.nanmean(err_ms):+.2f} ms y máximo "
              f"{np.nanmax(np.abs(err_ms)):.2f} ms (< 15 ms)", not np.isnan(err_ms).any() and np.nanmax(np.abs(err_ms)) < 15.0)
    z = pcm_loader.load(TONE_WAV, tempo_ratio=ratio)
    a, b = int(1.5 * SR), int(min(len(z), 9 * SR / ratio))
    f1, f2 = dominant_hz(z[a:b, 0], 900, 1100), dominant_hz(z[a:b, 0], 180, 260)
    e1, e2 = abs(f1 - 1000.0) / 1000.0 * 100, abs(f2 - 220.0) / 220.0 * 100
    check(f"ratio {ratio}: tono conservado, 1000 Hz sale a {f1:.2f} Hz ({e1:.3f} %) y 220 Hz a {f2:.2f} Hz ({e2:.3f} %), < 0,5 %",
          e1 < 0.5 and e2 < 0.5)
    check(f"ratio {ratio}: duración del tono {len(z) / SR:.3f} s (esperado {10.0 / ratio:.3f})", abs(len(z) / SR - 10.0 / ratio) / (10.0 / ratio) < 0.005)

for ratio in (0.92, 1.0, 1.08):
    start = 3.2
    y = pcm_loader.load(CLICKS_MP3, tempo_ratio=ratio, start_s=start)
    exp_len = (20.0 - start) / ratio
    check(f"start_s=3,2 ratio {ratio}: dura {len(y) / SR:.3f} s (esperado {exp_len:.3f}, error {abs(len(y) / SR - exp_len) / exp_len * 100:.3f} %)",
          abs(len(y) / SR - exp_len) / exp_len < 0.005)
    sel = click_times > start + 0.2
    expected = (base_c[sel] - start) / ratio
    err_ms = (centroids(y, expected) - expected) * 1000.0
    check(f"start_s=3,2 ratio {ratio}: un instante t cae en (t - start_s)/ratio, error máximo {np.nanmax(np.abs(err_ms)):.2f} ms (< 15 ms)",
          not np.isnan(err_ms).any() and np.nanmax(np.abs(err_ms)) < 15.0)
y = pcm_loader.load(CLICKS_WAV, tempo_ratio=1.08, start_s=2.0, duration_s=6.0)
check(f"duration_s se mide en el original: 6 s a ratio 1,08 dan {len(y) / SR:.3f} s (esperado {6 / 1.08:.3f})", abs(len(y) / SR - 6 / 1.08) < 0.03)
y = pcm_loader.load(CLICKS_WAV, start_s=2.0, duration_s=6.0)
check(f"start_s y duration_s sin estirar: {len(y) / SR:.3f} s y el primer golpe tras 2 s cae donde toca",
      abs(len(y) / SR - 6.0) < 0.005 and abs(centroids(y, [base_c[click_times > 2.0][0] - 2.0])[0] - (base_c[click_times > 2.0][0] - 2.0)) < 0.002)

mono = os.path.join(TMP, "mono48k.wav")
write_wav(mono, (0.3 * np.sin(2 * np.pi * 440.0 * np.arange(5 * 48000) / 48000)).astype(np.float32), rate=48000)
y = pcm_loader.load(mono, tempo_ratio=1.05)
check(f"un wav mono de 48 kHz sale estéreo a 44,1 kHz (L = R, {len(y) / SR:.3f} s, esperado {5 / 1.05:.3f})",
      y is not None and y.shape[1] == 2 and np.abs(y[:, 0] - y[:, 1]).max() < 1e-6 and abs(len(y) / SR - 5 / 1.05) < 0.03)

# ------------------------------------------------------------------ (b) casos que devuelven None
check("ratio fuera de 0,5 a 2,0 (0,49, 2,01, 0, -1, NaN, 'x') devuelve None", all(
    pcm_loader.load(CLICKS_WAV, tempo_ratio=r) is None for r in (0.49, 2.01, 0.0, -1.0, float("nan"), "x")))
check("ratios en el borde (0,5 y 2,0) sí se cargan", all(pcm_loader.load(CLICKS_WAV, tempo_ratio=r, duration_s=3) is not None for r in (0.5, 2.0)))
check("archivo inexistente devuelve None (sin excepción)", pcm_loader.load(os.path.join(TMP, "no_existe.mp3")) is None
      and pcm_loader.load(os.path.join(TMP, "no_existe.mp3"), tempo_ratio=1.05) is None)
garbage = os.path.join(TMP, "basura.mp3")
with open(garbage, "wb") as fh:
    fh.write(b"esto no es audio" * 50)
check("un archivo que no es audio devuelve None", pcm_loader.load(garbage) is None)
check("start_s pasado del final devuelve None, y duration_s 0 o negativa también", pcm_loader.load(CLICKS_WAV, start_s=99.0) is None
      and pcm_loader.load(CLICKS_WAV, duration_s=0) is None and pcm_loader.load(CLICKS_WAV, duration_s=-2) is None)
real_cache = pcm_loader._rubberband_cache
pcm_loader._rubberband_cache = False                  # simula una compilación de FFmpeg sin el filtro
check("sin rubberband: ratio != 1 devuelve None", pcm_loader.load(CLICKS_WAV, tempo_ratio=1.05) is None and pcm_loader.rubberband_available() is False)
check("sin rubberband: ratio 1,0 sigue cargando", pcm_loader.load(CLICKS_WAV) is not None)
pcm_loader._rubberband_cache = real_cache
real_path = FFmpegService.get_ffmpeg_path
FFmpegService.get_ffmpeg_path = staticmethod(lambda: None)
check("sin FFmpeg: devuelve None con y sin estirar", pcm_loader.load(CLICKS_WAV) is None and pcm_loader.load(CLICKS_WAV, tempo_ratio=1.05) is None)
pcm_loader._rubberband_cache = None
check("sin FFmpeg: rubberband_available() es False", pcm_loader.rubberband_available() is False)
FFmpegService.get_ffmpeg_path = real_path
pcm_loader._rubberband_cache = None
check("al volver FFmpeg y vaciar la caché, rubberband_available() vuelve a ser True", pcm_loader.rubberband_available() is True)

# ------------------------------------------------------------------ (c) velocidad (4 minutos, umbral holgado por la carga)
rng = np.random.default_rng(7)
n4 = 240 * SR
t4 = np.arange(n4) / SR
music = 0.15 * np.sin(2 * np.pi * 110 * t4) + 0.1 * np.sin(2 * np.pi * 440 * t4) + 0.05 * rng.standard_normal(n4)
beat = np.zeros(n4)
for k in range(int(240 / 0.5)):
    i = int(k * 0.5 * SR)
    beat[i:i + 2000] += 0.6 * np.exp(-np.arange(2000) / 400.0) * np.sin(2 * np.pi * 60 * np.arange(2000) / SR)
long_wav = os.path.join(TMP, "cuatro_minutos.wav")
write_wav(long_wav, np.stack([music + beat, music - beat], axis=1))
t0 = time.time()
y = pcm_loader.load(long_wav, tempo_ratio=1.06)
dt = time.time() - t0
check(f"estirar 4 minutos tarda {dt:.1f} s (límite holgado: 30 s) y dura {len(y) / SR:.1f} s (esperado {240 / 1.06:.1f})",
      y is not None and dt < 30 and abs(len(y) / SR - 240 / 1.06) < 1.0)
t0 = time.time()
y = pcm_loader.load(long_wav)
check(f"cargar 4 minutos sin estirar tarda {time.time() - t0:.2f} s (límite 10 s)", y is not None and time.time() - t0 < 10)
del y, music, beat, t4

# ------------------------------------------------------------------ (d) canciones reales de solo lectura
songs = sorted(glob.glob(os.path.join(os.path.expanduser("~"), "Music", "Canciones_YouTube", "*.mp3")))[:2]
if not songs:
    print("OMITIDO canciones reales: no hay carpeta ~/Music/Canciones_YouTube", flush=True)
for song in songs:
    name = os.path.basename(song)[:30]
    ref = pcm_loader.load(song)
    if ref is None:
        check(f"{name}: carga sin estirar", False)
        continue
    ref_peak = float(np.abs(ref).max())
    for ratio in (0.94, 1.06):
        t0 = time.time()
        y = pcm_loader.load(song, tempo_ratio=ratio)
        dt = time.time() - t0
        ok = y is not None and np.isfinite(y).all()
        peak = float(np.abs(y).max()) if y is not None else -1.0
        exp = len(ref) / ratio
        check(f"{name}: ratio {ratio}: {len(y) / SR:.1f} s en {dt:.1f} s, sin NaN, pico {peak:.2f} (original {ref_peak:.2f}), "
              f"duración {abs(len(y) - exp) / exp * 100:.3f} % de error",
              ok and 0.05 < peak < 2.0 and abs(len(y) - exp) / exp < 0.005 and dt < 40)
    del ref, y

# ------------------------------------------------------------------ (e) volumen igualado
def synth(peak_db, seconds=20.0, seed=3):
    """Música falsa (tonos y un poco de ruido) escalada para que su pico sea peak_db dBFS."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    x = (np.sin(2 * np.pi * 110 * t) + 0.6 * np.sin(2 * np.pi * 440 * t) + 0.3 * np.sin(2 * np.pi * 2500 * t)
         + 0.1 * rng.standard_normal(len(t)))
    x = x / np.abs(x).max() * 10 ** (peak_db / 20.0)
    return np.stack([x, x * 0.9], axis=1).astype(np.float32)


loud_wav, soft_wav, quiet_wav = (os.path.join(TMP, n) for n in ("fuerte.wav", "suave.wav", "muy_suave.wav"))
write_wav(loud_wav, synth(-4.0))
write_wav(soft_wav, synth(-12.0))
write_wav(quiet_wav, synth(-30.0))
lu_loud, lu_soft = dg.lufs_for(loud_wav), dg.lufs_for(soft_wav)
check(f"lufs_for mide la fuerte ({lu_loud}) y la suave ({lu_soft}) con la misma medición de la aplicación",
      lu_loud is not None and lu_soft is not None and lu_loud == loudness_service.measure(loud_wav) and lu_loud - lu_soft > 6)
check("lufs_for la guarda en la base de datos", loudness_service.stored(loud_wav) == lu_loud and library_db.get_loudness(
    soft_wav, os.path.getmtime(soft_wav)) == lu_soft)
real_measure = loudness_service.measure
loudness_service.measure = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debería medir de nuevo"))
try:
    again = dg.lufs_for(loud_wav)
except AssertionError:
    again = "midió otra vez"
loudness_service.measure = real_measure
check("la segunda vez lufs_for usa lo guardado (sin llamar a FFmpeg)", again == lu_loud)
check("lufs_for de un archivo que no existe o no es audio: None, y no se reintenta la medición del segundo",
      dg.lufs_for(os.path.join(TMP, "no_hay.wav")) is None and dg.lufs_for(garbage) is None and loudness_service.stored(garbage) == loudness_service.NOT_MEASURABLE
      and dg.lufs_for(garbage) is None)

g_loud, g_soft = dg.deck_gain(lu_loud), dg.deck_gain(lu_soft)
check(f"deck_gain: la fuerte baja ({g_loud:.3f}, {20 * np.log10(g_loud):+.1f} dB) y la suave sube ({g_soft:.3f}, {20 * np.log10(g_soft):+.1f} dB)",
      g_loud < 1.0 < g_soft)
write_wav(os.path.join(TMP, "fuerte_ig.wav"), pcm_loader.load(loud_wav) * g_loud)
write_wav(os.path.join(TMP, "suave_ig.wav"), pcm_loader.load(soft_wav) * g_soft)
after_loud, after_soft = real_measure(os.path.join(TMP, "fuerte_ig.wav")), real_measure(os.path.join(TMP, "suave_ig.wav"))
check(f"tras igualar: {after_loud} y {after_soft} LUFS (antes {lu_loud} y {lu_soft}), diferencia {abs(after_loud - after_soft):.2f} LU (< 1) y "
      f"cerca de -14", abs(after_loud - after_soft) < 1.0 and abs(after_loud + 14) < 1.0 and abs(after_soft + 14) < 1.0)
peak_soft_after = float(np.abs(pcm_loader.load(os.path.join(TMP, "suave_ig.wav"))).max())
check(f"con el pico de la canción, la suave subida no recorta (pico {peak_soft_after:.3f})",
      dg.deck_gain(lu_soft, dg.peak_of(pcm_loader.load(soft_wav))) * dg.peak_of(pcm_loader.load(soft_wav)) <= 1.0 + 1e-9 and peak_soft_after <= 1.0)

lu_quiet = dg.lufs_for(quiet_wav)
g_quiet = dg.deck_gain(lu_quiet)
check(f"tope de subida: muy suave ({lu_quiet} LUFS, haría falta {-14 - lu_quiet:+.1f} dB) solo sube {20 * np.log10(g_quiet):+.2f} dB (máx +6)",
      abs(20 * np.log10(g_quiet) - 6.0) < 1e-6)
write_wav(os.path.join(TMP, "muy_suave_ig.wav"), pcm_loader.load(quiet_wav) * g_quiet)
after_quiet = real_measure(os.path.join(TMP, "muy_suave_ig.wav"))
check(f"tope de subida medido: {lu_quiet} -> {after_quiet} LUFS (+{after_quiet - lu_quiet:.2f} dB reales)", abs(after_quiet - lu_quiet - 6.0) < 0.3)
check("tope de bajada: una canción a -2 LUFS solo baja 12 dB, no 12 y pico", abs(20 * np.log10(dg.deck_gain(-2.0)) + 12.0) < 1e-6
      and abs(20 * np.log10(dg.deck_gain(0.0)) + 12.0) < 1e-6)
check("topes configurables (max_boost_db 3, max_cut_db 6, target -16)", abs(20 * np.log10(dg.deck_gain(-30.0, max_boost_db=3.0)) - 3.0) < 1e-6
      and abs(20 * np.log10(dg.deck_gain(-5.0, max_cut_db=6.0)) + 6.0) < 1e-6 and abs(20 * np.log10(dg.deck_gain(-20.0, target=-16.0)) - 4.0) < 1e-6)
check("tope de pico: lufs -30 con pico 0,9 sube como mucho 1/0,9 (nunca pasa de 1,0)",
      abs(dg.deck_gain(-30.0, peak=0.9) - 1 / 0.9) < 1e-9 and dg.deck_gain(-30.0, peak=0.9) * 0.9 <= 1.0 + 1e-12)
check("tope de pico: con pico 1,0 no se sube nada, y con pico > 1 (mp3) tampoco (factor 1,0)",
      dg.deck_gain(-30.0, peak=1.0) == 1.0 and dg.deck_gain(-30.0, peak=1.4) == 1.0)
check("el pico no limita las bajadas (lufs -8 con pico 1,0 baja igual)", abs(20 * np.log10(dg.deck_gain(-8.0, peak=1.0)) + 6.0) < 1e-6)
check("pico absurdo (0, negativo, NaN, None) se ignora", all(dg.deck_gain(-20.0, peak=p) == dg.deck_gain(-20.0) for p in (0.0, -1.0, float("nan"), None)))
check("sin medir (None, NaN, inf, -99, -70) el factor es 1,0", all(dg.deck_gain(v) == 1.0 for v in (None, float("nan"), float("inf"), -float("inf"), -99.0, -70.0)))
check("ya en el objetivo (-14 LUFS) el factor es 1,0", dg.deck_gain(-14.0) == 1.0)
check("peak_of: pico de una matriz y None si está vacía", dg.peak_of(np.array([[0.1, -0.7], [0.3, 0.2]], dtype=np.float32)) == np.float32(0.7)
      and dg.peak_of(np.zeros((0, 2), dtype=np.float32)) is None)

print("FIN", flush=True)
