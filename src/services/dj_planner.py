"""Orden inteligente de las canciones del modo DJ.

Como hace un DJ, primero se decide **qué nivel de energía toca** en ese momento de la sesión (la curva de fiesta: calentar,
subir, pico, respiro y volver a subir) y se buscan las canciones de ese nivel (±0,2 de su posición de energía) que **se puedan
mezclar** con la anterior: que `mix_planner` no corte por tempo (como mucho ±8 %, contando la mitad y el doble como el mismo
ritmo; con un tempo desconocido también se mezcla) y de otro artista. Si no hay ninguna, se van aceptando peores, por escalones
(ver `_TIER_OF`): la ventana de energía ensanchada a ±0,35 antes que un salto de tempo imposible; un corte por tempo con otro
artista antes que repetir artista; y, al final, la mejor de todas (si hay que cortar, la de menor salto de tempo). Dentro de un
escalón, la siguiente se elige por, cada una de 0 a 1 (0,5 si no se sabe):
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

Primero es un algoritmo voraz (la mejor siguiente en cada paso), que se mete en callejones sin salida: las canciones fuertes
quedan para el final y, si sus tempos no casan entre sí, cada salto es un corte. Por eso después hay un **repaso** (`_polish`): prueba
a intercambiar canciones, dar la vuelta a tramos cortos o mover una canción unos puestos, y se queda con el cambio si no sube el
coste (cortes por tempo, artista repetido, tono, género, tempo y lo lejos que queda cada canción de la energía que pide su puesto,
con un margen libre). Así salen «familias de tempo» (rampas suaves de 85 a 110 BPM, por ejemplo) sin romper la curva.

Para que una biblioteca enorme se ordene en una fracción de segundo (se hace en el hilo de la interfaz): en cada paso se mira
solo una muestra al azar de las canciones que quedan, solo se ordenan las primeras 400 (el resto va detrás, al azar), el repaso
tiene un tope de intentos y la curva de energía se repite cada 80 canciones, que es más o menos una noche, en vez de estirarse
por toda la biblioteca. Sin Qt ni numpy: son listas de datos."""
import bisect
import math
import random
from collections import namedtuple

from services import camelot, mix_planner

# ref es lo que se devuelve ordenado (la ficha de la canción); el resto son los datos con los que se decide el orden
Track = namedtuple("Track", "ref bpm tone tone_conf energy genre artist")

# Curva de energía de una sesión de fiesta (progreso 0 a 1, energía 0 a 1): calentar, subir, pico, respiro y volver a subir
PARTY_CURVE = ((0.0, 0.30), (0.12, 0.45), (0.35, 0.75), (0.55, 0.92), (0.70, 0.60), (0.82, 0.85), (1.0, 0.95))

W_ENERGY, W_BPM, W_KEY, W_GENRE = 0.20, 0.35, 0.30, 0.10
ENERGY_WINDOW = 0.2             # diferencia de posición de energía (0 a 1) que todavía cuenta como «el nivel que toca»
NOISE = 0.30                    # azar que se suma a cada puntuación (el repaso final ya corrige lo que estropee)
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
WIDE_WINDOW = 0.35              # hasta dónde se ensancha el nivel de energía para encontrar una que se pueda mezclar
# escalón de cada candidata según (nivel de energía: 0 en la ventana, 1 en la ancha, 2 fuera; se puede mezclar; repite artista);
# gana la mejor del escalón más bajo que tenga alguna, y lo que no está en la tabla va al último (la mejor de todas)
_TIER_OF = {(0, True, False): 0, (1, True, False): 1, (0, False, False): 2, (0, True, True): 3, (0, False, True): 4,
            (1, True, True): 5}
