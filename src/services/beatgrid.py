"""Rejilla de golpes (beatgrid) de una canción: instante del primer golpe, tempo exacto y qué golpe abre cada compás.

Cómo se calcula (una vez por canción, a partir del audio mono de 11.025 Hz que ya decodifica `key_detect.decode`):
  1. Curva de novedad (onsets): transformada de Fourier por tramos de 46 ms cada 11,6 ms. Se suman las subidas del
     espectro (con el volumen comprimido en logaritmo, así que cuenta igual un golpe flojo que uno fuerte) en tres bandas
     (graves, medios y agudos), cada una a su escala, y se les quita lo que ya sonaba un momento antes.
  2. Tempo grueso: transformada de Fourier de esa curva (un «peine» de pulsos con armónicos). Con el tempo que ya dio el
     análisis (`bpm_hint`) se afina alrededor de él; su doble, su mitad y el que saldría sin pista solo se prueban si en el
     de la pista no hay pulso (las octavas y los 3:2 no se pueden decidir por la señal: un hi-hat a contratiempo es un pulso
     tan bueno como el bombo). Sin pista se toma el único tempo de la ventana de 78 a 156 (cada tempo tiene un solo sitio).
  3. Camino de golpes: programación dinámica sobre la curva de novedad (cada golpe elige el anterior a un periodo, con una
     multa por apartarse). Aguanta un tempo que deriva un poco, una parada y una introducción sin golpes: el primer golpe es
     el primero con una tanda de golpes seguidos detrás (un efecto suelto no vale).
  4. Tempo exacto: recta (mínimos cuadrados con pesos y descartando atípicos) sobre los golpes encontrados. El primer golpe
     sale de esa recta, o del ajuste de los primeros golpes si el tempo no es constante.
  5. Golpe fuerte del compás: de cada 4 golpes, el que más acentúa los graves (por tramos de 8 compases, para que una parte
     muy fuerte no decida sola), más un voto por cada cambio claro del bajo (principio de parte o de frase, que cae en un
     compás) en el golpe en que ocurre.
  6. Confianza: lo que destacan los golpes sobre el resto de fases del periodo (si no hay pulso, se parecen) y la fracción de
     golpes encontrados, algo rebajada si el golpe fuerte del compás no está claro. Por debajo de 0,15 no hay rejilla.

numpy se carga solo cuando hace falta (comparte la carga de `key_detect`) y es opcional: sin él, o sin pulso claro,
devuelve None (la aplicación funciona igual, sin rejilla).

Limitaciones conocidas: la rejilla es de tempo fijo (con un tempo que deriva, la rejilla acierta cerca del principio y se
va separando); siempre compases de 4 golpes; el golpe fuerte del compás es una estimación (el patrón de acentos de algunos
géneros, como el dembow, no marca el 1 con claridad) y la octava del tempo (95 u 190) la decide la pista del análisis."""
import logging

from services import key_detect
from services.mix_types import BeatGrid

logger = logging.getLogger(__name__)

SAMPLE_RATE = key_detect.SAMPLE_RATE
WINDOW_S = 0.046                       # tramo de la transformada: 512 muestras a 11.025 Hz
HOP_S = 0.0116                         # 128 muestras: una lectura de novedad cada 11,6 ms (86 por segundo)
LATENCY_S = -0.0073                     # retraso medio entre el golpe real y el pico de novedad (se mide con audio sintético)
BAND_HZ = ((30.0, 150.0), (150.0, 1500.0), (1500.0, 5000.0))     # graves, medios, agudos
BAND_WEIGHT = (1.0, 0.8, 0.5)
SECTION_HZ = (30.0, 300.0)             # banda de graves en la que se mira cuándo cambia el bajo (principios de frase y de parte)
SECTION_BEATS = 4                      # y cuántos golpes antes y después se comparan
LOCAL_MEAN_S = 0.5                     # lo que ya sonaba: media móvil de este ancho
MIN_SECONDS = 20                       # con menos música no hay rejilla fiable
MIN_BPM, MAX_BPM = 60.0, 210.0
WINDOW_BPM = (78.0, 156.0)             # sin pista, el tempo se lleva a esta ventana (el doble de ancha: un solo sitio posible)
HARMONICS = (1.0, 0.7, 0.5)            # peso de cada armónico del pulso en el tempo grueso
HINT_RANGE = 0.05                      # el tempo se busca a menos de este margen de la pista (y de su mitad y su doble)
DRIFT_RANGE = 0.05                     # cada intervalo entre golpes puede apartarse así del periodo
TIGHTNESS = 3000.0                     # multa por apartarse del periodo (cuanto más, más rígida la cadena)
HIT_SHARE = 0.35                       # un golpe cuenta si su novedad llega a esta parte de la mediana de los golpes
RUN_BEATS, RUN_HITS = 8, 6             # el primer golpe es el que tiene detrás RUN_HITS de RUN_BEATS encontrados
MIN_BEATS = 16                         # con menos golpes seguidos no se da rejilla
SECTION_WEIGHT = 0.15                  # lo que pesan los cambios de bajo frente al acento de los graves (por tramo de BAR_SEGMENT)
BAR_SEGMENT = 32                       # golpes por tramo para decidir el golpe fuerte del compás (8 compases)
MIN_CONFIDENCE = 0.15                  # por debajo, no hay rejilla (None)

