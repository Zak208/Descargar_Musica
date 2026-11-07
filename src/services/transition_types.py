"""Tipos de transición del modo DJ (fases 16 y 21): además de la mezcla con cambio de graves de `dj_dsp`, un corte en el compás,
eco de salida, filtro por barrido, reverb envolvente (reverb_wash), delay drop con ping-pong y mezcla inteligente con Mid-Carve;
y la regla que elige uno u otro según lo fiables que sean los datos de las dos canciones, la compatibilidad armónica y la energía.

Misma convención que `dj_dsp.render_transition`: `a` es el audio de A desde `plan.a_start_s`, `b` el de B ya
estirada de tempo y empezando donde entra (su primer fotograma es el primero de la mezcla), mono o estéreo, float32 a 44.100 Hz.
Mientras dura la mezcla, `a[i]` y `b[i]` suenan en el instante i de la salida en todos los tipos: B nunca se desplaza, así que
lo que va después (el cuerpo de B desde `b_start_s + length_s * tempo_ratio_b`) sigue en su sitio.

Tipos (constantes TYPE_*):
  blend            «mezcla»: `dj_dsp.render_transition` tal cual: fundido de potencia constante en medios y agudos y cambio de graves
                   en `plan.bass_swap_at` (40 ms). Lo mejor cuando las rejillas son fiables y los tonos encajan.
  cut_bar          «corte en el compás»: A suena sola hasta el instante del cambio de graves (`plan.bass_swap_at`, que el planificador
                   con rejillas pone en un comienzo de compás) y B sola desde ahí, de modo que lo primero que se oye de B es su golpe
                   fuerte. A baja en 5 ms y B sube en 2 ms, y las dos rampas acaban justo en el corte: el ataque del golpe de B queda
                   entero. Nunca suenan las dos canciones a la vez (más de 2 ms), así que ni el tono ni el tempo pueden chocar.
  echo_out         «eco de salida»: como el corte, pero el último golpe de A antes del corte se manda a un eco al tempo (3/4 de golpe,
                   realimentación 0,45, sin graves) cuya cola sigue sonando por encima de B. Los graves de A se cortan en el golpe de
                   entrada de B (el eco no lleva graves): nunca dos bombos. Sirve para tapar un final brusco de A o un corte entre
                   tempos muy distintos (el eco va al tempo de A y se apaga en unos segundos).
  filter           «filtro»: A pasa por un paso alto que sube de 20 Hz a 2 kHz (pierde graves y luego cuerpo) mientras B entra con
                   un paso bajo que se abre de 300 Hz a 20 kHz (al 85 % ya está abierto y en el último 15 % se funde con B sin
                   filtrar, para acabar exactamente en B). Volúmenes con el fundido de potencia constante y, encima, el mismo cambio de
                   graves de la mezcla (B no lleva graves hasta `bass_swap_at`). Las dos canciones suenan a la vez, pero con poco
                   contenido en común: es lo que se usa cuando los tonos chocan y el tempo se puede igualar.
  reverb_wash      «washout con reverb»: Track A barre un filtro paso alto creciente hacia 1800 Hz y expande una reverberación
                   envolvente hasta el corte, dejando una cola difusa etérea sobre Track B. Ideal para caídas de energía o perfiles Chill.
  delay_drop       «delay drop»: el último pulso de A antes del corte se inyecta en un tempo delay estéreo con ping-pong y ducking,
                   mientras Track B entra de golpe con máxima contundencia en el primer tiempo.
  smart_filter_eq  «mezcla inteligente con Mid-Carve»: mezcla armónica con cruce Linkwitz-Riley de graves y atenuación dinámica
                   de medios vocales (Mid-Carve de -5 dB en 1-3 kHz) en A para evitar choque vocal y saturación en mezclas largas.
"""
import math

from services import camelot, dj_dsp, dj_fx, mix_planner, mix_points
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid, TransitionPlan

TYPE_BLEND = "blend"
TYPE_CUT_BAR = "cut_bar"
TYPE_ECHO_OUT = "echo_out"
TYPE_FILTER = "filter"
TYPE_REVERB_WASH = "reverb_wash"
TYPE_DELAY_DROP = "delay_drop"
TYPE_SMART_FILTER_EQ = "smart_filter_eq"

