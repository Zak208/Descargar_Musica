"""Tempo (pulsaciones por minuto) de cada canción, para igualar el ritmo de las dos canciones durante el fundido.

No se analiza el audio otra vez: se calcula a partir de la envolvente de graves y medios que ya se guarda para el
visualizador (una lectura cada 0,1 s). Se prueban todos los tempos entre 70 y 180 y se queda el que mejor encaja con los
golpes de la música (un «peine» de pulsos); con una canción entera la precisión es de un par de por ciento, suficiente para
acercar el ritmo de una canción al de la otra. Si no está claro (música sin pulso), no se da ningún tempo y no se toca nada."""
import math

from services import envelope

STEP_S = envelope.STEP_MS / 1000.0
BAND_COUNT = envelope.BANDS
MIN_BPM, MAX_BPM = 70.0, 180.0
MAX_MATCH = 0.10               # solo se acerca el ritmo si la diferencia es de menos del 10 %
MIN_MATCH = 0.012              # y no hace falta si ya es prácticamente igual
MIN_CONFIDENCE = 1.25          # lo bien que tiene que destacar el mejor tempo sobre la media

_cache: dict = {}


def onset_signal(data: bytes) -> list:
    """Golpes de la música: subidas de los graves (y algo de los medios) de un instante al siguiente."""
    n = len(data) // BAND_COUNT
    low = [data[i * BAND_COUNT] for i in range(n)]
    mid = [data[i * BAND_COUNT + 1] for i in range(n)]
    out = [0.0] * n
    for i in range(1, n):
        out[i] = max(0.0, low[i] - low[i - 1]) + 0.5 * max(0.0, mid[i] - mid[i - 1])
    if not out:
        return out
    mean = sum(out) / len(out)
    return [max(0.0, v - mean) for v in out]       # solo lo que sobresale del nivel medio


def _interp(signal: list, pos: float) -> float:
    i = int(pos)
    if i < 0 or i + 1 >= len(signal):
        return 0.0
    f = pos - i
    return signal[i] * (1 - f) + signal[i + 1] * f


def estimate_bpm(data: bytes):
    """Tempo estimado (float) o None si la música no tiene un pulso claro."""
    signal = onset_signal(data)
    if len(signal) < 600 or max(signal, default=0) <= 0:          # menos de un minuto: no se fía
        return None
    # se usa la parte central de la canción (introducciones y finales suelen tener otro ritmo)
    n = len(signal)
    lo, hi = int(n * 0.15), int(n * 0.85)
    core = signal[lo:hi]
    scores = []
    bpm = MIN_BPM
    while bpm <= MAX_BPM:
        period = 60.0 / bpm / STEP_S                                # en lecturas
        best = 0.0
        for phase_i in range(8):                                    # dónde cae el primer pulso
            phase = period * phase_i / 8
            total, count, pos = 0.0, 0, phase
            while pos < len(core) - 2:
                total += _interp(core, pos)
                count += 1
                pos += period
            if count:
                best = max(best, total / count)
        scores.append((bpm, best))
        bpm += 0.5
    top_bpm, top = max(scores, key=lambda s: s[1])
    mean = sum(s for _b, s in scores) / len(scores)
    if mean <= 0 or top / mean < MIN_CONFIDENCE:
        return None
    return top_bpm


def remember(path: str, data: bytes):
    """Calcula (si hace falta) y recuerda el tempo de esa canción. Devuelve el tempo o None."""
    if path in _cache:
        return _cache[path]
    value = estimate_bpm(data) if data else None
    _cache[path] = value
    return value


def known(path: str) -> bool:
    return path in _cache


def get(path: str):
    return _cache.get(path)


def match_rate(bpm_out, bpm_in):
    """Velocidad con la que hay que reproducir la canción que entra para que lleve el ritmo de la que sale (1,0 = nada),
    o None si no se puede o no merece la pena. Se tiene en cuenta que un tempo puede estar medido al doble o a la mitad."""
    if not bpm_out or not bpm_in:
        return None
    ratio = bpm_out / bpm_in
    best = min((ratio, ratio * 2.0, ratio / 2.0), key=lambda r: abs(math.log(r)))
    if abs(best - 1.0) > MAX_MATCH or abs(best - 1.0) < MIN_MATCH:
        return None
    return best
