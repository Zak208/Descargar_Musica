"""Sesión del modo DJ automático sobre el motor de audio propio (fase 10): une el cargador (`pcm_loader`), el planificador
(`mix_planner`), la mezcla (`dj_dsp`), el volumen igualado (`deck_gain`) y el motor (`audio_engine.MixEngine`). Sin Qt: la
interfaz llama a `tick()` cada 50 ms en su hilo y a los métodos de transporte (play, pause, seek...).

Cómo suena una canción A y cómo se pasa a la siguiente B (todo a precisión de muestra):
    [entrada de A] [cuerpo de A en trozos de 15 s ... hasta el punto de mezcla] [1.ª mitad de la mezcla] [2.ª mitad] [cuerpo de B ...]
  * El cuerpo es la canción entera decodificada a tempo 1,0, con la ganancia de volumen igualado ya aplicada (en el sitio, sin
    copia). Los trozos son vistas del mismo array (no gastan memoria). Se trocea porque el motor no puede cortar el segmento que
    suena (`replace_queue` lo deja acabar): con trozos de 15 s, cuando llega el plan se sustituye todo lo que viene detrás del
    trozo actual y el punto de mezcla cae justo donde dice el plan.
  * La mezcla (`render_transition`) se encola partida en dos mitades: cuando empieza la segunda, B domina y `tick()` avisa con
    `advanced`. Esa segunda mitad pasa a ser la «entrada» de B, y luego sigue su cuerpo desde
    `b_start_s + length_s * tempo_ratio_b` (en su tiempo original).
  * Un corte limpio (KIND_CUT, o una mezcla imposible) se encola igual, en dos piezas de 0,5 s: el final de A con su rampa de
    bajada de 5 ms y el principio de B con su rampa de subida (las hace `render_transition` con el plan de corte).
  * Tipos de transición (`typed=True`, lo normal; ver `transition_types`): `choose_type(ficha A, ficha B, plan, BPM de A)`
    decide entre mezcla larga (blend, la de siempre), corte en el compás (cut_bar), eco de salida (echo_out) y filtro (filter);
    su regla de seguridad manda (rejillas poco fiables o tempo a más del 5 % nunca dan una mezcla larga). La mezcla mide lo
    mismo en todos los tipos y B no se desplaza, así que todo lo demás (cuerpo de B, empalme, posiciones) no cambia. Con
    cut_bar y echo_out B suena sola desde el corte (`plan.bass_swap_at`): la mezcla se parte ahí (y no en la mitad) para que
    `advanced` salga cuando entra B. La cola del eco (lo que suena después de la mezcla) se SUMA al principio del cuerpo de B
    en una copia: se encola un trozo «entry» con el empalme del tramo estirado (si lo hay), el cuerpo de B desde `b_body` y la
    cola encima, y el cuerpo normal sigue detrás. En un corte (plan de corte, corte por mezcla imposible o tardío) solo cabe
    cut_bar (el corte limpio de siempre) o echo_out (tempos lejanos o final brusco, con el tempo de A). El tipo se añade al
    motivo del plan («; tipo: ...») y al estado (`transition_type`). `typed=False`: exactamente lo de antes.
  * Puntuador (`audio_check="light"`, lo normal; ver docs/MOTOR_DJ.md): antes de renderizar, `transition_scorer.score_plan`;
    si dice «descartar», corte limpio con su motivo. Después de renderizar una mezcla en la que suenan las dos, si hay clic
    en una unión, recorte, hueco o salto de volumen (umbrales del puntuador), se cambia por un corte en el compás en vez de
    retocarla. Unos 0,1 s por mezcla de 32 s, en el hilo de trabajo. `audio_check="full"` usa `score_audio` entero.
  * Bucles (`loops=True`; APAGADO por defecto, ver docs/MOTOR_DJ.md): si `loops.needs_loop` lo pide, A suena hasta
    `loop_start`, repite sus 4 compases de antes del punto de mezcla (segmentos «loop» de `loops.extend_body`) y la mezcla, la
    misma y desde la misma muestra de A, llega `loop_bars` compases más tarde. Con el bucle sonando, B ya no se cambia.
  * Silencios: un corte limpio no corta A cuando ya calla (se adelanta a donde deja de sonar) ni hace entrar B donde aún
    calla (entra donde empieza a sonar); con corte en el compás o eco, el corte se mueve al compás más cercano en que suenan
    las dos. Si aun así el corte en el compás deja un hueco, se cambia por la mezcla (la otra canción lo tapa).
  * Ganancia de entrada (`entry_gain=True`, lo normal; ver docs/MOTOR_DJ.md): el volumen igualado es el de la canción entera,
    pero lo último de A y lo primero de B pueden sonar muy distintos. Se mide el nivel de 400 ms a cada lado del momento en
    que entra B (sin contar el silencio) y B se sube o se baja (de -12 a +6 dB); en un corte, lo que falte lo pone el final de
    A, llevado en sus últimos 2 s. La ganancia de B vuelve a 1,0 en 8 s (coseno en dB), sobre copias: el cuerpo de B no se
    toca. En una mezcla solo se sube B y solo desde 6 dB de diferencia. Un corte tampoco cae cuando A se está apagando (va
    antes del apagado) ni hace entrar a B por una arrancada muy callada; y una mezcla que pisaría el silencio final de A se
    adelanta.
  * Rampa de tempo (`tempo_ramp=True`; APAGADA por defecto, ver docs/MOTOR_DJ.md): tras una mezcla con B estirada, 3 tramos
    de 2 s con el tempo cada vez más cerca de 1,0 antes del cuerpo original, en vez del empalme directo de 20 ms.
  * Si cuando llega el plan el punto de mezcla cae dentro del trozo que ya suena y aún le faltan más de 0,25 s para llegar,
    el motor acorta ese trozo justo en él (`MixEngine.truncate_current`): no hace falta que el trozo acabe antes (canciones
    de 20 s, o `play(start_s)` cerca del final).
  * Plan tardío: si cuando llega el plan lo que suena ya pasa del punto de mezcla, se hace un corte limpio en el primer
    comienzo de compás de A que deje sitio a la pieza de 0,5 s tras el final de ese trozo (o justo ahí si no hay rejilla).
  * Una mezcla que no se puede hacer (el audio no cuadra con el análisis) pasa a corte limpio en el compás de donde la mezcla
    habría acabado (A ya se habría ido), no en su principio: no se tira el final de A. El plan puede pasarse del final de A
    hasta 50 ms (redondeos): lo que falta se rellena con silencio, con la rampa de `render_transition`.
  * Canción más larga que el tope del cargador (`pcm_loader.MAX_SECONDS`, 8 min): se carga hasta el tope y su final no existe
    en lo cargado. Si lo cargado llega al tope y el análisis dice que dura más (o no lo dice), se marca `truncated`, el final
    se toma como «de golpe» y la transición es un corte limpio en el último compás antes del tope, con ese motivo. La barra
    muestra la duración cargada (8:00).
  * Si A se acaba antes de que esté lista B (preparación lentísima), B entra con su rampa de subida en cuanto llega.

Hilos: un solo hilo de trabajo con una cola de tareas («cargar A», «preparar B»). Cada tarea lleva la generación de la sesión
(`_gen`, cambia con play y stop) y la de la preparación (`_pgen`, cambia también con replan y al avanzar): si al acabar ya no
coinciden, el resultado se tira. Todo lo que toca la cola del motor se hace con el candado de la sesión, así que el hilo de
trabajo y la interfaz nunca la cambian a la vez. La llamada de audio sí puede avanzar mientras tanto: `_install_locked`
comprueba con `current()` que el segmento que sonaba sigue sonando (o que ya suena uno de los nuevos) y si no, lo rehace.
Ninguna excepción sale del hilo de trabajo: se guarda en `error` y la sesión sigue (salta esa canción) o se para limpiamente.

Memoria: en la sesión solo hay A y B (y las dos mitades de la mezcla, 16 s = 5,6 MB). A se suelta al avanzar: sus trozos ya
han sonado y la mezcla es un array aparte. Al saltar con play() se vacía el futuro del motor nada más pedirlo, así que solo
queda la A vieja (por el trozo que suena) mientras se decodifica la nueva.

Volumen igualado: A arranca con el LUFS ya guardado (`loudness_service.stored`, sin medir: no retrasa el sonido; si no hay,
ganancia 1,0). B se prepara con `deck_gain.lufs_for` (lo mide si hace falta, en el hilo de trabajo). La ganancia de cada
canción se fija una vez al cargarla y no cambia mientras suena. El pico se calcula con max/min (sin copia de 85 MB).

Decisiones y límites:
  * `next_after` solo se llama desde `tick()`, con la ruta de la canción actual, y tras `advanced` en un tick posterior (la
    interfaz aún no ha movido su lista). Excepción: si B no se pudo cargar, se pide `next_after(B)` para saltarla (máximo 5
    intentos seguidos); si se agotan, A suena hasta el final y luego `ended`.
  * `replan()` con la mezcla ya sonando (su primera mitad empezó) no hace nada: B ya está entrando; lo nuevo se pedirá al avanzar.
  * Si `next_after` devuelve lo mismo que ya está preparado, no se rehace nada.
  * Con `tempo_ratio_b` = 1,0 el tramo de B de la mezcla se toma del cuerpo ya cargado (no se vuelve a decodificar).
  * La preparación de B empieza en cuanto suena A (no se espera a `lead_s`; el parámetro se guarda pero no cambia nada:
    empezar antes no cuesta y evita planes tardíos). Un salto rápido con play() mientras se prepara una B espera a que acabe
    esa tarea (un solo hilo, el cargador no se puede interrumpir): como mucho lo que tarde estirarla.
  * play() de la canción que ya está cargada no la vuelve a decodificar (reinicia desde start_s, como seek).

Mediciones (pruebas/prueba_motor_dj.py, Windows 11, CPU compartida; cargador real, mp3 sintéticos de 3 min a 192 kbps):
  * De play() a A encolada y sonando: 0,22 a 0,30 s (decodificar con FFmpeg + pico + ganancia; el tick la ve 0 a 40 ms después).
  * De play() a la transición encolada: 1,34 a 1,47 s. Incluye decodificar B entera, medir su LUFS con ebur128 (no estaba
    guardado), estirar 32 s de B con rubberband (tempo 0,9615) y `render_transition` de 32 s.
  * Con el cargador falso y un hilo que saca audio 20 veces más deprisa que el tiempo real mientras la interfaz hace replan
    cada 0,35 s y algún seek: sin huecos, repeticiones ni clics, y nunca más de 2 canciones enteras en memoria."""
