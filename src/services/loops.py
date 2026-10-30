"""Bucles del modo DJ (fase 21): repetir 4 u 8 compases de una canción para alargar una parte buena o para que la mezcla caiga
en su sitio (en un comienzo de frase de 8 compases, o cuando la que entra ya tiene su intro hecha).

Funciones puras sobre arrays de numpy (n, 2), float32, a 44.100 Hz (`mix_types.SAMPLE_RATE`); un array de una dimensión (n,)
también vale. Sin Qt. numpy se carga solo cuando hace falta (`key_detect._numpy()`).

Cómo se repite sin clic y sin cambiar la duración (`repeat`):
  Entre dos repeticiones el final de la región salta al principio de la región, y casi nunca coinciden (el audio no es
  exactamente periódico): ese escalón de valor es el clic. Se quita repartiendo el escalón entre los dos lados de la unión
  con una curva suave (medio coseno) de `crossfade_ms` (3 ms por defecto) en total, centrada en la unión: el final de la
  región sube hasta el valor medio entre su última muestra y la primera, y el principio baja desde ese mismo valor hasta
  su propio valor. Es un fundido del escalón y no del audio: la señal se queda como estaba y la potencia no cambia.
  Se descartó el fundido de potencia constante entre dos copias porque no hay dos copias: lo que seguiría al final de la
  región y lo que precedería a su principio no existe en `repeat`. Rellenarlo con el espejo de la propia región hace que una
  señal que ya engancha sola (un seno que acaba en 0) se cancele en la unión (probado: -6 dB de potencia), y un fundido con
  solape gasta muestras (cada repetición saldría `crossfade` más corta y los golpes se irían adelantando 3 ms por compás).
  Resultado:
    * Longitud EXACTA: `times * len(region)`. El periodo es exactamente el de la región.
    * Si la región ya engancha consigo misma, no se toca nada (el escalón es 0).
    * Solo cambian los ~3 ms que rodean cada unión interior; el principio de la primera repetición y el final de la última
      NO se tocan, así que el bucle empalma sin saltos con el audio original por los dos lados si sale de él (`extend_body`).

Cómo se coloca un bucle en la canción (`extend_body`) y qué debe hacer el motor:
  La mezcla iba a empezar en el instante M (`mix_start_s`). Se toman los `loop_bars` compases justo antes de M, [L, M), y se
  repiten hasta que sumen `loop_bars + extra_bars` compases: sonará la región original una vez más `extra_bars / loop_bars`
  veces, y la mezcla empieza después, en el compás `extra_bars` posterior (`new_mix_start_s`). La mezcla en sí NO cambia: se
  sigue renderizando con el audio de A desde M (`a.data[M:M + n]`) y con el mismo plan; solo se retrasa en el tiempo de salida.
  El motor debe encolar, en este orden:
      cuerpo normal de A hasta la muestra L (`loop_start_frame`)  ->  los segmentos de `extend_body`  ->  la mezcla desde M
  Los segmentos empalman sin saltos con `data[L - 1]` por delante y con `data[M]` por detrás (la primera y la última muestra
  de los segmentos son las del audio original), y suman `(loop_bars + extra_bars) / loop_bars * len(region)` muestras. La
  duración total de A en la sesión crece en `extra_bars` compases."""
import math

from services import key_detect
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid

ZERO_CROSS_S = 0.002            # `loop_region` mueve el comienzo hasta 2 ms para empezar en un cruce por cero
MIN_CONFIDENCE = 0.4            # por debajo, la rejilla no es fiable y no se hacen bucles
PHRASE_BARS = 8                 # una frase: la mezcla debe caer en un múltiplo de 8 compases de A
LOOP_CHOICES = (4, 8)           # compases extra posibles
ON_BAR_TOL = 0.05               # una mezcla a menos de 0,05 compases de un comienzo de compás cuenta como cuadrada
INTRO_TOL_BARS = 1.0            # la intro de B "no está lista" si le falta al menos un compás de B al acabar la mezcla


