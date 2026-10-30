"""Puntuador automático de transiciones del modo DJ (fase 25): una nota de 0 a 1 y un veredicto («ok», «dudosa» o
«descartar») sin que nadie escuche, para tirar lo malo antes de que suene.

Dos niveles, del más barato al más caro:
  * `score_plan(a_info, b_info, plan)`: solo con los datos del análisis (sin audio). Mira el cambio de tempo, si los tonos
    casan en la rueda Camelot, lo fiables que son las dos rejillas de golpes, el salto de energía y si la mezcla cabe en
    las canciones. Cuesta microsegundos: sirve para descartar planes antes de cargar y renderizar nada.
  * `score_audio(mix, a_part, b_part, plan, ...)`: con la mezcla ya hecha (`dj_dsp.render_transition`) y los trozos de
    A y de B que entraron en ella. Mide desfase de golpes, graves que chocan, voces solapadas, tonos, saltos de volumen,
    recorte, huecos de silencio y clics. Una mezcla de 32 s se mide en unas décimas de segundo.

Las dos devuelven {"score": 0..1, "verdict": "ok" | "dudosa" | "descartar", "reasons": [str], "metrics": {...}}. Cada
métrica es un dict con su valor físico ("value", en las unidades de su nombre) y su nota ("note", 0..1; None si no se pudo
medir o no aplica), más algún dato de apoyo. La nota final es la media de las notas con los pesos de abajo (las que son
None no cuentan y el resto se reparte su peso). Encima hay reglas duras: algunos fallos bastan para dudar o descartar
aunque la media salga bien (un clic, un recorte fuerte, un galope claro...). El veredicto es el peor de los dos y la nota
se recorta para que cuadre con él (una «descartar» nunca tiene más nota que una «dudosa», ni esta más que una «ok»).

Qué NO garantiza: la puerta de la fase 25 («descarta las mismas transiciones que descartarías tú en 8 de 10 casos») solo
se puede comprobar escuchando. Los umbrales de abajo son una elección razonable y razonada, no un dato medido con oídos;
las pruebas (pruebas/prueba_puntuador.py) solo demuestran que cada medida da el valor físico correcto en casos sintéticos
construidos a propósito. Cuando haya votos (fase 24), los umbrales se deben ajustar con ellos.

Cómo se mide cada cosa con audio (todas las funciones aceptan mono, estéreo, vacío y NaN sin lanzar excepciones):
  * Graves: la mezcla de los dos canales se filtra por debajo de 250 Hz con las mismas máscaras de `dj_dsp` (Linkwitz-Riley
    de 8.º orden, fase cero) y a la vez se rebaja a 2.205 Hz, todo con una sola FFT (la banda grave no tiene nada por encima
    de 1 kHz, así que basta con quedarse con los primeros puntos del espectro).
  * beat_offset_ms: curva de novedad de los graves de cada trozo (subidas del logaritmo de su envolvente de 25 ms respecto a
    10 ms antes, suavizadas 10 ms), pesada por el tramo en que suenan las dos (sen(2θ) del fundido). Con la duración de un
    golpe (de la rejilla de A, o la de B corregida por su estiramiento; sin rejillas, de la autocorrelación) cada curva se
    dobla sobre un golpe: el perfil medio de dónde caen los ataques dentro del golpe, con todos los golpes de la mezcla. Los
    dos perfiles se correlan en círculo y se toma el pico en ±120 ms (o ±0,45 golpes si es menos); si fuera de esa ventana
    hay un pico claramente mejor (medio golpe, por ejemplo), se da ese. Positivo: B va por detrás de A. Correlar las curvas
    sin doblar no sirvió con canciones reales (dibujos de bajo distintos: correlación de 0,05 a 0,18 incluso entre una
    canción y ella misma un golpe después; doblada, 0,99). Sin rejilla es menos fiable (el periodo puede salir el doble o la
    mitad). Si los perfiles no se parecen (correlación < 0,3), no se da valor. Limitación: mide dónde coinciden los ataques
    de graves; con dos dibujos sincopados distintos (dembow contra cuatro por cuatro) el mejor encaje puede no ser el golpe.
  * bass_clash: en tramos de 100 ms se busca qué cantidad de los graves de A y de B lleva la mezcla (mínimos cuadrados:
    graves de la mezcla ≈ ga·graves de A + gb·graves de B). Así se mide la mezcla real, se haya hecho como se haya hecho.
    Un tramo choca si las dos tienen graves en él (cerca de su nivel normal, no entre bombo y bombo) y la mezcla lleva
    los de las dos a más de -12 dB de su nivel original. Valor: tramos que chocan / tramos medidos (toda la mezcla, salvo
    el paso corto del cambio de graves, `plan.bass_swap_at` ± 150 ms). Con bombos sueltos sale menos que el tiempo de
    solape (entre golpe y golpe no hay graves que chocar): un fundido sin cambio de graves da 0,5 a 0,6, no 0,68.
  * loudness_step_db: nivel a corto plazo (RMS de 400 ms, evaluado cada 10 ms y no cada 100 ms: con pasos de 100 ms un
    salto que cae entre dos pasos se subestima hasta 3 dB) de la mezcla con los 2 s de antes (`a_before`) y de después
    (`b_after`) si se dan. El salto es la diferencia entre dos ventanas seguidas (400 ms y los 400 ms siguientes). Se
    compara con el que «traían» A y B: el de la curva esperada (potencia de A por su fundido² más la de B por el suyo), de
    modo que un cambio que ya está en la canción (la entrada de un estribillo) no cuenta y uno que mete la mezcla sí. En un
    corte, el salto entre A y B sí cuenta (es justo lo que el corte crea). La curva esperada no incluye el cambio de
    graves: si los graves de B suenan mucho más fuertes que los de A, el salto en ese instante cuenta (se oye). Valor:
    el mayor exceso, en dB.
  * clipping: fracción de valores (muestras de los dos canales) con |x| > 1,0; la nota usa lo que la mezcla añade sobre
    lo que ya recortaban A y B (un mp3 que ya pasa un poco de 1,0 no es culpa de la mezcla).
  * silence_gap_ms: tramo más largo por debajo de -60 dBFS (bloques de 10 ms) dentro de la mezcla.
  * click: mayor salto entre muestras consecutivas dividido por el salto normal de su alrededor (RMS de los saltos en
    50 ms). En música sale de 2 a 6; un clic, decenas. Solo cuenta como clic si además pasa de 1,5 veces lo que ya tenían
    A y B medido igual (un golpe seco que ya está en la canción no es culpa de la mezcla).

Qué tiene que pasar quien integre (ver `dj_engine._blend`): `mix` = lo que devuelve `render_transition`; `a_part` = el trozo
de A que se le pasó (a.data[a_mix:a_mix + n]); `b_part` = el de B (ya estirado y con su ganancia, tal cual se le pasó);
`a_before` = los 2 s de A justo antes de la mezcla; `b_after` = los 2 s del cuerpo de B justo después. En un corte, `a_part`
y `b_part` son las dos piezas, que en la mezcla van una detrás de otra. Las curvas de voz, una lectura por segundo desde el
primer fotograma de cada trozo."""
import logging
import math

