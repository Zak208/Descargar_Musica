"""Motor de audio propio del modo DJ (fases 9 y 10): un flujo de salida continuo que reproduce, uno detrás de otro y a
precisión de muestra, segmentos de audio ya preparados (arrays estéreo float32 a 44.100 Hz).

La idea (decisión razonada y medida en docs/MOTOR_DJ.md): todo lo caro (decodificar, estirar el tempo, ecualizar, mezclar
dos canciones) se hace antes, en un hilo de trabajo, y aquí solo se copian trozos de arrays. La llamada de audio
(`_callback`, que la llama PortAudio desde su propio hilo) hace lo mínimo: copiar, aplicar una ganancia y apuntar cifras.

Uso típico (desde el hilo de la interfaz):
    eng = MixEngine()
    eng.on_segment_start = lambda label, seg_id, start_frame: ...
    eng.on_queue_empty = lambda position_frames: ...
    eng.start()                         # abre el flujo (silencio mientras no haya nada que tocar)
    eng.queue(cuerpo_a, "A")            # se tocan seguidos, sin huecos ni solapes
    eng.queue(transicion_ab, "A>B")
    eng.play()
    ... un QTimer cada 50 ms llama a eng.dispatch_events() (las notificaciones nunca se ejecutan en la llamada de audio)

Sin sounddevice (o sin tarjeta de sonido) `available()` devuelve False y `start()` devuelve False; todo lo demás funciona
igual con `pull(frames)`, que es la misma función que usa la llamada de audio (así se prueba el motor sin sonido).

Ganancias: la salida es contenido × ganancia maestra (`set_master_gain`, con rampa) × ganancia de pausa (micro-fundido de
15 ms al pausar, reanudar o saltar, para no hacer clic). No se recorta nada: si el contenido pasa de ±1, lo recorta el
dispositivo; quien prepara los segmentos debe dejar margen (el limitador, si hace falta, va en la preparación)."""
import itertools
import logging
import math
import queue as _queue
import threading
import time
from collections import deque

from services.mix_types import SAMPLE_RATE

log = logging.getLogger(__name__)

CHANNELS = 2
FADE_MS = 15.0                  # micro-fundido de pausa, reanudación y salto
GAIN_RAMP_MS = 50.0             # lo que tarda la ganancia maestra en ir de 0 a 1 (o al revés)
DEFAULT_BLOCKSIZE = 1024        # muestras por llamada de audio (23 ms a 44.100 Hz)
DEFAULT_LATENCY = "high"        # lo que PortAudio deja de colchón; ver docs/MOTOR_DJ.md

# Notificaciones (primer elemento de cada tupla que devuelve `poll_events`)
EV_SEGMENT_START = "segment_start"      # (EV_SEGMENT_START, label, seg_id, start_frame)
EV_QUEUE_EMPTY = "queue_empty"          # (EV_QUEUE_EMPTY, position_frames)
EV_STREAM_FINISHED = "stream_finished"  # (EV_STREAM_FINISHED, motivo): el flujo se paró sin que se pidiera (dispositivo perdido)

_numpy_module = None
_numpy_checked = False
_sd_module = None
_sd_checked = False


def _numpy():
    """numpy, cargado la primera vez que se pide (tarda un poco y no hace falta si nadie usa el modo DJ), o None."""
    global _numpy_module, _numpy_checked
    if not _numpy_checked:
        _numpy_checked = True
        try:
            import numpy
            _numpy_module = numpy
        except ImportError:                # depende de cómo esté instalado
            _numpy_module = None
    return _numpy_module


def _sounddevice():
    """sounddevice, cargado la primera vez que se pide, o None. Puede fallar con ImportError (no instalado) o con OSError
    (no encuentra la biblioteca PortAudio); en los dos casos el motor sigue sirviendo sin dispositivo (`pull`)."""
    global _sd_module, _sd_checked
    if not _sd_checked:
        _sd_checked = True
        try:
            import sounddevice
            _sd_module = sounddevice
        except (ImportError, OSError) as e:
            log.info("sounddevice no disponible: %s", e)
            _sd_module = None
    return _sd_module


