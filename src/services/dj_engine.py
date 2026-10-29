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
  * Plan tardío: si cuando llega el plan el trozo que suena ya pasa del punto de mezcla, se hace un corte limpio en el primer
    comienzo de compás de A que deje sitio a la pieza de 0,5 s tras el final de ese trozo (o justo ahí si no hay rejilla).
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
import itertools
import logging
import math
import queue as _queue
import threading
import time

from services import dj_dsp, mix_planner, mix_points
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid, TransitionPlan

log = logging.getLogger(__name__)

CHUNK_S = 15.0                  # tamaño de los trozos del cuerpo
MIN_CHUNK_S = 1.0               # un último trozo más corto se junta con el anterior
CUT_PIECE_S = 0.5               # piezas del corte limpio (A con rampa de bajada, B con rampa de subida)
MIN_GAP_FRAMES = 4096           # en un corte tardío, el trozo de A que queda antes no puede ser más corto que esto
MAX_TRIES = 5                   # canciones seguidas que se intentan cargar como siguiente antes de rendirse
INSTALL_TRIES = 8               # reintentos de cambiar la cola si la llamada de audio avanza a la vez

_track_ids = itertools.count(1)


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


class _Pair:
    """Paso preparado de la actual (A) a la siguiente (B)."""
    __slots__ = ("b", "plan", "a_mix", "x1", "x1_label", "entry", "b_body", "b_cut", "grid_a")

    def __init__(self, b, plan, a_mix, x1, x1_label, entry, b_body, b_cut, grid_a):
        self.b = b
        self.plan = plan
        self.a_mix = a_mix              # muestra de A donde acaba su cuerpo y empieza x1
        self.x1 = x1                    # array (o None) que suena en tiempo de A
        self.x1_label = x1_label
        self.entry = entry              # [(array, etiqueta)] en tiempo de B: con él empieza `advanced`
        self.b_body = b_body            # muestra de B donde sigue su cuerpo
        self.b_cut = b_cut              # muestra de B por la que entraría un corte limpio (para el plan tardío)
        self.grid_a = grid_a