_numpy = key_detect._numpy


def available() -> bool:
    """¿Se puede calcular la rejilla? (hace falta numpy)"""
    return _numpy() is not None


# ------------------------------------------------------------------ curva de novedad
def _novelty(np, samples, sample_rate):
    """(novedad total, acento de graves, lecturas por segundo, instante de la primera lectura, espectro de los graves), o None si
    es silencio. La novedad ya viene sin la media móvil y a escala (la media de cada banda vale 1); el acento de graves es la
    subida lineal de los graves (conserva lo fuerte que es cada golpe), también con media 1."""
    x = np.asarray(samples, dtype=np.float32)
    x = x[np.isfinite(x)] if not np.isfinite(x).all() else x
    level = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0
    if level < 1e-5:
        return None
    x = x / level
    nfft = 1 << max(6, int(round(np.log2(WINDOW_S * sample_rate))))
    hop = max(1, int(round(HOP_S * sample_rate)))
    if len(x) < nfft + 8 * hop:
        return None
    window = np.hanning(nfft).astype(np.float32)
    freqs = np.fft.rfftfreq(nfft, 1.0 / sample_rate)
    edges = [(int(np.searchsorted(freqs, lo)), max(int(np.searchsorted(freqs, lo)) + 1, int(np.searchsorted(freqs, hi))))
             for lo, hi in BAND_HZ]
    frames_all = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop]
    count = len(frames_all)
    flux = np.zeros((len(BAND_HZ), count))
    linear = np.zeros(count)                   # subida de los graves sin comprimir: conserva lo fuerte que es cada golpe
    previous = previous_lin = None
    tone = (int(np.searchsorted(freqs, SECTION_HZ[0])), max(int(np.searchsorted(freqs, SECTION_HZ[0])) + 1,
                                                            int(np.searchsorted(freqs, SECTION_HZ[1]))))
    kept = []                                  # espectro de los graves, para ver cuándo cambia el bajo
    for first in range(0, count, 1024):
        frames = np.asarray(frames_all[first:first + 1024])
        mag = np.abs(np.fft.rfft(frames * window, axis=1))
        logmag = np.log1p(mag)
        kept.append(logmag[:, tone[0]:tone[1]].astype(np.float32))
        lin = mag[:, edges[0][0]:edges[0][1]].sum(axis=1)
        if previous is not None:
            logmag = np.vstack((previous, logmag))
            lin = np.concatenate((previous_lin, lin))
            start = first - 1
        else:
            start = first
        rise = np.maximum(logmag[1:] - logmag[:-1], 0.0)
        offset = start + 1
        for b, (lo, hi) in enumerate(edges):
            flux[b, offset:offset + len(rise)] = rise[:, lo:hi].sum(axis=1)
        linear[offset:offset + len(rise)] = np.maximum(lin[1:] - lin[:-1], 0.0)
        previous, previous_lin = logmag[-1:], lin[-1:]
    fps = sample_rate / hop
    kernel_len = max(3, int(round(LOCAL_MEAN_S * fps)))
    kernel = np.ones(kernel_len) / kernel_len
    bands = []
    for b in range(len(BAND_HZ)):
        row = flux[b] - np.convolve(flux[b], kernel, mode="same")           # lo que ya sonaba no cuenta
        row = np.maximum(row, 0.0)
        scale = float(row.mean())
        if scale <= 1e-9:
            bands.append(np.zeros(count))
        else:
            bands.append(row / scale)
    total = sum(w * row for w, row in zip(BAND_WEIGHT, bands))
    if float(total.max()) <= 0:
        return None
    smooth = np.array([0.25, 0.5, 0.25])
    total = np.convolve(total, smooth, mode="same")
    bass = np.convolve(linear, smooth, mode="same")
    bass = bass / max(float(bass.mean()), 1e-12)
    first_time = nfft / 2.0 / sample_rate - LATENCY_S
    return total, bass, fps, first_time, np.vstack(kept)