from services import camelot, dj_dsp, key_detect, mix_points
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid

logger = logging.getLogger(__name__)

VERDICT_OK, VERDICT_DOUBT, VERDICT_DISCARD = "ok", "dudosa", "descartar"
_LEVELS = (VERDICT_OK, VERDICT_DOUBT, VERDICT_DISCARD)

# ------------------------------------------------------------------ veredicto a partir de la nota
OK_SCORE = 0.75                 # desde aquí, «ok»: todas las medidas en su zona buena o casi
DISCARD_SCORE = 0.5             # por debajo, «descartar»: más de la mitad del peso está en zona mala

# ------------------------------------------------------------------ plan (sin audio)
TEMPO_GOOD, TEMPO_BAD = 0.02, 0.10      # un 2 % de estiramiento no se nota; hacia el 8 al 10 % rubberband ya suena a máquina
MAX_TEMPO_CHANGE = 0.08                 # el mismo tope que `mix_planner`: más allá, una mezcla se descarta (debió ser un corte)
GRID_GOOD, GRID_BAD = 0.7, 0.3          # confianza de rejilla: 0,4 es el mínimo con que se usa (track_analysis); 0,7, de fiar
GRID_USABLE = 0.4                       # igual que track_analysis.MIN_GRID_CONFIDENCE (no se importa: arrastraría Qt)
NO_GRID_LONG_S = 8.0                    # sin rejilla, una mezcla más larga que esto no cuadra golpes: se duda
ENERGY_GOOD, ENERGY_BAD = 0.10, 0.50    # diferencia de energía (0 a 1): 0,1 es ruido de la medida; 0,5, de balada a fiesta
SHARE_GOOD, SHARE_BAD = 1 / 3, 0.5      # parte de la canción más corta que se come la mezcla (mix_points tope: un tercio)
FIT_TOLERANCE_S = 0.05                  # margen al comprobar que la mezcla cabe en las canciones (redondeos del planificador)
TONE_DOUBT_WEIGHT = 0.5                 # un tono dudoso (confianza < key_detect.CONFIDENT) pesa la mitad
TONE_CUT_WEIGHT = 0.5                   # en un corte los tonos casi no se solapan: su peso se reduce a la mitad
TONE_LONG_S = 8.0                       # dos tonos que chocan con más de esto de mezcla: se duda

PLAN_WEIGHTS = {"tempo_change": 0.30, "tone_clash": 0.25, "grid_confidence": 0.20, "energy_diff": 0.10, "mix_share": 0.15}

# ------------------------------------------------------------------ audio
LOW_HZ = dj_dsp.LOW_HZ                  # graves: por debajo de 250 Hz, el mismo cruce que el cambio de graves
LOW_RATE = 2205.0                       # a qué frecuencia se rebajan los graves (de sobra para 250 Hz y 0,45 ms de detalle)
BEAT_WINDOW_MS = 120.0                  # se busca el desfase en ±120 ms (más allá ya no es «galope», es otro golpe)
BEAT_WINDOW_BEATS = 0.45                # y nunca más de 0,45 golpes (con tempos rápidos, medio golpe es ambiguo)
BEAT_ENV_S = 0.025                      # envolvente de los graves: 25 ms (más de un periodo de 40 Hz: quita el rizado de un 808)
BEAT_RISE_S = 0.010                     # la subida se mide contra 10 ms antes (no muestra a muestra: ahí manda el ruido)
BEAT_RISE_FLOOR = 0.05                  # subidas de menos de 0,4 dB en 10 ms no cuentan (rizado de un tono; un bombo sube 20 dB)
BEAT_SMOOTH_S = 0.010                  # y se suaviza 10 ms (los golpes repetidos se parecen; el detalle fino no)
BEAT_MIN_CORR = 0.30                    # correlación mínima de los perfiles de golpe para decir que hay golpes comunes
BEAT_MIN_RISE = 0.5                     # subida total de la envolvente (en logaritmo natural) por segundo para decir que hay
                                        # ataques: un bombo sube de 3 a 5 cada golpe; un tono continuo, casi 0
BEAT_MIN_BEATS = 4                     # para doblar las curvas sobre un golpe hacen falta al menos 4 golpes de mezcla
BEAT_BEYOND = 1.2                       # si fuera de la ventana hay un pico un 20 % mejor, el desfase real es ese (≥ 120 ms)
BEAT_PERIOD_MIN = 0.1                   # sin rejilla, el periodo se saca de la autocorrelación si destaca al menos esto
BEAT_GOOD_MS, BEAT_BAD_MS = 10.0, 60.0  # 10 ms no se oye; 30 ms ya galopa (bombo doble «ta-ta»); 60 ms es claramente roto
BEAT_DOUBT_MS, BEAT_DISCARD_MS = 30.0, 50.0
BASS_FRAME_S = 0.10                     # tramos de 100 ms para separar qué graves lleva la mezcla
BASS_REL_DB = -12.0                     # los graves de una canción «suenan» si la mezcla los lleva a más de -12 dB de su nivel
BASS_PRESENT_DB = -20.0                 # y solo en tramos con graves de verdad: a menos de 20 dB de los suyos normales y de
                                        # los de la mezcla (entre bombo y bombo no hay nada que chocar)
