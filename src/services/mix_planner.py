"""Planificador de mezclas por frases del modo DJ (fase 13): con la rejilla de golpes de las dos canciones, la mezcla
empieza en un comienzo de frase de la que suena (A), la que entra (B) arranca en un comienzo de frase suyo, el tempo de B
se ajusta al de A y el cambio de graves cae en un golpe hacia la mitad.

Puro (sin Qt ni numpy). Recibe las fichas de canción de `mix_types` (o el análisis de `track_analysis`, con las claves
en milisegundos) y devuelve un `TransitionPlan`. Cómo decide:

- **Punto de partida**: el de la fase 8 (`mix_points.plan`): la mezcla empieza al principio del final de A y el cuerpo
  de B debería llegar cuando A se ha ido.
- **Tempo**: `tempo_ratio_b` = tempo de A / tempo de B, contando la mitad y el doble como el mismo ritmo (70 y 140 BPM se
  mezclan sin tocar nada). Más allá de ±8 % el cambio se oye (suena artificial): entonces **corte limpio**, con su motivo.
- **Con rejillas** en las dos: la mezcla dura `bars` compases de A (16 por defecto; si pasan de 32 s, se parten por la
  mitad hasta caber, para seguir siendo una frase; también se parten si pasan de un tercio de B o si tras la mezcla a B no
  le quedaría al menos 1 s de cuerpo). Empieza en el comienzo de frase de A (múltiplo de 16 compases y, si
  no cabe ninguno, de 8) más cercano al punto de partida, siempre a partir de la mitad de la canción y con sitio para
  la mezcla entera antes de que A acabe. B entra en el comienzo de frase suyo (múltiplo de 8 compases) más cercano al
  punto en que su cuerpo llegaría al acabar la mezcla. El cambio de graves cae en el comienzo de compás más cercano a la
  mitad.
- **Sin rejillas** (falta alguna): el punto de la fase 8 tal cual, con el tempo igualado si se sabe el BPM de las dos.
- **Con datos que faltan**: nunca falla; devuelve un corte limpio con el motivo.
- **Con estructura** (`structure` en la ficha: el dict de `structure.analyse`, ya leído con `track_analysis.structure_from`;
  opcional, sin ella todo es como arriba), solo en la mezcla por frases:
  * Dos drops a la vez (`structure.drops_overlap`: un drop de cada una dentro de la mezcla, o el de una en plena subida de
    la otra): la frase se parte por la mitad hasta que no coincidan; si con 4 compases siguen coincidiendo, corte limpio en
    el principio de la frase de A (el tipo de transición decide luego si va con eco).
  * Drop de B al final de la mezcla (`structure.drop_aligned_b_start`): es solo una candidata para la entrada de B. Se usa si
    cae en un comienzo de compás de B que cuadra con la frase al menos tan bien como la que ya había (comienzo de frase de 8,
    de 4 o solo de compás), cabe en B, no pasa de su mitad y no hace coincidir drops.
  * Voces (`structure.vocal_overlap`), con peso BAJO porque la voz es una estimación que distingue poco en música real: si
    las dos tienen voz en más del 60 % de una mezcla de más de 16 s, se prueba UNA vez la frase de la mitad y se queda la que
    tenga menos voz solapada. Nunca lleva a un corte."""
import math

from services import mix_points
from services.mix_types import KIND_BLEND, KIND_CUT, BeatGrid, TransitionPlan

MAX_TEMPO_CHANGE = 0.08         # ±8 %: más allá, el cambio de tempo se nota
A_PHRASES = (16, 8)             # comienzos de frase de A que se prueban, de más a menos largos
B_PHRASE = 8                    # B entra en un comienzo de frase de 8 compases
MIN_BARS = 4                    # una mezcla por frases de menos de 4 compases no tiene sentido: se usa la de la fase 8
B_BODY_MIN_S = 1.0              # tras la mezcla, a B le debe quedar al menos esto de cuerpo (el motor lo exige)
VOCAL_SHORTEN = 0.6             # voz de las dos en más de esto de la mezcla: se prueba una frase más corta (peso bajo)
VOCAL_LONG_S = 16.0             # solo con mezclas más largas que esto


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _grid(info) -> BeatGrid:
    grid = info.get("beatgrid") if isinstance(info, dict) else None
    if not isinstance(grid, BeatGrid) or _number(grid.bpm) is None or grid.beats_per_bar < 1:
        return None
    return grid


def _bpm(info, grid):
    return grid.bpm if grid is not None else _number(info.get("bpm") if isinstance(info, dict) else None)


def tempo_ratio(bpm_a, bpm_b):
    """Factor que se aplica a B para que lleve el tempo de A (la mitad y el doble de B cuentan como su mismo ritmo), o
    None si falta alguno de los dos."""
    bpm_a, bpm_b = _number(bpm_a), _number(bpm_b)
    if bpm_a is None or bpm_b is None:
        return None
    return min((bpm_a / (bpm_b * k) for k in (0.5, 1.0, 2.0)), key=lambda r: abs(math.log(r)))