_TIERS = 7
JUMP_PENALTY = 0.5              # si hay que cortar por tempo, castigo por cada unidad de salto (en logaritmo): mejor uno pequeño
# repaso (`_polish`): coste de cada salto (un corte por tempo, repetir artista, cambio de tempo dentro del ±8 % (0,2 en el
# borde), tono que choca, otro género) y de cada puesto (energía fuera de su sitio más allá del margen, al cuadrado: mejor
# muchas un poco fuera que una muy fuera); intentos por canción y tope total, y largo de los tramos que se mueven
COST_CUT, COST_REPEAT, COST_TEMPO, COST_KEY, COST_GENRE = 1.5, 1.0, 0.2, 0.3, 0.1
COST_ENERGY, ENERGY_SLACK = 15.0, 0.1
POLISH_TRIES, POLISH_BUDGET, NEAR_SWAP = 60, 8000, 4
_LN2 = math.log(2.0)
# cambio de tempo (en logaritmo, ver `tempo_step`) que `mix_planner` todavía mezcla: su ±8 % aplicado a la que entra
_STEP_UP, _STEP_DOWN = math.log(1.0 + mix_planner.MAX_TEMPO_CHANGE), -math.log(1.0 - mix_planner.MAX_TEMPO_CHANGE)


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


def tempo_step(a, b):
    """Cambio de tempo de `a` a `b` en logaritmo (con signo: positivo si `b` es más rápida), contando la mitad y el doble de
    `b` como su mismo ritmo (igual que `mix_planner.tempo_ratio`), o None si falta alguno."""
    if not a or not b or a <= 0 or b <= 0:
        return None
    step = math.log(b / a)
    return min((step, step - _LN2, step + _LN2), key=abs)


def _fit_of_step(step) -> float:
    if step is None:
        return NEUTRAL
    return min(1.0, max(0.0, 1.0 - (abs(step) - BPM_GOOD) / (BPM_BAD - BPM_GOOD)))


def bpm_fit(a, b) -> float:
    """1 si los tempos casi coinciden (contando la mitad y el doble), 0 si están a más de un 12 %, 0,5 si falta alguno."""
    return _fit_of_step(tempo_step(a, b))


def mixable(a, b) -> bool:
    """Si `mix_planner` mezclaría estos dos tempos (cambio de ±8 % como mucho, con la mitad y el doble) en vez de cortar.
    Con algún tempo desconocido, sí (el planificador de mezclas mezcla sin igualar el ritmo)."""
    step = tempo_step(a, b)
    return step is None or -_STEP_UP <= step <= _STEP_DOWN


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


def _score(previous, candidate, target, rank, recent, rng, step=None) -> float:
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
    score = (W_ENERGY * energy_fit + W_BPM * _fit_of_step(step) + W_KEY * key_fit(previous, candidate)
             + W_GENRE * genre_fit(previous.genre, candidate.genre))
    artist = _artist(candidate.artist)
    if artist:
        if recent and artist == recent[-1]:
            score -= SAME_ARTIST_NOW
        elif artist in recent:
            score -= SAME_ARTIST_RECENT
    return score + rng.random() * NOISE


def _tier(distance, ok, repeated) -> int:
    """Escalón (0 el mejor) de una candidata: lo lejos que está de la energía que toca, si se puede mezclar y si repite artista."""
    band = 0 if distance <= ENERGY_WINDOW else 1 if distance <= WIDE_WINDOW else 2
    return _TIER_OF.get((band, ok, repeated), _TIERS - 1)


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
    pool_rank = energy_ranker([t.energy for t in (energy_pool if energy_pool is not None and not dynamic else remaining)])
    wanted = target_ranks(start_index, positions, total)           # la energía que pide cada puesto, como posición 0 a 1
    if dynamic:
        energies = sorted(t.energy for t in remaining if t.energy is not None)
        targets = sorted(raw)
    else:
        rank = pool_rank
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
        # la mejor de cada escalón (ver `_tier`); gana la del escalón más bajo que tenga alguna
        tier_best, tier_score = [-1] * _TIERS, [-1e9] * _TIERS
        last_artist = recent[-1] if recent else ""
        for i in indexes:
            candidate = remaining[i]
            change = tempo_step(current.bpm, candidate.bpm) if current is not None else None
            score = _score(current, candidate, target, rank, recent, rng, change)
            energy = rank(candidate.energy)
            distance = 0.0 if energy is None else abs(energy - target)
            artist = _artist(candidate.artist)
            repeated = bool(artist and artist == last_artist)
            ok = change is None or -_STEP_UP <= change <= _STEP_DOWN
            tier = _tier(distance, ok, repeated)
            if not ok:
                score -= JUMP_PENALTY * abs(change)      # si hay que cortar, mejor un salto pequeño
            if score > tier_score[tier]:
                tier_best[tier], tier_score[tier] = i, score
        best = next(i for i in tier_best if i >= 0)
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
    ordered = _polish(ordered, previous, wanted, pool_rank, rng)
    rng.shuffle(remaining)
    return ordered + remaining