BASS_SAME_CORR = 0.9                    # si los graves de A y B se parecen tanto, son el mismo sonido: no se puede separar
BASS_SWAP_GUARD_S = 0.15                # alrededor del cambio de graves (40 ms de paso + un tramo) no se cuenta
BASS_GOOD, BASS_BAD = 0.05, 0.30        # fracción de la mezcla con graves dobles
BASS_DOUBT, BASS_DISCARD = 0.15, 0.40
AUDIBLE_GAIN = 0.25                     # una canción suena en la mezcla si su fundido pasa de -12 dB
VOCAL_ON = 0.5                          # una lectura de voz cuenta como «hay voz» desde 0,5
VOCAL_GOOD, VOCAL_BAD = 0.10, 0.40      # fracción de la mezcla con las dos voces
VOCAL_DOUBT, VOCAL_DISCARD = 0.25, 0.50
VOCAL_DISCARD_MIN_S = 4                 # y para descartar, al menos 4 s seguidos o no (una frase entera pisada)
LOUD_WINDOW_S = 0.400                   # nivel a corto plazo: RMS de 400 ms
LOUD_HOP_S = 0.010                      # evaluado cada 10 ms
LOUD_CONTEXT_S = 2.0                    # 2 s antes y después de la mezcla
LOUD_FLOOR_DB = -60.0                   # suelo de la curva de nivel (no se miden saltos de ruido de fondo)
LOUD_SILENT_DB = -45.0                  # una ventana más floja que esto es silencio o un final apagándose: el salto desde o
                                        # hacia ella no cuenta como salto de volumen (es un hueco, y eso lo mide silence_gap_ms)
LOUD_GOOD_DB, LOUD_BAD_DB = 3.0, 8.0    # 3 dB es un cambio que se nota poco; 8 dB de golpe es un salto evidente
LOUD_DOUBT_DB, LOUD_DISCARD_DB = 5.0, 8.0   # (con rampas de 20 ms un salto de 9 dB se mide 8,5: el tope no puede ser 9)
CLIP_GOOD, CLIP_BAD = 1e-5, 1e-3        # fracción de valores que pasan de 1,0 añadida por la mezcla
CLIP_DOUBT, CLIP_DISCARD = 1e-4, 1e-3   # 0,1 % (unas 1.400 muestras en 16 s) ya es distorsión audible en los golpes
GAP_BLOCK_S = 0.010
GAP_FLOOR_DB = -60.0
GAP_GOOD_MS, GAP_BAD_MS = 100.0, 500.0  # 100 ms de silencio pasan por una pausa; medio segundo es un hueco
GAP_DOUBT_MS, GAP_DISCARD_MS = 250.0, 500.0
CLICK_WINDOW_S = 0.050                  # «lo normal» alrededor de cada salto: 50 ms
CLICK_FLOOR = 1e-4                      # salto normal mínimo (-80 dB): en silencio digital no se divide entre cero
CLICK_RATIO = 10.0                      # un salto de 10 veces lo normal de su alrededor (la música llega a 5 o 6)
CLICK_VS_PARTS = 1.5                    # y 1,5 veces lo que ya tenían A y B medido igual

AUDIO_WEIGHTS = {"beat_offset_ms": 0.25, "bass_clash": 0.20, "vocal_overlap": 0.15, "tone_clash": 0.10,
                 "loudness_step_db": 0.15, "clipping": 0.05, "silence_gap_ms": 0.05, "click": 0.05}


# ------------------------------------------------------------------ utilidades
def _lin(value, good, bad):
    """Nota 0..1: 1 hasta `good`, 0 desde `bad` y en línea recta entre medias (sirve también con good > bad)."""
    if value is None:
        return None
    if good == bad:
        return 1.0 if value <= good else 0.0
    return float(min(1.0, max(0.0, 1.0 - (value - good) / (bad - good))))


def _num(value, default=None):
    """`value` como número finito, o `default`."""
    if isinstance(value, bool):
        return default
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def _db(x: float) -> str:
    return f"{x:.1f} dB".replace(".", ",")


class _Verdict:
    """Acumula métricas, motivos y reglas duras, y al final da el dict de resultado."""

    def __init__(self, weights):
        self.weights = weights
        self.metrics = {}
        self.reasons = []
        self.level = 0

    def metric(self, name, value, note, **extra):
        self.metrics[name] = {"value": value, "note": None if note is None else round(float(note), 3), **extra}

    def rule(self, verdict, reason):
        self.level = max(self.level, _LEVELS.index(verdict))
        self.reasons.append(reason)

    def note(self, reason):
        self.reasons.append(reason)

    def result(self) -> dict:
        total = weight = 0.0
        for name, w in self.weights.items():
            note = (self.metrics.get(name) or {}).get("note")
            if note is not None:
                total += w * note
                weight += w
        score = total / weight if weight > 0 else 0.5
        level = self.level
        if weight <= 0:
            level = max(level, 1)
            self.reasons.append("nada que medir: no se puede opinar")
        level = max(level, 0 if score >= OK_SCORE else 1 if score >= DISCARD_SCORE else 2)
        if level == 1:
            score = min(score, OK_SCORE - 0.001)
        elif level == 2:
            score = min(score, DISCARD_SCORE - 0.001)
        if not self.reasons:
            self.reasons.append("nada que objetar en lo medido")
        return {"score": round(score, 3), "verdict": _LEVELS[level], "reasons": self.reasons, "metrics": self.metrics}


def _plan_fields(plan):
    """(es corte, duración, tempo de B, instante del cambio de graves) de un plan, con valores por omisión si falta algo."""
    kind = getattr(plan, "kind", None)
    length = max(0.0, _num(getattr(plan, "length_s", 0.0), 0.0))
    ratio = _num(getattr(plan, "tempo_ratio_b", 1.0), 1.0)
    try:
        swap = _num(plan.bass_swap_at, length / 2.0)
    except Exception:
        swap = length / 2.0
    return kind == KIND_CUT or length <= 0, length, ratio, swap


def _tone_metric(v: _Verdict, tone_a, tone_b, conf_a, conf_b, weight_scale: float, long_overlap: bool):
    """Métrica «tone_clash»: 0 = mismo tono, 1 = chocan (1 menos la puntuación de `camelot.score`)."""
    code_a, code_b = camelot.from_text(tone_a), camelot.from_text(tone_b)
    if not code_a or not code_b:
        v.metric("tone_clash", None, None, a=code_a, b=code_b)
        return
    conf = min(_num(conf_a, 1.0), _num(conf_b, 1.0))
    doubtful = conf < key_detect.CONFIDENT
    clash = 1.0 - camelot.score(code_a, code_b)
    weight = (TONE_DOUBT_WEIGHT if doubtful else 1.0) * weight_scale
    note = 1.0 - clash * weight
    distance, same_letter = camelot.steps(code_a, code_b)
    v.metric("tone_clash", round(clash, 3), note, a=code_a, b=code_b, steps=distance, same_letter=same_letter,
             confident=not doubtful)
    if clash >= 1.0 - camelot.SCORE_BAD - 1e-9:
        if doubtful:
            v.note(f"tonos que chocan ({code_a} y {code_b}), pero alguno es dudoso: pesa menos")
        elif long_overlap:
            v.rule(VERDICT_DOUBT, f"tonos que chocan ({code_a} y {code_b}) en una mezcla larga")
        else:
            v.note(f"tonos que chocan ({code_a} y {code_b})")