import dataclasses
import itertools
import logging
import math
import os
import queue as _queue
import threading
import time

from services import dj_dsp, dj_fx, loops, mix_planner, mix_points, transition_scorer, transition_types
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid, TransitionPlan

log = logging.getLogger(__name__)

CHUNK_S = 15.0                  # tamaño de los trozos del cuerpo
MIN_CHUNK_S = 1.0               # un último trozo más corto se junta con el anterior
CUT_PIECE_S = 0.5               # piezas del corte limpio (A con rampa de bajada, B con rampa de subida)
JOIN_S = 0.020                  # con tempo estirado, fundido lineal entre el final del tramo estirado y el cuerpo original de B
MIN_GAP_FRAMES = 4096           # en un corte tardío, el trozo de A que queda antes no puede ser más corto que esto
TRUNC_GUARD_S = 0.25            # el trozo que suena se acorta en el punto de mezcla solo si aún le faltan 0,25 s para llegar
FIT_TOL_S = 0.05                # la mezcla puede pasarse del final de A hasta 50 ms (redondeos del plan): se rellena con silencio
TRUNCATED_TOL_S = 0.05          # una canción cargada hasta el tope del cargador (menos esto) se ha truncado si dura más
SILENCE_SHIFT_MIN_S = 0.5       # una mezcla que pisa más de esto del silencio final de A se adelanta
CHECK_CONTEXT_S = 2.0           # el puntuador mira también los 2 s de antes y de después de la mezcla (saltos de volumen)
CHECK_CLICK_S = 0.05            # y busca clics en ±50 ms alrededor de cada unión de la mezcla
AUDIO_CHECKS = ("light", "full")
SILENCE_DB = -50.0              # 100 ms más flojos que esto (dBFS) son silencio: ni se corta A ni entra B en él
SOUND_WIN_S = 0.1               # ventana con la que se mira si algo suena justo antes o justo después de un corte
SOUND_SEARCH_S = 30.0           # hasta dónde se busca sonido antes del corte (A) o después de la entrada (B)
TRIM_LEVEL_S = 0.4              # ganancia de entrada: nivel de lo último de A y de lo primero de B, 400 ms a cada lado del corte
FADE_REF_S = 6.0                # A «se apaga» o B «empieza callada» frente a lo que suena en los 6 s de antes (A) o después (B)
FADE_REL_DB = 6.0               # si queda 6 dB o más por debajo: el corte va antes del apagado / B entra donde ya suena
TRIM_BLOCK_S = 0.05             # en bloques de 50 ms; los que están por debajo de SILENCE_DB no cuentan (silencio)
TRIM_RAMP_S = 8.0               # la ganancia de B vuelve a 1,0 en 8 s desde que B domina (coseno en dB, sin escalón)
TRIM_B_DB = (-12.0, 6.0)        # lo que se puede bajar o subir B
TRIM_A_DB = (-12.0, 6.0)        # y lo que falte, el final de A (en un corte; en una mezcla A no se toca)
TRIM_A_FADE_S = 2.0             # el final de A se lleva a su ganancia en los 2 s de antes del corte (coseno en dB)
TRIM_MIN_DB = 1.0               # diferencias más pequeñas no se tocan
TRIM_BLEND_DB = 6.0             # en una mezcla (las dos suenan a la vez) solo si la diferencia es grande, y solo B
TRIM_PEAK = 0.98                # al subir B o A, que su pico no pase de esto (el limitador queda para lo excepcional)
MAX_TRIES = 5                   # canciones seguidas que se intentan cargar como siguiente antes de rendirse
INSTALL_TRIES = 8               # reintentos de cambiar la cola si la llamada de audio avanza a la vez

LOOP_BARS = 4                   # el bucle repite los 4 compases de antes del punto de mezcla
RAMP_STEPS = 3                  # rampa de vuelta al tempo original de B: 3 tramos con el tempo cada vez más cerca de 1,0
RAMP_SEG_S = 2.0                # de 2 s de salida cada uno
RAMP_PREROLL_S = 0.5            # cada tramo se estira desde 0,5 s antes y eso se tira (el principio de un estirado no es fiel)

_track_ids = itertools.count(1)
_loop_ids = itertools.count(1)


def _key(path):
    """La misma ruta escrita de dos formas (barras `/` de Qt o `\\` de la ventana, mayúsculas) es la misma canción."""
    return os.path.normcase(os.path.normpath(path)) if path else path


class _Track:
    """Una canción cargada: su audio entero (tempo 1,0, ganancia ya aplicada) y qué suena antes de su cuerpo."""
    __slots__ = ("id", "path", "data", "gain", "entry", "body_start")

    def __init__(self, path, data, gain):
        self.id = next(_track_ids)
        self.path = path
        self.data = data
        self.gain = gain
        self.entry = []                 # [(array, etiqueta)]: la 2.ª mitad de la mezcla que la trajo (mientras no acabe)
        self.body_start = 0             # muestra del cuerpo donde sigue al acabar `entry`

    @property
    def frames(self) -> int:
        return len(self.data)


class _Label:
    """Etiqueta de cada segmento encolado: de qué canción es y en qué instante de ella (tiempo original) empieza."""
    __slots__ = ("track_id", "role", "t0", "ratio", "f0", "f1", "idx", "tag")

    def __init__(self, track_id, role, t0, ratio=1.0, f0=0, f1=0, idx=0, tag=None):
        self.track_id = track_id
        self.role = role                # "body" (trozo del cuerpo), "loop" (repetición del bucle), "x1" (1.ª mitad o final
                                        # del corte), "entry"
        self.t0 = t0                    # segundo de la canción en el que empieza el segmento
        self.ratio = ratio              # segundos de la canción por segundo de salida (tempo de B en la mezcla)
        self.f0 = f0                    # "body", "loop" y "x1": primera muestra del cuerpo que cubre
        self.f1 = f1                    # "body": muestra del cuerpo donde acaba (sin incluir); "loop": el punto de mezcla
        self.idx = idx                  # "entry": posición en track.entry; "loop": número de repetición
        self.tag = tag                  # "loop": de qué bucle es (_Pair.loop_id)

    def __repr__(self):
        return f"<{self.role} pista {self.track_id} desde {self.t0:.3f} s>"


class _Ctx:
    """Lo que se sabe de las dos canciones al preparar el paso (para elegir el tipo y para el corte tardío)."""
    __slots__ = ("info_a", "info_b", "grid_a", "bpm_a")

    def __init__(self, info_a, info_b, grid_a):
        self.info_a = info_a if isinstance(info_a, dict) else {}
        self.info_b = info_b if isinstance(info_b, dict) else {}
        self.grid_a = grid_a
        bpm = grid_a.bpm if grid_a is not None else self.info_a.get("bpm")
        self.bpm_a = float(bpm) if isinstance(bpm, (int, float)) and not isinstance(bpm, bool) and bpm > 0 else None


class _Pair:
    """Paso preparado de la actual (A) a la siguiente (B)."""
    __slots__ = ("b", "plan", "a_mix", "x1", "x1_label", "entry", "b_body", "b_cut", "grid_a", "ctx", "kind", "check",
                 "loop_segs", "loop_start", "loop_id", "loop_bars")

    def __init__(self, b, plan, a_mix, x1, x1_label, entry, b_body, b_cut, grid_a, ctx=None, kind=None):
        self.b = b
        self.plan = plan
        self.a_mix = a_mix              # muestra de A donde acaba su cuerpo y empieza x1
        self.x1 = x1                    # array (o None) que suena en tiempo de A
        self.x1_label = x1_label
        self.entry = entry              # [(array, etiqueta)] en tiempo de B: con él empieza `advanced`
        self.b_body = b_body            # muestra de B donde sigue su cuerpo
        self.b_cut = b_cut              # muestra de B por la que entraría un corte limpio (para el plan tardío)
        self.grid_a = grid_a
        self.ctx = ctx                  # _Ctx (fichas de las dos), para rehacer un corte tardío con su tipo
        self.kind = kind                # tipo de transición (transition_types.TYPE_*) que suena
        self.check = {}                 # lo que dijo el puntuador: "plan" (veredicto), "audio" (motivos), "swapped", "seconds"
        self.loop_segs = []             # bucle (loops.extend_body): repeticiones que suenan entre loop_start y a_mix
        self.loop_start = a_mix         # muestra de A donde empieza el bucle (el cuerpo de A suena hasta aquí)
        self.loop_id = None
        self.loop_bars = 0              # compases que añade el bucle (0: sin bucle)


class _Ask:
    """Petición pendiente de `next_after` (la hace tick())."""
    __slots__ = ("kind", "after", "a_id", "attempt", "not_before", "force")

    def __init__(self, kind, after, a_id, attempt, not_before):
        self.kind = kind                # "next" (tras cargar o avanzar), "replan" o "skip" (B no se pudo cargar)
        self.after = after              # ruta que se pasa a next_after
        self.a_id = a_id
        self.attempt = attempt
        self.not_before = not_before    # número de tick a partir del cual se puede pedir
        self.force = False              # «replan» que rehace la mezcla aunque la siguiente sea la misma (llegó un análisis)


def _sounds(x) -> bool:
    """¿Suena algo en x (RMS por encima de `SILENCE_DB`)? Un trozo vacío no suena."""
    if not len(x):
        return False
    np = dj_dsp._np()
    return float(np.mean(np.square(x, dtype=np.float64))) > 10 ** (SILENCE_DB / 10.0)


def _gated_rms(x):
    """RMS de x contando solo los bloques de 50 ms que suenan (por encima de `SILENCE_DB`), o None si nada suena."""
    np = dj_dsp._np()
    block = int(TRIM_BLOCK_S * SAMPLE_RATE)
    k = len(x) // block
    if k < 1:
        return None
    p = np.square(x[:k * block], dtype=np.float64).mean(axis=1).reshape(k, block).mean(axis=1)
    p = p[p > 10 ** (SILENCE_DB / 10.0)]
    return float(np.sqrt(p.mean())) if len(p) else None