def _np():
    np = key_detect._numpy()
    if np is None:
        raise RuntimeError("loops necesita numpy")
    return np


def _empty(np, data):
    shape = (0, data.shape[1]) if getattr(data, "ndim", 0) == 2 else (0,)
    return np.zeros(shape, dtype=getattr(data, "dtype", np.float32))


def _valid_grid(grid) -> bool:
    return (isinstance(grid, BeatGrid) and isinstance(grid.bpm, (int, float)) and math.isfinite(grid.bpm) and grid.bpm > 0
            and isinstance(grid.beats_per_bar, int) and grid.beats_per_bar >= 1 and math.isfinite(grid.first_beat_s))


def _audio_ok(data) -> bool:
    return getattr(data, "ndim", 0) in (1, 2) and len(data) > 0


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _bar_frames(grid: BeatGrid, bars: int, sample_rate: int) -> int:
    return max(1, round(bars * grid.bar_s * sample_rate))


def _snap_zero_cross(np, data, frame: int, length: int, sample_rate: int) -> int:
    """Muestra `frame` movida (hasta ZERO_CROSS_S) al cruce por cero más cercano si con eso la señal queda más cerca de 0
    (y el trozo `length` sigue dentro del array). Se mira la media de los canales."""
    reach = round(ZERO_CROSS_S * sample_rate)
    lo, hi = max(0, frame - reach), min(len(data) - length, frame + reach)
    if hi < lo:
        return frame
    seg = data[max(0, lo - 1):hi + 2]
    m = seg.mean(axis=1) if seg.ndim == 2 else seg
    m = m.astype(np.float64)
    base = max(0, lo - 1)
    sign = np.signbit(m)
    cross = np.where(sign[:-1] != sign[1:])[0]          # el cruce está entre cross[i] y cross[i] + 1
    if len(cross) == 0:
        return frame
    # de cada par se queda la muestra más cercana a cero
    cand = np.where(np.abs(m[cross]) <= np.abs(m[cross + 1]), cross, cross + 1) + base
    cand = cand[(cand >= lo) & (cand <= hi)]
    if len(cand) == 0:
        return frame
    best = int(cand[np.argmin(np.abs(cand - frame))])
    cur = abs(float(data[frame].mean() if data.ndim == 2 else data[frame]))
    new = abs(float(data[best].mean() if data.ndim == 2 else data[best]))
    return best if new < cur else frame


def loop_region(data, grid, start_s, bars, sample_rate=SAMPLE_RATE):
    """Región de `bars` compases enteros que empieza en el comienzo de compás más cercano a `start_s`.

    Devuelve `(array, start_frame, end_frame)`: `array = data[start_frame:end_frame]` (una vista, no la modifiques) y los
    índices en muestras del array original. La longitud es siempre `round(bars * bar_s * sample_rate)`. El comienzo se mueve
    hasta 2 ms al cruce por cero más cercano si así empieza más cerca de 0 (el final no se toca: la región no se acorta ni se
    alarga); por eso `start_frame` puede apartarse del compás hasta 2 ms.
    Si el compás más cercano no deja sitio (antes del principio o pasado el final), se usa el más cercano que sí cabe. Si la
    región entera no cabe en `data`, o faltan datos (sin audio, sin rejilla válida, `bars` < 1), devuelve `(vacío, 0, 0)`;
    nunca lanza excepciones por datos malos."""
    np = _np()
    if not _audio_ok(data) or not _valid_grid(grid) or not isinstance(bars, int) or isinstance(bars, bool) or bars < 1:
        return _empty(np, data if _audio_ok(data) else np.zeros((0, 2), np.float32)), 0, 0
    start_s = _number(start_s)
    n = _bar_frames(grid, bars, sample_rate)
    if start_s is None or n > len(data):
        return _empty(np, data), 0, 0
    idx = round(grid.bar_at(start_s))
    # compases cuyo comienzo (redondeado a muestra) deja la región dentro del array
    first = math.ceil(grid.bar_at(0.0) - 1e-9)
    while round(grid.bar_time(first) * sample_rate) < 0:
        first += 1
    last = math.floor(grid.bar_at((len(data) - n) / sample_rate) + 1e-9)
    while last >= first and round(grid.bar_time(last) * sample_rate) + n > len(data):
        last -= 1
    if last < first:
        return _empty(np, data), 0, 0
    idx = min(max(idx, first), last)
    start = round(grid.bar_time(idx) * sample_rate)
    start = _snap_zero_cross(np, data, start, n, sample_rate)
    return data[start:start + n], start, start + n