# ------------------------------------------------------------------ tempo grueso
def _coarse_tempo(np, nov, fps, bpm_hint):
    """Tempo grueso en BPM (con la pista, el más cercano a ella o a su mitad o su doble), o None."""
    x = nov - nov.mean()
    size = 1 << max(16, int(np.ceil(np.log2(len(x) * 4))))
    mag = np.abs(np.fft.rfft(x, size))
    bin_bpm = fps * 60.0 / size                                   # BPM por contenedor

    def score_at(bins):
        total = np.zeros(len(bins))
        for h, w in enumerate(HARMONICS, start=1):
            total += w * mag[np.minimum(bins * h, len(mag) - 1)]
        return total

    def best_in(lo, hi):
        bins = np.arange(int(lo / bin_bpm), int(hi / bin_bpm) + 1)
        if len(bins) < 3:
            return None, 0.0
        score = score_at(bins)
        # suavizado mínimo para que un pico estrecho y alto no gane a uno ancho y real
        score = np.convolve(score, np.ones(3) / 3, mode="same")
        i = int(np.argmax(score))
        shift = 0.0
        if 0 < i < len(score) - 1:
            a, b, c = score[i - 1], score[i], score[i + 1]
            denom = a - 2 * b + c
            if denom < 0:
                shift = float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
        return (bins[i] + shift) * bin_bpm, float(score[i])

    if not bpm_hint or not (bpm_hint > 0):
        bpm, _s = best_in(*WINDOW_BPM)
        return [bpm] if bpm else []
    out = []
    for factor in (1.0, 2.0, 0.5):                                # el tempo de la pista primero; su doble y su mitad de reserva
        centre = bpm_hint * factor
        if not (MIN_BPM <= centre <= MAX_BPM):
            continue
        bpm, _s = best_in(max(MIN_BPM, centre * (1 - HINT_RANGE)), min(MAX_BPM, centre * (1 + HINT_RANGE)))
        if bpm:
            out.append(bpm)
    free, _s = best_in(*WINDOW_BPM)                              # y el que saldría sin pista (la pista puede estar a 3:2)
    if free and all(abs(free / o - 1.0) > HINT_RANGE for o in out):
        out.append(free)
    return out


# ------------------------------------------------------------------ camino de golpes
def _beat_path(np, nov, period):
    """Posiciones (lecturas enteras) de la cadena de golpes que más novedad suma con intervalos cercanos a `period`
    (programación dinámica: cada golpe elige el anterior entre period·(1 ± DRIFT_RANGE), con una multa por apartarse del
    periodo). Así se aguanta un tempo que deriva, una parada o una introducción sin golpes, y no se salta a un contratiempo."""
    n = len(nov)
    lo = max(1, int(np.floor(period * (1.0 - DRIFT_RANGE))))
    hi = max(lo + 1, int(np.ceil(period * (1.0 + DRIFT_RANGE))))
    penalty = -TIGHTNESS * np.log(np.arange(lo, hi + 1) / period) ** 2
    score = np.asarray(nov, dtype=np.float64).copy()
    back = np.full(n, -1, dtype=np.int64)
    for t in range(lo, n):
        prev = score[max(0, t - hi):t - lo + 1][::-1]                # el golpe anterior a lo, lo + 1, ... lecturas
        cand = prev + penalty[:len(prev)]
        j = int(cand.argmax())
        if cand[j] > 0.0:                                            # si no merece la pena, la cadena empieza aquí
            score[t] += cand[j]
            back[t] = t - lo - j
    last = int(np.argmax(score[max(0, n - hi):])) + max(0, n - hi)
    path = [last]
    while back[path[-1]] >= 0:
        path.append(int(back[path[-1]]))
    return np.array(path[::-1])


