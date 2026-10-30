"""Tipos de transición del modo DJ (fase 16): además de la mezcla con cambio de graves de `dj_dsp`, un corte en el compás, un
eco de salida y un filtro; y la regla que elige uno u otro según lo fiables que sean los datos de las dos canciones.

Misma convención que `dj_dsp.render_transition` (léela allí): `a` es el audio de A desde `plan.a_start_s`, `b` el de B ya
estirada de tempo y empezando donde entra (su primer fotograma es el primero de la mezcla), mono o estéreo, float32 a 44.100 Hz.
Mientras dura la mezcla, `a[i]` y `b[i]` suenan en el instante i de la salida en todos los tipos: B nunca se desplaza, así que
lo que va después (el cuerpo de B desde `b_start_s + length_s * tempo_ratio_b`) sigue en su sitio.

Tipos (constantes TYPE_*):
  blend     «mezcla»: `dj_dsp.render_transition` tal cual: fundido de potencia constante en medios y agudos y cambio de graves
            en `plan.bass_swap_at` (40 ms). Lo mejor cuando las rejillas son fiables y los tonos encajan.
  cut_bar   «corte en el compás»: A suena sola hasta el instante del cambio de graves (`plan.bass_swap_at`, que el planificador
            con rejillas pone en un comienzo de compás) y B sola desde ahí, de modo que lo primero que se oye de B es su golpe
            fuerte. A baja en 5 ms y B sube en 2 ms, y las dos rampas acaban justo en el corte: el ataque del golpe de B queda
            entero. Nunca suenan las dos canciones a la vez (más de 2 ms), así que ni el tono ni el tempo pueden chocar.
  echo_out  «eco de salida»: como el corte, pero el último golpe de A antes del corte se manda a un eco al tempo (3/4 de golpe,
            realimentación 0,45, sin graves) cuya cola sigue sonando por encima de B. Los graves de A se cortan en el golpe de
            entrada de B (el eco no lleva graves): nunca dos bombos. Sirve para tapar un final brusco de A o un corte entre
            tempos muy distintos (el eco va al tempo de A y se apaga en unos segundos).
  filter    «filtro»: A pasa por un paso alto que sube de 20 Hz a 2 kHz (pierde graves y luego cuerpo) mientras B entra con
            un paso bajo que se abre de 300 Hz a 20 kHz (al 85 % ya está abierto y en el último 15 % se funde con B sin
            filtrar, para acabar exactamente en B). Volúmenes con el fundido de potencia constante y, encima, el mismo cambio de
            graves de la mezcla (B no lleva graves hasta `bass_swap_at`). Las dos canciones suenan a la vez, pero con poco
            contenido en común: es lo que se usa cuando los tonos chocan y el tempo se puede igualar.

Longitud devuelta (fotogramas):
  * Mezcla (plan.kind distinto de «cut» y length_s > 0): exactamente round(plan.length_s * sample_rate) en todos los tipos.
    Si `a` o `b` son más cortos, se rellenan con silencio (con rampa de 5 ms, como `render_transition`).
  * Plan de corte (kind «cut» o length_s <= 0): len(a) + len(b), como `render_transition` (A entera y luego B entera con
    rampas de 5 ms). blend, cut_bar y filter dan exactamente el corte limpio de `render_transition`; echo_out añade el eco del
    último golpe de A encima de B.
  * Cola (solo echo_out): `render_typed_parts` devuelve (mezcla, cola). La mezcla tiene la longitud de arriba; la cola son los
    fotogramas del eco que caen DESPUÉS de la mezcla y hay que SUMARLA (no encolarla detrás) a lo primero que suene después:
    el cuerpo de B a partir de su primer fotograma. Para los otros tipos la cola está vacía. Por defecto la cola dura lo que el
    eco tarda en caer 60 dB (con 128 BPM, unos 3,9 s desde el corte; si el corte cae a la mitad de una mezcla larga, el eco se
    apaga dentro y la cola sale vacía); `tail_s` la limita (con rampa de 50 ms al final). `render_typed` devuelve solo la
    mezcla: si el eco no cabe, se baja a cero en los últimos 250 ms de la mezcla (se pierde el final del eco, sin clic).

Nada de esto recorta ni normaliza (como `render_transition`): la suma de B y el eco puede pasar de 1,0 si B ya va al límite.

Regla de elección (`choose_type`), de arriba abajo; la primera que se cumple decide:
  1. Plan de corte: echo_out si se sabe el tempo de A y además los tempos están a más del 8 % (por eso se cortaba) o A tiene
     un final brusco; si no, cut_bar (que con un plan de corte es el corte limpio).
  2. Dudas sobre el ritmo (falta la rejilla de alguna o su confianza es menor de 0,4, o el tempo no se sabe, o hay que cambiarlo
     más de un 5 %): corta y limpia: blend si la mezcla ya es corta (8 s o menos), cut_bar si es más larga.
  3. Final brusco de A (menos de 3 s de final según el análisis) con rejillas fiables: echo_out.
  4. Tonos que chocan (`camelot.score` 0): filter.
  5. Tonos que no se sabe si encajan (falta alguno, o están a dos pasos o en diagonal) y mezcla de más de 16 s: filter; con
     una mezcla de 16 s o menos, blend.
  6. Lo demás (rejillas fiables, tempo a menos del 5 %, tonos compatibles): blend, la mezcla larga de graves.
  La energía (`energy`) no se usa todavía. Los umbrales (3 s, 5 %, 8 s, 16 s) son de criterio, no medidos: hay que oírlos."""
