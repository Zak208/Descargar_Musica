"""Estructura de una canción para el modo DJ (fases 18 y 19, versión ligera): subidas (build-ups), caídas (drops), parones
(breaks), partes de la canción y una estimación aproximada de dónde hay voz.

Se calcula con el mismo audio que ya se decodifica para el tono y la rejilla (mono, 11.025 Hz; ver `key_detect.decode`), solo
con numpy (opcional, como en `key_detect`): sin numpy, o con audio vacío, en silencio o ilegible, todo devuelve vacío o None y
nada lanza excepciones.

Cómo se calcula (una pasada de Fourier por tramos de 93 ms cada 23 ms, agrupada en bloques de 0,25 s):
  * Por bloque: potencia total (30 Hz a 5 kHz), de graves (30 a 150 Hz), de la banda de la voz (300 a 3.400 Hz) y de agudos
    (2 a 5 kHz, el «brillo»). La energía y los graves que se devuelven (uno por segundo, de 0 a 1) son el nivel en dB respecto
    al máximo de la canción, con 30 dB de recorrido: comparables dentro de la canción, no entre canciones.
  * Drop: los graves (media de 4 s después frente a 4 s antes) suben de golpe 9 dB o más, hasta cerca de lo más fuerte de la
    canción, y sin venir de un silencio. El instante exacto se afina con ventanas de 1 s.
  * Break: lo contrario (los graves caen 9 dB o más desde cerca del máximo) y vuelven más tarde; si no vuelven es el final de
    la canción (outro), no un break. Termina donde vuelven los graves (o en el drop que lo cierra).
  * Subida: antes de cada drop se busca el tramo en que la energía y el brillo crecen (al menos 3 dB cada uno, sostenido: la
    recta que mejor se ajusta explica la mitad o más de la variación) durante 4 s o más. Termina en el drop.
  * Con rejilla (`BeatGrid`), todos los instantes se ajustan al comienzo de compás más cercano.
  * Partes: intro y outro por el nivel (como `track_analysis`: el cuerpo es lo que suena a menos de 6 dB de la mediana), y en
    medio subida, drop (hasta el siguiente evento), break o «verse» (lo demás).

Limitaciones conocidas: en reguetón, dembow, drill o trap el bajo suena casi todo el rato y los drops apenas se marcan, así
que lo normal es que salgan pocos o ninguno (y es correcto: no hay un drop que respetar). Una entrada del bajo tras una intro
tranquila también cuenta como drop. No hay verdad de referencia con canciones reales: los umbrales están elegidos con audio
sintético y revisados a ojo con una carpeta pequeña.

Voz (fase 19): separar la voz de verdad (Demucs) necesita PyTorch y no es viable aquí. `vocal_activity` es solo una
APROXIMACIÓN con la señal: mezcla cuánta energía cae en la banda de la voz, lo armónico (poco ruidoso) que es esa banda y lo
que se modula al ritmo de las sílabas (3 a 8 Hz). Confunde la voz con instrumentos solistas en la misma banda (una guitarra,
un sintetizador que canta una melodía, un saxo) y, en una mezcla densa, la batería y los colchones la rebajan. Sirve para
evitar lo más obvio (dos estribillos cantados a la vez), no para saber con certeza si alguien canta."""
import json
import logging
import math

from services import key_detect

logger = logging.getLogger(__name__)