def _refine(np, nov, pos, width=2):
    """(posición con decimales, valor) del mayor pico de `nov` a menos de `width` lecturas de `pos`."""
    n = len(nov)
    lo, hi = max(0, pos - width), min(n - 1, pos + width)
    i = lo + int(np.argmax(nov[lo:hi + 1]))
    off = 0.0
    if 0 < i < n - 1:
        a, b, c = nov[i - 1], nov[i], nov[i + 1]
        denom = a - 2 * b + c
        if denom < 0:
            off = float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
    return i + off, float(nov[i])


def _fit_line(np, k, t, w, period):
    """(origen, pendiente) de la recta t = a + b·k por mínimos cuadrados con pesos, descartando atípicos."""
    w = w.astype(float).copy()
    a, b = float(t[0]), float(period)
    for _ in range(4):
        if w.sum() <= 0 or np.count_nonzero(w) < 3:
            break
        sw = w.sum()
        km, tm = (w * k).sum() / sw, (w * t).sum() / sw
        var = (w * (k - km) ** 2).sum()
        if var <= 0:
            break
        b = float((w * (k - km) * (t - tm)).sum() / var)
        a = float(tm - b * km)
        resid = np.abs(t - (a + b * k))
        w = np.where(resid <= 0.2 * period, w, 0.0)
    return a, b


def _section_peaks(np, spectrum, beat_pos, period):
    """Golpes donde el bajo cambia de verdad (el espectro de graves de los SECTION_BEATS golpes siguientes no se parece al de los
    anteriores) y están por encima de lo normal: [(número de golpe, peso)]. Entran las partes y las frases nuevas, que empiezan
    en un compás; el dibujo de la batería, que se repite, no cuenta (sus golpes se parecen antes y después)."""
    total = np.vstack((np.zeros((1, spectrum.shape[1])), np.cumsum(spectrum, axis=0, dtype=np.float64)))
    n, span = len(spectrum), SECTION_BEATS * period

    def mean_span(a, c):
        a, c = np.clip(np.rint(a).astype(int), 0, n), np.clip(np.rint(c).astype(int), 0, n)
        return (total[c] - total[a]) / np.maximum(c - a, 1)[:, None], (c - a) >= 0.8 * span

    before, ok_before = mean_span(beat_pos - span, beat_pos)
    after, ok_after = mean_span(beat_pos, beat_pos + span)
    valid = ok_before & ok_after
    change = np.where(valid, np.abs(after - before).sum(axis=1), 0.0)
    if not valid.any():
        return []
    typical = float(np.median(change[valid]))
    if typical <= 0:
        return []
    peaks = []
    for j in np.nonzero(valid)[0]:
        near = change[max(0, j - SECTION_BEATS):j + SECTION_BEATS + 1]
        if change[j] >= near.max() and change[j] > 1.5 * typical:
            peaks.append((int(j), float(change[j] / typical - 1.0)))
    return peaks


def _bar_score(np, segments, peaks, first, last):
    """Puntuación de cada uno de los 4 golpes como golpe fuerte del compás con los golpes de [first, last): el acento de los
    graves (por tramos) más los cambios de bajo (que votan por el golpe en que ocurren, módulo 4)."""
    chosen = [z for start, z in segments if first <= start < last]
    score = np.sum(chosen, axis=0) if chosen else np.zeros(4)
    votes = np.zeros(4)
    for j, weight in peaks:
        if first <= j < last:
            votes[j % 4] += weight
    if votes.sum() > 0:
        score = score + SECTION_WEIGHT * max(1, len(chosen)) * votes / votes.sum()
    return score


# ------------------------------------------------------------------ cálculo
def analyse(samples, bpm_hint=None, sample_rate=SAMPLE_RATE):
    """Como `compute`, pero devolviendo también lo que sirve para depurar y probar: un dict con "grid" (BeatGrid),
    "beats" (instantes de los golpes encontrados desde el primero, en segundos), "hits" (cuáles se encontraron),
    "strength" (acento de graves de cada uno), "bar_score" (puntuación de cada uno de los 4 golpes como golpe fuerte del
    compás) y "bar_halves" (lo mismo con solo la primera mitad y solo la segunda, para ver si se mantiene), "contrast",
    "hit_share" y "clarity".
    None si no hay numpy, el audio es demasiado corto o no hay un pulso claro."""
    np = _numpy()
    if np is None or samples is None or len(samples) < MIN_SECONDS * sample_rate:
        return None
    try:
        return _analyse(np, samples, bpm_hint, sample_rate)
    except Exception as e:
        logger.warning(f"No se pudo calcular la rejilla de golpes: {e}")
        return None