def refresh_devices() -> None:
    """Vuelve a leer los dispositivos de audio de Windows (PortAudio los lista al cargarse y no se entera de unos auriculares
    conectados después). Solo si no hay ningún flujo abierto. No hace nada si falla."""
    sd = _sounddevice()
    if sd is None:
        return
    try:
        sd._terminate()
        sd._initialize()
    except Exception as e:
        log.info("no se pudieron refrescar los dispositivos de audio: %s", e)


def available() -> bool:
    """True si se puede abrir un flujo de audio de verdad (numpy, sounddevice y al menos un dispositivo de salida)."""
    return output_device_info() is not None


def output_device_info(device=None) -> dict:
    """Datos del dispositivo de salida (`device` = None: el predeterminado), o None si no hay ninguno o falta algo."""
    sd = _sounddevice()
    if sd is None or _numpy() is None:
        return None
    try:
        info = sd.query_devices(device, kind="output")
    except Exception as e:                  # sd.PortAudioError o ValueError: no hay dispositivo de salida
        log.info("sin dispositivo de salida de audio: %s", e)
        return None
    return dict(info) if info and info.get("max_output_channels", 0) >= CHANNELS else None


class _Segment:
    __slots__ = ("data", "label", "seg_id", "frames")

    def __init__(self, data, label, seg_id):
        self.data = data
        self.label = label
        self.seg_id = seg_id
        self.frames = int(data.shape[0])