def _pct(ratio: float) -> str:
    return f"{(ratio - 1) * 100:+.1f} %".replace(".", ",")


def _phrase_starts(grid: BeatGrid, near: float, multiple: int) -> tuple:
    """Los dos comienzos de frase (múltiplos de `multiple` compases) que rodean el instante `near`."""
    after = grid.next_bar_time(near, multiple)
    return after, after - multiple * grid.bar_s


def _closest(candidates, target, low, high):
    fit = [t for t in candidates if low - 1e-6 <= t <= high + 1e-6]
    return min(fit, key=lambda t: abs(t - target)) if fit else None


def optimal_bars_for_genre(genre_a: str, genre_b: str = None, default_bars: int = 16) -> int:
    """Calcula los compases de mezcla ideales según los géneros musicales de las canciones.

    - House / Tech House / Techno: 16 o 32 compases (mezclas largas progresivas).
    - Reggaetón / Urbano / Dembow: 8 compases (mezclas dinámicas y cortas).
    - Hip-Hop / Boom Bap / Trap: 4 u 8 compases (cortes rítmicos).
    - Pop / Comercial: 16 u 8 compases (fundidos melódicos alineados).
    - EDM / Festival: 16 compases (build-up y drop).
    """
    try:
        from services.dj_planner import (
            classify_genre, GENRE_HOUSE, GENRE_REGGAETON, GENRE_HIPHOP, GENRE_EDM, GENRE_POP
        )
        fa = classify_genre(genre_a)
        fb = classify_genre(genre_b)
        fam = fa or fb
        if fam in (GENRE_REGGAETON, GENRE_HIPHOP):
            return 8
        elif fam == GENRE_HOUSE or fam in (GENRE_POP, GENRE_EDM):
            return 16
    except Exception:
        pass
    return default_bars