SAMPLE_RATE = key_detect.SAMPLE_RATE
VERSION = 1                             # súbela si cambia el cálculo (para recalcular lo guardado)
STEP_S = 0.25                           # bloque de trabajo
FRAME_S = 0.093                         # tramo de la transformada (1024 muestras a 11.025 Hz)
FULL_HZ = (30.0, 5000.0)
BASS_HZ = (30.0, 150.0)
VOCAL_HZ = (300.0, 3400.0)
HIGH_HZ = (2000.0, 5000.0)
RANGE_DB = 30.0                         # recorrido de las curvas de 0 a 1 (por debajo del máximo de la canción)
FLOOR_DB = 60.0                         # nada cuenta por debajo de esto respecto al máximo (los silencios no dan saltos infinitos)
SILENT_DB = 45.0                        # un tramo a más de esto por debajo del máximo es silencio
MIN_SECONDS = 8.0                       # con menos audio no hay estructura
WINDOW_S = 4.0                          # ventanas que se comparan para ver un salto de graves
FINE_S = 1.0                            # y para afinar dónde cae
JUMP_DB = 9.0                           # salto de graves mínimo para un drop o un break
NEAR_TOP_DB = 6.0                       # el lado fuerte del salto tiene que estar a menos de esto de los graves máximos
BASS_SHARE_DB = 15.0                    # y los graves no pueden estar más de esto por debajo del total (que se oigan)
MIN_GAP_S = 8.0                         # dos drops (o dos breaks) no están más cerca que esto
RETURN_DB = 4.0                         # el break acaba cuando los graves vuelven a menos de esto de lo que había antes
BUILD_MIN_S, BUILD_MAX_S = 4.0, 40.0    # duración de una subida
BUILD_RISE_DB = 3.0                     # cuánto tiene que crecer la energía en una subida
BRIGHT_RISE_DB = 3.0                    # y el brillo
BUILD_FIT = 0.5                         # la recta tiene que explicar al menos esta parte de la variación (subida sostenida)
KNEE_SHARE = 0.15                       # la subida empieza donde se supera el 15 % de lo que va a crecer
BODY_DB = 6.0                           # intro y outro: lo que suena a más de esto por debajo del cuerpo
VOCAL_ON = 0.5                          # a partir de aquí se considera que hay voz (para `vocal_overlap`)
VOCAL_AUDIBLE_DB = 20.0                 # la banda de la voz no cuenta si queda más de esto por debajo del total de ese segundo
MOD_DEPTH = 1.0                         # desviación de la envolvente (logaritmo de la potencia) que cuenta como modulación plena
KINDS_EVENT = ("buildup", "drop", "break")
KINDS_SECTION = ("intro", "verse", "build", "drop", "break", "outro")

_numpy = key_detect._numpy


def empty() -> dict:
    """Resultado vacío (no se pudo analizar o no hay nada)."""
    return {"energy": [], "bass": [], "events": [], "vocal": [], "sections": []}


def available() -> bool:
    """¿Se puede calcular la estructura? (hace falta numpy)"""
    return _numpy() is not None


# ------------------------------------------------------------------ medidas por bloque
def _features(np, samples, sample_rate):
    """Medidas por bloque de 0,25 s y por tramo, o None si no hay audio suficiente o es silencio."""
    x = np.asarray(samples, dtype=np.float32).ravel()
    if not len(x) or len(x) < MIN_SECONDS * sample_rate:
        return None
    if not np.isfinite(x).all():
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    nfft = 1 << max(8, int(round(math.log2(FRAME_S * sample_rate))))
    hop = nfft // 4
    if len(x) < nfft + hop:
        return None
    window = np.hanning(nfft).astype(np.float32)
    freqs = np.fft.rfftfreq(nfft, 1.0 / sample_rate)

    def band(lo, hi):
        return (freqs >= lo) & (freqs < hi)

    full, bass, vocal, high = band(*FULL_HZ), band(*BASS_HZ), band(*VOCAL_HZ), band(*HIGH_HZ)
    frames_all = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop]
    count = len(frames_all)
    p_full, p_bass, p_vocal, p_high, flat = (np.zeros(count) for _ in range(5))
    for first in range(0, count, 2048):
        frames = np.asarray(frames_all[first:first + 2048])
        power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
        end = first + len(frames)
        p_full[first:end] = power[:, full].sum(axis=1)
        p_bass[first:end] = power[:, bass].sum(axis=1)
        pv = power[:, vocal] + 1e-12
        p_vocal[first:end] = pv.sum(axis=1)
        p_high[first:end] = power[:, high].sum(axis=1)
        flat[first:end] = np.exp(np.mean(np.log(pv), axis=1)) / np.mean(pv, axis=1)       # planitud: 1 ruido, 0 tono puro
    fps = sample_rate / hop
    centres = (np.arange(count) * hop + nfft / 2.0) / sample_rate
    n_blocks = int(math.ceil(len(x) / sample_rate / STEP_S))
    block = np.minimum((centres / STEP_S).astype(int), n_blocks - 1)
    hits = np.maximum(np.bincount(block, minlength=n_blocks), 1)

    def per_block(values):
        out = np.bincount(block, weights=values, minlength=n_blocks) / hits
        empty_blocks = np.bincount(block, minlength=n_blocks) == 0
        if empty_blocks.any():                                        # el último bloque, si se queda sin tramos
            out[empty_blocks] = out[~empty_blocks][-1] if (~empty_blocks).any() else 0.0
        return out

    blocks = {"full": per_block(p_full), "bass": per_block(p_bass), "vocal": per_block(p_vocal), "high": per_block(p_high)}
    peak = float(np.percentile(blocks["full"], 98))
    if not (peak > 1e-9):
        return None
    return {"blocks": blocks, "peak": peak, "frame_vocal": p_vocal, "frame_full": p_full, "frame_bass": p_bass, "frame_flat": flat, "fps": fps,
            "seconds": len(x) / sample_rate, "frame_block": block, "n_blocks": n_blocks}