def _seam(np, region, h: int):
    """Los 2h fotogramas que sustituyen a los que rodean una unión (h antes y h después): el escalón de valor entre el final
    y el principio de la región repartido por mitades con curvas de medio coseno (ver la explicación del módulo)."""
    n = len(region)
    r = region.astype(np.float64)
    d = r[0] - r[n - 1]                                                 # escalón de la unión (por canal)
    m = np.arange(h)
    shape = (h,) + (1,) * (r.ndim - 1)
    up = ((1.0 - np.cos(math.pi * (m + 1) / h)) / 2.0).reshape(shape)  # 0 a 1 hacia la unión
    down = ((1.0 + np.cos(math.pi * m / h)) / 2.0).reshape(shape)      # 1 a 0 desde la unión
    left = r[n - h:] + d / 2.0 * up                                     # el final sube hasta el valor medio
    right = r[:h] - d / 2.0 * down                                      # el principio baja desde ese mismo valor
    return np.concatenate([left, right], axis=0)


def _tile(np, region, times: int, crossfade_ms: float, sample_rate: int):
    n = len(region)
    out = np.concatenate([region] * times, axis=0) if times > 1 else region.copy()
    cf = _number(crossfade_ms) or 0.0
    h = min(round(max(cf, 0.0) * sample_rate / 1000.0) // 2, n // 4)
    if times > 1 and h >= 1:
        zone = _seam(np, region, h).astype(out.dtype)
        for k in range(1, times):
            out[k * n - h:k * n + h] = zone
    return out


def repeat(region, times, crossfade_ms=3.0, sample_rate=SAMPLE_RATE):
    """`region` repetida `times` veces seguidas, sin clic y con la duración EXACTA `times * len(region)`.

    Las uniones interiores llevan un micro fundido del escalón de `crossfade_ms` centrado en la unión, sin gastar muestras
    (ver la explicación del módulo); el principio y el final del resultado son los de `region`, sin tocar. Con
    `crossfade_ms` = 0 es una repetición a pelo. `times` < 1 o una región vacía dan un array vacío. Siempre devuelve una
    copia (nunca una vista de `region`)."""
    np = _np()
    if not _audio_ok(region):
        return _empty(np, region if hasattr(region, "ndim") and hasattr(region, "dtype") else np.zeros((0, 2), np.float32))
    if not isinstance(times, int) or isinstance(times, bool) or times < 1:
        return _empty(np, region)
    return _tile(np, region, times, crossfade_ms, sample_rate)


def _divisor_at_most(extra_bars: int, loop_bars: int) -> int:
    for d in range(min(loop_bars, extra_bars), 0, -1):
        if extra_bars % d == 0:
            return d
    return 1


def extend_body(data, grid, mix_start_s, extra_bars, loop_bars=4, sample_rate=SAMPLE_RATE):
    """Alarga el cuerpo de una canción `extra_bars` compases repitiendo los `loop_bars` compases justo antes de la mezcla.

    Devuelve `(segments, new_mix_start_s)`:
      * `segments`: lista de arrays (n, 2), uno por repetición (cada uno de `loop_bars` compases, vistas de un mismo array), en
        el orden en que suenan. Juntos suman `(loop_bars + extra_bars) / loop_bars` regiones y empalman sin saltos con
        `data[L - 1]` antes y con `data[M]` después, siendo M = `round(mix_start_s * sample_rate)` y L = M menos la longitud
        de la región. Aquí no se mueve nada al cruce por cero: los dos empalmes son con el audio original, tal cual.
      * `new_mix_start_s` = `mix_start_s + extra_bars * bar_s`: el instante de la mezcla en la línea de tiempo alargada. La
        mezcla se renderiza igual que antes (con `data` desde M); solo se retrasa. Si `mix_start_s` cae en un comienzo de
        compás (lo normal con el plan por frases), el nuevo también, y es un comienzo de frase de 8 cuando el de antes estaba
        a 4 compases de uno.
    Cómo debe encolarlo el motor: cuerpo normal de A hasta la muestra L = M - len(segments[0]), luego estos segmentos, luego
    la mezcla desde M (más detalles en la explicación del módulo).
    `extra_bars` debe ser un entero positivo; si no es múltiplo de `loop_bars` se usa el mayor divisor suyo no mayor que
    `loop_bars`, y si no caben tantos compases antes de M (L < 0) se prueba con una región más corta (si divide a
    `extra_bars`). Con datos malos (sin audio, sin rejilla, M fuera del audio, `extra_bars` no válido) devuelve
    `([], mix_start_s)`: no hay nada que alargar y el motor sigue como estaba. Nunca lanza excepciones por datos malos."""
    np = _np()
    mix = _number(mix_start_s)
    nothing = ([], mix_start_s)
    if (not _audio_ok(data) or not _valid_grid(grid) or mix is None or mix < 0 or isinstance(extra_bars, bool)
            or not isinstance(extra_bars, int) or extra_bars < 1 or isinstance(loop_bars, bool)
            or not isinstance(loop_bars, int) or loop_bars < 1):
        return nothing
    m_frame = round(mix * sample_rate)
    if m_frame > len(data):
        return nothing
    lb = _divisor_at_most(extra_bars, loop_bars)
    n = _bar_frames(grid, lb, sample_rate)
    while m_frame - n < 0 and lb > 1:
        lb = _divisor_at_most(extra_bars, lb - 1)
        n = _bar_frames(grid, lb, sample_rate)
    if m_frame - n < 0:
        return nothing
    region = data[m_frame - n:m_frame]
    times = 1 + extra_bars // lb
    out = _tile(np, region, times, 3.0, sample_rate)
    segments = [out[i * n:(i + 1) * n] for i in range(times)]
    return segments, mix + extra_bars * grid.bar_s


def needs_loop(a_info, b_info, plan, grid_a, grid_b):
    """Cuántos compases extra (0, 4 u 8) conviene añadir antes de la mezcla: `(bars, motivo)`.

    Devuelve 0 siempre que: falte plan o fichas, falte la rejilla de A o de B o alguna tenga `confidence` < 0,4, el plan sea
    un corte limpio, no se sepa la duración de A, la mezcla no caiga en un comienzo de compás de A, o los compases extra no
    quepan (`a_start_s + extra * bar_s + length_s` debe ser <= duración de A).
    Con rejilla fiable, se añaden compases por dos motivos:
      * Frase: la mezcla cae en el compás n de A (contando desde la rejilla). Si n no es múltiplo de 8 y n + 4 sí, se añaden 4
        (con otros restos, 4 u 8 compases no la dejarían en su sitio y no se hace nada por este motivo).
      * Intro de B: la que entra llega a su cuerpo en `b_start_s + length_s * tempo_ratio_b` (en su tiempo). Si su `intro_s`
        acaba al menos un compás suyo después, su intro no está lista: se piden 4 compases extra si le faltan hasta 4
        compases de A (en tiempo de salida) y 8 si le faltan más. Para no descuadrar la frase, si A ya estaba en un comienzo de
        frase se pide 8 en vez de 4 (8 compases la mantienen). OJO: este motivo solo retrasa la mezcla; la que entra se
        mezcla con el mismo `b_start_s`. Si quien lo use quiere que B llegue de verdad más tarde a su cuerpo, debe
        recalcular `b_start_s` (esta función no lo toca).
    Si se cumplen los dos se elige el menor número que sirve a ambos (4 si A está a 4 compases de una frase y a B le faltan
    hasta 4 compases; 8 si a B le faltan más). Si lo que se pide no cabe en A, se prueba con 4 solo si con 4 se cumple lo que
    se buscaba; si no, 0 con el motivo de falta de margen."""
    try:
        return _needs_loop(a_info, b_info, plan, grid_a, grid_b)
    except Exception as e:                              # una regla de ayuda nunca debe romper la mezcla
        return 0, f"sin bucle: no se pudo decidir ({type(e).__name__})"


def _needs_loop(a_info, b_info, plan, grid_a, grid_b):
    if plan is None or not hasattr(plan, "a_start_s") or not isinstance(a_info, dict) or not isinstance(b_info, dict):
        return 0, "sin bucle: faltan el plan o los datos de las canciones"
    if not _valid_grid(grid_a) or not _valid_grid(grid_b):
        return 0, "sin bucle: falta la rejilla de golpes de alguna de las dos canciones"
    low = min(grid_a.confidence, grid_b.confidence)
    if not isinstance(low, (int, float)) or not math.isfinite(low) or low < MIN_CONFIDENCE:
        return 0, f"sin bucle: la rejilla no es fiable (confianza {low:.2f}, mínimo {MIN_CONFIDENCE})"
    if plan.kind == KIND_CUT:
        return 0, "sin bucle: la transición es un corte limpio"
    a_start, length = _number(plan.a_start_s), _number(plan.length_s)
    duration = _number(a_info.get("duration_s"))
    if a_start is None or length is None or a_start < 0 or length < 0 or duration is None or duration <= 0:
        return 0, "sin bucle: no se sabe dónde acaba la canción o dónde empieza la mezcla"
    bar_f = grid_a.bar_at(a_start)
    bar = round(bar_f)
    if abs(bar_f - bar) > ON_BAR_TOL:
        return 0, "sin bucle: la mezcla no empieza en un comienzo de compás de la que suena"
    bar_s = grid_a.bar_s
    on_phrase = bar % PHRASE_BARS == 0

    # lo que se busca: compases mínimos que pide la intro de B y si se quiere llegar a un comienzo de frase
    intro_need = 0
    intro_txt = ""
    intro_b = _number(b_info.get("intro_s"))
    if intro_b is not None and intro_b > 0:
        ratio = _number(plan.tempo_ratio_b) or 1.0
        pending = intro_b - (_number(plan.b_start_s) or 0.0) - length * ratio       # segundos de B que le faltan de intro
        if pending >= INTRO_TOL_BARS * grid_b.bar_s:
            out_bars = pending / ratio / bar_s
            intro_need = 4 if out_bars <= 4 else 8
            intro_txt = f"a la que entra le faltan {pending:.1f} s de intro al acabar la mezcla"
    phrase_txt = ""
    phrase_fix = bar % PHRASE_BARS == PHRASE_BARS // 2
    if phrase_fix:
        phrase_txt = f"la mezcla cae en el compás {bar} y 4 compases más la dejan en un comienzo de frase de 8"

    if intro_need:
        wanted = intro_need
        if on_phrase:
            wanted = 8                                  # 8 compases mantienen el comienzo de frase
        elif phrase_fix and intro_need == 4:
            wanted = 4                                  # sirve a los dos
        options = [wanted] + ([4] if wanted == 8 and intro_need == 4 else [])
        why = intro_txt
        if phrase_fix and wanted == 4:
            why += "; y 4 compases la dejan en un comienzo de frase"
    elif phrase_fix:
        options = [4]
        why = phrase_txt
    else:
        if on_phrase:
            return 0, "sin bucle: la mezcla ya cae en un comienzo de frase y la intro de la que entra está lista"
        return 0, f"sin bucle: la mezcla cae en el compás {bar} y 4 u 8 compases no la dejarían en un comienzo de frase"

    for extra in options:
        if a_start + extra * bar_s + length <= duration + 1e-6:
            if extra != options[0]:
                why += f" (8 compases no caben en la canción, se dejan {extra})"
            return extra, f"bucle de {extra} compases: {why}"
    return 0, f"sin bucle: la canción no tiene margen para {options[-1]} compases extra más la mezcla ({why})"