import math

from services import camelot, dj_dsp, dj_fx, mix_planner, mix_points
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid, TransitionPlan

TYPE_BLEND = "blend"
TYPE_CUT_BAR = "cut_bar"
TYPE_ECHO_OUT = "echo_out"
TYPE_FILTER = "filter"
TYPES = (TYPE_BLEND, TYPE_CUT_BAR, TYPE_ECHO_OUT, TYPE_FILTER)

CUT_A_RAMP_S = 0.005            # A baja en 5 ms hasta el corte
CUT_B_RAMP_S = 0.002            # B sube en 2 ms y está entera en el corte (el golpe no pierde el ataque)
ECHO_BEATS = 0.75               # retardo del eco de salida, en golpes
ECHO_FEEDBACK = 0.45
ECHO_LEVEL = 0.6                # primera repetición del eco respecto a A
ECHO_SEND_BEATS = 1.0           # cuánto de A (antes del corte) entra en el eco
ECHO_SEND_RAMP_S = 0.005
DEFAULT_BPM = 120.0             # tempo que se supone para el eco si no se sabe (choose_type no elige echo_out sin tempo)
FOLD_FADE_S = 0.25              # render_typed: el eco que no cabe se baja a cero en este tiempo
FILTER_A = (20.0, 2000.0, 0.9)  # paso alto de A: de, a, fracción de la mezcla en que llega
FILTER_B = (300.0, 20000.0, 0.85)   # paso bajo de B
FILTER_DRY_S = 0.1              # al principio, A se funde de seco a filtrado en este tiempo (como mínimo)

MIN_GRID_CONFIDENCE = 0.4       # el mismo umbral que `track_analysis`: por debajo, la rejilla no es de fiar
SAFE_TEMPO_CHANGE = 0.05        # más de un 5 % de cambio de tempo es una duda
SHORT_MIX_S = 8.0               # una mezcla de hasta 8 s ya es «corta»
LONG_MIX_S = 16.0               # con tonos sin confirmar, una mezcla más larga que esto va con filtro
ABRUPT_OUTRO_S = 3.0            # un final de menos de 3 s es un final brusco


def _np():
    return dj_dsp._np()


def _check_kind(kind):
    if kind not in TYPES:
        raise ValueError(f"tipo de transición desconocido: {kind!r} (valen {', '.join(TYPES)})")


def _is_cut(plan, sample_rate) -> bool:
    return plan.kind == KIND_CUT or int(round(float(plan.length_s) * sample_rate)) <= 0


def base_length(a, b, plan, sample_rate: int = SAMPLE_RATE) -> int:
    """Fotogramas de la mezcla (sin la cola): round(length_s * sample_rate), o len(a) + len(b) con un plan de corte."""
    if _is_cut(plan, sample_rate):
        return len(a) + len(b)
    return int(round(float(plan.length_s) * sample_rate))


def _cut_point(plan, n: int, sample_rate: int) -> int:
    """Muestra del corte dentro de la mezcla: `plan.bass_swap_at`, con sitio para las rampas a los dos lados."""
    ra = int(round(CUT_A_RAMP_S * sample_rate))
    c = int(round(float(plan.bass_swap_at) * sample_rate))
    return min(max(c, min(ra, n)), max(0, n - 1))


