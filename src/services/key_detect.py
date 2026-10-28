"""Tono (tonalidad) de una canción, en notación Camelot, a partir del audio.

Cómo se calcula (una vez por canción, en segundo plano, ver `track_analysis`):
  1. FFmpeg decodifica el audio a mono y a 11.025 Hz (hasta 8 minutos) y lo entrega por una tubería.
  2. Con numpy se hace la transformada de Fourier por tramos de 1,5 s y se buscan los picos (las notas que suenan), entre
     55 Hz y 2 kHz, con la frecuencia afinada por interpolación.
  3. Se estima la afinación de la canción (muchas no están a 440 Hz) y cada pico se suma a su nota (do, do sostenido...).
  4. Ese perfil de 12 notas se compara con los perfiles de tonalidad de Krumhansl y Kessler (24 tonos: 12 mayores y 12
     menores) y gana el que más se parece (correlación de Pearson).
Si la canción trae el tono en sus etiquetas (`TKEY` de ID3, `initialkey` de FLAC/MP4...: Mixed In Key y las tiendas de
música lo escriben), se usa ese y no se calcula nada.

numpy se carga solo cuando hace falta (no al abrir la aplicación) y es opcional: sin él, la aplicación funciona igual, sin tono.

Limitaciones conocidas: música sin armonía clara (solo ritmo o bajo) da un tono poco fiable (se ve en la confianza), y el
relativo mayor o menor (8A y 8B) es la confusión más habitual; para mezclar da igual, porque mezclan bien entre sí."""
import logging
import subprocess

from services import camelot
from services.ffmpeg_service import FFmpegService

logger = logging.getLogger(__name__)

SAMPLE_RATE = 11025
FFT_SIZE = 16384                       # 1,5 s: resolución de 0,67 Hz, de sobra para distinguir las notas graves
HOP = 8192
CHUNK = 32                             # tramos que se procesan a la vez (limita la memoria)
MIN_HZ, MAX_HZ = 55.0, 2000.0          # de la nota la1 a un poco más de si6
MAX_SECONDS = 480                      # de una mezcla larga solo se mira el principio
MIN_SECONDS = 20                       # con menos música no hay tono fiable
SILENCE_FLOOR = 1e-6                   # por debajo de este nivel (silencio digital) un tramo nunca cuenta
SILENCE_SHARE = 0.1                    # y tampoco los que suenan 20 dB por debajo de lo normal de la canción (su percentil 90)
PEAK_RATIO = 6.0                       # un pico tiene que sobresalir 6 veces del nivel de fondo del tramo
MIN_NOTES = 4                          # con menos notas distintas el tono no es fiable (un bajo solo, un tono puro...)
CONFIDENT = 0.55                       # por debajo, el tono se enseña con una «?» (correlación de Pearson con el perfil)

# Perfiles de tonalidad de Krumhansl y Kessler (1982): cuánto pesa cada nota (empezando por la tónica) en un tono
KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)

_numpy_module = None
_numpy_checked = False


def _numpy():
    """numpy, cargado la primera vez que se pide (tarda un poco y no hace falta si nadie usa el modo DJ), o None."""
    global _numpy_module, _numpy_checked
    if not _numpy_checked:
        _numpy_checked = True
        try:
            import numpy
            _numpy_module = numpy
        except ImportError:                # depende de cómo esté instalado
            _numpy_module = None
    return _numpy_module


def available() -> bool:
    """¿Se puede calcular el tono? (hace falta numpy y FFmpeg)"""
    return _numpy() is not None and bool(FFmpegService.get_ffmpeg_path())


# ------------------------------------------------------------------ tono guardado en las etiquetas
def tag_key(path: str):
    """Código Camelot del tono que traiga el archivo en sus etiquetas, o None."""
    try:
        import mutagen
        audio = mutagen.File(path)
        tags = getattr(audio, "tags", None)
        if not tags:
            return None
        raw = None
        if hasattr(tags, "getall"):                                  # ID3 (mp3, wav, aiff)
            frames = tags.getall("TKEY")
            raw = frames[0].text[0] if frames and frames[0].text else None
        else:                                                         # FLAC y Ogg (initialkey) o MP4 (etiqueta de iTunes)
            for name in ("initialkey", "INITIALKEY", "----:com.apple.iTunes:initialkey", "----:com.apple.iTunes:INITIALKEY"):
                value = tags.get(name)
                if value:
                    raw = value[0]
                    break
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "ignore")
        return camelot.from_text(raw) if raw else None
    except Exception:
        return None