# ------------------------------------------------------------------ plan (sin audio)
def _grid_conf(info: dict):
    """Confianza de la rejilla de golpes de una ficha, o None si no tiene una utilizable."""
    if "beatgrid" in info:
        grid = info.get("beatgrid")
        return _num(grid.confidence, 0.0) if isinstance(grid, BeatGrid) else None
    conf = _num(info.get("beat_conf"))
    return conf if conf is not None and conf >= GRID_USABLE and _num(info.get("beat_bpm")) else None


def score_plan(a_info, b_info, plan) -> dict:
    """Nota barata de una transición, solo con las fichas de las dos canciones (`mix_types.TrackInfo` o el análisis de
    `track_analysis`) y el `TransitionPlan`. Nunca lanza excepciones. Ver la explicación del módulo."""
    v = _Verdict(PLAN_WEIGHTS)
    try:
        _score_plan(v, a_info if isinstance(a_info, dict) else {}, b_info if isinstance(b_info, dict) else {}, plan)
    except Exception as e:
        logger.warning("no se pudo puntuar el plan: %s", e)
        v.rule(VERDICT_DOUBT, f"no se pudo puntuar el plan: {e}")
    return v.result()


def _score_plan(v: _Verdict, a: dict, b: dict, plan):
    if plan is None:
        v.rule(VERDICT_DISCARD, "no hay plan")
        return
    cut, length, ratio, _swap = _plan_fields(plan)
    a_start, b_start = _num(getattr(plan, "a_start_s", None)), _num(getattr(plan, "b_start_s", None))
    if a_start is None or b_start is None or a_start < 0 or b_start < 0 or ratio <= 0:
        v.rule(VERDICT_DISCARD, "el plan tiene números imposibles (inicio negativo o que no es un número)")
        return
    v.metric("kind", "corte" if cut else "mezcla", None, length_s=length)
    # tempo
    if cut:
        v.metric("tempo_change", None, None)
    else:
        change = abs(ratio - 1.0)
        v.metric("tempo_change", round(change, 4), _lin(change, TEMPO_GOOD, TEMPO_BAD), ratio=ratio)
        if change > MAX_TEMPO_CHANGE + 1e-9:
            v.rule(VERDICT_DISCARD, f"cambio de tempo de {_pct(change)}: pasa del ±{round(MAX_TEMPO_CHANGE * 100)} %")
        elif change > TEMPO_GOOD:
            v.note(f"la que entra se estira un {_pct(change)}")
    # tonos
    _tone_metric(v, a.get("tone"), b.get("tone"), a.get("tone_conf"), b.get("tone_conf"),
                 TONE_CUT_WEIGHT if cut else 1.0, not cut and length >= TONE_LONG_S)
    # rejillas
    conf_a, conf_b = _grid_conf(a), _grid_conf(b)
    if cut:
        v.metric("grid_confidence", None, None, a=conf_a, b=conf_b)
    elif conf_a is None or conf_b is None:
        v.metric("grid_confidence", 0.0, 0.0, a=conf_a, b=conf_b)
        which = "las dos" if conf_a is None and conf_b is None else "la que suena" if conf_a is None else "la que entra"
        text = f"sin rejilla de golpes en {which}: los golpes pueden no cuadrar"
        if length > NO_GRID_LONG_S:
            v.rule(VERDICT_DOUBT, text + f" en {mix_points.fmt_seconds(length)} de mezcla")
        else:
            v.note(text)
    else:
        conf = min(conf_a, conf_b)
        v.metric("grid_confidence", round(conf, 3), _lin(conf, GRID_GOOD, GRID_BAD), a=conf_a, b=conf_b)
        if conf < (GRID_GOOD + GRID_BAD) / 2:
            v.note(f"rejilla de golpes poco fiable ({conf:.2f})".replace(".", ","))
    # energía
    e_a, e_b = _num(a.get("energy")), _num(b.get("energy"))
    if e_a is None or e_b is None:
        v.metric("energy_diff", None, None)
    else:
        diff = abs(e_a - e_b)
        v.metric("energy_diff", round(diff, 3), _lin(diff, ENERGY_GOOD, ENERGY_BAD), a=e_a, b=e_b)
        if diff >= (ENERGY_GOOD + ENERGY_BAD) / 2:
            v.note(f"salto de energía grande ({e_a:.2f} a {e_b:.2f})".replace(".", ","))
    # duración: que quepa y que no se coma las canciones
    dur_a, dur_b = mix_points.seconds(a, "duration"), mix_points.seconds(b, "duration")
    if dur_a is not None and a_start + length > dur_a + FIT_TOLERANCE_S:
        v.rule(VERDICT_DISCARD, "la mezcla no cabe en la canción que suena")
    if dur_b is not None and b_start + length * ratio > dur_b + FIT_TOLERANCE_S:
        v.rule(VERDICT_DISCARD, "la mezcla no cabe en la canción que entra")
    known = [d for d in (dur_a, dur_b) if d]
    if cut:
        v.metric("mix_share", 0.0, 1.0)
    elif not known:
        v.metric("mix_share", None, None)
    else:
        share = length / min(known)
        v.metric("mix_share", round(share, 3), _lin(share, SHARE_GOOD, SHARE_BAD))
        if share > SHARE_GOOD + 0.01:
            v.note(f"la mezcla ocupa un {_pct(share)} de la canción más corta")


