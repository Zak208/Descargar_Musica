"""Medidas absolutas del audio de una canción para el modo DJ: cuánto suena de fuerte, cuánto brilla y cuánta actividad tiene.

Se calculan con el mismo audio que ya se decodifica para sacar el tono (mono, 11.025 Hz; ver `key_detect`), sin otra pasada
de FFmpeg. A diferencia de la envolvente del visualizador (que se normaliza canción a canción para que todas se muevan), estas
medidas se pueden comparar entre canciones: sirven para saber cuál tiene más energía que otra.

  * volumen (`loudness_db`): nivel medio, en dB respecto al máximo, de los tramos que suenan (sin silencios). Es una
    aproximación del volumen percibido; no pasa por el filtro de LUFS.
  * brillo (`brightness_hz`): dónde está el «centro de gravedad» del espectro (mediana de los tramos). Más agudos (platillos,
    sintetizadores) = más brillo.
  * actividad (`flux`): cuánto cambia el espectro de un tramo al siguiente (flujo espectral medio: cuánto sube, de media, cada
    nota de un tramo al otro). Se mide con el audio ya igualado de volumen y solo en los tramos que suenan, para que no dependa
    del volumen de la grabación (el volumen ya cuenta aparte) ni de una intro muy suave. Una base rítmica densa, con muchos golpes y cambios, da más que un colchón de sonido continuo.
    Se mide así, y no contando golpes, porque contar golpes se descuadra (cuenta dos veces los espaciados y se queda corto con
    los muy seguidos) y esto es continuo.
La energía (0 a 1) es una mezcla fija de las tres. Los pesos y los rangos son una elección razonable, no un dato medido:
para ordenar canciones se usa su posición entre las de la sesión (ver `dj_planner`), así que lo que importa es el orden."""
import logging

from services import key_detect

logger = logging.getLogger(__name__)

FRAME = 2048                    # 186 ms
HOP = 1024
CHUNK = 256                     # tramos que se procesan a la vez (limita la memoria)
MIN_SECONDS = 20                # con menos música no se mide
MIN_ACTIVE = 10                 # tramos que suenan como mínimo
LEVEL_TARGET = 0.1              # nivel (RMS) al que se iguala el audio antes de medir el brillo y la actividad
BAND_HZ = (50.0, 5000.0)        # de aquí sale el brillo y el flujo espectral
SILENCE_FLOOR = 1e-6
SILENCE_SHARE = 0.1             # un tramo cuenta si suena al menos a la décima parte (-20 dB) de lo normal en la canción

NOT_MEASURED = -99.0            # volumen que se guarda cuando se intentó y no hay música que medir (para no reintentarlo siempre)

LOUD_RANGE = (-14.0, -3.0)      # dB: de una grabación suave a un master muy comprimido (el pop y lo urbano actual: -10 a -3)
BRIGHT_RANGE = (700.0, 2000.0)  # Hz
FLUX_RANGE = (0.10, 0.20)       # actividad media por nota y tramo, con el volumen igualado (en música actual sale entre 0,12 y 0,18)
WEIGHTS = (0.45, 0.25, 0.30)    # volumen, brillo, actividad


def _scale(value, bounds) -> float:
    low, high = bounds
    return min(1.0, max(0.0, (value - low) / (high - low)))


def energy_score(features) -> float:
    """Energía de 0 a 1 a partir de las tres medidas, o None si faltan."""
    if not features or any(features.get(k) is None for k in ("loudness_db", "brightness_hz", "flux")):
        return None
    if features["loudness_db"] <= NOT_MEASURED + 1:
        return None
    loud, bright, activity = (_scale(features["loudness_db"], LOUD_RANGE), _scale(features["brightness_hz"], BRIGHT_RANGE),
                              _scale(features["flux"], FLUX_RANGE))
    return round(WEIGHTS[0] * loud + WEIGHTS[1] * bright + WEIGHTS[2] * activity, 3)


def compute(samples):
    """{loudness_db, brightness_hz, flux} de un audio ya decodificado (mono, 11.025 Hz), o None si no hay música
    suficiente (silencio, menos de 20 s) o no hay numpy."""
    np = key_detect._numpy()
    if np is None or samples is None or len(samples) < max(MIN_SECONDS * key_detect.SAMPLE_RATE, FRAME):
        return None
    rate = key_detect.SAMPLE_RATE
    starts = np.arange(0, len(samples) - FRAME + 1, HOP)
    squares = np.concatenate(([0.0], np.cumsum(samples.astype(np.float64) ** 2)))
    levels = np.sqrt(np.maximum(squares[starts + FRAME] - squares[starts], 0.0) / FRAME)       # nivel (RMS) de cada tramo
    gate = max(SILENCE_FLOOR, SILENCE_SHARE * float(np.percentile(levels, 90)))
    active = levels >= gate
    if int(active.sum()) < MIN_ACTIVE:
        return None
    loudness_db = 10.0 * float(np.log10(np.mean(levels[active] ** 2) + 1e-12))

    window = (np.hanning(FRAME) * (LEVEL_TARGET / np.sqrt(np.mean(levels[active] ** 2)))).astype(np.float32)   # y de paso, igualado de volumen
    freqs = np.fft.rfftfreq(FRAME, 1.0 / rate)
    band = (freqs >= BAND_HZ[0]) & (freqs <= BAND_HZ[1])
    band_freqs = freqs[band]
    frames_all = np.lib.stride_tricks.sliding_window_view(samples, FRAME)[::HOP]
    centroids = np.zeros(len(starts))
    flux = np.zeros(len(starts))
    previous = None
    for first in range(0, len(frames_all), CHUNK):
        frames = np.asarray(frames_all[first:first + CHUNK])
        mag = np.abs(np.fft.rfft(frames * window, axis=1))[:, band]
        total = mag.sum(axis=1)
        centroids[first:first + len(frames)] = (mag @ band_freqs) / np.maximum(total, 1e-12)
        logmag = np.log1p(mag)
        diff = np.diff(logmag, axis=0, prepend=logmag[:1] if previous is None else previous[None, :])
        flux[first:first + len(frames)] = np.maximum(diff, 0.0).mean(axis=1)       # media por nota: no depende del ancho de banda
        previous = logmag[-1]
    brightness_hz = float(np.median(centroids[active]))

    activity = float(np.mean(flux[active]))
    return {"loudness_db": round(loudness_db, 2), "brightness_hz": round(brightness_hz, 1), "flux": round(activity, 4)}