class MixEngine:
    """Reproductor de segmentos ya preparados sobre un flujo de salida continuo (estéreo, float32).

    Hilos: los métodos públicos se llaman desde el hilo de la interfaz (o el de trabajo); la llamada de audio corre en el
    hilo de PortAudio. Comparten un candado que solo se sostiene unos microsegundos (añadir a una cola, copiar un bloque).
    Los arrays encolados no se copian si ya son float32 contiguos de forma (n, 2): no hay que modificarlos después."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, blocksize: int = DEFAULT_BLOCKSIZE, device=None,
                 latency=DEFAULT_LATENCY, master_gain: float = 1.0, fade_ms: float = FADE_MS, meter: bool = False,
                 extra_settings=None):
        np = _numpy()
        if np is None:
            raise RuntimeError("el motor de audio necesita numpy")
        self._np = np
        self.sample_rate = int(sample_rate)
        self.blocksize = int(blocksize)
        self.device = device
        self.latency = latency
        self.extra_settings = extra_settings    # p. ej. sd.WasapiSettings(auto_convert=True) para WASAPI a otra frecuencia
        self.meter = meter                      # True: apunta el pico de la salida (`peak_out`) en cada bloque
        self.on_segment_start = None            # fn(label, seg_id, start_frame)
        self.on_queue_empty = None              # fn(position_frames)
        self.on_stream_finished = None          # fn(motivo)
        self.last_error = ""

        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._events = _queue.SimpleQueue()
        self._cur = None                        # segmento que suena
        self._off = 0                           # muestras ya tocadas del segmento que suena
        self._pending = deque()                 # los que vienen detrás, en orden
        self._pos = 0                           # muestras de contenido ya tocadas en total (no cuenta el silencio)
        self._playing = False
        self._fade_frames = max(1, round(self.sample_rate * fade_ms / 1000.0))
        self._pause_gain = 0.0                  # 0 = en pausa del todo; 1 = sonando; entre medias, fundiendo
        g = min(1.0, max(0.0, float(master_gain)))
        self._master = g
        self._master_target = g
        self._master_step = 1.0 / max(1.0, self.sample_rate * GAIN_RAMP_MS / 1000.0)
        self._tail = None                       # salto con fundido: (array, posición) de lo que se está apagando
        self._tail_pos = 0                      # muestras ya fundidas del salto

        self._stream = None
        self._stopping = False
        self._latency_s = 0.0
        self.reset_stats()

    # ---- cola ---------------------------------------------------------------------------------------------------------
    def _segment(self, data, label):
        np = self._np
        a = np.asarray(data, dtype=np.float32)
        if a.ndim == 1:                         # mono: el mismo canal a los dos lados
            a = np.repeat(a[:, None], CHANNELS, axis=1)
        elif a.ndim != 2 or a.shape[1] != CHANNELS:
            raise ValueError(f"se esperaba un array (n, 2) o (n,), no {a.shape}")
        if a.shape[0] == 0:
            return None
        return _Segment(np.ascontiguousarray(a), label, next(self._ids))

    def queue(self, data, label=None):
        """Añade un segmento al final de la cola; sonará justo después del anterior, sin hueco ni solape.
        Devuelve su número (seg_id), o None si el array está vacío (no se encola nada)."""
        seg = self._segment(data, label)
        if seg is None:
            return None
        with self._lock:
            self._pending.append(seg)
        return seg.seg_id

    def clear_queue(self) -> int:
        """Quita lo que estaba por venir (lo que suena sigue hasta su final). Devuelve cuántos segmentos se quitaron."""
        with self._lock:
            n = len(self._pending)
            self._pending.clear()
        return n

    def replace_queue(self, segments) -> list:
        """Sustituye el futuro: lo que suena sigue hasta su final y después vienen `segments` (lista de arrays o de
        (array, label)). Sirve para cambiar la siguiente transición sin cortar. Devuelve los seg_id nuevos."""
        segs = self._segments(segments)
        with self._lock:
            self._pending = deque(segs)
        return [s.seg_id for s in segs]

    def replace(self, segments=(), fade: bool = True) -> list:
        """Salta ya: corta lo que suena y empieza `segments` (lista vacía: silencio). Con `fade`, lo que suena se funde
        con lo nuevo en 15 ms para no hacer clic. Devuelve los seg_id nuevos."""
        segs = self._segments(segments)
        with self._lock:
            audible = self._playing or self._pause_gain > 0.0
            if fade and audible and self._cur is not None:
                self._tail = (self._cur.data, self._off)
                self._tail_pos = 0
            self._cur = None
            self._off = 0
            self._pending = deque(segs)
            if not segs:
                self._events.put((EV_QUEUE_EMPTY, self._pos))
        return [s.seg_id for s in segs]

    def _segments(self, segments) -> list:
        out = []
        for item in segments:
            data, label = item if isinstance(item, tuple) else (item, None)
            seg = self._segment(data, label)
            if seg is not None:
                out.append(seg)
        return out

    # ---- transporte ---------------------------------------------------------------------------------------------------
    def play(self, fade: bool = True):
        """Reanuda (o empieza) con un fundido de entrada de 15 ms (sin `fade`, de golpe)."""
        with self._lock:
            self._playing = True
            if not fade:
                self._pause_gain = 1.0

    def pause(self, fade: bool = True):
        """Pausa con un fundido de salida de 15 ms; la posición se queda donde acaba el fundido (sin `fade`, de golpe)."""
        with self._lock:
            self._playing = False
            if not fade:
                self._pause_gain = 0.0

    def set_master_gain(self, gain: float, ramp_ms: float = GAIN_RAMP_MS):
        """Ganancia maestra (0 a 1), con una rampa lineal (`ramp_ms` es lo que tardaría en ir de 0 a 1; 0 = al momento)."""
        g = min(1.0, max(0.0, float(gain)))
        with self._lock:
            self._master_target = g
            if ramp_ms <= 0:
                self._master = g
            else:
                self._master_step = 1.0 / max(1.0, self.sample_rate * ramp_ms / 1000.0)

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def master_gain(self) -> float:
        """La ganancia maestra pedida (la que suena puede estar aún en la rampa)."""
        return self._master_target

    @property
    def position_frames(self) -> int:
        """Muestras de contenido ya entregadas al dispositivo (no cuenta el silencio de pausa ni de cola vacía). Lo que
        se oye va `output_latency_s` por detrás."""
        return self._pos

    @property
    def position_s(self) -> float:
        return self._pos / self.sample_rate

    def current(self):
        """(label, seg_id, muestras ya tocadas del segmento, muestras que tiene) del segmento que suena, o None."""
        with self._lock:
            cur = self._cur
            if cur is None and self._pending:
                cur, off = self._pending[0], 0
            else:
                off = self._off
            return None if cur is None else (cur.label, cur.seg_id, off, cur.frames)

    @property
    def remaining_frames(self) -> int:
        """Muestras que quedan por tocar (lo que falta del actual más todo lo encolado): la sesión DJ prepara la siguiente
        transición cuando esto baja de cierto margen."""
        with self._lock:
            n = (self._cur.frames - self._off) if self._cur is not None else 0
            return n + sum(s.frames for s in self._pending)

    @property
    def queued_count(self) -> int:
        with self._lock:
            return len(self._pending) + (1 if self._cur is not None else 0)

    # ---- notificaciones ------------------------------------------------------------------------------------------------
    def poll_events(self) -> list:
        """Notificaciones pendientes (tuplas EV_*), en orden. No bloquea; se puede llamar desde cualquier hilo."""
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except _queue.Empty:
                return out

    def dispatch_events(self) -> int:
        """Recoge las notificaciones y llama a on_segment_start / on_queue_empty / on_stream_finished en el hilo que lo
        llame (el de la interfaz, con un QTimer). Devuelve cuántas había."""
        events = self.poll_events()
        for ev in events:
            fn = {EV_SEGMENT_START: self.on_segment_start, EV_QUEUE_EMPTY: self.on_queue_empty,
                  EV_STREAM_FINISHED: self.on_stream_finished}.get(ev[0])
            if fn is not None:
                try:
                    fn(*ev[1:])
                except Exception:
                    log.exception("fallo en la notificación %s del motor de audio", ev[0])
        return len(events)

    # ---- render (lo mismo para la llamada de audio y para pull) --------------------------------------------------------
    def pull(self, frames: int):
        """Genera los siguientes `frames` de salida sin dispositivo (array (frames, 2) float32). Es exactamente lo que
        hace la llamada de audio; sirve para pruebas y para grabar el mix sin sonido."""
        out = self._np.empty((int(frames), CHANNELS), dtype=self._np.float32)
        self._render(out)
        return out

    def _ramp(self, cur, target, step, n):
        """Rampa lineal de `cur` hacia `target`: devuelve (valor final, None si no cambia o array de n ganancias)."""
        if cur == target:
            return cur, None
        np = self._np
        k = np.arange(1, n + 1, dtype=np.float32) * np.float32(step)
        vals = np.minimum(cur + k, target) if target > cur else np.maximum(cur - k, target)
        return float(vals[-1]), vals

    def _render(self, out):
        frames = out.shape[0]
        if frames == 0:
            return
        with self._lock:
            if not self._playing and self._pause_gain <= 0.0:
                out.fill(0.0)                   # en pausa: silencio, la posición no avanza
                self._master = self._master_target
                self._tail = None
                return
            fill = frames
            if not self._playing:               # fundido de salida: solo se avanza hasta donde acaba
                fill = min(frames, math.ceil(self._pause_gain * self._fade_frames - 1e-9))
            n = self._fill(out, fill)
            if n < frames:
                out[n:].fill(0.0)
            if self._tail is not None:
                self._mix_tail(out)
            self._pause_gain, pg = self._ramp(self._pause_gain, 1.0 if self._playing else 0.0, 1.0 / self._fade_frames, frames)
            self._master, mg = self._ramp(self._master, self._master_target, self._master_step, frames)
            if pg is None and mg is None:       # lo normal: una sola ganancia para todo el bloque
                gain = self._master * self._pause_gain
                if gain == 0.0:
                    out.fill(0.0)
                elif gain != 1.0:
                    out *= self._np.float32(gain)
            else:                               # alguna rampa en marcha: ganancia muestra a muestra
                g = (pg if pg is not None else self._pause_gain) * (mg if mg is not None else self._master)
                out *= g[:, None]
        if self.meter:
            self.peak_out = max(self.peak_out, float(self._np.abs(out).max()))

    def _fill(self, out, frames) -> int:
        """Copia hasta `frames` muestras de la cola en `out`; avanza la posición y apunta notificaciones. Con el candado."""
        pos = 0
        while pos < frames:
            cur = self._cur
            if cur is None:
                if not self._pending:
                    break
                cur = self._cur = self._pending.popleft()
                self._off = 0
                self._events.put((EV_SEGMENT_START, cur.label, cur.seg_id, self._pos + pos))
            take = min(frames - pos, cur.frames - self._off)
            out[pos:pos + take] = cur.data[self._off:self._off + take]
            pos += take
            self._off += take
            if self._off >= cur.frames:
                self._cur = None
                self._off = 0
                if not self._pending:
                    self._events.put((EV_QUEUE_EMPTY, self._pos + pos))
        self._pos += pos
        return pos

    def _mix_tail(self, out):
        """Salto con fundido: lo nuevo entra y lo que sonaba se apaga, en `_fade_frames` muestras, en línea recta."""
        np = self._np
        data, off = self._tail
        k = min(out.shape[0], self._fade_frames - self._tail_pos)
        w_in = (np.arange(self._tail_pos + 1, self._tail_pos + k + 1, dtype=np.float32) / np.float32(self._fade_frames))[:, None]
        old = data[off + self._tail_pos:off + self._tail_pos + k]
        out[:k] *= w_in
        if old.shape[0]:
            out[:old.shape[0]] += old * (1.0 - w_in[:old.shape[0]])
        self._tail_pos += k
        if self._tail_pos >= self._fade_frames:
            self._tail = None

    # ---- dispositivo ---------------------------------------------------------------------------------------------------
    def start(self) -> bool:
        """Abre el flujo de salida (silencio mientras no haya nada que tocar o esté en pausa). False si no se puede (sin
        sounddevice o sin dispositivo); el motivo queda en `last_error`. Si ya estaba abierto, no hace nada."""
        if self._stream is not None:
            return True
        sd = _sounddevice()
        if sd is None:
            self.last_error = "sounddevice no está instalado"
            return False
        self._stopping = False
        try:
            stream = sd.OutputStream(samplerate=self.sample_rate, channels=CHANNELS, dtype="float32", blocksize=self.blocksize,
                                     latency=self.latency, device=self.device, extra_settings=self.extra_settings,
                                     callback=self._callback,
                                     finished_callback=self._on_finished)
            stream.start()
        except Exception as e:                  # sd.PortAudioError, ValueError (dispositivo o frecuencia no válidos)
            self.last_error = str(e)
            log.warning("no se pudo abrir el audio: %s", e)
            return False
        self._stream = stream
        self._latency_s = float(stream.latency)
        self.last_error = ""
        return True

    def stop(self, fade: bool = True):
        """Cierra el flujo. Con `fade`, si sonaba, pausa con fundido y espera a que acabe (unas decenas de ms). La cola y
        la posición se conservan: `start()` + `play()` siguen donde estaba."""
        stream = self._stream
        if stream is None:
            return
        if fade and self._playing:
            self.pause()
            deadline = time.monotonic() + 0.25
            while self._pause_gain > 0.0 and time.monotonic() < deadline:
                time.sleep(0.005)
        self._stopping = True
        self._stream = None
        try:
            stream.stop()
            stream.close()
        except Exception as e:
            log.warning("fallo al cerrar el audio: %s", e)

    @property
    def stream_active(self) -> bool:
        s = self._stream
        return bool(s is not None and s.active)

    @property
    def output_latency_s(self) -> float:
        """Retraso entre entregar una muestra y oírla, según PortAudio (el del último flujo abierto; 0 si nunca se abrió)."""
        return self._latency_s

    def _on_finished(self):
        if not self._stopping:                  # se paró solo: dispositivo desconectado o error de PortAudio
            self._events.put((EV_STREAM_FINISHED, "el flujo de audio se ha parado"))

    def _callback(self, outdata, frames, time_info, status):
        t0 = time.perf_counter()
        if status:
            if status.output_underflow:
                self.underflows += 1
            else:
                self.other_status += 1
        try:
            self._render(outdata)
        except Exception:                       # nunca se deja escapar nada de la llamada de audio: silencio
            outdata.fill(0.0)
            self.callback_errors += 1
        dt = time.perf_counter() - t0
        self.callbacks += 1
        self.callback_total_s += dt
        if dt > self.callback_max_s:
            self.callback_max_s = dt

    # ---- cifras --------------------------------------------------------------------------------------------------------
    def reset_stats(self):
        self.callbacks = 0
        self.underflows = 0
        self.other_status = 0
        self.callback_errors = 0
        self.callback_max_s = 0.0
        self.callback_total_s = 0.0
        self.peak_out = 0.0

    def stats(self) -> dict:
        """Contadores de la llamada de audio: cuántas, subdesbordamientos, otros avisos, errores, duración máxima y media
        (ms), presupuesto de cada llamada (ms) y latencia de salida (s)."""
        n = self.callbacks
        return {"callbacks": n, "underflows": self.underflows, "other_status": self.other_status,
                "errors": self.callback_errors, "max_ms": self.callback_max_s * 1000.0,
                "mean_ms": (self.callback_total_s / n * 1000.0) if n else 0.0,
                "budget_ms": self.blocksize / self.sample_rate * 1000.0, "latency_s": self.output_latency_s,
                "peak_out": self.peak_out}