class _Ask:
    """Petición pendiente de `next_after` (la hace tick())."""
    __slots__ = ("kind", "after", "a_id", "attempt", "not_before")

    def __init__(self, kind, after, a_id, attempt, not_before):
        self.kind = kind                # "next" (tras cargar o avanzar), "replan" o "skip" (B no se pudo cargar)
        self.after = after              # ruta que se pasa a next_after
        self.a_id = a_id
        self.attempt = attempt
        self.not_before = not_before    # número de tick a partir del cual se puede pedir


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

    def __init__(self, engine, info_for, next_after, bars=16, loader=None, lead_s=45.0, lufs_stored=None, lufs_measure=None):
        if loader is None:
            from services import pcm_loader
            loader = pcm_loader.load
        self._engine = engine
        self._info_for = info_for
        self._next_after = next_after
        self.bars = bars
        self.lead_s = lead_s
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
            if self._loading is not None and self._loading == path:
                self._load_start = start_s
                return
            if self._loading is None and self._a is not None and self._a.path == path:
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
            if path is not None and path == self._pending_adopt:
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

    def stop(self):
        """Para, vacía el motor, suelta los arrays y termina el hilo de trabajo."""
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

    def replan(self):
        """La siguiente canción cambió: en el próximo tick se pide `next_after` y se rehace lo que aún no ha empezado."""
        with self._lock:
            if self._loading is not None or self._a is None:
                return
            self._sync_locked()
            if self._locked_in_locked():
                return
            self._no_next = False
            if self._ask is None or self._ask.kind != "skip":
                self._ask = _Ask("replan", self._a.path, self._a.id, 1, 0)

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
                "error": error, "plan": p.plan if p is not None else None, "next_path": nxt}

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
        if ask.kind == "replan" and ((p is not None and p.b.path == nxt) or (p is None and self._preparing == nxt)):
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
            return self._from_frame_locked(lab.f1 if started else lab.f0)
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
        data = self._load(path)
        g = self._apply_gain(self._lufs_stored, path, data) if data is not None else 1.0
        with self._lock:
            if gen != self._gen:
                return
            self._loading = None
            if data is None:
                self._error = self._error or f"no se pudo cargar {path}"
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
        if info.get("duration_s") is None and info.get("duration_ms") is None:
            info["duration_s"] = frames / SAMPLE_RATE       # sin análisis: la duración real
        return info

    def _build_pair(self, a, b_path):
        """Carga B, iguala su volumen, planifica y prepara la mezcla. None si B no se pudo cargar."""
        body = self._load(b_path)
        if body is None:
            return None
        gain = self._apply_gain(self._lufs_measure, b_path, body)
        b = _Track(b_path, body, gain)
        info_a = self._info(a.path, a.frames)
        plan = mix_planner.plan_transition(info_a, self._info(b_path, b.frames), self.bars)
        grid_a = info_a.get("beatgrid") if isinstance(info_a.get("beatgrid"), BeatGrid) else None
        if plan.kind != KIND_CUT and plan.length_s > 0:
            pair, why = self._blend(a, b, plan, grid_a)
            if pair is not None:
                return pair
            plan = mix_points.cut(min(plan.a_start_s, a.frames / SAMPLE_RATE), plan.b_start_s, "corte limpio: " + why)
        return self._cut(a, b, plan, grid_a, round(plan.a_start_s * SAMPLE_RATE), round(plan.b_start_s * SAMPLE_RATE))

    def _blend(self, a, b, plan, grid_a):
        """(_Pair, None) con la mezcla hecha, o (None, motivo) si no cabe (datos del análisis que no cuadran con el audio)."""
        sr = SAMPLE_RATE
        ratio = float(plan.tempo_ratio_b or 1.0)
        a_mix, n = round(plan.a_start_s * sr), round(plan.length_s * sr)
        bs, b_body = round(plan.b_start_s * sr), round((plan.b_start_s + plan.length_s * ratio) * sr)
        if a_mix < 0 or a_mix + n > a.frames:
            return None, "la mezcla no cabe en la canción que suena"
        if b_body + int(MIN_CHUNK_S * sr) > b.frames:
            return None, "la canción que entra es demasiado corta"
        if abs(ratio - 1.0) < 1e-6:
            piece = b.data[bs:bs + n]                           # ya con su ganancia
        else:
            piece = self._load_piece(b.path, ratio, plan)
            if piece is None:
                return None, "no se pudo cambiar el tempo de la que entra"
            piece *= b.gain
        x = dj_dsp.render_transition(a.data[a_mix:a_mix + n], piece, plan)
        del piece
        half = len(x) // 2
        x1_label = _Label(a.id, "x1", a_mix / sr, 1.0, a_mix)
        entry = [(x[half:], _Label(b.id, "entry", plan.b_start_s + half * ratio / sr, ratio))]
        return _Pair(b, plan, a_mix, x[:half], x1_label, entry, b_body, bs, grid_a), None

    def _load_piece(self, path, ratio, plan):
        try:
            piece = self._loader(path, tempo_ratio=ratio, start_s=plan.b_start_s, duration_s=plan.length_s * ratio)
        except Exception as e:
            log.warning("no se pudo estirar %s: %s", path, e)
            return None
        return piece if piece is not None and len(piece) else None

    def _cut(self, a, b, plan, grid_a, c, bs, lo_min=0):
        """Corte limpio en la muestra c de A hacia la muestra bs de B: dos piezas de 0,5 s con sus rampas."""
        sr = SAMPLE_RATE
        piece = int(CUT_PIECE_S * sr)
        c = min(max(c, lo_min), a.frames)
        bs = min(max(bs, 0), max(0, b.frames - 1))
        lo = max(lo_min, c - piece)
        if plan.kind != KIND_CUT:
            plan = TransitionPlan(c / sr, bs / sr, 0.0, 1.0, None, KIND_CUT, plan.reason)
        x = dj_dsp.render_transition(a.data[lo:c], b.data[bs:bs + piece], plan)
        k = c - lo
        x1 = x[:k] if k else None
        entry = [(x[k:], _Label(b.id, "entry", bs / sr, 1.0))]
        return _Pair(b, plan, lo, x1, _Label(a.id, "x1", lo / sr, 1.0, lo), entry, bs + (len(x) - k), bs, grid_a)

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
        self._pair = self._cut(a, p.b, plan, p.grid_a, c, p.b_cut, lo_min=f)
