"""Orden inteligente de las canciones del modo DJ.

Como hace un DJ, primero se decide **qué nivel de energía toca** en ese momento de la sesión (la curva de fiesta: calentar,
subir, pico, respiro y volver a subir) y solo se consideran las canciones de ese nivel (±0,2 de su posición de energía), mejor si son de otro artista
que la anterior; si en el nivel solo quedan del mismo artista, se repite (la energía pesa más que el artista, y en una biblioteca
casi toda de un artista no hay otra opción); si en el nivel no queda ninguna, la mejor de todas. Entre ellas, la siguiente se elige por, cada una de 0 a 1 (0,5 si no se sabe):
  * ritmo (BPM): 1 si los tempos difieren menos de un 3 % (la mitad o el doble cuentan como el mismo), 0 si más de un 12 %;
  * tono: la compatibilidad en la rueda Camelot (ver `camelot.score`), atenuada si el tono es poco fiable;
  * género: el mismo género suma, otro resta un poco;
  * energía: lo cerca que está de lo que toca, y un pequeño castigo a los saltos bruscos respecto a la que suena.
Además se evita repetir el artista seguido, y un poco de azar hace que cada sesión salga distinta.
(Si la energía fuera un sumando más, ganarían siempre las que encajan en ritmo y tono aunque estén fuera de sitio en la curva.)

La energía se compara por **posición**, no en valor: cada canción pasa a un percentil entre las de la sesión (la más suave es 0 y
la más fuerte es 1), y cada puesto de la sesión pide el percentil que le toca según la propia curva (el puesto más tranquilo de la
curva pide la canción más suave, el del pico pide la más fuerte). Así da igual cómo estén de comprimidos los másteres de tu música,
y la curva se reparte igual que la energía de las canciones: si no, los picos agotarían las canciones fuertes y al final solo
quedarían las sobras. Cuando la sesión usa todas las canciones de la lista, además, esas posiciones se recalculan en cada paso con lo
que queda (los puestos que faltan frente a las canciones que faltan): así lo que se va gastando no deja al final solo sobras.

Es un algoritmo voraz (la mejor siguiente en cada paso), no el mejor orden posible. Para que una biblioteca enorme se ordene en una
fracción de segundo (se hace en el hilo de la interfaz): en cada paso se mira solo una muestra al azar de las canciones que quedan,
solo se ordenan las primeras 400 (el resto va detrás, al azar) y la curva de energía se repite cada 80 canciones, que es más o menos
una noche, en vez de estirarse por toda la biblioteca. Sin Qt ni numpy: son listas de datos."""
import bisect
import math
import random
from collections import namedtuple

from services import camelot

# ref es lo que se devuelve ordenado (la ficha de la canción); el resto son los datos con los que se decide el orden
Track = namedtuple("Track", "ref bpm tone tone_conf energy genre artist")

# Curva de energía de una sesión de fiesta (progreso 0 a 1, energía 0 a 1): calentar, subir, pico, respiro y volver a subir
PARTY_CURVE = ((0.0, 0.30), (0.12, 0.45), (0.35, 0.75), (0.55, 0.92), (0.70, 0.60), (0.82, 0.85), (1.0, 0.95))

W_ENERGY, W_BPM, W_KEY, W_GENRE = 0.20, 0.35, 0.30, 0.10
ENERGY_WINDOW = 0.2             # diferencia de posición de energía (0 a 1) que todavía cuenta como «el nivel que toca»
NOISE = 0.10                    # azar que se suma a cada puntuación
NEUTRAL = 0.5                   # lo que vale una medida que no se conoce
BPM_GOOD, BPM_BAD = 0.03, 0.12  # diferencia de tempo (en proporción) que vale 1 y la que vale 0
KEY_CONFIDENT = 0.6             # con esta confianza el tono pesa entero; con menos, se acerca a lo neutro
JUMP_FREE = 0.25                # saltos de energía que no se castigan
OTHER_GENRE = 0.3
SAME_ARTIST_NOW, SAME_ARTIST_RECENT = 0.5, 0.15
RECENT_ARTISTS = 3
SAMPLE_BUDGET = 60000           # puntuaciones máximas por paso aproximadas: el tamaño de la muestra baja si hay muchas canciones
MIN_SAMPLE, MAX_SAMPLE = 40, 150
PLAN_LIMIT = 400                # canciones que se ordenan; las demás van detrás, al azar
CURVE_SONGS = 80                # canciones que dura una vuelta de la curva de energía (una sesión: unas 4 horas)