def _polish(ordered, previous, wanted, rank, rng) -> list:
    """Repaso del orden voraz: prueba a intercambiar canciones (al azar, sobre todo vecinas) y se queda con el cambio si el
    coste total no sube. El coste de cada salto: un corte por tempo (lo que `mix_planner` no mezcla), repetir artista, lo que
    cambia el tempo aunque se pueda mezclar, el tono y el género; y el de cada puesto, lo lejos que queda su energía de la que
    pide la curva (con un margen libre). Así se arreglan los callejones sin salida del voraz (la última canción fuerte que
    no encaja en tempo con ninguna) sin romper la curva."""
    n = len(ordered)
    if n < 3:
        return ordered
    items = ([previous] if previous is not None else []) + list(ordered)
    fixed = len(items) - n                       # la que suena (si la hay) no se mueve
    logs = [math.log(t.bpm) if t.bpm else None for t in items]
    artists = [_artist(t.artist) for t in items]
    genres = [_genre(t.genre) for t in items]
    energies = [rank(t.energy) for t in items]
    size = len(items)
    cache = {}

    def link(a, b):
        key = a * size + b
        cost = cache.get(key)
        if cost is None:
            cost = COST_KEY * (1.0 - key_fit(items[a], items[b]))
            if logs[a] is not None and logs[b] is not None:
                change = logs[b] - logs[a]
                change = min((change, change - _LN2, change + _LN2), key=abs)
                cost += COST_TEMPO * abs(change) / _STEP_UP if -_STEP_UP <= change <= _STEP_DOWN else COST_CUT
            else:                                # se mezcla, pero sin igualar el ritmo: ni bien ni mal (no es un comodín)
                cost += COST_CUT * NEUTRAL
            if artists[a] and artists[a] == artists[b]:
                cost += COST_REPEAT
            if genres[a] and genres[b] and genres[a] != genres[b]:
                cost += COST_GENRE
            cache[key] = cost
        return cost

    def spot(position, item):
        energy = energies[item]
        if energy is None:
            return 0.0
        return COST_ENERGY * max(0.0, abs(energy - wanted[position - fixed]) - ENERGY_SLACK) ** 2

    def stretch(i, j):
        """Coste de los puestos i..j y de los saltos que los tocan."""
        return (sum(link(seq[k - 1], seq[k]) for k in range(max(1, i), min(size, j + 2)))
                + sum(spot(p, seq[p]) for p in range(i, j + 1)))

    seq = list(range(size))
    for _ in range(min(POLISH_TRIES * n, POLISH_BUDGET)):
        i = rng.randrange(fixed, size)
        move = rng.random()
        if move < 0.5:                           # intercambiar dos (cualquiera): solo cambian sus saltos y sus puestos
            j = rng.randrange(fixed, size)
            if i == j:
                continue
            i, j = min(i, j), max(i, j)
            links = {k for k in (i, i + 1, j, j + 1) if 1 <= k < size}
            before = sum(link(seq[k - 1], seq[k]) for k in links) + spot(i, seq[i]) + spot(j, seq[j])
            seq[i], seq[j] = seq[j], seq[i]
            after = sum(link(seq[k - 1], seq[k]) for k in links) + spot(i, seq[i]) + spot(j, seq[j])
            if after > before + 1e-12:
                seq[i], seq[j] = seq[j], seq[i]
            continue
        j = i + rng.randint(1, NEAR_SWAP)        # un tramo corto: darle la vuelta o mover una canción dentro de él
        if j >= size:
            continue
        old = seq[i:j + 1]
        before = stretch(i, j)
        if move < 0.75:
            seq[i:j + 1] = old[::-1]
        elif move < 0.875:
            seq[i:j + 1] = old[1:] + old[:1]
        else:
            seq[i:j + 1] = old[-1:] + old[:-1]
        if stretch(i, j) > before + 1e-12:
            seq[i:j + 1] = old
    return [items[k] for k in seq[fixed:]]