def _trim_curve(g0, split, total):
    """Ganancia de entrada de B en la línea de la transición (muestra 0 = principio de la mezcla): `g0` hasta `split` (donde
    B empieza a dominar) y de ahí a 1,0 en `TRIM_RAMP_S` (coseno en dB), y 1,0 después. float32 de `total` muestras."""
    np = dj_dsp._np()
    r = int(TRIM_RAMP_S * SAMPLE_RATE)
    t = np.arange(total, dtype=np.float64) - split
    u = np.clip(t / r, 0.0, 1.0)
    db0 = 20.0 * math.log10(g0)
    return (10.0 ** (db0 * (0.5 + 0.5 * np.cos(np.pi * u)) / 20.0)).astype(np.float32)


def _fade_to(g, n):
    """Ganancia de A en sus últimas n muestras antes del corte: de 1,0 a g (coseno en dB). float32."""
    np = dj_dsp._np()
    u = (np.arange(n, dtype=np.float64) + 1.0) / max(1, n)
    db = 20.0 * math.log10(g)
    return (10.0 ** (db * (0.5 - 0.5 * np.cos(np.pi * u)) / 20.0)).astype(np.float32)


def _peak(*parts) -> float:
    np = dj_dsp._np()
    return max([float(np.abs(x).max()) for x in parts if len(x)] or [0.0])


def _block_loud(x, block, thr_db=SILENCE_DB):
    """Por cada bloque de `block` muestras de x: ¿suena (RMS por encima de `thr_db` dBFS)?"""
    np = dj_dsp._np()
    k = len(x) // block
    if k < 1:
        return np.zeros(0, dtype=bool)
    p = np.square(x[:k * block], dtype=np.float64).mean(axis=1).reshape(k, block).mean(axis=1)
    return p > 10 ** (thr_db / 10.0)


def _last_sound(data, end, search_s=SOUND_SEARCH_S, thr_db=SILENCE_DB, block_s=0.01):
    """Muestra donde acaba el último bloque (10 ms) que suena por encima de `thr_db` antes de `end` (buscando `search_s`
    hacia atrás), o None."""
    block = int(block_s * SAMPLE_RATE)
    lo = max(0, end - int(search_s * SAMPLE_RATE))
    lo = end - (end - lo) // block * block
    loud = _block_loud(data[lo:end], block, thr_db)
    hits = loud.nonzero()[0]
    return None if not len(hits) else lo + (int(hits[-1]) + 1) * block


def _first_sound(data, start, search_s=SOUND_SEARCH_S, thr_db=SILENCE_DB, block_s=0.01):
    """Muestra donde empieza el primer bloque (10 ms) que suena por encima de `thr_db` desde `start` (buscando `search_s`),
    o None."""
    block = int(block_s * SAMPLE_RATE)
    loud = _block_loud(data[start:start + int(search_s * SAMPLE_RATE)], block, thr_db)
    hits = loud.nonzero()[0]
    return None if not len(hits) else start + int(hits[0]) * block


def _rms(x) -> float:
    np = dj_dsp._np()
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def _db(v):
    return 20.0 * math.log10(v) if v else -120.0


def _fading_end(data, c):
    """Si A se apaga justo antes de c (sus últimos `TRIM_LEVEL_S` quedan más de `FADE_REL_DB` por debajo de lo que sonaba en
    los segundos de antes), la muestra donde aún sonaba a su nivel (fin del último bloque de 50 ms a menos de `FADE_REL_DB`
    de él); si no, None."""
    lvl = int(TRIM_LEVEL_S * SAMPLE_RATE)
    ref = _gated_rms(data[max(0, c - int(FADE_REF_S * SAMPLE_RATE)):max(0, c - lvl)])
    last = _rms(data[max(0, c - lvl):c])                    # sin puerta: un silencio corto al final también cuenta
    if ref is None or _db(last) >= _db(ref) - FADE_REL_DB:
        return None
    return _last_sound(data, c, FADE_REF_S, _db(ref) - FADE_REL_DB, TRIM_BLOCK_S)


def _quiet_start(data, s):
    """Si B empieza mucho más callada que lo que suena justo después (sus primeros `TRIM_LEVEL_S` más de `FADE_REL_DB` por
    debajo de los segundos siguientes), la muestra donde llega a su nivel; si no, None."""
    lvl = int(TRIM_LEVEL_S * SAMPLE_RATE)
    ref = _gated_rms(data[s + lvl:s + int(FADE_REF_S * SAMPLE_RATE)])
    first = _rms(data[s:s + lvl])                           # sin puerta: un silencio corto al principio también cuenta
    if ref is None or _db(first) >= _db(ref) - FADE_REL_DB:
        return None
    return _first_sound(data, s, FADE_REF_S, _db(ref) - FADE_REL_DB, TRIM_BLOCK_S)


def _max_minutes():
    from services import pcm_loader
    return round(pcm_loader.MAX_SECONDS / 60)


def _truncated(frames, known_s) -> bool:
    """¿El cargador cortó la canción en su tope (`pcm_loader.MAX_SECONDS`)? Si lo cargado llega al tope y el análisis dice que
    dura más (o no lo dice: una canción de justo 8:00 es rara)."""
    from services import pcm_loader
    top = pcm_loader.MAX_SECONDS
    return frames >= (top - TRUNCATED_TOL_S) * SAMPLE_RATE and (known_s is None or known_s > frames / SAMPLE_RATE + 0.5)


def _stored_lufs(path):
    """LUFS ya guardado, sin medir (para que A arranque ya). Importa loudness_service (trae Qt) solo cuando hace falta."""
    from services import deck_gain, loudness_service
    v = loudness_service.stored(path)
    return v if v is not None and v > deck_gain.UNMEASURED_LUFS else None


def _measured_lufs(path):
    from services import deck_gain
    return deck_gain.lufs_for(path)


def _gain_for(lufs, peak) -> float:
    from services import deck_gain
    return deck_gain.deck_gain(lufs, peak)