def curve_progress(index: int, total: int) -> float:
    """Punto de la curva (0 a 1) que le toca a la canción número `index` de una sesión de `total`: la sesión entera si es de
    hasta 120 canciones, y si es más larga la curva da una vuelta cada 80."""
    span = max(1, total if total <= CURVE_SONGS * 3 // 2 else CURVE_SONGS)
    return (index % span) / max(1, span - 1)


def target_ranks(start_index: int, positions: int, total: int) -> list:
    """Para cada uno de los `positions` puestos que se van a rellenar (desde el `start_index` de una sesión de `total`), qué
    posición de energía (0 a 1) pide: la de ese puesto entre todos los puestos según la curva. Es la curva, pero medida en
    posiciones, para que pida la misma proporción de canciones suaves y fuertes que hay."""
    values = [target_energy(curve_progress(start_index + i, total)) for i in range(positions)]
    result = [0.5] * positions
    for place, index in enumerate(sorted(range(positions), key=values.__getitem__)):
        result[index] = (place + 0.5) / positions
    return result


def target_energy(progress: float, curve=PARTY_CURVE) -> float:
    """Energía que toca en ese punto de la sesión (progreso de 0 a 1), interpolando entre los puntos de la curva."""
    progress = min(1.0, max(0.0, progress))
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if progress <= x1:
            return y0 + (y1 - y0) * (progress - x0) / (x1 - x0) if x1 > x0 else y1
    return curve[-1][1]


def energy_ranker(values):
    """Función que pasa una energía a su posición (0 a 1) entre `values`. Con menos de 5 valores no hay posiciones que valgan:
    la energía se deja como está."""
    ordered = sorted(v for v in values if v is not None)
    if len(ordered) < 5:
        return lambda value: None if value is None else min(1.0, max(0.0, value))
    size = len(ordered)

    def rank(value):
        if value is None:
            return None
        return (bisect.bisect_left(ordered, value) + bisect.bisect_right(ordered, value)) / (2.0 * size)
    return rank


def _percentile(ordered, value):
    """Posición (0 a 1) de `value` entre los valores de `ordered` (una lista ya ordenada); 0,5 si no hay ninguno."""
    if value is None:
        return None
    if not ordered:
        return 0.5
    return (bisect.bisect_left(ordered, value) + bisect.bisect_right(ordered, value)) / (2.0 * len(ordered))


def _clean(track: Track) -> Track:
    """La misma ficha con el tempo y la energía a None si no son números finitos (por si llegan estropeados del análisis)."""
    bpm = track.bpm if isinstance(track.bpm, (int, float)) and math.isfinite(track.bpm) and track.bpm > 0 else None
    energy = track.energy if isinstance(track.energy, (int, float)) and math.isfinite(track.energy) else None
    return track if (bpm is track.bpm and energy is track.energy) else track._replace(bpm=bpm, energy=energy)


def bpm_fit(a, b) -> float:
    """1 si los tempos casi coinciden (contando la mitad y el doble), 0 si están a más de un 12 %, 0,5 si falta alguno."""
    if not a or not b or a <= 0 or b <= 0:
        return NEUTRAL
    ratio = b / a
    diff = min(abs(math.log(r)) for r in (ratio, ratio * 2.0, ratio / 2.0))
    return min(1.0, max(0.0, 1.0 - (diff - BPM_GOOD) / (BPM_BAD - BPM_GOOD)))


def key_fit(a: Track, b: Track) -> float:
    """Compatibilidad de tonos (rueda Camelot) llevada hacia lo neutro si alguno de los dos tonos es poco fiable."""
    if not a.tone or not b.tone:
        return NEUTRAL
    trust = min(1.0, min(a.tone_conf or 0.0, b.tone_conf or 0.0) / KEY_CONFIDENT)
    return NEUTRAL + (camelot.score(a.tone, b.tone) - NEUTRAL) * trust


def _genre(text) -> str:
    return str(text or "").lower().replace("/", ";").replace(",", ";").split(";")[0].strip()


def genre_fit(a, b) -> float:
    ga, gb = _genre(a), _genre(b)
    if not ga or not gb:
        return NEUTRAL
    return 1.0 if ga == gb else OTHER_GENRE


def _artist(text) -> str:
    return str(text or "").strip().lower()


def _score(previous, candidate, target, rank, recent, rng) -> float:
    energy = rank(candidate.energy)
    if energy is None:
        energy_fit = NEUTRAL
    else:
        fit = 1.0 - min(1.0, abs(energy - target) / 0.5)
        before = rank(previous.energy) if previous is not None else None
        if before is None:
            energy_fit = fit
        else:
            smooth = 1.0 - min(1.0, max(0.0, abs(energy - before) - JUMP_FREE) / 0.5)
            energy_fit = 0.7 * fit + 0.3 * smooth
    if previous is None:                        # la primera de la sesión: solo cuenta lo tranquila que arranca
        return energy_fit + rng.random() * NOISE
    score = (W_ENERGY * energy_fit + W_BPM * bpm_fit(previous.bpm, candidate.bpm) + W_KEY * key_fit(previous, candidate)
             + W_GENRE * genre_fit(previous.genre, candidate.genre))
    artist = _artist(candidate.artist)
    if artist:
        if recent and artist == recent[-1]:
            score -= SAME_ARTIST_NOW
        elif artist in recent:
            score -= SAME_ARTIST_RECENT
    return score + rng.random() * NOISE


def plan(tracks, previous=None, start_index: int = 0, total: int = None, rng=None, energy_pool=None,
         limit: int = PLAN_LIMIT) -> list:
    """Las canciones de `tracks` (lista de `Track`) en el orden en que conviene que suenen.

    `previous`: la que suena ahora (la primera de las nuevas se elige pensando en ella). `start_index` y `total`: dónde cae la
    primera de estas en toda la sesión y cuántas canciones tiene (para saber en qué punto de la curva de energía va). `rng`:
    un `random.Random` (con semilla, para que el resultado se repita). `energy_pool`: las canciones con las que se calcula la
    posición de cada energía cuando solo se ordena una parte de una lista más larga (por defecto, `tracks`; si se ordenan
    todas, la posición se calcula en cada paso con las que quedan y esto no se usa). `limit`: cuántas se ordenan (las demás
    van detrás, al azar)."""
    remaining = [_clean(t) for t in tracks]
    if not remaining:
        return []
    if previous is not None:
        previous = _clean(previous)
    rng = rng or random.Random()
    total = max(total or 0, start_index + len(remaining))
    positions = min(len(remaining), limit)
    raw = [target_energy(curve_progress(start_index + i, total)) for i in range(positions)]
    # Si se van a ordenar todas, las posiciones se recalculan en cada paso con lo que queda; si solo se ordena una parte de una
    # lista más larga (nunca se agotan), valen las del principio.
    dynamic = len(remaining) <= limit and sum(t.energy is not None for t in remaining) >= 5
    if dynamic:
        energies = sorted(t.energy for t in remaining if t.energy is not None)
        targets = sorted(raw)
    else:
        rank = energy_ranker([t.energy for t in (energy_pool if energy_pool is not None else remaining)])
        wanted = target_ranks(start_index, positions, total)       # la energía que pide cada puesto, como posición 0 a 1
    ordered = []
    current = previous
    recent = [_artist(previous.artist)] if previous is not None else []         # «» = artista desconocido (no cuenta como repetido)
    while remaining and len(ordered) < limit:
        step = len(ordered)
        if dynamic:
            rank = lambda value, pool=energies: _percentile(pool, value)          # noqa: E731
            target = _percentile(targets, raw[step])
        else:
            target = wanted[step]
        count = len(remaining)
        size = count if count <= MIN_SAMPLE else max(MIN_SAMPLE, min(MAX_SAMPLE, SAMPLE_BUDGET // count))
        indexes = range(count) if size >= count else rng.sample(range(count), size)
        best, best_score = -1, -1e9              # la mejor de todas
        level, level_score = -1, -1e9            # la mejor de las que están en el nivel de energía que toca y son de otro artista
        same, same_score = -1, -1e9              # ...y la mejor de ese nivel aunque sea del mismo artista
        for i in indexes:
            candidate = remaining[i]
            score = _score(current, candidate, target, rank, recent, rng)
            if score > best_score:
                best, best_score = i, score
            energy = rank(candidate.energy)
            if energy is None or abs(energy - target) <= ENERGY_WINDOW:
                if score > same_score:
                    same, same_score = i, score
                artist = _artist(candidate.artist)
                if not (artist and recent and artist == recent[-1]) and score > level_score:
                    level, level_score = i, score
        if level >= 0:
            best = level
        elif same >= 0:
            best = same
        chosen = remaining[best]
        remaining[best] = remaining[-1]
        remaining.pop()
        ordered.append(chosen)
        if dynamic:
            del targets[bisect.bisect_left(targets, raw[step])]
            if chosen.energy is not None:
                del energies[bisect.bisect_left(energies, chosen.energy)]
        current = chosen
        recent = (recent + [_artist(chosen.artist)])[-RECENT_ARTISTS:]
    rng.shuffle(remaining)
    return ordered + remaining


def transition_quality(ordered, previous=None) -> dict:
    """Cómo encajan de media los saltos de una lista: {«bpm», «key», «genre»} entre 0 y 1 (sirve para medir si un orden es
    mejor que otro; la energía no entra porque depende de la curva)."""
    sequence = ([previous] if previous is not None else []) + list(ordered)
    pairs = list(zip(sequence, sequence[1:]))
    if not pairs:
        return {"bpm": NEUTRAL, "key": NEUTRAL, "genre": NEUTRAL}
    return {"bpm": sum(bpm_fit(a.bpm, b.bpm) for a, b in pairs) / len(pairs),
            "key": sum(key_fit(a, b) for a, b in pairs) / len(pairs),
            "genre": sum(genre_fit(a.genre, b.genre) for a, b in pairs) / len(pairs)}