TYPES = (
    TYPE_BLEND,
    TYPE_CUT_BAR,
    TYPE_ECHO_OUT,
    TYPE_FILTER,
    TYPE_REVERB_WASH,
    TYPE_DELAY_DROP,
    TYPE_SMART_FILTER_EQ,
)

CUT_A_RAMP_S = 0.005            # A baja en 5 ms hasta el corte
CUT_B_RAMP_S = 0.002            # B sube en 2 ms y está entera en el corte (el golpe no pierde el ataque)
ECHO_BEATS = 0.75               # retardo del eco de salida, en golpes
ECHO_FEEDBACK = 0.45
ECHO_LEVEL = 0.6                # primera repetición del eco respecto a A
ECHO_SEND_BEATS = 1.0           # cuánto de A (antes del corte) entra en el eco
ECHO_SEND_RAMP_S = 0.005
DEFAULT_BPM = 120.0             # tempo que se supone para el eco si no se sabe
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


def _render_delay_drop(dry, a, c: int, bpm, sample_rate: int, limit_frames: int):
    """(mezcla, cola) para delay_drop: captura el último golpe de A antes del corte c,
    lo manda a tempo_delay estéreo con ping-pong y ducking, y la cola suena sobre B."""
    np = _np()
    n = len(dry)
    beat = 60.0 / (bpm if bpm and bpm > 0 else DEFAULT_BPM)
    send_n = min(c, int(round(ECHO_SEND_BEATS * beat * sample_rate)))
    if send_n <= 0 or not np.any(a[c - send_n:c]):
        return dry[:n].astype(np.float32), np.zeros((0, 2), dtype=np.float32)
    send = dj_dsp.kill_low(a[c - send_n:c], sample_rate=sample_rate).astype(np.float64)
    r = min(int(round(ECHO_SEND_RAMP_S * sample_rate)), send_n // 2)
    if r:
        send[:r] *= dj_dsp._ramp(r, down=False)[:, None]
        send[send_n - r:] *= dj_dsp._ramp(r, down=True)[:, None]

    is_mono = np.array_equal(a[:, 0], a[:, 1])
    tail_dur = 4.0
    wet = dj_fx.tempo_delay(send, bpm=bpm or DEFAULT_BPM, beats=0.75, feedback=0.55,
                            mix=0.8, ping_pong=not is_mono, ducking=0.25, tail_s=tail_dur,
                            sample_rate=sample_rate).astype(np.float64)
    if is_mono:
        wet[:, 1] = wet[:, 0]

    start = c - send_n
    keep = min(len(wet), max(0, limit_frames - start))
    if keep < len(wet):
        wet = wet[:keep].copy()
        dj_fx._fade_out(wet, min(keep, int(round((FOLD_FADE_S if limit_frames <= n else dj_fx.TAIL_FADE_S) * sample_rate))))
    total = max(n, start + len(wet))
    full = np.zeros((total, 2), dtype=np.float64)
    full[:n] = dry
    full[start:start + len(wet)] += wet
    if is_mono:
        full[:, 1] = full[:, 0]
    return full[:n].astype(np.float32), full[n:].astype(np.float32)


def _render_reverb_wash(dry, a, b, c: int, sample_rate: int, limit_frames: int):
    """(mezcla, cola) para reverb_wash: aplica filtro paso alto y reverb envolvente creciente
    a A antes de c, y deja que la cola de reverberación se extienda suavemente sobre B."""
    np = _np()
    n = len(dry)
    beat = 60.0 / DEFAULT_BPM
    check_n = min(c, int(round(ECHO_SEND_BEATS * beat * sample_rate)))
    if c <= 0 or not np.any(a[:c]) or (check_n > 0 and not np.any(a[c - check_n:c])):
        return dry[:n].astype(np.float32), np.zeros((0, 2), dtype=np.float32)
    a_part = a[:c].astype(np.float64)
    is_mono = np.array_equal(a[:, 0], a[:, 1]) and np.array_equal(b[:, 0], b[:, 1])
    tail_dur = 4.0
    washed = dj_fx.washout_reverb(a_part, decay_s=3.0, mix_start=0.1, mix_end=0.85,
                                  tail_s=tail_dur, sample_rate=sample_rate).astype(np.float64)
    if is_mono:
        washed[:, 1] = washed[:, 0]

    wet_tail = washed[c:]
    b_has_audio = np.any(b[c:] != 0, axis=1) if len(b) > c else np.array([False])
    if np.any(b_has_audio):
        b_last = c + int(np.max(np.where(b_has_audio)[0])) + 1
        silence_limit = min(limit_frames, b_last + int(0.1 * sample_rate))
    else:
        silence_limit = c + int(0.1 * sample_rate)

    effective_limit = min(limit_frames, silence_limit) if len(b) > 0 and not np.all(b[c:] != 0) else limit_frames

    total = max(n, c + len(wet_tail))
    full = np.zeros((total, 2), dtype=np.float64)
    full[:n] = dry
    full[:c] = washed[:c]
    ra = min(int(round(CUT_A_RAMP_S * sample_rate)), c)
    if ra:
        full[c - ra:c] *= dj_dsp._ramp(ra, down=True)[:, None]

    keep_tail = min(len(wet_tail), max(0, effective_limit - c))
    if keep_tail > 0:
        full[c:c + keep_tail] += wet_tail[:keep_tail]

    if is_mono:
        full[:, 1] = full[:, 0]

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


def _render_smart_filter_eq(a, b, plan, sample_rate):
    """Mezcla inteligente con cambio de graves Linkwitz-Riley y Mid-Carve dinámico
    en el rango vocal (1-3 kHz) para evitar colisión de voces en mezclas largas."""
    np = _np()
    n = len(a)
    a64, b64 = a.astype(np.float64), b.astype(np.float64)

    # Mid-Carve en A: despeja rango vocal 1500 Hz
    a_carved = dj_dsp.mid_carve(a64, center_hz=1500.0, width_oct=1.2, gain_db=-5.0,
                                sample_rate=sample_rate).astype(np.float64)
    u = np.linspace(0.0, 1.0, n)
    carve_w = np.clip((u - 0.2) / 0.4, 0.0, 1.0)[:, None]
    pa = a64 * (1.0 - carve_w) + a_carved * carve_w
    pb = b64

    angle = (np.arange(n, dtype=np.float64) + 0.5) / n * (math.pi / 2.0)
    fade_a, fade_b = np.cos(angle), np.sin(angle)
    step = min(dj_dsp.SWAP_STEP_S, n / sample_rate)
    swap = min(max(float(plan.bass_swap_at), step / 2.0), n / sample_rate - step / 2.0)
    bass_b = dj_dsp.band_gains(n, [(swap - step / 2.0, 0.0), (swap + step / 2.0, 1.0)], sample_rate).astype(np.float64)
    bass_a = 1.0 - bass_b
    low_a = dj_dsp._lowpass(pa, dj_dsp.LOW_HZ, sample_rate)
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
    if kind == TYPE_BLEND or (cut and kind not in (TYPE_ECHO_OUT, TYPE_DELAY_DROP, TYPE_REVERB_WASH)):
        return dj_dsp.render_transition(a, b, plan, sample_rate), empty
    if cut:
        dry = dj_dsp.render_transition(a, b, plan, sample_rate).astype(np.float64)
        a_line, c = a, len(a)
    else:
        n = int(round(float(plan.length_s) * sample_rate))
        a, b = dj_dsp._fit(a, n), dj_dsp._fit(b, n)
        if kind == TYPE_FILTER:
            return _render_filter(a, b, plan, sample_rate), empty
        if kind == TYPE_SMART_FILTER_EQ:
            return _render_smart_filter_eq(a, b, plan, sample_rate), empty
        c = _cut_point(plan, n, sample_rate)
        dry = _dry_cut(a.astype(np.float64), b.astype(np.float64), c, sample_rate)
        if kind == TYPE_CUT_BAR:
            return dry.astype(np.float32), empty
        a_line = a

    limit = len(dry) + (10 ** 12 if tail_s is None else max(0, int(round(float(tail_s) * sample_rate))))
    if kind == TYPE_ECHO_OUT:
        return _render_echo_out(dry, a_line, c, bpm, sample_rate, limit)
    if kind == TYPE_DELAY_DROP:
        return _render_delay_drop(dry, a_line, c, bpm, sample_rate, limit)
    if kind == TYPE_REVERB_WASH:
        return _render_reverb_wash(dry, a_line, b, c, sample_rate, limit)
    return dry.astype(np.float32), empty


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


def choose_type(a_info: dict, b_info: dict, plan: TransitionPlan, bpm_a: float = None,
                profile: str = None):
    """(tipo, motivo en español) para pasar de A a B con `plan` (el de `mix_planner.plan_transition`). `a_info` y `b_info`
    son las fichas de `mix_types` (duration_s o duration_ms, intro, outro, bpm, beatgrid, tone, energy; lo que falte cuenta
    como «no se sabe»). `bpm_a`: tempo de A si se sabe mejor que por la ficha. `profile`: 'club', 'radio' o 'chill'.
    Nunca falla."""
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

    energy_a = mix_planner._number(a_info.get("energy"))
    energy_b = mix_planner._number(b_info.get("energy"))

    # 1. Plan de corte
    if is_cut:
        far = ratio is not None and abs(ratio - 1.0) > mix_planner.MAX_TEMPO_CHANGE + 1e-9
        if tempo_a and (far or abrupt):
            what = f"tempos a {_pct(ratio)}" if far else abrupt_note
            if (energy_a is not None and energy_a >= 0.75) or profile == "radio":
                return TYPE_DELAY_DROP, f"delay drop con ping-pong: se corta ({what}) y el delay rítmico sostiene el cambio"
            return TYPE_ECHO_OUT, f"eco de salida: se corta ({what}) y el eco al tempo de la que suena tapa el corte"
        if profile == "radio" and tempo_a:
            return TYPE_DELAY_DROP, "delay drop: corte dinámico perfil Radio"
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
        if (energy_a is not None and energy_a >= 0.75) or profile == "radio":
            return TYPE_DELAY_DROP, "delay drop con ping-pong: " + abrupt_note
        if profile == "chill":
            return TYPE_REVERB_WASH, "reverb wash: salida suave con cola etérea tras final brusco"
        return TYPE_ECHO_OUT, "eco de salida: " + abrupt_note

    # 4. Caída pronunciada de energía o perfil Chill
    if profile == "chill":
        return TYPE_REVERB_WASH, "reverb wash: perfil Chill con transición etérea y cola envolvente"
    if energy_a is not None and energy_b is not None and (energy_a - energy_b) >= 0.35:
        return TYPE_REVERB_WASH, f"washout con reverb envolvente: caída notable de energía ({energy_a:.2f} a {energy_b:.2f})"

    # 5. Tonos
    tone_a, tone_b = camelot.normalize(a_info.get("tone")), camelot.normalize(b_info.get("tone"))
    key_score = camelot.score(tone_a, tone_b)
    if tone_a and tone_b and key_score <= camelot.SCORE_BAD:
        if energy_a is not None and energy_a >= 0.75 and (energy_a - (energy_b or 0.5)) > 0.2:
            return TYPE_REVERB_WASH, f"washout con reverb: los tonos chocan ({tone_a} y {tone_b}) y la reverb disuelve la disonancia"
        return TYPE_FILTER, f"filtro: los tonos chocan ({tone_a} y {tone_b}) y el tempo se puede igualar"
    if key_score < camelot.SCORE_GOOD:
        what = f"tonos que encajan a medias ({tone_a} y {tone_b})" if tone_a and tone_b else "no se sabe el tono de las dos"
        if length > LONG_MIX_S + 1e-9:
            return TYPE_FILTER, f"filtro: {what} y la mezcla es larga ({mix_points.fmt_seconds(length)})"
        return TYPE_BLEND, f"mezcla: {what}, pero la mezcla es corta ({mix_points.fmt_seconds(length)})"

    # 6. Todo encaja: mezcla larga
    tones = "mismo tono" if tone_a == tone_b else f"tonos compatibles ({tone_a} y {tone_b})"
    if ((energy_a is not None and energy_a >= 0.75 and energy_b is not None and energy_b >= 0.70)
            or profile == "club") and length > LONG_MIX_S + 1e-9:
        return TYPE_SMART_FILTER_EQ, f"mezcla inteligente con Mid-Carve: energía alta, {tones} y despeje de medios vocales"

    return TYPE_BLEND, f"mezcla larga con cambio de graves: rejillas fiables, tempo igualable y {tones}"