class EngineSession:
    """Sesión del DJ sobre un `MixEngine` (ver la explicación del módulo). El dueño del motor hace start()/stop() del flujo."""

    def __init__(self, engine, info_for, next_after, bars=16, loader=None, lead_s=45.0, lufs_stored=None, lufs_measure=None,
                 typed=True, audio_check="light", loops=False, tempo_ramp=False, entry_gain=True, profile="club"):
        if loader is None:
            from services import pcm_loader
            loader = pcm_loader.load
        self._engine = engine
        self._info_for = info_for
        self._next_after = next_after
        self.bars = bars
        self.lead_s = lead_s
        self.typed = bool(typed)        # tipos de transición (transition_types); False: solo mezcla larga o corte limpio
        # puntuador (transition_scorer): "light" (por defecto) mide recorte, huecos, clics en las uniones y saltos de volumen
        # con sus funciones y umbrales; "full" llama a score_audio entero (0,1 a 0,4 s más por mezcla); None: no se puntúa
        self.audio_check = audio_check if audio_check in AUDIO_CHECKS else None
        self.loops = bool(loops)        # bucles de 4 u 8 compases antes de la mezcla (loops.needs_loop); ver docs/MOTOR_DJ.md
        self.tempo_ramp = bool(tempo_ramp)  # B vuelve a su tempo en 3 tramos de 2 s en vez de en el empalme de 20 ms
        self.entry_gain = bool(entry_gain)  # ganancia de entrada de B igualada a lo último de A (ver docs/MOTOR_DJ.md)
        self.profile = str(profile or "club").lower()
        self._loader = loader
        self._lufs_stored = lufs_stored or _stored_lufs
        self._lufs_measure = lufs_measure or _measured_lufs
        self._lock = threading.RLock()
        self._worker = None
        self._tasks = None
        self._gen = 0
        self._pgen = 0
        self._tick_no = 0
        self._a = None                  # canción actual (_Track)
        self._pair = None               # paso preparado a la siguiente (_Pair)
        self._loading = None            # ruta que se está cargando como actual
        self._load_start = 0.0
        self._want_play = False
        self._ask = None
        self._preparing = None          # ruta de la siguiente que se está preparando
        self._no_next = False           # next_after dijo que no hay siguiente (o se agotaron los intentos)
        self._advanced = None
        self._pending_adopt = None
        self._ended = False
        self._error = None
        self._last_pos = 0.0
        self._t_play = 0.0
        self.timings = {}               # segundos desde play(): "sound" (A encolada) y "ready" (transición encolada)

    # ---- API pública --------------------------------------------------------------------------------------------------
    def play(self, path, start_s=0.0, autoplay=True):
        """Empieza `path` desde `start_s`. Carga en el hilo de trabajo; lo que suena sigue hasta que la nueva está lista y
        entonces se corta con el fundido corto del motor. La misma canción ya cargada: reinicio desde start_s."""
        with self._lock:
            self._pending_adopt = None
            self._want_play = bool(autoplay)
            start_s = max(0.0, float(start_s or 0.0))
            if self._loading is not None and _key(self._loading) == _key(path):
                self._load_start = start_s
                return
            if self._loading is None and self._a is not None and _key(self._a.path) == _key(path):
                self._seek_locked(start_s)
                return
            self._gen += 1
            self._pgen += 1
            self._a = None
            self._pair = None
            self._ask = None
            self._preparing = None
            self._no_next = False
            self._ended = False
            self._loading = path
            self._load_start = start_s
            self._last_pos = start_s
            self._t_play = time.monotonic()
            self.timings = {}
            self._engine.replace_queue([])      # suelta el futuro (y la B vieja); lo que suena acaba o se corta al cargar
            self._ensure_worker()
            self._tasks.put((self._task_load, self._gen, path))

    def adopt(self, path) -> bool:
        """True si `path` es la canción a la que la sesión acaba de avanzar sola (y entonces no hay que hacer nada más)."""
        with self._lock:
            if path is not None and self._pending_adopt is not None and _key(path) == _key(self._pending_adopt):
                self._pending_adopt = None
                return True
            return False

    def pause(self):
        with self._lock:
            self._want_play = False
            self._engine.pause()

    def resume(self):
        """Reanuda. Si aún carga, se apunta y sonará en cuanto esté (no se pierde)."""
        with self._lock:
            self._want_play = True
            if self._loading is None and self._a is not None:
                self._engine.play()

    def stop(self, wait=True):
        """Para, vacía el motor, suelta los arrays y termina el hilo de trabajo (con `wait=False` no se espera a que acabe
        lo que estuviera haciendo: la interfaz no debe quedarse parada hasta 2 s; su resultado se tira)."""
        with self._lock:
            self._gen += 1
            self._pgen += 1
            self._a = None
            self._pair = None
            self._loading = None
            self._ask = None
            self._preparing = None
            self._no_next = False
            self._want_play = False
            self._pending_adopt = None
            try:
                self._engine.replace([], fade=True)
                self._engine.pause()
            except Exception as e:
                log.warning("fallo al parar el motor del DJ: %s", e)
            worker, tasks = self._worker, self._tasks
            self._worker = None
            self._tasks = None
        if worker is not None:
            tasks.put(None)
            if wait:
                worker.join(timeout=2.0)

    def seek(self, seconds):
        """Salta dentro de la canción actual. Si cae en la mezcla o después, salta al principio del cuerpo de B."""
        with self._lock:
            if self._loading is not None:
                self._load_start = max(0.0, float(seconds))
                self._last_pos = self._load_start
                return
            if self._a is None:
                return
            self._sync_locked()
            self._seek_locked(float(seconds))

    def replan(self, force=False):
        """La siguiente canción cambió: en el próximo tick se pide `next_after` y se rehace lo que aún no ha empezado. Con
        `force`, se rehace aunque la siguiente sea la misma (por ejemplo, llegó el análisis de una de las dos canciones)."""
        with self._lock:
            if self._loading is not None or self._a is None:
                return
            self._sync_locked()
            if self._locked_in_locked():
                return
            self._no_next = False
            if self._ask is None or self._ask.kind != "skip":
                self._ask = _Ask("replan", self._a.path, self._a.id, 1, 0)
                self._ask.force = bool(force)

    def set_volume(self, gain):
        self._engine.set_master_gain(gain)

    @property
    def current_path(self):
        with self._lock:
            if self._loading is not None:
                return self._loading
            return self._a.path if self._a is not None else None

    @property
    def duration_s(self) -> float:
        a = self._a
        return a.frames / SAMPLE_RATE if a is not None and self._loading is None else 0.0

    def has_audio_ready(self) -> bool:
        """True si la canción actual ya está decodificada y encolada (puede sonar)."""
        with self._lock:
            return self._loading is None and self._a is not None

    def tick(self) -> dict:
        """Lo llama la interfaz cada 50 ms en su hilo: recoge notificaciones del motor, detecta el paso a la siguiente, pide
        `next_after` cuando toca y devuelve el estado. Barato: sin E/S ni cálculo pesado (salvo lo que haga next_after)."""
        try:
            self._engine.dispatch_events()
        except Exception as e:
            self._error = f"notificaciones del motor: {e}"
        ask = None
        with self._lock:
            self._tick_no += 1
            self._sync_locked()
            advanced, self._advanced = self._advanced, None
            if advanced is not None and self._ask is not None:
                self._ask.not_before = self._tick_no + 1          # next_after(nueva) en un tick posterior
            if (advanced is None and self._ask is not None and self._ask.not_before <= self._tick_no
                    and self._loading is None and self._a is not None and self._ask.a_id == self._a.id):
                ask, self._ask = self._ask, None
                gen, pgen = self._gen, self._pgen
        if ask is not None:
            try:
                nxt = self._next_after(ask.after)
            except Exception as e:
                log.exception("fallo en next_after")
                nxt = None
                self._error = f"next_after: {e}"
            with self._lock:
                if gen == self._gen and pgen == self._pgen and self._a is not None and self._a.id == ask.a_id:
                    self._apply_next_locked(ask, nxt)
        with self._lock:
            return self._state_locked(advanced)

    # ---- estado ---------------------------------------------------------------------------------------------------------
    def _state_locked(self, advanced) -> dict:
        ended, self._ended = self._ended, False
        error, self._error = self._error, None
        a, p = self._a, self._pair
        if self._loading is not None:
            path, pos, dur, state = self._loading, self._load_start, 0.0, "loading"
        elif a is None:
            path, pos, dur, state = None, 0.0, 0.0, "stopped"
        else:
            path, dur = a.path, a.frames / SAMPLE_RATE
            cur = self._engine.current()
            lab = cur[0] if cur is not None else None
            if isinstance(lab, _Label) and lab.track_id == a.id:
                pos = lab.t0 + cur[2] * lab.ratio / SAMPLE_RATE - self._engine.output_latency_s
                self._last_pos = pos
            else:
                pos = self._last_pos
            pos = min(max(0.0, pos), dur)
            state = "playing" if self._want_play else "paused"
        nxt = p.b.path if p is not None else self._preparing
        return {"path": path, "position_s": pos, "duration_s": dur, "state": state, "advanced": advanced, "ended": ended,
                "error": error, "plan": p.plan if p is not None else None, "next_path": nxt,
                "transition_type": p.kind if p is not None else None, "loop_bars": p.loop_bars if p is not None else 0}

    def _locked_in_locked(self) -> bool:
        """¿Ha empezado ya la mezcla hacia B (su primera mitad suena)? Entonces B ya no se puede cambiar."""
        p = self._pair
        if p is None:
            return False
        cur = self._engine.current()
        lab = cur[0] if cur is not None else None
        if isinstance(lab, _Label) and lab.role == "loop" and lab.track_id == self._a.id:
            return lab.tag == p.loop_id and (cur[2] > 0 or lab.idx > 0)    # el bucle ya suena: va derecho a la mezcla
        return isinstance(lab, _Label) and ((lab.role == "x1" and lab.track_id == self._a.id and cur[2] > 0)
                                            or lab.track_id == p.b.id)

    def _sync_locked(self):
        """Mira qué suena: si ya es B, avanza; si A ya acabó y no hay siguiente, fin."""
        a = self._a
        if a is None or self._loading is not None:
            return
        cur = self._engine.current()
        lab = cur[0] if cur is not None else None
        ours = isinstance(lab, _Label)
        if ours and self._pair is not None and lab.track_id == self._pair.b.id:
            self._advance_locked(jump=False)
            return
        if ours and lab.track_id == a.id and lab.role == "body" and a.entry:
            a.entry = []                                        # la entrada ya sonó: se suelta
        if (self._pair is None and self._no_next and self._preparing is None and self._ask is None
                and not (ours and lab.track_id == a.id)):
            self._ended = True
            self._a = None
            self._pgen += 1

    def _advance_locked(self, jump):
        p = self._pair
        b = p.b
        b.entry = [] if jump else list(p.entry)
        b.body_start = p.b_body
        self._a = b                     # la A vieja ya no la referencia nadie de la sesión: se libera
        self._pair = None
        self._pgen += 1
        self._preparing = None
        self._no_next = False
        self._advanced = b.path
        self._pending_adopt = b.path
        self._ask = _Ask("next", b.path, b.id, 1, math.inf)     # tick() lo habilita para el tick siguiente

    def _apply_next_locked(self, ask, nxt):
        a = self._a
        if self._locked_in_locked():
            return
        p = self._pair
        if nxt is None:
            if p is not None:                                   # ya no hay siguiente: A hasta el final
                self._pair = None
                self._install_locked()
            self._pgen += 1
            self._preparing = None
            self._no_next = True
            return
        if ask.kind == "replan" and not ask.force and ((p is not None and p.b.path == nxt) or (p is None and self._preparing == nxt)):
            return                                              # la misma de antes: nada que rehacer
        if p is not None:
            self._pair = None
            self._install_locked()                              # quita la transición vieja mientras se prepara la nueva
        self._pgen += 1
        self._preparing = nxt
        self._ensure_worker()
        self._tasks.put((self._task_prep, self._gen, self._pgen, a.id, nxt, ask.attempt))

    # ---- cola del motor -------------------------------------------------------------------------------------------------
    def _body_segs(self, tr, f, end) -> list:
        """Trozos de 15 s (vistas, sin copia) del cuerpo de `tr` entre las muestras f y end."""
        out = []
        chunk = int(CHUNK_S * SAMPLE_RATE)
        tail = int(MIN_CHUNK_S * SAMPLE_RATE)
        f, end = max(0, int(f)), min(tr.frames, int(end))
        while f < end:
            e = min(end, f + chunk)
            if end - e < tail:
                e = end
            out.append((tr.data[f:e], _Label(tr.id, "body", f / SAMPLE_RATE, 1.0, f, e)))
            f = e
        return out

    def _from_frame_locked(self, f) -> list:
        """Lo que debe sonar desde la muestra f del cuerpo de A: su cuerpo hasta la mezcla, la mezcla y el cuerpo de B."""
        a, p = self._a, self._pair
        if p is None:
            return self._body_segs(a, f, a.frames)
        if f > p.a_mix:
            self._late_cut_locked(f)
            p = self._pair
        if p.loop_segs and f < p.a_mix:                         # cuerpo hasta el bucle (o desde dentro de su región)
            return self._body_segs(a, f, p.loop_start) + self._loop_from_locked(p, max(0, f - p.loop_start), 0)
        return self._body_segs(a, f, p.a_mix) + self._mix_on_locked(p)

    def _mix_on_locked(self, p) -> list:
        """La mezcla (primera parte), la entrada de B y el cuerpo de B."""
        segs = [(p.x1, p.x1_label)] if p.x1 is not None else []
        segs += p.entry
        segs += self._body_segs(p.b, p.b_body, p.b.frames)
        return segs

    def _loop_from_locked(self, p, off, i) -> list:
        """Las repeticiones del bucle desde la número i (la primera, desde su muestra `off`) y luego la mezcla."""
        a = self._a
        segs = []
        for k in range(i, len(p.loop_segs)):
            arr = p.loop_segs[k][off if k == i else 0:]
            o = len(p.loop_segs[k]) - len(arr)
            if len(arr):
                segs.append((arr, _Label(a.id, "loop", (p.loop_start + o) / SAMPLE_RATE, 1.0, p.loop_start + o, p.a_mix,
                                         idx=k, tag=p.loop_id)))
        return segs + self._mix_on_locked(p)

    def _future_locked(self, cur):
        """Lo que debe venir detrás del segmento que suena (o desde él, si aún no ha empezado). None: no tocar nada."""
        a = self._a
        if a is None:
            return None
        if cur is None:                                         # A ya acabó entera: B entra en cuanto esté
            return self._from_frame_locked(a.frames)
        lab, started = cur[0], cur[2] > 0
        if not isinstance(lab, _Label) or lab.track_id != a.id:
            return None
        if lab.role == "entry":
            i = lab.idx + (1 if started else 0)
            return list(a.entry[i:]) + self._from_frame_locked(a.body_start)
        if lab.role == "body":
            if not started:
                return self._from_frame_locked(lab.f0)
            p = self._pair
            end = (p.loop_start if p.loop_segs else p.a_mix) if p is not None else None
            if (p is not None and lab.f0 < end < lab.f1
                    and self._engine.truncate_current(cur[1], end - lab.f0, round(TRUNC_GUARD_S * SAMPLE_RATE))):
                lab.f1 = end                                    # el trozo que suena acaba ya en el bucle o el punto de mezcla
            return self._from_frame_locked(lab.f1)
        if lab.role == "loop":
            p = self._pair
            if p is not None and lab.tag == p.loop_id:
                return self._loop_from_locked(p, 0, lab.idx + (1 if started else 0))
            return self._from_frame_locked(lab.f1 if started else lab.f0)   # bucle de un plan que ya no está
        if lab.role == "x1" and not started:
            return self._from_frame_locked(lab.f0)
        return None                                             # la mezcla ya suena: no se toca

    def _install_locked(self):
        """Sustituye el futuro del motor sin cortar lo que suena. Si la llamada de audio pasa de segmento a la vez, se rehace."""
        eng = self._engine
        for _ in range(INSTALL_TRIES):
            cur = eng.current()
            segs = self._future_locked(cur)
            if segs is None:
                return
            ids = eng.replace_queue(segs)
            after = eng.current()
            if after is None or after[1] in ids or (cur is not None and cur[2] > 0 and after[1] == cur[1]):
                return
        log.warning("no se pudo cambiar la cola del motor del DJ: la llamada de audio avanzaba a la vez")

    def _start_locked(self, segs):
        """Sustituye ya lo que suena por `segs` (fundido corto del motor) y aplica play/pausa."""
        eng = self._engine
        if eng.current() is None:                               # nada que fundir: entrada desde silencio con rampa
            eng.pause(fade=False)
            eng.replace(segs, fade=False)
        else:
            eng.replace(segs, fade=True)
        if self._want_play:
            eng.play()
        else:
            eng.pause()

    def _seek_locked(self, seconds):
        a, p = self._a, self._pair
        f = min(max(0, round(seconds * SAMPLE_RATE)), max(0, a.frames - 1))
        a.entry = []
        if p is not None and f >= p.a_mix:                      # dentro o después de la mezcla: al cuerpo de B
            self._advance_locked(jump=True)
            b = self._a
            self._last_pos = b.body_start / SAMPLE_RATE
            self._start_locked(self._body_segs(b, b.body_start, b.frames))
            return
        self._last_pos = f / SAMPLE_RATE
        self._start_locked(self._from_frame_locked(f))

    # ---- preparación (hilo de trabajo) ------------------------------------------------------------------------------------
    def _ensure_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._tasks = _queue.Queue()
            self._worker = threading.Thread(target=self._run, args=(self._tasks,), name="dj-engine", daemon=True)
            self._worker.start()

    def _run(self, tasks):
        while True:
            task = tasks.get()
            if task is None:
                return
            try:
                task[0](*task[1:])
            except Exception as e:                              # nunca sale nada del hilo
                log.exception("fallo en el hilo de trabajo del DJ")
                with self._lock:
                    self._error = str(e) or type(e).__name__

    def _load(self, path):
        try:
            data = self._loader(path)
        except Exception as e:
            log.warning("el cargador falló con %s: %s", path, e)
            with self._lock:
                self._error = f"no se pudo cargar {path}: {e}"
            return None
        return data if data is not None and len(data) else None

    def _apply_gain(self, lufs_fn, path, data) -> float:
        """Ganancia de volumen igualado, aplicada en el sitio. El pico con max/min: sin copia del array."""
        try:
            lufs = lufs_fn(path)
        except Exception as e:
            log.warning("no se pudo saber el volumen de %s: %s", path, e)
            lufs = None
        peak = max(float(data.max()), -float(data.min()))
        g = _gain_for(lufs, peak)
        if g != 1.0:
            data *= g
        return g

    def _task_load(self, gen, path):
        with self._lock:
            if gen != self._gen:
                return
        data, g, err = None, 1.0, None
        try:
            data = self._load(path)
            if data is not None:
                g = self._apply_gain(self._lufs_stored, path, data)
        except Exception as e:                              # el volumen o el pico fallaron: no se queda «cargando» para siempre
            log.exception("fallo al preparar %s", path)
            data, err = None, f"no se pudo cargar {path}: {e}"
        with self._lock:
            if gen != self._gen:
                return
            self._loading = None
            if data is None:
                self._error = err or self._error or f"no se pudo cargar {path}"
                self._a = None
                return
            a = self._a = _Track(path, data, g)
            f = min(max(0, round(self._load_start * SAMPLE_RATE)), a.frames - 1)
            self._last_pos = f / SAMPLE_RATE
            self._start_locked(self._body_segs(a, f, a.frames))
            self.timings["sound"] = time.monotonic() - self._t_play
            self._ask = _Ask("next", path, a.id, 1, self._tick_no + 1)

    def _task_prep(self, gen, pgen, a_id, b_path, attempt):
        with self._lock:
            a = self._a
            if gen != self._gen or pgen != self._pgen or a is None or a.id != a_id:
                return
        try:
            pair = self._build_pair(a, b_path)
            err = None
        except Exception as e:
            log.exception("no se pudo preparar la transición a %s", b_path)
            pair, err = None, f"no se pudo preparar {b_path}: {e}"
        with self._lock:
            if gen != self._gen or pgen != self._pgen or self._a is not a:
                return
            self._preparing = None
            if err:
                self._error = err
            if pair is None:
                if attempt < MAX_TRIES:
                    self._ask = _Ask("skip", b_path, a.id, attempt + 1, 0)
                else:
                    self._no_next = True
                return
            self._pair = pair
            self._install_locked()
            if "ready" not in self.timings:
                self.timings["ready"] = time.monotonic() - self._t_play

    def _info(self, path, frames) -> dict:
        try:
            info = self._info_for(path)
        except Exception as e:
            log.warning("info_for falló con %s: %s", path, e)
            info = None
        info = dict(info) if isinstance(info, dict) else {}
        known = mix_points.seconds(info, "duration")
        info["duration_s"] = frames / SAMPLE_RATE           # la duración de lo decodificado, no la del análisis (podría pasarse por una muestra)
        info.pop("duration_ms", None)
        if _truncated(frames, known):
            # el cargador la cortó en su tope: su final (outro) no está en lo cargado. Se marca y el final pasa a ser «de golpe»
            info["truncated"] = True
            info.pop("outro_ms", None)
            info["outro_s"] = 0.0
        return info

    def _build_pair(self, a, b_path):
        """Carga B, iguala su volumen, planifica y prepara la mezcla. None si B no se pudo cargar."""
        body = self._load(b_path)
        if body is None:
            return None
        gain = self._apply_gain(self._lufs_measure, b_path, body)
        b = _Track(b_path, body, gain)
        info_a, info_b = self._info(a.path, a.frames), self._info(b_path, b.frames)
        plan = mix_planner.plan_transition(info_a, info_b, self.bars)
        grid_a = info_a.get("beatgrid") if isinstance(info_a.get("beatgrid"), BeatGrid) else None
        ctx = _Ctx(info_a, info_b, grid_a)
        if info_a.get("truncated"):
            c = self._bar_before(a, grid_a, a.frames)
            plan = mix_points.cut(c / SAMPLE_RATE, plan.b_start_s,
                                  f"corte limpio al llegar al tope de {_max_minutes()} min que se carga de cada canción "
                                  "(el resto de la que suena no se carga)")
        if plan.kind != KIND_CUT and plan.length_s > 0:
            plan = self._before_silence(a, plan, grid_a)
        verdict = None
        if plan.kind != KIND_CUT and plan.length_s > 0 and self.audio_check:
            verdict = transition_scorer.score_plan(info_a, info_b, plan)
            if verdict["verdict"] == transition_scorer.VERDICT_DISCARD:
                end = min(a.frames, round((plan.a_start_s + plan.length_s) * SAMPLE_RATE))
                plan = mix_points.cut(self._bar_before(a, grid_a, end) / SAMPLE_RATE, plan.b_start_s,
                                      "corte limpio: el puntuador descartó la mezcla (" + "; ".join(verdict["reasons"]) + ")")
        if plan.kind != KIND_CUT and plan.length_s > 0:
            pair, why = self._blend(a, b, plan, ctx)
            if pair is not None:
                if verdict is not None:
                    pair.check["plan"] = verdict["verdict"]
                if self.loops:
                    self._add_loop(pair, a, ctx)
                return pair
            # donde A se habría ido del todo (su final, si la mezcla no cabía): no se tira el final de A
            end = min(a.frames, round((plan.a_start_s + plan.length_s) * SAMPLE_RATE))
            plan = mix_points.cut(self._bar_before(a, grid_a, end) / SAMPLE_RATE, plan.b_start_s, "corte limpio: " + why)
        return self._cut(a, b, plan, ctx, round(plan.a_start_s * SAMPLE_RATE), round(plan.b_start_s * SAMPLE_RATE))

    @staticmethod
    def _add_loop(pair, a, ctx):
        """Bucle antes de la mezcla si `loops.needs_loop` lo pide: A repite sus `LOOP_BARS` compases de antes del punto de mezcla
        y la mezcla (la misma, desde la misma muestra de A) suena `loop_bars` compases más tarde."""
        grid_b = ctx.info_b.get("beatgrid") if isinstance(ctx.info_b.get("beatgrid"), BeatGrid) else None
        info_b = dict(ctx.info_b, intro_s=mix_points.seconds(ctx.info_b, "intro"))     # needs_loop solo lee intro_s
        try:
            extra, why = loops.needs_loop(ctx.info_a, info_b, pair.plan, ctx.grid_a, grid_b)
            if extra <= 0:
                return
            segs, _ = loops.extend_body(a.data, ctx.grid_a, pair.plan.a_start_s, extra, loop_bars=LOOP_BARS)
        except Exception as e:                                  # una ayuda nunca debe romper la mezcla
            log.warning("no se pudo preparar el bucle: %s", e)
            return
        if not segs or round(pair.plan.a_start_s * SAMPLE_RATE) != pair.a_mix:
            return
        pair.loop_segs = segs
        pair.loop_start = pair.a_mix - len(segs[0])
        pair.loop_id = next(_loop_ids)
        pair.loop_bars = extra
        pair.plan = dataclasses.replace(pair.plan, reason=f"{pair.plan.reason}; {why}")

    @staticmethod
    def _before_silence(a, plan, grid_a):
        """Si A se queda en silencio digital dentro de la mezcla (muchos mp3 acaban con segundos de silencio y el final del
        análisis lo incluye), la mezcla se adelanta (compases enteros con rejilla) para que acabe donde A deja de sonar: si no,
        la mitad de la mezcla sería B entrando sola y floja sobre un silencio (un bajón de volumen)."""
        sr = SAMPLE_RATE
        a_mix, n = round(plan.a_start_s * sr), round(plan.length_s * sr)
        end = min(a_mix + n, a.frames)
        last = _last_sound(a.data, end, plan.length_s)
        if last is None or end - last < int(SILENCE_SHIFT_MIN_S * sr):
            return plan
        need = (end - last) / sr
        low = max(0.0, a.frames / sr / 2.0)
        shift = need
        if grid_a is not None:                                  # frases de 8 compases si cabe, si no de 4, si no compases
            for bars in (8, 4, 1):
                shift = math.ceil(need / (bars * grid_a.bar_s) - 1e-9) * bars * grid_a.bar_s
                if plan.a_start_s - shift >= low:
                    break
        start = plan.a_start_s - shift
        if start < low:
            return plan
        return dataclasses.replace(plan, a_start_s=round(start, 3),
                                   reason=f"{plan.reason}; adelantada {mix_points.fmt_seconds(shift)}: la que suena acaba en silencio")

    @staticmethod
    def _bar_before(a, grid_a, end) -> int:
        """Muestra del comienzo de compás de A más cercano antes de `end` (a menos de un compás), o `end` sin rejilla."""
        if grid_a is None:
            return int(end)
        try:
            bar = math.floor(grid_a.bar_at(end / SAMPLE_RATE) + 1e-9)
            c = round(grid_a.bar_time(bar) * SAMPLE_RATE)
        except (ValueError, ZeroDivisionError, OverflowError):
            return int(end)
        return c if 0 < c <= end and end - c <= grid_a.bar_s * SAMPLE_RATE + 1 else int(end)

    # ---- tipos de transición -------------------------------------------------------------------------------------------
    def _choose(self, ctx, plan):
        """(tipo, motivo) de la transición. Sin `typed`: mezcla larga (o corte limpio, que con un plan de corte es lo mismo)."""
        cut = plan.kind == KIND_CUT or plan.length_s <= 0
        default = transition_types.TYPE_CUT_BAR if cut else transition_types.TYPE_BLEND
        if not self.typed or ctx is None:
            return default, ""
        try:
            return transition_types.choose_type(ctx.info_a, ctx.info_b, plan, ctx.bpm_a, profile=getattr(self, "profile", None))
        except Exception as e:                                  # una regla de ayuda nunca debe romper la mezcla
            log.warning("no se pudo elegir el tipo de transición: %s", e)
            return default, ""

    @staticmethod
    def _render(a_part, b_part, plan, kind, ctx):
        """(mezcla, cola) del tipo `kind`. La mezcla larga y el corte limpio, con `render_transition` tal cual."""
        if kind == transition_types.TYPE_BLEND or (kind == transition_types.TYPE_CUT_BAR and plan.kind == KIND_CUT):
            x = dj_dsp.render_transition(a_part, b_part, plan)
            return x, x[:0]
        return transition_types.render_typed_parts(a_part, b_part, plan, kind, bpm=ctx.bpm_a if ctx else None)

    @staticmethod
    def _typed_plan(plan, why):
        return dataclasses.replace(plan, reason=f"{plan.reason}; tipo: {why}") if why else plan

    @staticmethod
    def _tail_entry(b, b_body, join, tail, t0, ratio, gain=None):
        """Lo que suena tras la mezcla antes del cuerpo normal de B: el empalme del tramo estirado (`join`) y, si el tipo deja
        cola (eco de salida) o hay ganancia de entrada (`gain`, una por muestra desde el final de la mezcla), el principio del
        cuerpo de B con la ganancia aplicada y la cola SUMADA (copia: el cuerpo de B no se toca). Devuelve
        ([(array, etiqueta)], muestra de B donde sigue su cuerpo)."""
        np = dj_dsp._np()
        k_join = len(join) if join is not None else 0
        m = len(tail)
        k_gain = len(gain) if gain is not None else 0
        only_join = ([(join, _Label(b.id, "entry", t0, ratio))], b_body + k_join) if k_join else ([], b_body)
        length = min(max(m, k_join, k_gain), b.frames - b_body)
        if (not m and not k_gain) or length <= 0:
            return only_join
        post = np.empty((length, 2), dtype=np.float32)
        kj = min(k_join, length)
        if kj:
            post[:kj] = join[:kj]
        post[kj:] = b.data[b_body + kj:b_body + length]
        kg = min(k_gain, length)
        if kg:
            post[:kg] *= gain[:kg, None]
        k = min(m, length)
        add = tail[:k]
        if k < m:                                               # B se acaba antes que el eco: que la cola baje a cero
            add = add.copy()
            dj_fx._fade_out(add, min(k, int(0.05 * SAMPLE_RATE)))
        post[:k] += add
        return [(post, _Label(b.id, "entry", t0, 1.0))], b_body + length

    def _blend(self, a, b, plan, ctx):
        """(_Pair, None) con la mezcla hecha, o (None, motivo) si no cabe (datos del análisis que no cuadran con el audio)."""
        sr = SAMPLE_RATE
        ratio = float(plan.tempo_ratio_b or 1.0)
        a_mix, n = round(plan.a_start_s * sr), round(plan.length_s * sr)
        bs, b_body = round(plan.b_start_s * sr), round((plan.b_start_s + plan.length_s * ratio) * sr)
        if a_mix < 0 or a_mix + n > a.frames + round(FIT_TOL_S * sr):
            return None, "la mezcla no cabe en la canción que suena"
        if b_body + int(MIN_CHUNK_S * sr) > b.frames:
            return None, "la canción que entra es demasiado corta"
        join = join_tail = None
        if abs(ratio - 1.0) < 1e-6:
            piece = b.data[bs:bs + n]                           # ya con su ganancia
        else:
            piece = self._load_piece(b.path, ratio, plan, extra_s=JOIN_S)
            if piece is None:
                return None, "no se pudo cambiar el tempo de la que entra"
            piece *= b.gain
            join_tail = piece[n:]
            join, piece = self._join_piece(join_tail, b, b_body), piece[:n]
        kind, why = self._choose(ctx, plan)
        a_part = a.data[a_mix:a_mix + n]
        base_plan = plan
        raw_piece = piece

        def make(kind):
            """(plan, A y B en la mezcla con sus ganancias de entrada, mezcla, cola, split, (ganancia de B, de A), curva de B
            tras la mezcla)."""
            plan_k = self._audible_plan(base_plan, kind, a_part, raw_piece, ctx)
            split_k = self._split(kind, plan_k, n)
            lvl, fade = int(TRIM_LEVEL_S * sr), int(TRIM_A_FADE_S * sr)
            together = kind in (transition_types.TYPE_BLEND, transition_types.TYPE_FILTER)
            gains = self._entry_trim(a_part[max(0, split_k - lvl):split_k], raw_piece[split_k:split_k + lvl], together,
                                     (raw_piece[split_k:], b.data[b_body:b_body + int(TRIM_RAMP_S * sr)]),
                                     (a_part[max(0, split_k - fade):split_k],))
            a_k, piece_k, post_gain = a_part, raw_piece, None
            if gains[0] != 1.0:
                curve = _trim_curve(gains[0], split_k, max(n, split_k + int(TRIM_RAMP_S * sr)))
                piece_k = raw_piece * curve[:len(raw_piece), None]
                post_gain = curve[n:] if len(curve) > n else None
            if gains[1] != 1.0:                                 # el final de A, en los 2 s de antes del corte, y luego nada
                lo_f = max(0, split_k - fade)
                a_k = a_part.copy()
                a_k[lo_f:split_k] *= _fade_to(gains[1], split_k - lo_f)[:, None]
                a_k[split_k:] *= np.float32(gains[1])
            x_k, tail_k = self._render(a_k, piece_k, plan_k, kind, ctx)
            return plan_k, a_k, piece_k, x_k, tail_k, split_k, gains, post_gain

        np = dj_dsp._np()
        plan, a_used, piece, x, tail, split, gains, post_gain = make(kind)
        check = {}
        if self.audio_check:
            t0 = time.perf_counter()
            k = int(CHECK_CONTEXT_S * sr)
            # lo que suena de verdad tras la mezcla: el empalme y el cuerpo, con la ganancia de entrada
            after = self._after_mix(b, b_body, join, k, post_gain)
            bad = self._audio_problems(x, a_used, piece, plan, kind, split, ctx, a.data[max(0, a_mix - k):a_mix], after)
            check = {"audio": bad}
            new = None
            if bad and kind != transition_types.TYPE_CUT_BAR:
                new = transition_types.TYPE_CUT_BAR
            elif bad and any("hueco" in m for m in bad):      # el corte deja un silencio: la mezcla lo tapa con la otra
                new = transition_types.TYPE_BLEND
            if new is not None:
                old, kind = kind, new
                what = "corte en el compás" if new == transition_types.TYPE_CUT_BAR else "mezcla"
                why = f"{what}: el puntuador descartó «{old}» ({'; '.join(bad)})"
                plan, a_used, piece, x, tail, split, gains, post_gain = make(kind)
                check["swapped"] = old
            check["seconds"] = round(time.perf_counter() - t0, 4)
        piece = a_part = raw_piece = a_used = None             # se sueltan (make los usa por cierre)
        self._note_gains(check, gains)
        x1_label = _Label(a.id, "x1", a_mix / sr, 1.0, a_mix)
        entry = [(x[split:], _Label(b.id, "entry", plan.b_start_s + split * ratio / sr, ratio))]
        ramp = None
        if join is not None and self.tempo_ramp and not len(tail) and post_gain is None:
            ramp = self._ramp_entry(b, join_tail, plan.b_start_s + plan.length_s * ratio, ratio)
        if ramp is not None:
            entry += ramp[0]
            b_body = ramp[1]
        else:
            more, b_body = self._tail_entry(b, b_body, join, tail, plan.b_start_s + n * ratio / sr, ratio, post_gain)
            entry += more
        for i, (_, lab) in enumerate(entry):
            lab.idx = i
        plan = self._typed_plan(plan, why)
        pair = _Pair(b, plan, a_mix, x[:split], x1_label, entry, b_body, bs, ctx.grid_a, ctx, kind)
        pair.check = check
        return pair, None

    def _entry_trim(self, a_end, b_start, together, b_parts, a_parts):
        """(ganancia de B, ganancia del final de A), como el mando de ganancia de un DJ: el nivel de lo último que suena de A
        (`a_end`) y el de lo primero de B (`b_start`, ya con su volumen igualado), sin contar el silencio, deben quedar iguales.
        Primero se mueve B (entre -12 y +6 dB, sin que su pico en `b_parts` pase de `TRIM_PEAK`) y lo que falte, el final de A
        (entre -12 y +6 dB, con el mismo tope en `a_parts`). En una mezcla (`together`, las dos suenan a la vez) solo B y solo
        desde `TRIM_BLEND_DB`. (1, 1) si está apagada, si A ya calla, si B calla o si la diferencia es pequeña."""
        if not self.entry_gain:
            return 1.0, 1.0
        la, lb = _gated_rms(a_end), _gated_rms(b_start)
        if la is None or lb is None:
            return 1.0, 1.0
        diff = 20.0 * math.log10(la / lb)                       # positivo: B entra más floja que lo que acaba de A
        if abs(diff) < TRIM_MIN_DB or (together and diff < TRIM_BLEND_DB):
            return 1.0, 1.0                                     # en una mezcla B solo se sube (bajarla destaparía el final de A)
        db_b = min(max(diff, TRIM_B_DB[0]), TRIM_B_DB[1])
        if db_b > 0:
            pb = _peak(*b_parts)
            if pb > 0:
                db_b = min(db_b, max(0.0, 20.0 * math.log10(TRIM_PEAK / pb)))
        db_a = 0.0 if together else min(max(db_b - diff, TRIM_A_DB[0]), TRIM_A_DB[1])
        if db_a > 0:
            pa = _peak(*a_parts)
            if pa > 0:
                db_a = min(db_a, max(0.0, 20.0 * math.log10(TRIM_PEAK / pa)))
        return (10.0 ** (db_b / 20.0) if abs(db_b) >= 0.1 else 1.0), (10.0 ** (db_a / 20.0) if abs(db_a) >= 0.1 else 1.0)

    @staticmethod
    def _note_gains(check, gains):
        if gains[0] != 1.0:
            check["entry_gain_db"] = round(20.0 * math.log10(gains[0]), 2)
        if gains[1] != 1.0:
            check["a_end_gain_db"] = round(20.0 * math.log10(gains[1]), 2)

    @staticmethod
    def _after_mix(b, b_body, join, k, gain):
        """Los primeros k muestras que suenan tras la mezcla (empalme y cuerpo de B), con la ganancia de entrada si la hay."""
        np = dj_dsp._np()
        after = b.data[b_body:b_body + k]
        if join is not None:
            after = np.concatenate((join, b.data[b_body + len(join):b_body + k]))
        if gain is not None and len(gain):
            after = after.copy()
            kg = min(len(gain), len(after))
            after[:kg] *= gain[:kg, None]
        return after

    @staticmethod
    def _audible_plan(plan, kind, a_part, b_part, ctx):
        """Con corte en el compás o eco, el corte (`bass_swap_at`) debe caer donde A aún suena justo antes y B ya suena justo
        después (si no, un silencio: A con su final mudo o B con su principio mudo). Si no es así, se mueve al comienzo de
        compás de A más cercano en que sí (o cada medio segundo sin rejilla). Con los demás tipos, el plan tal cual."""
        if kind not in (transition_types.TYPE_CUT_BAR, transition_types.TYPE_ECHO_OUT):
            return plan
        sr = SAMPLE_RATE
        n = round(plan.length_s * sr)
        win = int(SOUND_WIN_S * sr)

        def ok(c):
            return (_sounds(a_part[max(0, c - win):c]) and _sounds(b_part[c:c + win])
                    and _fading_end(a_part, c) is None and _quiet_start(b_part, c) is None)

        c = transition_types._cut_point(plan, n, sr)
        if ok(c):
            return plan
        grid = ctx.grid_a if ctx is not None else None
        if grid is not None:
            first = math.ceil(grid.bar_at(plan.a_start_s) - 1e-9)
            last = math.floor(grid.bar_at(plan.a_start_s + plan.length_s) + 1e-9)
            cands = [round((grid.bar_time(k) - plan.a_start_s) * sr) for k in range(first, last + 1)]
        else:
            cands = list(range(0, n, int(0.5 * sr)))
        cands = sorted((x for x in cands if win <= x <= n - win), key=lambda x: abs(x - c))
        best = next((x for x in cands if ok(x)), None)
        if best is None:
            return plan
        return dataclasses.replace(plan, bass_swap_s=round(best / sr, 3))

    @staticmethod
    def _split(kind, plan, n) -> int:
        """Dónde se parte la mezcla (desde ahí domina B): la mitad, o el corte con corte en el compás y eco de salida."""
        if kind in (transition_types.TYPE_CUT_BAR, transition_types.TYPE_ECHO_OUT):
            return transition_types._cut_point(plan, n, SAMPLE_RATE)
        return n // 2

    def _audio_problems(self, x, a_part, b_part, plan, kind, split, ctx, a_before, b_after) -> list:
        """Motivos (en español) por los que el puntuador DESCARTA esta mezcla por algo que un corte en el compás arregla: clic,
        recorte, hueco de silencio o salto de volumen. [] si nada. Los veredictos de gusto (golpes, graves, voces, tonos) no se
        usan aquí. Umbrales: los de `transition_scorer` (CLICK_RATIO, CLIP_DISCARD, GAP_DISCARD_MS, LOUD_DISCARD_DB)."""
        try:
            if self.audio_check == "full":
                return self._full_problems(x, a_part, b_part, plan, kind, split, ctx, a_before, b_after)
            return self._light_problems(x, a_part, b_part, kind, split, a_before, b_after)
        except Exception as e:                                  # el puntuador nunca debe romper la mezcla
            log.warning("no se pudo puntuar la mezcla: %s", e)
            return []

    @staticmethod
    def _lines(np, x, a_part, b_part, kind, split):
        """A y B en la línea de tiempo de la mezcla y su ganancia de medios y agudos (fundido, o escalón en el corte)."""
        ts = transition_scorer
        n = len(x)
        if kind in (transition_types.TYPE_ECHO_OUT, transition_types.TYPE_CUT_BAR):
            a_line, b_line = ts._place(np, a_part[:split], 0, n), ts._place(np, b_part[split:], split, n)
            gain_a = (np.arange(n) < split).astype(np.float64)
            return a_line, b_line, gain_a, 1.0 - gain_a
        gain_a, gain_b = ts._fades(np, np.arange(n) / SAMPLE_RATE, n / SAMPLE_RATE)
        return ts._place(np, a_part, 0, n), ts._place(np, b_part, 0, n), gain_a, gain_b

    def _light_problems(self, x, a_part, b_part, kind, split, a_before, b_after) -> list:
        ts = transition_scorer
        np = dj_dsp._np()
        sr = SAMPLE_RATE
        n = len(x)
        bad = []
        a_line, b_line, gain_a, gain_b = self._lines(np, x, a_part, b_part, kind, split)
        added = float((np.abs(x) > 1.0).mean()) - max(float((np.abs(a_line) > 1.0).mean()), float((np.abs(b_line) > 1.0).mean()))
        if added >= ts.CLIP_DISCARD:
            bad.append(f"recorte en un {added * 100:.2f} % de las muestras".replace(".", ","))
        gap = ts._silence_gap_ms(np, x, sr)
        if gap >= ts.GAP_DISCARD_MS:
            bad.append(f"hueco de silencio de {gap:.0f} ms")
        w = int(CHECK_CLICK_S * sr)
        joins = [(np.concatenate((a_before[-w:], x[:w])), (np.concatenate((a_before[-w:], a_part[:w])),)),
                 (np.concatenate((x[-w:], b_after[:w])), (np.concatenate((b_part[-w:], b_after[:w])),))]
        if kind in (transition_types.TYPE_ECHO_OUT, transition_types.TYPE_CUT_BAR):
            lo, hi = max(0, split - w), min(n, split + w)
            joins.append((x[lo:hi], (a_part[lo:hi], b_part[lo:hi])))
        for seq, refs in joins:
            ratio = ts._click_ratio(np, seq, sr)[0]
            base = max((ts._click_ratio(np, r, sr)[0] for r in refs if len(r) > 2), default=0.0)
            if ratio >= ts.CLICK_RATIO and (base <= 0 or ratio >= ts.CLICK_VS_PARTS * base):
                bad.append(f"clic en una unión (salto de {ratio:.0f} veces lo normal)")
                break
        k = int(CHECK_CONTEXT_S * sr)
        excess = ts._loudness(np, x, a_line, b_line, gain_a, gain_b, a_before[-k:], b_after[:k], sr,
                              split if kind in (transition_types.TYPE_ECHO_OUT, transition_types.TYPE_CUT_BAR) else None)[0]
        if excess is not None and excess >= ts.LOUD_DISCARD_DB:
            bad.append(f"salto de volumen de {excess:.1f} dB".replace(".", ","))
        return bad

    @staticmethod
    def _full_problems(x, a_part, b_part, plan, kind, split, ctx, a_before, b_after) -> list:
        ts = transition_scorer
        if kind in (transition_types.TYPE_ECHO_OUT, transition_types.TYPE_CUT_BAR):     # como un corte en `split`
            a_part, b_part = a_part[:split], b_part[split:]
            plan = TransitionPlan(plan.a_start_s, plan.b_start_s, 0.0, 1.0, None, KIND_CUT, plan.reason)
        info_a, info_b = ctx.info_a if ctx else {}, ctx.info_b if ctx else {}
        grid_b = info_b.get("beatgrid") if isinstance(info_b.get("beatgrid"), BeatGrid) else None
        res = ts.score_audio(x, a_part, b_part, plan, ctx.grid_a if ctx else None, grid_b, tone_a=info_a.get("tone"),
                             tone_b=info_b.get("tone"), tone_conf_a=info_a.get("tone_conf"), tone_conf_b=info_b.get("tone_conf"),
                             a_before=a_before, b_after=b_after)
        m = res["metrics"]
        bad = []
        if (m.get("click") or {}).get("note") == 0.0:
            bad.append("clic")
        if ((m.get("clipping") or {}).get("added") or 0.0) >= ts.CLIP_DISCARD:
            bad.append("recorte")
        if ((m.get("silence_gap_ms") or {}).get("value") or 0.0) >= ts.GAP_DISCARD_MS:
            bad.append("hueco de silencio")
        if ((m.get("loudness_step_db") or {}).get("value") or 0.0) >= ts.LOUD_DISCARD_DB:
            bad.append("salto de volumen")
        return bad

    def _ramp_entry(self, b, tail, t, ratio):
        """Rampa de vuelta al tempo original de B tras una mezcla con B estirada: `RAMP_STEPS` tramos de `RAMP_SEG_S` s con
        el tempo cada vez más cerca de 1,0 (con 0,96: 0,97, 0,98, 0,99), cada uno cargado con el cargador desde donde acaba
        el anterior (en el tiempo de B) y empalmado con el mismo fundido de 20 ms que el empalme normal; el último se empalma
        con el cuerpo original de B. `tail`: lo que el tramo estirado de la mezcla sigue tras ella. Devuelve
        ([(array, etiqueta)], muestra de B donde sigue su cuerpo) o None si algún tramo no se pudo cargar o no cabe."""
        np = dj_dsp._np()
        sr = SAMPLE_RATE
        seg_n = round(RAMP_SEG_S * sr)
        out = []
        for i in range(1, RAMP_STEPS + 1):
            r = ratio + (1.0 - ratio) * i / (RAMP_STEPS + 1)
            if round((t + (RAMP_SEG_S + JOIN_S) * r) * sr) + int(MIN_CHUNK_S * sr) > b.frames:
                return None
            pre = min(RAMP_PREROLL_S, t)                        # se carga desde antes y se tira: el arranque de rubberband
            skip = round(pre / r * sr)
            try:
                seg = self._loader(b.path, tempo_ratio=r, start_s=t - pre, duration_s=pre + (RAMP_SEG_S + JOIN_S) * r)
            except Exception as e:
                log.warning("no se pudo cargar la rampa de tempo de %s: %s", b.path, e)
                return None
            if seg is None or len(seg) < skip + seg_n + 8:
                return None
            seg = (seg[skip:] * np.float32(b.gain)).astype(np.float32)
            k = min(len(tail), seg_n)
            if k:
                fade = np.linspace(0.0, 1.0, k, dtype="float32")[:, None]
                seg[:k] = tail[:k] * (1.0 - fade) + seg[:k] * fade
            out.append((seg[:seg_n], _Label(b.id, "entry", t, r)))
            tail = seg[seg_n:]
            t += RAMP_SEG_S * r
        b_body = round(t * sr)
        join = self._join_piece(tail, b, b_body)
        if join is not None:
            out.append((join, _Label(b.id, "entry", t, 1.0)))
            b_body += len(join)
        return out, b_body

    @staticmethod
    def _join_piece(tail, b, b_body):
        """El empalme de B: el tramo estirado sigue unos 20 ms más (`tail`) y se funde en línea recta con el cuerpo original de B desde
        `b_body`. Las dos versiones son la misma música con unos milisegundos de desfase del estirado: sin este fundido, el paso de una a
        otra es un salto de la onda (un clic en cada mezcla con cambio de tempo). None si no hay tramo suficiente."""
        k = min(len(tail), b.frames - b_body)
        if k < 8:
            return None
        import numpy as np
        fade = np.linspace(0.0, 1.0, k, dtype="float32")
        body = b.data[b_body:b_body + k]
        return (tail[:k] * (1.0 - fade)[:, None] + body * fade[:, None]).astype("float32")

    def _load_piece(self, path, ratio, plan, extra_s=0.0):
        try:
            piece = self._loader(path, tempo_ratio=ratio, start_s=plan.b_start_s, duration_s=(plan.length_s + extra_s) * ratio)
        except Exception as e:
            log.warning("no se pudo estirar %s: %s", path, e)
            return None
        return piece if piece is not None and len(piece) else None

    def _cut(self, a, b, plan, ctx, c, bs, lo_min=0):
        """Corte limpio en la muestra c de A hacia la muestra bs de B: dos piezas de 0,5 s con sus rampas (y, con el tipo eco
        de salida, el eco del último golpe de A sumado a lo que sigue de B)."""
        sr = SAMPLE_RATE
        piece = int(CUT_PIECE_S * sr)
        c = min(max(c, lo_min), a.frames)
        bs = min(max(bs, 0), max(0, b.frames - 1))
        win = int(SOUND_WIN_S * sr)
        moved = []
        if c > lo_min and not _sounds(a.data[max(lo_min, c - win):c]):     # A ya no suena: se corta donde deja de sonar
            end = _last_sound(a.data, c)
            if end is not None and end > lo_min:
                c = end
                moved.append("la que suena ya estaba en silencio")
        if not _sounds(b.data[bs:bs + win]):                               # B empieza en silencio: entra donde suena
            first = _first_sound(b.data, bs)
            if first is not None and first + int(MIN_CHUNK_S * sr) < b.frames:
                bs = max(0, first - int(0.01 * sr))
                moved.append("la que entra empezaba en silencio")
        end = _fading_end(a.data, c) if self.entry_gain else None
        if end is not None and lo_min < end < c:                           # A se apagaba: se corta antes del apagado
            c = end
            moved.append("la que suena se estaba apagando")
        first = _quiet_start(b.data, bs) if self.entry_gain else None
        if first is not None and first > bs and first + int(MIN_CHUNK_S * sr) < b.frames:
            bs = first                                                     # B arrancaba muy callada: entra donde ya suena
            moved.append("la que entra arrancaba muy callada")
        lo = max(lo_min, c - piece)
        if plan.kind != KIND_CUT:
            plan = TransitionPlan(c / sr, bs / sr, 0.0, 1.0, None, KIND_CUT, plan.reason)
        if moved:
            plan = dataclasses.replace(plan, a_start_s=round(c / sr, 3), b_start_s=round(bs / sr, 3),
                                       reason=f"{plan.reason}; corte movido: {' y '.join(moved)}")
        kind, why = self._choose(ctx, plan)
        b_part = b.data[bs:bs + piece]
        lvl, fade = int(TRIM_LEVEL_S * sr), int(TRIM_A_FADE_S * sr)
        gains = self._entry_trim(a.data[max(0, c - lvl):c], b.data[bs:bs + lvl], False,
                                 (b.data[bs:bs + int(TRIM_RAMP_S * sr)],), (a.data[max(lo_min, c - fade):c],))
        if gains[1] != 1.0:
            lo = max(lo_min, c - fade)                          # el final de A va en la pieza del corte para poder bajarlo
        k = c - lo
        a_piece = a.data[lo:c]
        if gains[1] != 1.0:
            a_piece = a_piece * _fade_to(gains[1], k)[:, None]
        post_gain = None
        if gains[0] != 1.0:
            curve = _trim_curve(gains[0], k, k + len(b_part) + int(TRIM_RAMP_S * sr))
            b_part = b_part * curve[k:k + len(b_part), None]
            post_gain = curve[k + len(b_part):]
        x, tail = self._render(a_piece, b_part, plan, kind, ctx)
        x1 = x[:k] if k else None
        entry = [(x[k:], _Label(b.id, "entry", bs / sr, 1.0))]
        b_body = bs + (len(x) - k)
        more, b_body = self._tail_entry(b, b_body, None, tail, b_body / sr, 1.0, post_gain)
        entry += more
        for i, (_, lab) in enumerate(entry):
            lab.idx = i
        pair = _Pair(b, self._typed_plan(plan, why), lo, x1, _Label(a.id, "x1", lo / sr, 1.0, lo), entry, b_body, bs,
                     ctx.grid_a if ctx else None, ctx, kind)
        self._note_gains(pair.check, gains)
        return pair

    def _late_cut_locked(self, f):
        """El plan llegó tarde (lo que suena ya pasa del punto de mezcla): corte limpio en el siguiente compás tras f."""
        a, p = self._a, self._pair
        sr = SAMPLE_RATE
        piece = int(CUT_PIECE_S * sr)
        c = f + piece
        if p.grid_a is not None:
            cb = round(p.grid_a.next_bar_time((f + piece + MIN_GAP_FRAMES) / sr) * sr)
            if cb <= a.frames:
                c = cb
        plan = TransitionPlan(min(c, a.frames) / sr, p.b_cut / sr, 0.0, 1.0, None, KIND_CUT,
                              "corte limpio en el siguiente compás: la transición llegó cuando el punto de mezcla ya había pasado")
        self._pair = self._cut(a, p.b, plan, p.ctx, c, p.b_cut, lo_min=f)