RETARGET_SHIFT = 0.30           # «más / menos energía»: cuánto se mueve la posición de energía pedida respecto a la que suena
RETARGET_RAMP = 3               # canciones en las que se llega a esa energía (subida o bajada gradual, no de golpe)
RETARGET_HORIZON = 12           # canciones que se reordenan (unos 40 minutos); las demás siguen en el orden que tenían
RETARGET_WEIGHT = 0.6           # peso extra de la energía pedida (si no, el azar de `_score` la tapa dentro del mismo escalón)


def retarget(tracks, current, direction: int, rng=None, horizon: int = RETARGET_HORIZON, shift: float = RETARGET_SHIFT,
             ramp: int = RETARGET_RAMP) -> list:
    """«Más energía» (`direction` > 0) o «menos energía» (< 0) en plena sesión: las canciones de `tracks` (lo que queda, lista de
    `Track`, en el orden de ahora) reordenadas para que las próximas `horizon` suban (o bajen) de energía respecto a `current`
    (la que suena, o la que ya está preparada para sonar después y no se puede cambiar).

    La energía que se pide sale de la posición de `current` entre todas (la que suena y las que quedan): se desplaza `shift`
    hacia arriba o hacia abajo y se llega a ella en `ramp` canciones; luego se mantiene. Cada puesto se elige como en `plan`
    (los mismos escalones: primero las que se pueden mezclar sin cortar por tempo y de otro artista, y entre ellas por tempo,
    tono, género y energía), con dos cambios para que lo pedido se note: la energía pesa `RETARGET_WEIGHT` más, y una canción
    que va al revés (más suave que la actual cuando se pide más) no entra en el primer escalón. Aquí no se pasa el repaso de `plan` (`_polish`): cambia energía por tono y aquí lo que se ha pedido
    es la energía; los escalones ya evitan los cortes por tempo mientras haya alguna que se pueda mezclar. Las canciones sin
    energía conocida van detrás de las que sí la tienen (no se sabe si suben o bajan). Lo que no entra en las `horizon`
    primeras se queda en su orden de antes, detrás. Con `direction` 0, sin canciones o sin `current`, devuelve la lista tal
    cual (copia). No cambia nada de `plan`: es una función aparte."""
    remaining = [_clean(t) for t in tracks]
    if not remaining or not direction or current is None:
        return list(tracks)
    current = _clean(current)
    rng = rng or random.Random()
    sign = 1 if direction > 0 else -1
    rank = energy_ranker([current.energy] + [t.energy for t in remaining])
    start = rank(current.energy)
    if start is None:
        start = NEUTRAL
    goal = min(1.0, max(0.0, start + sign * shift))
    count = min(len(remaining), max(1, int(horizon)))
    steps = max(1, int(ramp))
    wanted = [start + (goal - start) * min(1.0, (i + 1) / steps) for i in range(count)]
    order = {id(t): i for i, t in enumerate(remaining)}        # para devolver el resto en su orden de antes
    pool = list(remaining)
    ordered = []
    previous = current
    recent = [_artist(current.artist)]
    for target in wanted:
        tier_best, tier_score = [-1] * _TIERS, [-1e9] * _TIERS
        last_artist = recent[-1] if recent else ""
        for i, candidate in enumerate(pool):
            change = tempo_step(previous.bpm, candidate.bpm)
            score = _score(previous, candidate, target, rank, recent, rng, change)
            energy = rank(candidate.energy)
            if energy is None:
                distance = WIDE_WINDOW + 0.01
            else:
                distance = abs(energy - target)
                if sign * (energy - start) < 0:          # va al revés de lo pedido: como mucho, en la ventana ancha
                    distance = max(distance, ENERGY_WINDOW + 0.001)
                score += RETARGET_WEIGHT * (1.0 - min(1.0, distance / 0.5))
            artist = _artist(candidate.artist)
            ok = change is None or -_STEP_UP <= change <= _STEP_DOWN
            tier = _tier(distance, ok, bool(artist and artist == last_artist))
            if not ok:
                score -= JUMP_PENALTY * abs(change)
            if score > tier_score[tier]:
                tier_best[tier], tier_score[tier] = i, score
        best = next(i for i in tier_best if i >= 0)
        chosen = pool.pop(best)
        ordered.append(chosen)
        previous = chosen
        recent = (recent + [_artist(chosen.artist)])[-RECENT_ARTISTS:]
    pool.sort(key=lambda t: order[id(t)])
    return ordered + pool


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