def _analyse(np, samples, bpm_hint, sample_rate):
    made = _novelty(np, samples, sample_rate)
    if made is None:
        return None
    nov, bass, fps, t0, spectrum = made
    for coarse in _coarse_tempo(np, nov, fps, bpm_hint):
        found = _grid_at(np, nov, bass, fps, t0, spectrum, coarse)
        if found is not None:
            return found
    return None


def _grid_at(np, nov, bass, fps, t0, spectrum, coarse):
    """Rejilla con el tempo grueso `coarse` (BPM), o None si a ese tempo no hay un pulso claro."""
    period = 60.0 / coarse * fps                                # en lecturas
    path = _beat_path(np, nov, period)
    if len(path) < MIN_BEATS:
        return None
    refined = [_refine(np, nov, int(p)) for p in path]
    pos = np.array([r[0] for r in refined])
    strength_peak = np.array([r[1] for r in refined])
    ref = float(np.median(strength_peak))
    hit = strength_peak >= HIT_SHARE * ref                      # golpe «encontrado»: la novedad llega a una parte de lo normal
    # primer golpe: el primero encontrado que tiene detrás una tanda de golpes seguidos
    ahead_hits = np.array([hit[i:i + RUN_BEATS].sum() for i in range(len(hit))])
    good = np.nonzero(hit & (ahead_hits >= min(RUN_HITS, len(hit))))[0]
    if not len(good):
        return None
    k0 = int(good[0])
    pos, hit, strength_peak = pos[k0:], hit[k0:], strength_peak[k0:]
    if len(pos) < MIN_BEATS:
        return None
    k = np.arange(len(pos), dtype=float)
    a, b = _fit_line(np, k[hit], pos[hit], np.minimum(strength_peak[hit], 3.0 * ref), period)
    if not (b > 0):
        return None
    # primer golpe: la recta de todo el tramo si el tempo es constante; si deriva, el ajuste local de los primeros golpes
    first = a
    local = hit & (k < 32)
    if np.count_nonzero(local) >= 8:
        la, lb = _fit_line(np, k[local], pos[local], np.ones(np.count_nonzero(local)), period)
        if lb > 0 and abs(lb / b - 1.0) > 0.004:
            first = la
    first_s = float(first / fps + t0)
    bpm = 60.0 * fps / b
    # acento de cada golpe y golpe fuerte del compás (donde de verdad cayó cada golpe, que con un tempo que deriva no es la recta)
    beat_pos = np.where(hit, pos, first + b * k)
    width = max(2.0, 0.08 * b)
    strong, full = np.zeros(len(k)), np.zeros(len(k))
    for i, p in enumerate(beat_pos):
        lo, hi = max(0, int(np.ceil(p - width))), min(len(nov) - 1, int(np.floor(p + width)))
        if hi >= lo:
            strong[i] = float(bass[lo:hi + 1].max())
            full[i] = float(nov[lo:hi + 1].max())
    accent = strong + 0.2 * full
    segments = []                                                # (golpe en que empieza el tramo, qué golpe de 4 destaca)
    for start in range(0, len(k) - 7, BAR_SEGMENT):
        chunk = accent[start:start + BAR_SEGMENT]
        if float(chunk.mean()) > 0:
            slots = np.array([chunk[r::4].mean() if len(chunk[r::4]) else 0.0 for r in range(4)])
            segments.append((start, (slots - slots.mean()) / float(chunk.mean())))
    peaks = _section_peaks(np, spectrum, beat_pos, b)
    score = _bar_score(np, segments, peaks, 0, len(k))
    halves = (_bar_score(np, segments, peaks, 0, len(k) // 2), _bar_score(np, segments, peaks, len(k) // 2, len(k)))
    offset = int(np.argmax(score))
    ordered = np.sort(score)
    clarity = float((ordered[-1] - ordered[-2]) / (np.abs(score).sum() + 1e-9) * 2.0) if segments else 0.0
    clarity = min(1.0, max(0.0, clarity))
    # confianza: destaque de los golpes sobre el resto de fases del periodo y fracción de golpes encontrados
    def level_at(shift):
        total = 0.0
        for p in beat_pos:
            lo, hi = max(0, int(np.ceil(p + shift - width))), min(len(nov) - 1, int(np.floor(p + shift + width)))
            total += float(nov[lo:hi + 1].max()) if hi >= lo else 0.0
        return total / len(beat_pos)

    others = [level_at(b * s / 12.0) for s in range(1, 12) if min(s / 12.0, 1.0 - s / 12.0) * b > 2.0 * width]
    contrast = (level_at(0.0) + 1e-9) / (float(np.median(others)) + 1e-9) if others else 1.0
    hit_share = float(np.count_nonzero(hit)) / len(hit)
    confidence = hit_share * (1.0 - float(np.exp(-1.5 * (contrast - 1.0)))) * (0.7 + 0.3 * clarity)
    confidence = float(min(1.0, max(0.0, confidence)))
    if confidence < MIN_CONFIDENCE:
        return None
    skipped = 0
    while first_s < 0.0:                                         # un primer golpe antes de que empiece la canción no sirve
        first_s += 60.0 / bpm
        skipped += 1
    offset = (offset - skipped) % 4
    grid = BeatGrid(first_beat_s=first_s, bpm=float(bpm), beats_per_bar=4, downbeat_offset=offset, confidence=round(confidence, 3))
    return {"grid": grid, "beats": beat_pos / fps + t0, "hits": hit, "strength": strong, "bar_score": score, "bar_halves": halves,
            "contrast": float(contrast), "hit_share": hit_share, "clarity": clarity, "novelty": nov, "fps": fps, "t0": t0}


def compute(samples, bpm_hint=None, sample_rate=SAMPLE_RATE):
    """Rejilla de golpes de un audio mono ya decodificado (el de `key_detect.decode`: float32 a 11.025 Hz), o None si no hay
    numpy, es muy corto o no tiene un pulso claro. `bpm_hint` es el tempo ya conocido (del análisis o corregido a mano):
    se afina alrededor de él (su mitad, su doble y el tempo libre solo se prueban si en el suyo no hay pulso)."""
    found = analyse(samples, bpm_hint, sample_rate)
    return found["grid"] if found else None


def detect(path: str, bpm_hint=None):
    """Rejilla de golpes de una canción (decodifica con FFmpeg, hasta 8 minutos), o None si no se pudo (sin numpy ni FFmpeg,
    archivo ilegible, sin pulso claro): en ese caso la aplicación sigue sin rejilla."""
    samples = key_detect.decode(path)
    if samples is None:
        return None
    return compute(samples, bpm_hint, key_detect.SAMPLE_RATE)


def alignment(samples, grid, sample_rate=SAMPLE_RATE, tolerance_s=0.035):
    """Puntuación de alineación 0 a 1: qué fracción de los golpes que predice `grid` cae (a menos de `tolerance_s`) sobre un
    pico de la curva de novedad (un máximo local por encima de la media de la curva). Sirve de verificación de cordura donde
    no hay referencia; con ruido da en torno a 0,3 o menos. None si no se puede calcular."""
    np = _numpy()
    if np is None or grid is None or samples is None:
        return None
    made = _novelty(np, samples, sample_rate)
    if made is None:
        return None
    nov, _bass, fps, t0, _spectrum = made
    peaks = (nov[1:-1] > nov[:-2]) & (nov[1:-1] >= nov[2:]) & (nov[1:-1] > nov.mean() + 0.5 * nov.std())
    peak_times = (np.nonzero(peaks)[0] + 1) / fps + t0
    if not len(peak_times):
        return 0.0
    end = len(samples) / sample_rate
    count = int((end - grid.first_beat_s) / grid.beat_s)
    if count < 1:
        return None
    times = grid.first_beat_s + grid.beat_s * np.arange(count)
    place = np.clip(np.searchsorted(peak_times, times), 1, len(peak_times) - 1)
    near = np.minimum(np.abs(peak_times[place] - times), np.abs(peak_times[place - 1] - times))
    return float(np.mean(near <= tolerance_s))