# ------------------------------------------------------------------ audio: preparación
def _clean(np, x):
    """(audio float32 (n, 2) sin NaN ni infinitos, fracción de valores que no eran números). Lo que no se entiende, vacío."""
    empty = np.zeros((0, 2), dtype=np.float32)
    if x is None:
        return empty, 0.0
    try:
        arr = np.asarray(x, dtype=np.float32)
    except (TypeError, ValueError):
        return empty, 0.0
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.ndim != 2 or arr.shape[1] == 0 or arr.shape[0] == 0:
        return empty, 0.0
    if arr.shape[1] == 1:
        arr = np.repeat(arr, 2, axis=1)
    elif arr.shape[1] > 2:
        arr = arr[:, :2]
    bad = ~np.isfinite(arr)
    frac = float(bad.mean())
    if frac:
        arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)
    return np.ascontiguousarray(arr), frac


def _place(np, x, offset: int, n: int):
    """x colocado en una línea de tiempo de n fotogramas a partir de `offset` (lo que no cabe se corta; el resto, silencio)."""
    out = np.zeros((n, 2), dtype=np.float32)
    if offset < n and len(x):
        k = min(len(x), n - offset)
        out[offset:offset + k] = x[:k]
    return out


def _low_band(np, x, sr: int):
    """Graves (< LOW_HZ) de la mezcla de los dos canales, rebajados a unos LOW_RATE Hz: (señal float64, frecuencia nueva)."""
    step = max(1, int(sr // LOW_RATE))
    rate = sr / step
    n = len(x)
    if n == 0:
        return np.zeros(0), rate
    mono = x.astype(np.float64).mean(axis=1)
    pad = int(0.1 * sr)
    size = dj_dsp._fast_len(-(-(n + pad) // step)) * step
    spec = np.fft.rfft(mono, n=size)
    small = size // step
    freqs = np.fft.rfftfreq(small, 1.0 / rate)
    low = np.fft.irfft(spec[:len(freqs)] * dj_dsp._low_mask(freqs, LOW_HZ), n=small) / step
    return low[:-(-n // step)], rate


def _fades(np, t, length: float):
    """Ganancias de medios y agudos de A y de B en los instantes t (s) de una mezcla de `length` s (como render_transition)."""
    angle = np.clip(t / max(length, 1e-9), 0.0, 1.0) * (math.pi / 2.0)
    return np.cos(angle), np.sin(angle)


# ------------------------------------------------------------------ audio: medidas
def _beat_offset(np, low_a, low_b, rate, length, beat_s):
    """(desfase en ms con B por detrás positivo, correlación del pico) o (None, correlación) si no hay golpes comunes."""
    n = min(len(low_a), len(low_b))
    if n < int(2.0 * rate):
        return None, 0.0
    width = max(1, int(round(BEAT_ENV_S * rate)))
    kernel = np.ones(width) / width
    lag = max(1, int(round(BEAT_RISE_S * rate)))
    smooth = np.hanning(max(3, int(round(BEAT_SMOOTH_S * rate))))
    smooth /= smooth.sum()
    curves = []
    for low in (low_a[:n], low_b[:n]):
        env = np.sqrt(np.convolve(low * low, kernel, mode="same"))
        top = float(env.max())
        if top <= 1e-7:
            return None, 0.0
        log_env = np.log(env + 1e-3 * top)
        rise = np.zeros(n)
        rise[lag:] = log_env[lag:] - log_env[:-lag]
        rise[rise < BEAT_RISE_FLOOR] = 0.0               # el rizado de un tono continuo no es un ataque
        rise[:width + lag] = 0.0                       # los bordes de la envolvente no son golpes
        rise[n - width:] = 0.0
        if rise.sum() / (n / rate) < BEAT_MIN_RISE:      # un colchón o un bajo continuo: no hay ataques que comparar
            return None, 0.0
        curves.append(np.convolve(rise, smooth, mode="same"))
    t = np.arange(n) / rate
    fade_a, fade_b = _fades(np, t, length)
    weight = np.sqrt(np.maximum(2.0 * fade_a * fade_b, 0.0))           # sen(2θ): pesa donde suenan las dos
    na, nb = (c * weight for c in curves)
    period = beat_s or _period(np, na + nb, rate)
    window_s = BEAT_WINDOW_MS / 1000.0
    if period:
        window_s = min(window_s, BEAT_WINDOW_BEATS * period)
    lag_max = max(1, int(window_s * rate))
    if not period or n < BEAT_MIN_BEATS * period * rate:
        # sin periodo de golpe: correlación directa de las dos curvas en la ventana
        na, nb = na - na.mean(), nb - nb.mean()
        size = dj_dsp._fast_len(n + lag_max + 1)
        corr = np.fft.irfft(np.conj(np.fft.rfft(na, size)) * np.fft.rfft(nb, size), size)
        norm = math.sqrt(float((na * na).sum()) * float((nb * nb).sum()))
        if norm <= 0:
            return None, 0.0
        lags = np.concatenate((corr[size - lag_max:], corr[:lag_max + 1])) / norm   # lag de -lag_max a +lag_max
        i = int(np.argmax(lags))
        if lags[i] < BEAT_MIN_CORR:
            return None, float(lags[i])
        return (i - lag_max + _parabolic(lags, i)) / rate * 1000.0, float(lags[i])
    # con periodo: cada curva se «dobla» sobre un golpe (perfil medio de un golpe, con todos los de la mezcla) y se comparan
    # los perfiles en círculo; así no importa que A y B tengan dibujos de bajo distintos, solo dónde caen sus golpes
    bins = max(4, int(round(period * rate)))
    phase = np.minimum(np.floor(np.mod(np.arange(n), period * rate)).astype(np.int64), bins - 1)
    pa = np.bincount(phase, weights=na, minlength=bins)[:bins]
    pb = np.bincount(phase, weights=nb, minlength=bins)[:bins]
    pa, pb = pa - pa.mean(), pb - pb.mean()
    norm = math.sqrt(float((pa * pa).sum()) * float((pb * pb).sum()))
    if norm <= 0:
        return None, 0.0
    corr = np.fft.irfft(np.conj(np.fft.rfft(pa)) * np.fft.rfft(pb), bins) / norm
    lag_max = min(lag_max, (bins - 1) // 2)
    lags = np.concatenate((corr[bins - lag_max:], corr[:lag_max + 1]))
    i = int(np.argmax(lags))
    g = int(np.argmax(corr))
    if max(float(lags[i]), float(corr[g])) < BEAT_MIN_CORR:
        return None, max(float(lags[i]), float(corr[g]))
    if corr[g] > BEAT_BEYOND * lags[i] and corr[g] >= BEAT_MIN_CORR:
        # lo mejor queda fuera de la ventana (medio golpe, por ejemplo): se da ese desfase, que pasa de la ventana
        shift = _parabolic(np.roll(corr, 1 - g)[:3], 1)
        lag = g if g <= bins // 2 else g - bins
        return (lag + shift) / rate * 1000.0, float(corr[g])
    return (i - lag_max + _parabolic(lags, i)) / rate * 1000.0, float(lags[i])


def _parabolic(values, i) -> float:
    """Ajuste de parábola alrededor del máximo `i`: cuánto (de -0,5 a 0,5) está el pico real a la derecha de `i`."""
    if 0 < i < len(values) - 1:
        a, b, c = values[i - 1], values[i], values[i + 1]
        denom = a - 2 * b + c
        if denom < 0:
            return float(min(0.5, max(-0.5, 0.5 * (a - c) / denom)))
    return 0.0


def _period(np, curve, rate):
    """Duración de un golpe (s) a partir de la autocorrelación de una curva de novedad (de 60 a 200 BPM), o None."""
    x = curve - curve.mean()
    n = len(x)
    lo, hi = int(0.3 * rate), int(1.0 * rate)
    if n < 2 * hi:
        return None
    size = dj_dsp._fast_len(2 * n)
    spec = np.fft.rfft(x, size)
    ac = np.fft.irfft(spec * np.conj(spec), size)[:hi + 2]
    if ac[0] <= 0:
        return None
    k = lo + int(np.argmax(ac[lo:hi + 1]))
    if ac[k] / ac[0] < BEAT_PERIOD_MIN:
        return None
    return (k + _parabolic(ac, k)) / rate


def _bass_clash(np, low_m, low_a, low_b, rate, swap_s):
    """(fracción de tramos con graves de las dos, tramos medidos) según cuánto de cada una lleva la mezcla."""
    frame = max(4, int(round(BASS_FRAME_S * rate)))
    count = min(len(low_m), len(low_a), len(low_b)) // frame
    if count < 1:
        return None, 0
    shape = (count, frame)
    m, a, b = (x[:count * frame].reshape(shape) for x in (low_m, low_a, low_b))
    saa, sbb, sab = (a * a).sum(1), (b * b).sum(1), (a * b).sum(1)
    sma, smb, smm = (m * a).sum(1), (m * b).sum(1), (m * m).sum(1)
    ridge = 1e-9 * (saa + sbb) + 1e-18
    det = (saa + ridge) * (sbb + ridge) - sab * sab
    ga = (sma * (sbb + ridge) - smb * sab) / det
    gb = (smb * (saa + ridge) - sma * sab) / det
    rms_a, rms_b = np.sqrt(saa / frame), np.sqrt(sbb / frame)
    ref = float(np.percentile(np.sqrt(smm / frame), 90))
    if ref <= 1e-6:
        return 0.0, count
    present = 10 ** (BASS_PRESENT_DB / 20.0)
    # cada una «tiene graves» en el tramo si están cerca de su nivel normal (no entre bombo y bombo) y, puestos en la mezcla
    # con su ganancia, no son un rumor despreciable al lado de los graves de la mezcla
    on_a = (rms_a >= present * float(np.percentile(rms_a, 90))) & (np.abs(ga) * rms_a >= present * ref)
    on_b = (rms_b >= present * float(np.percentile(rms_b, 90))) & (np.abs(gb) * rms_b >= present * ref)
    gain_min = 10 ** (BASS_REL_DB / 20.0)
    corr = np.abs(sab) / np.sqrt(saa * sbb + 1e-30)
    clash = on_a & on_b & (np.abs(ga) >= gain_min) & (np.abs(gb) >= gain_min) & (corr < BASS_SAME_CORR)
    centres = (np.arange(count) + 0.5) * frame / rate
    keep = np.abs(centres - swap_s) > BASS_SWAP_GUARD_S + BASS_FRAME_S / 2
    if not keep.any():
        return 0.0, 0
    return float(clash[keep].mean()), int(keep.sum())


def _vocal_overlap(np, a_vocal, b_vocal, n, sr, length):
    """(fracción de segundos con voz en las dos y audibles, racha más larga en s), o (None, 0) si falta alguna curva."""
    def curve(x):
        try:
            arr = np.asarray(x, dtype=np.float64).ravel()
        except (TypeError, ValueError):
            return None
        return np.clip(np.nan_to_num(arr, nan=0.0), 0.0, 1.0) if arr.size else None

    va, vb = curve(a_vocal) if a_vocal is not None else None, curve(b_vocal) if b_vocal is not None else None
    seconds = int(math.ceil(n / sr))
    if va is None or vb is None or seconds < 1:
        return None, 0
    va = np.pad(va[:seconds], (0, max(0, seconds - len(va))))
    vb = np.pad(vb[:seconds], (0, max(0, seconds - len(vb))))
    fade_a, fade_b = _fades(np, np.arange(seconds) + 0.5, length)
    both = (va >= VOCAL_ON) & (vb >= VOCAL_ON) & (fade_a >= AUDIBLE_GAIN) & (fade_b >= AUDIBLE_GAIN)
    run = best = 0
    for flag in both:
        run = run + 1 if flag else 0
        best = max(best, run)
    return float(both.mean()), best


def _block_power(np, x, block: int):
    """Potencia media (de los dos canales) de cada bloque de `block` fotogramas (el último bloque incompleto se descarta)."""
    count = len(x) // block
    if count < 1:
        return np.zeros(0)
    p = (x[:count * block].astype(np.float64) ** 2).mean(axis=1)
    return p.reshape(count, block).mean(axis=1)


def _loudness(np, mix, a_line, b_line, gain_a, gain_b, tail, head, sr, cut_frame):
    """(mayor exceso de salto en dB, mayor salto en bruto en dB, instante del exceso en s desde el principio de la mezcla).
    a_line y b_line: A y B colocadas en la línea de tiempo de la mezcla; gain_a / gain_b: su ganancia por fotograma."""
    block = max(1, int(round(LOUD_HOP_S * sr)))
    win = max(1, int(round(LOUD_WINDOW_S / LOUD_HOP_S)))
    k_tail = len(tail) // block * block
    tail = tail[len(tail) - k_tail:]
    line = np.concatenate((tail, mix, head), axis=0)
    pa = np.concatenate((tail, a_line, np.zeros_like(head)), axis=0)
    pb = np.concatenate((np.zeros_like(tail), b_line, head), axis=0)
    ga = np.concatenate((np.ones(len(tail)), gain_a, np.zeros(len(head))))
    gb = np.concatenate((np.zeros(len(tail)), gain_b, np.ones(len(head))))
    p_mix = _block_power(np, line, block)
    count = len(p_mix)
    if count < 2 * win:
        return None, None, None
    ga_b = ga[:count * block].reshape(count, block).mean(axis=1)
    gb_b = gb[:count * block].reshape(count, block).mean(axis=1)
    p_exp = ga_b ** 2 * _block_power(np, pa, block) + gb_b ** 2 * _block_power(np, pb, block)
    floor = 10 ** (LOUD_FLOOR_DB / 10.0)

    def level(p):
        c = np.concatenate(([0.0], np.cumsum(p)))
        mean = (c[win:] - c[:-win]) / win
        return 10.0 * np.log10(np.maximum(mean, floor))

    lm, le = level(p_mix), level(p_exp)
    step_m = lm[win:] - lm[:-win]
    step_e = le[win:] - le[:-win]
    if cut_frame is not None:                    # en un corte, el salto de A a B lo crea el corte: no hay nada que excusar
        j = np.arange(len(step_m))
        switch = (k_tail + cut_frame) / block
        step_e = np.where((j <= switch) & (switch <= j + 2 * win), 0.0, step_e)
    # entrar o salir de un silencio no es un salto de volumen: es un hueco (lo mide silence_gap_ms)
    sound = (lm[win:] > LOUD_SILENT_DB) & (lm[:-win] > LOUD_SILENT_DB)
    step_m = np.where(sound, step_m, 0.0)
    excess = np.where(sound, np.abs(step_m - step_e), 0.0)
    i = int(np.argmax(excess))
    at = (i + win) * block / sr - k_tail / sr
    return float(excess[i]), float(np.abs(step_m).max()), at


def _silence_gap_ms(np, mix, sr):
    block = max(1, int(round(GAP_BLOCK_S * sr)))
    p = _block_power(np, mix, block)
    if not len(p):
        return 0.0
    silent = p < 10 ** (GAP_FLOOR_DB / 10.0)
    run = best = 0
    for flag in silent:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best * block / sr * 1000.0


def _click_ratio(np, x, sr):
    """(mayor salto entre muestras / salto normal de su alrededor, instante en s)."""
    if len(x) < 3:
        return 0.0, None
    d = np.abs(np.diff(x.astype(np.float64), axis=0))
    half = max(1, int(CLICK_WINDOW_S * sr) // 2)
    c = np.concatenate((np.zeros((1, d.shape[1])), np.cumsum(d * d, axis=0)), axis=0)
    idx = np.arange(len(d))
    lo, hi = np.clip(idx - half, 0, len(d)), np.clip(idx + half + 1, 0, len(d))
    local = np.sqrt((c[hi] - c[lo]) / (hi - lo)[:, None])
    ratio = d / np.maximum(local, CLICK_FLOOR)
    k = int(np.argmax(ratio))
    return float(ratio.flat[k]), (k // d.shape[1] + 1) / sr


# ------------------------------------------------------------------ audio: entrada
def score_audio(mix, a_part, b_part, plan, grid_a=None, grid_b=None, a_vocal=None, b_vocal=None, sample_rate=SAMPLE_RATE,
                tone_a=None, tone_b=None, tone_conf_a=None, tone_conf_b=None, a_before=None, b_after=None) -> dict:
    """Nota de una transición ya renderizada. `mix`: la salida de `dj_dsp.render_transition`; `a_part` y `b_part`: los trozos
    que se le pasaron (B ya estirada); `plan`: el `TransitionPlan`. Opcionales: las rejillas (para acotar la búsqueda del
    desfase a menos de medio golpe), las curvas de voz (una lectura por segundo, 0 a 1, desde el principio de cada trozo),
    los tonos Camelot y su confianza, y `a_before` / `b_after` (lo que suena justo antes y justo después de la mezcla, para
    medir también el salto de volumen en sus extremos; se usan los últimos / primeros 2 s). Nunca lanza excepciones."""
    v = _Verdict(AUDIO_WEIGHTS)
    np = key_detect._numpy()
    if np is None:
        v.rule(VERDICT_DOUBT, "sin numpy no se puede medir el audio")
        return v.result()
    try:
        _score_audio(np, v, mix, a_part, b_part, plan, grid_a, grid_b, a_vocal, b_vocal, sample_rate,
                     (tone_a, tone_b, tone_conf_a, tone_conf_b), a_before, b_after)
    except Exception as e:
        logger.warning("no se pudo medir la transición: %s", e)
        v.rule(VERDICT_DOUBT, f"no se pudo medir el audio: {e}")
    return v.result()


def _score_audio(np, v, mix, a_part, b_part, plan, grid_a, grid_b, a_vocal, b_vocal, sample_rate, tones, a_before, b_after):
    sr = int(_num(sample_rate, SAMPLE_RATE)) if _num(sample_rate, 0) >= 8000 else SAMPLE_RATE
    mix, bad_mix = _clean(np, mix)
    a, _bad_a = _clean(np, a_part)
    b, _bad_b = _clean(np, b_part)
    cut, length, ratio, swap = _plan_fields(plan)
    n = len(mix)
    v.metric("duration_s", round(n / sr, 3), None, kind="corte" if cut else "mezcla")
    if plan is None:
        v.note("sin plan: se mide como una mezcla de toda la duración")
    if n == 0:
        v.rule(VERDICT_DISCARD, "la mezcla está vacía")
        return
    if bad_mix:
        v.rule(VERDICT_DISCARD, f"la mezcla tiene valores que no son números (NaN o infinitos: {_pct(bad_mix)})")
    # dónde va cada trozo en la mezcla y con qué ganancia de medios y agudos
    if cut:
        b_off = min(len(a), n)
        a_line, b_line = _place(np, a, 0, n), _place(np, b, b_off, n)
        gain_a = (np.arange(n) < b_off).astype(np.float64)
        gain_b = 1.0 - gain_a
        mix_len = n / sr
    else:
        b_off = 0
        a_line, b_line = _place(np, a, 0, n), _place(np, b, 0, n)
        mix_len = n / sr                                  # la mezcla real manda (render_transition da length_s * sr)
        gain_a, gain_b = _fades(np, np.arange(n) / sr, mix_len)
    # recorte
    over = float((np.abs(mix) > 1.0).mean())
    inherited = max(float((np.abs(a_line) > 1.0).mean()), float((np.abs(b_line) > 1.0).mean()))
    added = max(0.0, over - inherited)
    peak = float(np.abs(mix).max())
    v.metric("clipping", round(over, 6), _lin(added, CLIP_GOOD, CLIP_BAD), added=round(added, 6), peak=round(peak, 3))
    if added >= CLIP_DISCARD:
        v.rule(VERDICT_DISCARD, f"recorte: un {_pct(added)} de las muestras pasa de 1,0 (pico {peak:.2f})".replace(".", ",", 1))
    elif added >= CLIP_DOUBT:
        v.rule(VERDICT_DOUBT, f"algo de recorte: un {_pct(added)} de las muestras pasa de 1,0")
    # hueco de silencio
    gap = _silence_gap_ms(np, mix, sr)
    v.metric("silence_gap_ms", round(gap, 1), _lin(gap, GAP_GOOD_MS, GAP_BAD_MS))
    if gap >= GAP_DISCARD_MS:
        v.rule(VERDICT_DISCARD, f"hueco de silencio de {gap:.0f} ms")
    elif gap >= GAP_DOUBT_MS:
        v.rule(VERDICT_DOUBT, f"hueco de silencio de {gap:.0f} ms")
    # clic
    ratio_mix, click_at = _click_ratio(np, mix, sr)
    ratio_parts = max(_click_ratio(np, a, sr)[0], _click_ratio(np, b, sr)[0])
    is_click = ratio_mix >= CLICK_RATIO and (ratio_parts <= 0 or ratio_mix >= CLICK_VS_PARTS * ratio_parts)
    v.metric("click", round(ratio_mix, 2), 0.0 if is_click else 1.0, parts=round(ratio_parts, 2),
             at_s=None if click_at is None else round(click_at, 3))
    if is_click:
        v.rule(VERDICT_DISCARD, f"clic a los {click_at:.2f} s (salto de {ratio_mix:.0f} veces lo normal)".replace(".", ",", 1))
    # salto de volumen
    tail, _ = _clean(np, a_before)
    head, _ = _clean(np, b_after)
    ctx = int(LOUD_CONTEXT_S * sr)
    excess, raw, at = _loudness(np, mix, a_line, b_line, gain_a, gain_b, tail[-ctx:] if len(tail) else tail, head[:ctx], sr,
                                b_off if cut else None)
    v.metric("loudness_step_db", None if excess is None else round(excess, 2), _lin(excess, LOUD_GOOD_DB, LOUD_BAD_DB),
             raw_db=None if raw is None else round(raw, 2), at_s=None if at is None else round(at, 2))
    if excess is not None and excess >= LOUD_DISCARD_DB:
        v.rule(VERDICT_DISCARD, f"salto de volumen de {_db(excess)} a los {at:.1f} s".replace(".", ",", 1))
    elif excess is not None and excess >= LOUD_DOUBT_DB:
        v.rule(VERDICT_DOUBT, f"salto de volumen de {_db(excess)} a los {at:.1f} s".replace(".", ",", 1))
    # tonos
    tone_a, tone_b, conf_a, conf_b = tones
    _tone_metric(v, tone_a, tone_b, conf_a, conf_b, TONE_CUT_WEIGHT if cut else 1.0, not cut and mix_len >= TONE_LONG_S)
    if cut:
        for name in ("beat_offset_ms", "bass_clash", "vocal_overlap"):
            v.metric(name, None, None)
        return
    # voces
    overlap, run = _vocal_overlap(np, a_vocal, b_vocal, n, sr, mix_len)
    v.metric("vocal_overlap", None if overlap is None else round(overlap, 3), _lin(overlap, VOCAL_GOOD, VOCAL_BAD),
             longest_s=run)
    if overlap is not None and overlap >= VOCAL_DISCARD and run >= VOCAL_DISCARD_MIN_S:
        v.rule(VERDICT_DISCARD, f"voces de las dos a la vez en un {_pct(overlap)} de la mezcla")
    elif overlap is not None and overlap >= VOCAL_DOUBT:
        v.rule(VERDICT_DOUBT, f"voces de las dos a la vez en un {_pct(overlap)} de la mezcla")
    # graves: desfase de golpes y graves que chocan
    low_m, rate = _low_band(np, mix, sr)
    low_a, _ = _low_band(np, a_line, sr)
    low_b, _ = _low_band(np, b_line, sr)
    # duración de un golpe en la mezcla: la de A, o la de B corregida por su estiramiento (la rejilla de B es de su tempo original)
    beat_s = next((g.beat_s / (1.0 if g is grid_a else max(ratio, 1e-6)) for g in (grid_a, grid_b)
                   if isinstance(g, BeatGrid) and _num(g.bpm, 0) > 0), None)
    offset, corr = _beat_offset(np, low_a, low_b, rate, mix_len, beat_s)
    if offset is None:
        v.metric("beat_offset_ms", None, None, corr=round(corr, 3))
        v.note("sin golpes claros comunes en los graves: no se mide el desfase")
    else:
        size = abs(offset)
        v.metric("beat_offset_ms", round(size, 1), _lin(size, BEAT_GOOD_MS, BEAT_BAD_MS), signed_ms=round(offset, 1),
                 corr=round(corr, 3))
        text = f"golpes desfasados {size:.0f} ms ({'la que entra va detrás' if offset > 0 else 'la que entra va delante'})"
        if size >= BEAT_DISCARD_MS:
            v.rule(VERDICT_DISCARD, text + ": galope")
        elif size >= BEAT_DOUBT_MS:
            v.rule(VERDICT_DOUBT, text + ": empieza a galopar")
    clash, frames = _bass_clash(np, low_m, low_a, low_b, rate, min(max(swap, 0.0), mix_len))
    v.metric("bass_clash", None if clash is None else round(clash, 3), _lin(clash, BASS_GOOD, BASS_BAD), frames=frames)
    if clash is not None and clash >= BASS_DISCARD:
        v.rule(VERDICT_DISCARD, f"graves de las dos a la vez en un {_pct(clash)} de la mezcla")
    elif clash is not None and clash >= BASS_DOUBT:
        v.rule(VERDICT_DOUBT, f"graves de las dos a la vez en un {_pct(clash)} de la mezcla")
