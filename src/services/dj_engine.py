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

from services import dj_dsp, dj_fx, mix_planner, mix_points, transition_scorer, transition_types
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
CHECK_CONTEXT_S = 2.0           # el puntuador mira también los 2 s de antes y de después de la mezcla (saltos de volumen)
CHECK_CLICK_S = 0.05            # y busca clics en ±50 ms alrededor de cada unión de la mezcla
AUDIO_CHECKS = ("light", "full")
MAX_TRIES = 5                   # canciones seguidas que se intentan cargar como siguiente antes de rendirse
INSTALL_TRIES = 8               # reintentos de cambiar la cola si la llamada de audio avanza a la vez

_track_ids = itertools.count(1)


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
    __slots__ = ("track_id", "role", "t0", "ratio", "f0", "f1", "idx")

    def __init__(self, track_id, role, t0, ratio=1.0, f0=0, f1=0, idx=0):
        self.track_id = track_id
        self.role = role                # "body" (trozo del cuerpo), "x1" (1.ª mitad o final del corte), "entry"
        self.t0 = t0                    # segundo de la canción en el que empieza el segmento
        self.ratio = ratio              # segundos de la canción por segundo de salida (tempo de B en la mezcla)
        self.f0 = f0                    # "body" y "x1": primera muestra del cuerpo que cubre
        self.f1 = f1                    # "body": muestra del cuerpo donde acaba (sin incluir)
        self.idx = idx                  # "entry": posición en track.entry

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
    __slots__ = ("b", "plan", "a_mix", "x1", "x1_label", "entry", "b_body", "b_cut", "grid_a", "ctx", "kind", "check")

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
                 typed=True, audio_check="light"):
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
                "transition_type": p.kind if p is not None else None}

    def _locked_in_locked(self) -> bool:
        """¿Ha empezado ya la mezcla hacia B (su primera mitad suena)? Entonces B ya no se puede cambiar."""
        p = self._pair
        if p is None:
            return False
        cur = self._engine.current()
        lab = cur[0] if cur is not None else None
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
        segs = self._body_segs(a, f, p.a_mix)
        if p.x1 is not None:
            segs.append((p.x1, p.x1_label))
        segs += p.entry
        segs += self._body_segs(p.b, p.b_body, p.b.frames)
        return segs

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
            if (p is not None and lab.f0 < p.a_mix < lab.f1
                    and self._engine.truncate_current(cur[1], p.a_mix - lab.f0, round(TRUNC_GUARD_S * SAMPLE_RATE))):
                lab.f1 = p.a_mix                                # el trozo que suena acaba ya en el punto de mezcla
            return self._from_frame_locked(lab.f1)
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
                return pair
            # donde A se habría ido del todo (su final, si la mezcla no cabía): no se tira el final de A
            end = min(a.frames, round((plan.a_start_s + plan.length_s) * SAMPLE_RATE))
            plan = mix_points.cut(self._bar_before(a, grid_a, end) / SAMPLE_RATE, plan.b_start_s, "corte limpio: " + why)
        return self._cut(a, b, plan, ctx, round(plan.a_start_s * SAMPLE_RATE), round(plan.b_start_s * SAMPLE_RATE))

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
            return transition_types.choose_type(ctx.info_a, ctx.info_b, plan, ctx.bpm_a)
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
    def _tail_entry(b, b_body, join, tail, t0, ratio):
        """Lo que suena tras la mezcla antes del cuerpo normal de B: el empalme del tramo estirado (`join`) y, si el tipo deja
        cola (eco de salida), el principio del cuerpo de B con la cola SUMADA (copia: el cuerpo de B no se toca). Devuelve
        ([(array, etiqueta)], muestra de B donde sigue su cuerpo)."""
        np = dj_dsp._np()
        k_join = len(join) if join is not None else 0
        m = len(tail)
        only_join = ([(join, _Label(b.id, "entry", t0, ratio))], b_body + k_join) if k_join else ([], b_body)
        length = min(max(m, k_join), b.frames - b_body)
        if not m or length <= 0:
            return only_join
        post = np.empty((length, 2), dtype=np.float32)
        kj = min(k_join, length)
        if kj:
            post[:kj] = join[:kj]
        post[kj:] = b.data[b_body + kj:b_body + length]
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
        join = None
        if abs(ratio - 1.0) < 1e-6:
            piece = b.data[bs:bs + n]                           # ya con su ganancia
        else:
            piece = self._load_piece(b.path, ratio, plan, extra_s=JOIN_S)
            if piece is None:
                return None, "no se pudo cambiar el tempo de la que entra"
            piece *= b.gain
            join, piece = self._join_piece(piece[n:], b, b_body), piece[:n]
        kind, why = self._choose(ctx, plan)
        a_part = a.data[a_mix:a_mix + n]
        x, tail = self._render(a_part, piece, plan, kind, ctx)
        split = self._split(kind, plan, len(x))
        check = {}
        if self.audio_check and kind != transition_types.TYPE_CUT_BAR:
            t0 = time.perf_counter()
            k = int(CHECK_CONTEXT_S * sr)
            after = b.data[b_body:b_body + k]
            if join is not None:                                # lo que suena de verdad tras la mezcla: el empalme y el cuerpo
                after = dj_dsp._np().concatenate((join, b.data[b_body + len(join):b_body + k]))
            bad = self._audio_problems(x, a_part, piece, plan, kind, split, ctx, a.data[max(0, a_mix - k):a_mix], after)
            check = {"audio": bad}
            if bad:
                old = kind
                kind = transition_types.TYPE_CUT_BAR
                why = f"corte en el compás: el puntuador descartó «{old}» ({'; '.join(bad)})"
                x, tail = self._render(a_part, piece, plan, kind, ctx)
                split = self._split(kind, plan, len(x))
                check["swapped"] = old
            check["seconds"] = round(time.perf_counter() - t0, 4)
        del piece, a_part
        x1_label = _Label(a.id, "x1", a_mix / sr, 1.0, a_mix)
        entry = [(x[split:], _Label(b.id, "entry", plan.b_start_s + split * ratio / sr, ratio))]
        more, b_body = self._tail_entry(b, b_body, join, tail, plan.b_start_s + n * ratio / sr, ratio)
        entry += more
        for i, (_, lab) in enumerate(entry):
            lab.idx = i
        plan = self._typed_plan(plan, why)
        pair = _Pair(b, plan, a_mix, x[:split], x1_label, entry, b_body, bs, ctx.grid_a, ctx, kind)
        pair.check = check
        return pair, None

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
        if kind == transition_types.TYPE_ECHO_OUT:
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
        if kind == transition_types.TYPE_ECHO_OUT:
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
                              split if kind == transition_types.TYPE_ECHO_OUT else None)[0]
        if excess is not None and excess >= ts.LOUD_DISCARD_DB:
            bad.append(f"salto de volumen de {excess:.1f} dB".replace(".", ","))
        return bad

    @staticmethod
    def _full_problems(x, a_part, b_part, plan, kind, split, ctx, a_before, b_after) -> list:
        ts = transition_scorer
        if kind == transition_types.TYPE_ECHO_OUT:             # se mide como un corte en `split` (B sola desde ahí)
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
        lo = max(lo_min, c - piece)
        if plan.kind != KIND_CUT:
            plan = TransitionPlan(c / sr, bs / sr, 0.0, 1.0, None, KIND_CUT, plan.reason)
        kind, why = self._choose(ctx, plan)
        x, tail = self._render(a.data[lo:c], b.data[bs:bs + piece], plan, kind, ctx)
        k = c - lo
        x1 = x[:k] if k else None
        entry = [(x[k:], _Label(b.id, "entry", bs / sr, 1.0))]
        b_body = bs + (len(x) - k)
        more, b_body = self._tail_entry(b, b_body, None, tail, b_body / sr, 1.0)
        entry += more
        for i, (_, lab) in enumerate(entry):
            lab.idx = i
        return _Pair(b, self._typed_plan(plan, why), lo, x1, _Label(a.id, "x1", lo / sr, 1.0, lo), entry, b_body, bs,
                     ctx.grid_a if ctx else None, ctx, kind)

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