def plan_transition(a: dict, b: dict, bars: int = None) -> TransitionPlan:
    """Plan de la mezcla de A (la que suena) a B (la que entra). Ver la explicación del módulo."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return mix_points.cut(0.0, 0.0, "corte limpio: faltan los datos de " + ("la que suena" if not isinstance(a, dict)
                                                                                 else "la que entra"))
    base = mix_points.plan(a, b)
    if base.kind == KIND_CUT:
        return base
    if bars is None:
        bars = optimal_bars_for_genre(
            a.get("genre") if isinstance(a, dict) else "",
            b.get("genre") if isinstance(b, dict) else "",
            default_bars=16
        )
    grid_a, grid_b = _grid(a), _grid(b)
    ratio = tempo_ratio(_bpm(a, grid_a), _bpm(b, grid_b))
    if ratio is None:
        return TransitionPlan(base.a_start_s, base.b_start_s, base.length_s, 1.0, None, base.kind,
                              base.reason + "; sin tempo de las dos: no se iguala el ritmo")
    if abs(ratio - 1.0) > MAX_TEMPO_CHANGE + 1e-9:
        # corte al principio del final de A (en un comienzo de compás si hay rejilla) hacia donde B iba a entrar
        a_cut = grid_a.next_bar_time(base.a_start_s) if grid_a is not None else base.a_start_s
        if a_cut > mix_points.seconds(a, "duration"):
            a_cut = base.a_start_s
        b_cut = grid_b.next_bar_time(base.b_start_s) if grid_b is not None else base.b_start_s
        return mix_points.cut(a_cut, b_cut,
                              f"corte limpio: los tempos están demasiado lejos (haría falta {_pct(ratio)} y el máximo "
                              f"es ±{round(MAX_TEMPO_CHANGE * 100)} %)")
    tempo_note = "mismo tempo" if abs(ratio - 1.0) < 1e-6 else f"tempo de la que entra {_pct(ratio)}"
    if grid_a is None or grid_b is None:
        return TransitionPlan(base.a_start_s, base.b_start_s, base.length_s, round(ratio, 6), None, base.kind,
                              f"{base.reason}; sin rejilla de golpes: sin cuadrar compases; {tempo_note}")
    phrased = _phrased(a, b, grid_a, grid_b, ratio, max(1, int(bars or 16)), base)
    if isinstance(phrased, dict):                       # los drops coinciden con cualquier frase: corte al empezar la de A
        return mix_points.cut(phrased["a_start"], phrased["b_start"],
                              "corte limpio: los drops de las dos caerían a la vez en cualquier mezcla por frases")
    if phrased is None:
        return TransitionPlan(base.a_start_s, base.b_start_s, base.length_s, round(ratio, 6), None, base.kind,
                              f"{base.reason}; no cabe una frase entera: sin cuadrar compases; {tempo_note}")
    return TransitionPlan(phrased[0], phrased[1], phrased[2], round(ratio, 6), phrased[3], KIND_BLEND,
                          f"{phrased[4]}; {tempo_note}")


def _structure(info):
    """Los eventos y la voz de la estructura de una ficha (o None)."""
    st = info.get("structure") if isinstance(info, dict) else None
    return st if isinstance(st, dict) else None


def _phrase_rank(grid: BeatGrid, t: float) -> int:
    """Lo bien que cuadra el instante t con las frases de la rejilla: 3 comienzo de frase de 8, 2 de 4, 1 de compás, 0 nada."""
    bar_f = grid.bar_at(t)
    bar = round(bar_f)
    if abs(bar_f - bar) > 0.05:
        return 0
    return 3 if bar % B_PHRASE == 0 else 2 if bar % 4 == 0 else 1


def _phrased(a, b, grid_a: BeatGrid, grid_b: BeatGrid, ratio: float, bars: int, base: TransitionPlan):
    """(a_start, b_start, length, bass_swap, motivo) cuadrados con las frases, o None si no cabe ninguna. Con estructura, un
    dict {"a_start", "b_start"} si cabía una frase pero los drops coinciden en todas (ver la explicación del módulo)."""
    a_dur = mix_points.seconds(a, "duration")
    b_dur = mix_points.seconds(b, "duration")
    intro_b = mix_points.seconds(b, "intro") or 0.0
    sa, sb = _structure(a), _structure(b)
    st = None
    if sa is not None or sb is not None:
        from services import structure as st            # solo si hay estructura (el planificador sigue siendo puro)
    ev_a, ev_b = (sa or {}).get("events"), (sb or {}).get("events")
    voc_a, voc_b = (sa or {}).get("vocal"), (sb or {}).get("vocal")
    clash, keep, vocal_tried = None, None, False
    max_len = 64.0 if bars >= 32 else mix_points.MAX_MIX_S
    while grid_a.bar_s * bars > max_len and bars > MIN_BARS:
        bars //= 2
    while bars >= MIN_BARS:
        length = grid_a.bar_s * bars
        latest = a_dur - length
        b_fits = not b_dur or length * ratio <= b_dur / mix_points.TRACK_SHARE + 1e-6    # como en la fase 8: un tercio de B
        if latest >= a_dur / 2 and b_fits:
            a_phrases = (32, 16, 8) if bars >= 32 else A_PHRASES
            for multiple in a_phrases:
                a_start = _closest(_phrase_starts(grid_a, base.a_start_s, multiple), base.a_start_s, a_dur / 2, latest)
                if a_start is not None:
                    break
            if a_start is not None:
                # B entra donde su cuerpo llegue al acabar la mezcla (lo que avanza B en la mezcla va a su tempo nuevo)
                target_b = max(0.0, intro_b - length * ratio)
                high_b = b_dur / 2 if b_dur else math.inf
                b_start = _closest(_phrase_starts(grid_b, target_b, B_PHRASE), target_b, 0.0, high_b)
                if b_start is None:
                    b_start = _closest((grid_b.next_bar_time(0.0),), target_b, 0.0, high_b)

                def fits(t, length=length, high_b=high_b):
                    return t is not None and 0.0 <= t <= high_b + 1e-6 and (not b_dur or t + length * ratio + B_BODY_MIN_S <= b_dur)

                if not fits(b_start):
                    b_start = None                      # el cuerpo de B no llegaría a sonar: frase más corta
                notes = []
                if b_start is not None and st is not None:
                    cand = st.drop_aligned_b_start(ev_a, ev_b, a_start, length, ratio, grid_b)
                    if (cand is not None and abs(cand - b_start) > 1e-6 and fits(cand)
                            and _phrase_rank(grid_b, cand) >= _phrase_rank(grid_b, b_start)
                            and not st.drops_overlap(a_start, length, ratio, cand, ev_a, ev_b)):
                        b_start = cand
                        notes.append("la que entra, con su drop al final de la mezcla")
                    if st.drops_overlap(a_start, length, ratio, b_start, ev_a, ev_b):
                        clash = clash or {"a_start": round(a_start, 3), "b_start": round(b_start, 3)}
                        b_start = None                  # dos drops a la vez: frase más corta
                        bars //= 2
                        continue
                if b_start is not None:
                    middle = a_start + length / 2
                    swap = grid_a.bar_time(round(grid_a.bar_at(middle))) - a_start
                    swap = min(max(swap, 0.0), length)
                    why = (f"mezcla de {bars} compases ({mix_points.fmt_seconds(length)}) desde un comienzo de frase "
                           f"de {multiple} compases; " + ("; ".join(notes) if notes else "la que entra, desde un comienzo de frase suyo"))
                    if clash is not None:
                        why += "; más corta para que no coincidan los drops de las dos"
                    found = (round(a_start, 3), round(b_start, 3), round(length, 3), round(swap, 3), why)
                    voc = st.vocal_overlap(a_start, length, ratio, b_start, voc_a, voc_b) if st is not None else 0.0
                    if keep is not None:                # la frase corta que se probó por las voces
                        return found[:4] + (found[4] + "; más corta: menos voces a la vez",) if voc < keep[1] else keep[0]
                    if voc >= VOCAL_SHORTEN and length > VOCAL_LONG_S and bars // 2 >= MIN_BARS and not vocal_tried:
                        keep, vocal_tried = (found, voc), True
                        bars //= 2
                        continue
                    return found
        bars //= 2
    if keep is not None:
        return keep[0]
    return clash