def _dry_cut(a, b, c: int, sample_rate: int):
    """A hasta c (rampa de 5 ms que acaba en c) y B desde c (rampa de 2 ms que acaba en c), sobre la línea de la mezcla."""
    np = _np()
    n = len(a)
    ga = np.zeros(n, dtype=np.float64)
    gb = np.zeros(n, dtype=np.float64)
    ga[:c] = 1.0
    gb[c:] = 1.0
    ra = min(int(round(CUT_A_RAMP_S * sample_rate)), c)
    rb = min(int(round(CUT_B_RAMP_S * sample_rate)), c)
    if ra:
        ga[c - ra:c] = dj_dsp._ramp(ra, down=True)
    if rb:
        gb[c - rb:c] = dj_dsp._ramp(rb, down=False)
    return ga[:, None] * a + gb[:, None] * b


def _echo_wet(a, c: int, bpm, sample_rate: int):
    """El eco del último golpe de A antes de la muestra c, sin graves: (inicio en la línea de la mezcla, array float64)."""
    np = _np()
    beat = 60.0 / (bpm if bpm and bpm > 0 else DEFAULT_BPM)
    send_n = min(c, int(round(ECHO_SEND_BEATS * beat * sample_rate)))
    if send_n <= 0:
        return c, np.zeros((0, 2), dtype=np.float64)
    if not np.any(a[c - send_n:c]):
        return c, np.zeros((0, 2), dtype=np.float64)          # A en silencio: no hay eco (ni cola de ceros)
    send = dj_dsp.kill_low(a[c - send_n:c], sample_rate=sample_rate).astype(np.float64)
    r = min(int(round(ECHO_SEND_RAMP_S * sample_rate)), send_n // 2)
    if r:
        send[:r] *= dj_dsp._ramp(r, down=False)[:, None]
        send[send_n - r:] *= dj_dsp._ramp(r, down=True)[:, None]
    delay = ECHO_BEATS * beat
    d = max(1, int(round(delay * sample_rate)))
    total = send_n + int(round(dj_fx.echo_tail_s(delay, ECHO_FEEDBACK) * sample_rate))
    wet = ECHO_LEVEL * dj_fx._echo_wet(send, d, ECHO_FEEDBACK, total)
    dj_fx._fade_out(wet, int(dj_fx.TAIL_FADE_S * sample_rate))    # a -60 dB ya casi no suena, pero que acabe en 0 exacto
    return c - send_n, wet


def _render_echo_out(dry, a, c, bpm, sample_rate, limit_frames):
    """(mezcla, cola): `dry` es la mezcla sin eco; el eco del golpe anterior a c se suma encima. La cola es lo que pasa de
    len(dry), hasta `limit_frames` fotogramas en total (rampa de bajada donde se recorta)."""
    np = _np()
    n = len(dry)
    start, wet = _echo_wet(a, c, bpm, sample_rate)
    keep = min(len(wet), max(0, limit_frames - start))
    if keep < len(wet):
        wet = wet[:keep].copy()
        dj_fx._fade_out(wet, min(keep, int(round((FOLD_FADE_S if limit_frames <= n else dj_fx.TAIL_FADE_S) * sample_rate))))
    total = max(n, start + len(wet))
    full = np.zeros((total, 2), dtype=np.float64)
    full[:n] = dry
    full[start:start + len(wet)] += wet
    return full[:n].astype(np.float32), full[n:].astype(np.float32)


def _sweep_dry_blend(n: int, frames: int, at_start: bool):
    """Peso del audio filtrado: sube de 0 a 1 en los primeros `frames` (at_start) o baja de 1 a 0 en los últimos."""
    np = _np()
    w = np.ones(n, dtype=np.float64)
    frames = min(max(1, frames), n)
    u = np.arange(frames, dtype=np.float64) / frames
    s = u * u * (3.0 - 2.0 * u)
    if at_start:
        w[:frames] = s
    else:
        w[n - frames:] = 1.0 - s
    return w


def _render_filter(a, b, plan, sample_rate):
    np = _np()
    n = len(a)
    a64, b64 = a.astype(np.float64), b.astype(np.float64)
    fa = dj_fx.filter_sweep(a, "hp", FILTER_A[0], FILTER_A[1], sample_rate=sample_rate, end_at=FILTER_A[2]).astype(np.float64)
    fb = dj_fx.filter_sweep(b, "lp", FILTER_B[0], min(FILTER_B[1], sample_rate / 2.0 * 0.95), sample_rate=sample_rate,
                            end_at=FILTER_B[2]).astype(np.float64)
    wa = _sweep_dry_blend(n, max(int(FILTER_DRY_S * sample_rate), int(0.05 * n)), at_start=True)[:, None]
    wb = _sweep_dry_blend(n, int((1.0 - FILTER_B[2]) * n), at_start=False)[:, None]
    pa = a64 * (1.0 - wa) + fa * wa
    pb = b64 * (1.0 - wb) + fb * wb
    angle = (np.arange(n, dtype=np.float64) + 0.5) / n * (math.pi / 2.0)
    fade_a, fade_b = np.cos(angle), np.sin(angle)
    step = min(dj_dsp.SWAP_STEP_S, n / sample_rate)
    swap = min(max(float(plan.bass_swap_at), step / 2.0), n / sample_rate - step / 2.0)
    bass_b = dj_dsp.band_gains(n, [(swap - step / 2.0, 0.0), (swap + step / 2.0, 1.0)], sample_rate).astype(np.float64)
    bass_a = 1.0 - bass_b
    low_a = dj_dsp._lowpass(pa, dj_dsp.LOW_HZ, sample_rate)      # la banda grave de split_bands, con una sola FFT
    low_b = dj_dsp._lowpass(pb, dj_dsp.LOW_HZ, sample_rate)
    out = (fade_a[:, None] * pa + fade_b[:, None] * pb
           + (bass_a - fade_a)[:, None] * low_a + (bass_b - fade_b)[:, None] * low_b)
    return out.astype(np.float32)


def render_typed_parts(a, b, plan: TransitionPlan, kind: str, bpm: float = None, sample_rate: int = SAMPLE_RATE,
                       tail_s: float = None):
    """(mezcla, cola) de la transición del tipo `kind`. Ver el docstring del módulo para la longitud de cada parte y cómo se
    encola la cola (se SUMA al cuerpo de B que sigue). `bpm`: el tempo de la mezcla (el de A; B ya va estirada a él), para el
    eco; sin él se supone 120. `tail_s`: máximo de cola en segundos (None = la que haga falta para que el eco caiga 60 dB;
    0 = sin cola, el eco se baja a cero al final de la mezcla). La cola de los tipos que no son echo_out es (0, 2).
    ValueError si el tipo no existe."""
    np = _np()
    _check_kind(kind)
    a = dj_dsp._to_stereo(a)
    b = dj_dsp._to_stereo(b)
    empty = np.zeros((0, 2), dtype=np.float32)
    cut = _is_cut(plan, sample_rate)
    if kind == TYPE_BLEND or (cut and kind != TYPE_ECHO_OUT):
        return dj_dsp.render_transition(a, b, plan, sample_rate), empty
    if cut:
        dry = dj_dsp.render_transition(a, b, plan, sample_rate).astype(np.float64)
        a_line, c = a, len(a)
    else:
        n = int(round(float(plan.length_s) * sample_rate))
        a, b = dj_dsp._fit(a, n), dj_dsp._fit(b, n)
        if kind == TYPE_FILTER:
            return _render_filter(a, b, plan, sample_rate), empty
        c = _cut_point(plan, n, sample_rate)
        dry = _dry_cut(a.astype(np.float64), b.astype(np.float64), c, sample_rate)
        if kind == TYPE_CUT_BAR:
            return dry.astype(np.float32), empty
        a_line = a
    limit = len(dry) + (10 ** 12 if tail_s is None else max(0, int(round(float(tail_s) * sample_rate))))
    return _render_echo_out(dry, a_line, c, bpm, sample_rate, limit)


def render_typed(a, b, plan: TransitionPlan, kind: str, bpm: float = None, sample_rate: int = SAMPLE_RATE):
    """La transición del tipo `kind` como un solo array float32 (n, 2) de la longitud de `base_length` (exactamente
    round(plan.length_s * sample_rate) en una mezcla). Con «blend» es exactamente `dj_dsp.render_transition`. En echo_out
    el eco que no cabe se baja a cero al final de la mezcla; para conservarlo entero, usar `render_typed_parts`."""
    return render_typed_parts(a, b, plan, kind, bpm, sample_rate, tail_s=0.0)[0]


# ------------------------------------------------------------------ elección del tipo

def _reliable_grid(info):
    grid = info.get("beatgrid") if isinstance(info, dict) else None
    if not isinstance(grid, BeatGrid) or mix_planner._number(grid.bpm) is None:
        return None, "sin rejilla de golpes"
    conf = grid.confidence if isinstance(grid.confidence, (int, float)) else 0.0
    if conf < MIN_GRID_CONFIDENCE:
        return None, f"rejilla poco fiable (confianza {conf:.2f})".replace(".", ",")
    return grid, ""


def _bpm_of(info, grid):
    if grid is not None:
        return float(grid.bpm)
    return mix_planner._number(info.get("bpm")) if isinstance(info, dict) else None


def _pct(ratio) -> str:
    return f"{abs(ratio - 1.0) * 100:.1f} %".replace(".", ",")


def choose_type(a_info: dict, b_info: dict, plan: TransitionPlan, bpm_a: float = None):
    """(tipo, motivo en español) para pasar de A a B con `plan` (el de `mix_planner.plan_transition`). `a_info` y `b_info`
    son las fichas de `mix_types` (duration_s o duration_ms, intro, outro, bpm, beatgrid, tone, energy; lo que falte cuenta
    como «no se sabe»). `bpm_a`: tempo de A si se sabe mejor que por la ficha. Nunca falla. Regla: ver el módulo."""
    a_info = a_info if isinstance(a_info, dict) else {}
    b_info = b_info if isinstance(b_info, dict) else {}
    grid_a, why_a = _reliable_grid(a_info)
    grid_b, why_b = _reliable_grid(b_info)
    tempo_a = mix_planner._number(bpm_a) or _bpm_of(a_info, grid_a) or mix_planner._number(a_info.get("bpm"))
    tempo_b = _bpm_of(b_info, grid_b) or mix_planner._number(b_info.get("bpm"))
    ratio = mix_planner.tempo_ratio(tempo_a, tempo_b)
    outro = mix_points.seconds(a_info, "outro")
    abrupt = outro is not None and outro < ABRUPT_OUTRO_S
    abrupt_note = f"la que suena acaba de golpe (final de {mix_points.fmt_seconds(outro)})" if abrupt else ""
    length = float(plan.length_s) if plan is not None else 0.0
    is_cut = plan is None or plan.kind == KIND_CUT or length <= 0

    # 1. Plan de corte
    if is_cut:
        far = ratio is not None and abs(ratio - 1.0) > mix_planner.MAX_TEMPO_CHANGE + 1e-9
        if tempo_a and (far or abrupt):
            what = f"tempos a {_pct(ratio)}" if far else abrupt_note
            return TYPE_ECHO_OUT, f"eco de salida: se corta ({what}) y el eco al tempo de la que suena tapa el corte"
        return TYPE_CUT_BAR, "corte limpio en el compás: el plan ya era un corte" + ("" if tempo_a else " y no se sabe el tempo")

    # 2. Dudas sobre el ritmo: corta y limpia
    doubts = [w for w in (why_a and why_a + " en la que suena", why_b and why_b + " en la que entra") if w]
    if ratio is None:
        doubts.append("no se sabe el tempo de las dos")
    elif abs(ratio - 1.0) > SAFE_TEMPO_CHANGE + 1e-9:
        doubts.append(f"hay que cambiar el tempo un {_pct(ratio)} (más del {round(SAFE_TEMPO_CHANGE * 100)} %)")
    if doubts:
        if length <= SHORT_MIX_S + 1e-9:
            return TYPE_BLEND, "mezcla corta: " + "; ".join(doubts)
        return TYPE_CUT_BAR, "corte en el compás (en vez de una mezcla larga): " + "; ".join(doubts)

    # 3. Final brusco
    if abrupt:
        return TYPE_ECHO_OUT, "eco de salida: " + abrupt_note

    # 4 y 5. Tonos
    tone_a, tone_b = camelot.normalize(a_info.get("tone")), camelot.normalize(b_info.get("tone"))
    key_score = camelot.score(tone_a, tone_b)
    if tone_a and tone_b and key_score <= camelot.SCORE_BAD:
        return TYPE_FILTER, f"filtro: los tonos chocan ({tone_a} y {tone_b}) y el tempo se puede igualar"
    if key_score < camelot.SCORE_GOOD:
        what = f"tonos que encajan a medias ({tone_a} y {tone_b})" if tone_a and tone_b else "no se sabe el tono de las dos"
        if length > LONG_MIX_S + 1e-9:
            return TYPE_FILTER, f"filtro: {what} y la mezcla es larga ({mix_points.fmt_seconds(length)})"
        return TYPE_BLEND, f"mezcla: {what}, pero la mezcla es corta ({mix_points.fmt_seconds(length)})"

    # 6. Todo encaja
    tones = "mismo tono" if tone_a == tone_b else f"tonos compatibles ({tone_a} y {tone_b})"
    return TYPE_BLEND, f"mezcla larga con cambio de graves: rejillas fiables, tempo igualable y {tones}"