# ------------------------------------------------------------------ cálculo a partir del audio
def decode(path: str, timeout: int = 180):
    """Audio mono de 11.025 Hz (numpy float32, de -1 a 1) o None si FFmpeg no pudo leerlo."""
    np = _numpy()
    ffmpeg = FFmpegService.get_ffmpeg_path()
    if np is None or not ffmpeg:
        return None
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
           "-t", str(MAX_SECONDS), "-f", "f32le", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout).stdout
    except Exception as e:
        logger.warning(f"No se pudo decodificar {path} para sacar el tono: {e}")
        return None
    out = out[:len(out) // 4 * 4]
    return np.frombuffer(out, dtype="<f4") if out else None


def _frame_levels(np, samples):
    """Nivel (RMS) de cada tramo de FFT_SIZE muestras, sin crear matrices grandes (suma acumulada de cuadrados)."""
    squares = np.concatenate(([0.0], np.cumsum(samples.astype(np.float64) ** 2)))
    starts = np.arange(0, len(samples) - FFT_SIZE + 1, HOP)
    return np.sqrt(np.maximum(squares[starts + FFT_SIZE] - squares[starts], 0.0) / FFT_SIZE)


def _peaks(samples):
    """(notas MIDI con decimales, peso relativo) de los picos de todos los tramos de la canción."""
    np = _numpy()
    window = np.hanning(FFT_SIZE).astype(np.float32)
    freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
    lo, hi = int(np.searchsorted(freqs, MIN_HZ)), int(np.searchsorted(freqs, MAX_HZ))
    frames_all = np.lib.stride_tricks.sliding_window_view(samples, FFT_SIZE)[::HOP]
    levels = _frame_levels(np, samples)
    gate = max(SILENCE_FLOOR, SILENCE_SHARE * float(np.percentile(levels, 90)))      # relativo: vale también para masters bajos
    midis, weights = [], []
    for first in range(0, len(frames_all), CHUNK):
        frames = np.asarray(frames_all[first:first + CHUNK])
        frames = frames[levels[first:first + CHUNK] >= gate]
        if not len(frames):
            continue
        mag = np.abs(np.fft.rfft(frames * window, axis=1))[:, lo - 1:hi + 1]
        centre = mag[:, 1:-1]
        is_peak = (centre > mag[:, :-2]) & (centre >= mag[:, 2:]) & (centre > PEAK_RATIO * np.median(mag, axis=1, keepdims=True))
        rows, cols = np.nonzero(is_peak)
        if not rows.size:
            continue
        left, mid, right = mag[rows, cols], mag[rows, cols + 1], mag[rows, cols + 2]
        la, lb, lc = np.log(left + 1e-12), np.log(mid + 1e-12), np.log(right + 1e-12)
        curve = la - 2.0 * lb + lc                                     # interpolación parabólica sobre el logaritmo
        shift = np.clip(np.where(curve < 0, 0.5 * (la - lc) / np.where(curve < 0, curve, -1.0), 0.0), -0.5, 0.5)
        hz = (lo + cols + shift) * SAMPLE_RATE / FFT_SIZE
        midis.append(69.0 + 12.0 * np.log2(hz / 440.0))
        weights.append(mid / mag.max(axis=1)[rows])
    if not midis:
        return None, None
    return np.concatenate(midis), np.concatenate(weights)


def pitch_class_profile(midi, weight):
    """Cuánto suena cada una de las 12 notas (do = 0), con la afinación de la canción corregida. Devuelve (perfil, desvío
    de afinación en semitonos)."""
    np = _numpy()
    angle = 2.0 * np.pi * (midi - np.round(midi))                      # desvío de cada pico respecto a la nota más cercana
    tuning = np.arctan2(np.sum(weight * np.sin(angle)), np.sum(weight * np.cos(angle))) / (2.0 * np.pi)
    notes = np.round(midi - tuning).astype(int) % 12
    return np.bincount(notes, weights=np.sqrt(weight), minlength=12), float(tuning)


def best_key(profile):
    """(nota tónica, ¿menor?, correlación, ventaja sobre el segundo) del tono que mejor encaja con el perfil, o None."""
    np = _numpy()
    if profile is None or not np.isfinite(profile).all() or np.std(profile) <= 0:
        return None
    scores = []
    for minor, base in ((False, KK_MAJOR), (True, KK_MINOR)):
        for tonic in range(12):
            scores.append((float(np.corrcoef(profile, np.roll(np.asarray(base), tonic))[0, 1]), tonic, minor))
    scores.sort(reverse=True)
    return scores[0][1], scores[0][2], scores[0][0], scores[0][0] - scores[1][0]


def detect_from_samples(samples):
    """Tono de un audio ya decodificado: {"tone": «8A», "tone_conf": correlación} (tone «» si no hay armonía clara). Si
    suenan menos de 4 notas distintas (un bajo solo, un tono puro), la confianza se limita para que se vea con «?»."""
    np = _numpy()
    if np is None or samples is None or len(samples) < MIN_SECONDS * SAMPLE_RATE:
        return {"tone": "", "tone_conf": 0.0}
    midi, weight = _peaks(samples)
    if midi is None:
        return {"tone": "", "tone_conf": 0.0}
    profile, _tuning = pitch_class_profile(midi, weight)
    found = best_key(profile)
    if found is None:
        return {"tone": "", "tone_conf": 0.0}
    tonic, minor, correlation, _margin = found
    confidence = max(0.0, correlation)
    if int(np.sum(profile >= 0.1 * profile.max())) < MIN_NOTES:
        confidence = min(confidence, CONFIDENT - 0.1)
    return {"tone": camelot.camelot(tonic, minor), "tone_conf": round(confidence, 3)}


def detect(path: str):
    """Tono de una canción (etiqueta o cálculo): {"tone": «8A» o «», "tone_conf": 0..1}. None si no se pudo intentar
    (sin numpy, sin FFmpeg o archivo ilegible): en ese caso se volverá a intentar más adelante."""
    tagged = tag_key(path)
    if tagged:
        return {"tone": tagged, "tone_conf": 1.0}
    samples = decode(path)
    if samples is None:
        return None
    try:
        return detect_from_samples(samples)
    except Exception as e:
        logger.warning(f"No se pudo calcular el tono de {path}: {e}")
        return None