def _db(np, power, ref):
    return 10.0 * np.log10(np.maximum(power, ref * 10.0 ** (-FLOOR_DB / 10.0)) / ref)


def _per_second(np, values, n_seconds):
    """Media de cada segundo (4 bloques) de una curva por bloque."""
    per = int(round(1.0 / STEP_S))
    out = np.zeros(n_seconds)
    for s in range(n_seconds):
        chunk = values[s * per:(s + 1) * per]
        out[s] = float(chunk.mean()) if len(chunk) else (out[s - 1] if s else 0.0)
    return out


def _smooth(np, values, width):
    width = max(1, int(width))
    if width <= 1 or len(values) < width:
        return values.copy()
    kernel = np.ones(width) / width
    padded = np.concatenate((np.full(width // 2, values[0]), values, np.full(width - 1 - width // 2, values[-1])))
    return np.convolve(padded, kernel, mode="valid")


def _window_means(np, power, w):
    """(media de los w bloques anteriores, media de los w siguientes) en cada frontera de bloque i (de 0 a n)."""
    total = np.concatenate(([0.0], np.cumsum(power)))
    n = len(power)
    i = np.arange(n + 1)
    lo, hi = np.maximum(i - w, 0), np.minimum(i + w, n)
    before = (total[i] - total[lo]) / np.maximum(i - lo, 1)
    after = (total[hi] - total[i]) / np.maximum(hi - i, 1)
    return before, after


# ------------------------------------------------------------------ eventos
def _snap(t, grid):
    """Comienzo de compás más cercano a `t` (sin rejilla, `t` tal cual)."""
    if grid is None:
        return float(t)
    try:
        snapped = float(grid.bar_time(round(grid.bar_at(t))))
        return snapped if snapped >= 0 else float(grid.bar_time(math.ceil(grid.bar_at(0.0) - 1e-9)))
    except Exception:
        return float(t)


def _jumps(np, f):
    """(saltos de graves en dB en cada frontera con ventanas de 4 s, ídem con 1 s, medias de graves y del total en dB)."""
    blocks, peak = f["blocks"], f["peak"]
    w, wf = int(round(WINDOW_S / STEP_S)), int(round(FINE_S / STEP_S))
    b_before, b_after = _window_means(np, blocks["bass"], w)
    t_before, t_after = _window_means(np, blocks["full"], w)
    fb_before, fb_after = _window_means(np, blocks["bass"], wf)
    db = {"b_before": _db(np, b_before, peak), "b_after": _db(np, b_after, peak), "t_before": _db(np, t_before, peak),
          "t_after": _db(np, t_after, peak), "fine_after": _db(np, fb_after, peak)}
    jump = db["b_after"] - db["b_before"]
    fine = db["fine_after"] - _db(np, fb_before, peak)
    return jump, fine, db, w, wf


def _pick(np, score, w, gap, allowed):
    """Fronteras donde `score` es máximo local (en ±w), pasa el umbral y cumple `allowed`, separadas al menos `gap` bloques."""
    n = len(score)
    order = [i for i in np.argsort(-score) if allowed[i] and score[i] >= JUMP_DB]
    chosen = []
    for i in order:
        i = int(i)
        if score[i] < score[max(0, i - w):min(n, i + w + 1)].max():
            continue
        if all(abs(i - j) >= gap for j in chosen):
            chosen.append(i)
    return sorted(chosen)


def _refine(np, fine, i, w):
    lo, hi = max(0, i - w // 2), min(len(fine), i + w // 2 + 1)
    return lo + int(np.argmax(fine[lo:hi]))


def _detect(np, f, grid):
    """Lista de eventos (sin ordenar) a partir de las medidas por bloque."""
    blocks = f["blocks"]
    n = len(blocks["full"])
    jump, fine, db, w, wf = _jumps(np, f)
    bass_db = _db(np, blocks["bass"], f["peak"])
    bass_top = float(np.percentile(bass_db, 95))
    gap = int(round(MIN_GAP_S / STEP_S))
    idx = np.arange(n + 1)
    full_windows = (idx >= w) & (idx <= n - w)
    # drops: los graves suben de golpe hasta cerca de su máximo, se oyen y no se viene de un silencio
    drop_ok = (full_windows & (db["b_after"] >= bass_top - NEAR_TOP_DB) & (db["b_after"] >= db["t_after"] - BASS_SHARE_DB)
               & (db["t_before"] >= -SILENT_DB))
    drops = [_refine(np, fine, i, w) for i in _pick(np, jump, w, gap, drop_ok)]
    # breaks: los graves caen de golpe desde cerca de su máximo... y vuelven más tarde
    break_ok = full_windows & (db["b_before"] >= bass_top - NEAR_TOP_DB) & (db["b_before"] >= db["t_before"] - BASS_SHARE_DB)
    breaks = []
    for i in _pick(np, -jump, w, gap, break_ok):
        i = _refine(np, -fine, i, w)
        level = float(db["b_before"][i])
        found = np.nonzero(db["fine_after"][i + w:n - wf + 1] >= level - RETURN_DB)[0]
        back = i + w + int(found[0]) if len(found) else None
        if back is None:
            continue                                                      # no vuelven: es el final, no un break
        after_drops = [d for d in drops if i < d <= back + w]
        end = after_drops[0] if after_drops else back
        breaks.append((i, end, float(-jump[i])))
    events = []
    for d in drops:
        events.append({"t": d, "type": "drop", "end": None, "strength": min(1.0, max(0.0, float(jump[d]) / 20.0))})
    for i, end, size in breaks:
        events.append({"t": i, "type": "break", "end": end, "strength": min(1.0, max(0.0, size / 20.0))})
    # subidas: antes de cada drop, desde el evento anterior como mucho
    e = _smooth(np, _db(np, blocks["full"], f["peak"]), int(round(1.0 / STEP_S)))
    h = _smooth(np, _db(np, blocks["high"], f["peak"]), int(round(1.0 / STEP_S)))
    for d in drops:
        previous = [ev["t"] for ev in events if ev["t"] < d] + [ev["end"] for ev in events if ev["end"] is not None and ev["end"] < d]
        built = _buildup(np, e, h, d, max(previous) if previous else 0)
        if built is not None:
            events.append(built)
    for ev in events:
        ev["t"] = round(_snap(ev["t"] * STEP_S, grid), 3)
        if ev["end"] is not None:
            ev["end"] = round(_snap(ev["end"] * STEP_S, grid), 3)
        ev["strength"] = round(ev["strength"], 3)
    events = [ev for ev in events if ev["end"] is None or ev["end"] > ev["t"]]
    events.sort(key=lambda ev: (ev["t"], KINDS_EVENT.index(ev["type"])))
    return events


def _buildup(np, e, h, d, floor):
    """La subida que acaba en el drop `d` (bloque), sin empezar antes del bloque `floor`, o None."""
    lo = max(int(floor), d - int(round(BUILD_MAX_S / STEP_S)))
    hi = d - int(round(BUILD_MIN_S / STEP_S))
    tail = int(round(2.0 / STEP_S))
    if hi <= lo or d - tail < lo:
        return None
    e_end = float(np.percentile(e[d - tail:d], 90))
    h_end = float(np.percentile(h[d - tail:d], 90))
    starts = []
    for curve, top in ((e, e_end), (h, h_end)):
        s0 = lo + int(np.argmin(curve[lo:hi + 1]))
        low = float(curve[s0])
        rise = top - low
        if rise <= 0:
            return None
        knee = [k for k in range(s0, hi + 1) if curve[k] <= low + KNEE_SHARE * rise]
        starts.append((knee[-1] if knee else s0, rise))
    start = min(starts[0][0], starts[1][0])
    rise_e = e_end - float(np.min(e[start:start + int(round(1.0 / STEP_S)) + 1]))
    rise_h = h_end - float(np.min(h[start:start + int(round(1.0 / STEP_S)) + 1]))
    if rise_e < BUILD_RISE_DB or rise_h < BRIGHT_RISE_DB or (d - start) * STEP_S < BUILD_MIN_S:
        return None
    seg = (e[start:d] + h[start:d]) / 2.0
    k = np.arange(len(seg), dtype=float)
    if len(seg) < 4 or float(np.std(seg)) <= 1e-9:
        return None
    r = float(np.corrcoef(k, seg)[0, 1])
    if not (r > 0 and r * r >= BUILD_FIT):
        return None
    return {"t": start, "type": "buildup", "end": d, "strength": min(1.0, max(0.0, (rise_e + rise_h) / 30.0))}


# ------------------------------------------------------------------ partes de la canción
def _sections(np, f, events, duration):
    e = _smooth(np, _db(np, f["blocks"]["full"], f["peak"]), int(round(2.0 / STEP_S)))
    n = len(e)
    core = np.sort(e[int(n * 0.15):int(n * 0.85)] if n > 10 else e)
    body = float(core[len(core) // 2])
    loud = np.nonzero(e >= body - BODY_DB)[0]
    intro_end = float(loud[0]) * STEP_S if len(loud) else 0.0
    outro_start = float(loud[-1] + 1) * STEP_S if len(loud) else duration
    starts = sorted(ev["t"] for ev in events)
    marks = starts + [ev["end"] for ev in events if ev["end"] is not None]
    if starts:
        intro_end = min(intro_end, starts[0])
        outro_start = max(outro_start, max(marks))
    outro_start = min(max(outro_start, intro_end), duration)
    cuts = sorted({0.0, duration, intro_end, outro_start, *[min(max(m, 0.0), duration) for m in marks]})

    def kind_at(m):
        if m < intro_end:
            return "intro"
        if m >= outro_start:
            return "outro"
        for ev in events:
            if ev["type"] in ("buildup", "break") and ev["end"] is not None and ev["t"] <= m < ev["end"]:
                return "build" if ev["type"] == "buildup" else "break"
        last = None
        for ev in events:
            if ev["t"] <= m:
                last = ev
        if last is not None and last["type"] == "drop":
            return "drop"
        return "verse"

    sections = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a <= 1e-6:
            continue
        kind = kind_at((a + b) / 2.0)
        if sections and sections[-1]["kind"] == kind:
            sections[-1]["end"] = round(b, 3)
        else:
            sections.append({"start": round(a, 3), "end": round(b, 3), "kind": kind})
    return sections


# ------------------------------------------------------------------ voz (aproximación)
def _vocal_from(np, f):
    """Actividad de voz estimada (0 a 1) por segundo a partir de las medidas por tramo."""
    n_seconds = int(math.ceil(f["seconds"]))
    fps = f["fps"]
    pv, pf, flat = f["frame_vocal"], f["frame_full"], f["frame_flat"]
    upper = np.maximum(pf - f["frame_bass"], 0.0)                        # lo que suena por encima de los graves
    peak_frame = float(np.percentile(pf, 98))
    if not (peak_frame > 1e-9):
        return [0.0] * n_seconds
    env = np.log(pv + peak_frame * 1e-6)                                  # envolvente (en logaritmo) de la banda de la voz
    second = np.minimum((np.arange(len(pv)) / fps).astype(int), n_seconds - 1)
    mod_freqs = None
    half = int(round(fps))                                                # ventana de 2 s centrada en cada segundo
    out = np.zeros(n_seconds)
    for s in range(n_seconds):
        sel = second == s
        if not sel.any():
            continue
        voiced = float(pv[sel].sum())
        if voiced < sel.sum() * peak_frame * 10.0 ** (-SILENT_DB / 10.0) or voiced < float(pf[sel].sum()) * 10.0 ** (-VOCAL_AUDIBLE_DB / 10.0):
            continue                                                      # la banda de la voz no suena o queda tapada
        share = voiced / max(float(upper[sel].sum()), 1e-12)
        flatness = float(np.median(flat[sel]))
        centre = int((s + 0.5) * fps)
        seg = env[max(0, centre - half):centre + half]
        mod = 0.0
        if len(seg) >= 16:
            depth = min(1.0, float(np.std(seg)) / MOD_DEPTH)                 # un tono fijo no se modula (aunque su espectro de modulación sea ruido)
            seg = (seg - seg.mean()) * np.hanning(len(seg))
            spec = np.abs(np.fft.rfft(seg, 256)) ** 2
            if mod_freqs is None or len(mod_freqs) != len(spec):
                mod_freqs = np.fft.rfftfreq(256, 1.0 / fps)
            total = float(spec[(mod_freqs >= 1.0) & (mod_freqs <= 16.0)].sum())
            if total > 1e-12:
                mod = depth * float(spec[(mod_freqs >= 3.0) & (mod_freqs <= 8.0)].sum()) / total
        score_band = min(1.0, max(0.0, (share - 0.3) / 0.3))
        score_tone = min(1.0, max(0.0, (0.45 - flatness) / 0.35))
        score_mod = min(1.0, max(0.0, (mod - 0.2) / 0.4))
        out[s] = score_band * score_tone * (0.1 + 0.9 * score_mod)
    out = _smooth(np, out, 3)
    return [round(float(v), 2) for v in np.clip(out, 0.0, 1.0)]


def vocal_activity(samples, sample_rate=SAMPLE_RATE) -> list:
    """Actividad de voz ESTIMADA (0 a 1) por segundo. Es una aproximación con la señal, no una separación de voces: mira la
    energía en 300 a 3.400 Hz frente a la total, lo armónica (poco ruidosa) que es esa banda y su modulación al ritmo de las
    sílabas (3 a 8 Hz). Confunde la voz con instrumentos solistas (guitarra, sintetizador melódico, viento) y en mezclas
    densas da valores bajos. Lista vacía si no se puede (sin numpy, audio corto o vacío)."""
    np = _numpy()
    if np is None or samples is None:
        return []
    try:
        f = _features(np, samples, sample_rate)
        return _vocal_from(np, f) if f is not None else []
    except Exception as e:
        logger.warning(f"No se pudo estimar la voz: {e}")
        return []


# ------------------------------------------------------------------ análisis completo
def analyse(samples, grid=None, sample_rate=SAMPLE_RATE) -> dict:
    """Estructura de un audio mono ya decodificado (el de `key_detect.decode`): {"energy", "bass", "vocal"} (listas de 0 a 1,
    una por segundo), "events" ([{"t", "type": buildup|drop|break, "end", "strength"}], en segundos de la canción) y
    "sections" ([{"start", "end", "kind": intro|verse|build|drop|break|outro}]). Con `grid` (`BeatGrid`) los instantes caen
    en comienzos de compás. Nunca lanza: si no se puede (sin numpy, audio corto, silencio) devuelve las listas vacías."""
    np = _numpy()
    if np is None or samples is None:
        return empty()
    try:
        f = _features(np, samples, sample_rate)
        if f is None:
            return empty()
        n_seconds = int(math.ceil(f["seconds"]))
        blocks = f["blocks"]
        energy = _per_second(np, np.clip((_db(np, blocks["full"], f["peak"]) + RANGE_DB) / RANGE_DB, 0.0, 1.0), n_seconds)
        bass = _per_second(np, np.clip((_db(np, blocks["bass"], f["peak"]) + RANGE_DB) / RANGE_DB, 0.0, 1.0), n_seconds)
        events = _detect(np, f, grid)
        return {"energy": [round(float(v), 3) for v in energy], "bass": [round(float(v), 3) for v in bass], "events": events,
                "vocal": _vocal_from(np, f), "sections": _sections(np, f, events, round(f["seconds"], 3))}
    except Exception as e:
        logger.warning(f"No se pudo analizar la estructura: {e}")
        return empty()


# ------------------------------------------------------------------ dos canciones en una mezcla
def _margin(length_s):
    """Al principio de la mezcla B apenas se oye y al final A ya no: un evento a menos de esto del borde no cuenta."""
    return min(max(0.5, 0.1 * length_s), length_s / 4.0)


def _of(events, kind):
    out = []
    for ev in events or ():
        try:
            if ev.get("type") == kind and ev.get("t") is not None:
                out.append((float(ev["t"]), None if ev.get("end") is None else float(ev["end"])))
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def drops_overlap(plan_a_start_s, length_s, tempo_ratio_b, b_start_s, a_events, b_events) -> bool:
    """¿Coinciden dos drops durante la mezcla, o el drop de una cae en plena subida de la otra? A suena a su tempo desde
    `plan_a_start_s` y se va al final de la mezcla; B entra en `b_start_s` (su tiempo original) a tempo `tempo_ratio_b` (por
    cada segundo de mezcla avanzan `tempo_ratio_b` segundos de B). Cerca de los bordes no cuenta lo que apenas se oye (ver
    `_margin`): por eso el drop de B justo al final de la mezcla (lo que propone `drop_aligned_b_start`) no se cruza con nada.
    Solo mira los instantes de drop y las subidas, no si toda una parte fuerte se solapa. False si faltan datos."""
    try:
        length = float(length_s)
        if not (length > 0):
            return False
        ratio = float(tempo_ratio_b or 1.0)
        ratio = ratio if ratio > 0 else 1.0
        a0, b0, m = float(plan_a_start_s), float(b_start_s), _margin(length)

        def out_a(t):
            return t - a0

        def out_b(t):
            return (t - b0) / ratio

        a_drops = [out_a(t) for t, _e in _of(a_events, "drop") if 0.0 <= out_a(t) < length - m]
        b_drops = [out_b(t) for t, _e in _of(b_events, "drop") if m < out_b(t) <= length]
        if a_drops and b_drops:
            return True
        for t, end in _of(a_events, "buildup"):
            s, e = out_a(t), out_a(end if end is not None else t)
            if any(s <= u <= e and u < length - m for u in b_drops):
                return True
        for t, end in _of(b_events, "buildup"):
            s, e = out_b(t), out_b(end if end is not None else t)
            if any(s <= u <= e and u > m for u in a_drops):
                return True
        return False
    except Exception:
        return False


def drop_aligned_b_start(a_events, b_events, a_mix_start_s, length_s, tempo_ratio_b, grid_b):
    """Desde dónde (segundos de B, en su tiempo original) tiene que entrar B para que su primer drop que quepa caiga al acabar
    la mezcla. Si A tiene una subida que termina en el último cuarto de la mezcla (o hasta 2 s después), el drop de B se lleva
    al final de esa subida: así el drop de B sustituye al de A (el planificador debería hacer acabar la mezcla ahí). Con
    `grid_b`, el resultado es el comienzo de compás de B más cercano (el drop cae a menos de medio compás del objetivo).
    None si B no tiene drops o ninguno deja sitio (habría que empezar B antes de su principio)."""
    try:
        length = float(length_s)
        ratio = float(tempo_ratio_b or 1.0)
        ratio = ratio if ratio > 0 else 1.0
        if not (length > 0):
            return None
        a0 = float(a_mix_start_s)
        target = length
        for _t, end in _of(a_events, "buildup"):
            if end is not None and a0 + 0.75 * length <= end <= a0 + length + 2.0:
                target = end - a0
                break
        for t, _e in sorted(_of(b_events, "drop")):
            start = t - target * ratio
            if start < 0:
                continue
            if grid_b is not None:
                snapped = _snap(start, grid_b)
                if snapped < 0:
                    snapped = float(grid_b.bar_time(math.ceil(grid_b.bar_at(0.0) - 1e-9)))
                start = snapped
            return round(float(start), 3)
        return None
    except Exception:
        return None


def vocal_overlap(plan_a_start_s, length_s, tempo_ratio_b, b_start_s, a_vocal, b_vocal) -> float:
    """Fracción (0 a 1) de la mezcla en que las dos canciones tienen voz (actividad estimada de `VOCAL_ON` o más; ver
    `vocal_activity`, que es una aproximación). 0.0 si faltan datos."""
    try:
        length = float(length_s)
        if not (length > 0) or not a_vocal or not b_vocal:
            return 0.0
        ratio = float(tempo_ratio_b or 1.0)
        ratio = ratio if ratio > 0 else 1.0
        a0, b0 = float(plan_a_start_s), float(b_start_s)
        steps = max(1, int(round(length / STEP_S)))
        both = 0
        for k in range(steps):
            u = (k + 0.5) * length / steps
            ia, ib = int(math.floor(a0 + u)), int(math.floor(b0 + u * ratio))
            va = float(a_vocal[ia]) if 0 <= ia < len(a_vocal) else 0.0
            vb = float(b_vocal[ib]) if 0 <= ib < len(b_vocal) else 0.0
            both += va >= VOCAL_ON and vb >= VOCAL_ON
        return round(both / steps, 3)
    except Exception:
        return 0.0


# ------------------------------------------------------------------ guardar
def to_json(result) -> str:
    """Texto JSON compacto del resultado de `analyse` (con la versión del cálculo), para guardarlo en el índice."""
    try:
        data = {"v": VERSION}
        for key in ("energy", "bass", "vocal"):
            data[key] = [round(float(v), 3) for v in (result or {}).get(key) or []]
        data["events"] = [{"t": round(float(ev["t"]), 3), "type": str(ev["type"]),
                           "end": None if ev.get("end") is None else round(float(ev["end"]), 3),
                           "strength": round(float(ev.get("strength") or 0.0), 3)} for ev in (result or {}).get("events") or []]
        data["sections"] = [{"start": round(float(s["start"]), 3), "end": round(float(s["end"]), 3), "kind": str(s["kind"])}
                            for s in (result or {}).get("sections") or []]
        return json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        return json.dumps({"v": VERSION, **empty()}, separators=(",", ":"))


def from_json(text):
    """El resultado guardado con `to_json`, o None si el texto no vale o es de otra versión del cálculo."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("v") != VERSION:
            return None
        out = empty()
        for key in ("energy", "bass", "vocal"):
            out[key] = [float(v) for v in data.get(key) or []]
        out["events"] = [{"t": float(ev["t"]), "type": ev["type"], "end": None if ev.get("end") is None else float(ev["end"]),
                          "strength": float(ev.get("strength") or 0.0)} for ev in data.get("events") or []
                         if ev.get("type") in KINDS_EVENT]
        out["sections"] = [{"start": float(s["start"]), "end": float(s["end"]), "kind": s["kind"]}
                           for s in data.get("sections") or [] if s.get("kind") in KINDS_SECTION]
        return out
    except Exception:
        return None
