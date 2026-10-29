"""Volumen igualado del modo DJ (fase 15): que ninguna canción de la mezcla suene más alta o más baja que las demás.

Va aparte de `pcm_loader` a propósito: aquí se usa `loudness_service` (que trae Qt) y la base de datos, y el cargador de audio
no necesita ni una cosa ni la otra.

Por qué no basta `loudness_service.gain_for`: ese factor es para el reproductor normal, donde el volumen es el control de
`QAudioOutput` (de 0 a 1), así que solo puede bajar; las canciones suaves se quedan como están. En el motor del DJ la mezcla
se hace con matrices de numpy en coma flotante, donde sí se puede subir, y hace falta: si solo se bajaran las fuertes, una
canción suave después de una fuerte seguiría sonando mucho más bajo. Por eso `deck_gain` baja las fuertes y sube un poco las
suaves (hasta +6 dB), pero sin provocar recortes: si se conoce el pico de la canción, la subida se limita para que el pico
no pase de 1,0.

Uso previsto: `g = deck_gain(lufs_for(path), peak_of(samples))` y se multiplica el audio por `g`. Llamar desde un hilo que no
sea el de la interfaz: medir una canción nueva con FFmpeg (ebur128) tarda un segundo aproximadamente."""
import logging
import math
import os

from services import library_db, loudness_service

logger = logging.getLogger(__name__)

TARGET_LUFS = loudness_service.TARGET_LUFS      # -14 LUFS, el mismo nivel de referencia que el reproductor normal
MAX_BOOST_DB = 6.0                              # lo máximo que se sube una canción suave
MAX_CUT_DB = loudness_service.MAX_CUT_DB        # lo máximo que se baja una fuerte (12 dB)
UNMEASURED_LUFS = -70.0                         # ebur128 no mide por debajo de esto (silencio): se trata como «no medido»


def lufs_for(path: str) -> float | None:
    """Volumen de la canción en LUFS, o None si no se pudo medir.

    Si ya está medido (y el archivo no cambió) se usa lo guardado; si no, se mide con FFmpeg y se guarda en el índice para la
    próxima vez, igual que hace `LoudnessWorker`. Si la medición falla se apunta como «no medible» para no reintentarla
    cada vez, y se devuelve None."""
    known = loudness_service.stored(path)
    if known is not None:
        return known if known > UNMEASURED_LUFS else None
    lufs = loudness_service.measure(path)
    try:
        library_db.set_loudness(path, os.path.getmtime(path), lufs if lufs is not None else loudness_service.NOT_MEASURABLE)
    except OSError:
        pass
    return lufs if lufs is not None and lufs > UNMEASURED_LUFS else None


def peak_of(samples) -> float | None:
    """Pico (valor absoluto máximo) de una matriz de audio de numpy, o None si está vacía."""
    try:
        return float(abs(samples).max()) if len(samples) else None
    except (TypeError, ValueError):
        return None


def deck_gain(lufs: float | None, peak: float | None = None, target: float = TARGET_LUFS,
              max_boost_db: float = MAX_BOOST_DB, max_cut_db: float = MAX_CUT_DB) -> float:
    """Factor lineal que lleva la canción al volumen `target` (LUFS): baja las fuertes (hasta `max_cut_db`) y sube las suaves
    (hasta `max_boost_db`).

    `peak` es el pico de la canción en escala lineal (1,0 = fondo de escala). Si se da, la subida se limita para que
    `peak * factor` no pase de 1,0 (nunca se sube lo que ya recortaría); las bajadas no se tocan. Con una canción que ya pasa de
    1,0 (el mp3 puede) no se sube nada: el factor queda en 1,0 como mínimo en ese caso.
    Sin volumen medido (None, NaN o por debajo de -70 LUFS): 1,0, sin ajuste."""
    if lufs is None or not math.isfinite(lufs) or lufs <= UNMEASURED_LUFS:
        return 1.0
    gain_db = max(-max_cut_db, min(max_boost_db, target - lufs))
    gain = 10 ** (gain_db / 20.0)
    if gain > 1.0 and peak is not None and math.isfinite(peak) and peak > 0:
        gain = min(gain, max(1.0, 1.0 / peak))
    return gain
