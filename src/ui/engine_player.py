"""Reproductor del modo DJ con el motor de mezcla propio (fases 9 y 10) que se hace pasar por un `QMediaPlayer`.

Durante una sesión DJ la ventana cambia su `player` por un `EnginePlayer`: tiene los mismos métodos y señales que usa el resto
de la aplicación (posición, duración, estado, fin de canción), así la barra de reproducción, la letra, el control multimedia de
Windows y la lista de reproducción siguen funcionando igual sin saber que el sonido sale de otro sitio.

Cómo encaja con la aplicación:
- `setSource(url)` de una canción local = «suena esta»: si la sesión del motor acaba de pasar sola a esa canción (la mezcla
  ya la ha hecho entrar) no se hace nada más (`adopt`); si no (la elegiste tú, o pulsaste «siguiente»), se empieza con `play`.
- Cuando la mezcla pasa a la siguiente canción, se emite `EndOfMedia`: la aplicación hace `play_next()` como siempre, que
  cambia el título, el historial y la cola y llama a `setSource` con la canción que ya está sonando.
- `stop()` se aplaza al siguiente turno del bucle de eventos: `play_local_file` hace `stop()` justo antes de `setSource()` y,
  si fuera inmediato, cortaría la mezcla que acaba de entrar.
- Algo que no es una canción local (una vista previa en streaming) no se puede tocar con el motor: se avisa con
  `foreign_source` y la ventana vuelve al reproductor de siempre."""
import os

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QMediaPlayer

TICK_MS = 50                    # cada cuánto se recoge el estado del motor (avisos y posición)
POSITION_STEP_MS = 90           # la posición se avisa como mucho cada tanto (la barra no necesita más)


class EngineOutput(QObject):
    """Hace de `QAudioOutput`: el volumen que calcula la ventana (volumen, fundidos, temporizador) va a la ganancia del motor."""
    direct_volume = True        # no es una salida de Qt: no hace falta el rodeo de `invokeMethod` (ver `_set_output_volume`)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session

    @Slot(float)
    def setVolume(self, volume: float):
        self._session.set_volume(volume)

    def device(self):
        return None

    def setDevice(self, _device):
        pass                    # el motor usa el dispositivo con el que se abrió


class EnginePlayer(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    mediaStatusChanged = Signal(object)
    playbackStateChanged = Signal(object)
    errorOccurred = Signal(object, str)
    foreign_source = Signal(QUrl)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.audio_output = EngineOutput(session, self)
        self._state = QMediaPlayer.StoppedState
        self._status = QMediaPlayer.NoMedia
        self._position_ms = 0
        self._duration_ms = 0
        self._last_emitted_pos = -10_000
        self._announced_loaded = False
        self._last_path = None                  # la última canción cargada (para volver a tocarla tras un fin o un error)
        self._stop_token = 0
        self.last_info = {}                     # el último estado de la sesión (para enseñar la mezcla planificada)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._on_tick)

    # ---- lo que la aplicación espera de un QMediaPlayer ------------------------------------------------------------
    def position(self) -> int:
        return self._position_ms

    def duration(self) -> int:
        return self._duration_ms

    def playbackState(self):
        return self._state

    def mediaStatus(self):
        return self._status

    def playbackRate(self) -> float:
        return 1.0

    def setPlaybackRate(self, _rate: float):
        pass                    # el motor iguala los tempos al preparar la mezcla; la velocidad suelta no se admite

    def setAudioOutput(self, _output):
        pass

    def source(self) -> QUrl:
        path = self.session.current_path
        return QUrl.fromLocalFile(path) if path else QUrl()

    def setSource(self, url: QUrl):
        self._stop_token += 1                   # un stop() aplazado de antes ya no vale: viene otra canción
        if url is None or url.isEmpty():
            self._stop_now()
            return
        path = os.path.normpath(url.toLocalFile()) if url.isLocalFile() else ""     # con las barras de la ventana (\), no las de Qt (/)
        if not path or not os.path.isfile(path):
            self._stop_now()
            if not path:
                self.foreign_source.emit(url)
            return
        self._announced_loaded = False
        self._last_path = path
        self._status = QMediaPlayer.LoadingMedia
        if self.session.adopt(path):
            self._set_state(QMediaPlayer.PlayingState if self._state != QMediaPlayer.PausedState else self._state)
            return
        self._position_ms = 0
        self._last_emitted_pos = -10_000
        self.session.play(path, 0.0, autoplay=False)
        self._timer.start()

    def play(self):
        if self.session.current_path is None and self._last_path and os.path.isfile(self._last_path):
            self._announced_loaded = False                  # tras «Fin de la lista» o un error: vuelve a empezar la última
            self.session.play(self._last_path, 0.0, autoplay=True)
        self.session.resume()
        self._timer.start()
        self._set_state(QMediaPlayer.PlayingState)

    def pause(self):
        self.session.pause()
        self._set_state(QMediaPlayer.PausedState)

    def stop(self):
        token = self._stop_token = self._stop_token + 1
        QTimer.singleShot(0, lambda: token == self._stop_token and self._stop_now())

    def setPosition(self, ms: int):
        ms = max(0, int(ms))
        if self.session.current_path is None and self._last_path and os.path.isfile(self._last_path):
            self._announced_loaded = False                  # repetir una canción que acabó (la sesión ya la había soltado)
            self.session.play(self._last_path, ms / 1000.0, autoplay=self._state == QMediaPlayer.PlayingState)
        else:
            self.session.seek(ms / 1000.0)
        self._position_ms = ms
        self._last_emitted_pos = ms
        self.positionChanged.emit(ms)

    def close(self):
        self._stop_token += 1                   # un stop() aplazado ya no vale
        self._timer.stop()
        self.session.stop(wait=False)

    # ---- por dentro -------------------------------------------------------------------------------------------------
    def _set_state(self, state):
        if state != self._state:
            self._state = state
            self.playbackStateChanged.emit(state)

    def _stop_now(self):
        self.session.stop(wait=False)
        self._timer.stop()
        self._status = QMediaPlayer.NoMedia
        self._position_ms = 0
        self._duration_ms = 0
        self._set_state(QMediaPlayer.StoppedState)

    def _on_tick(self):
        """Lo que haría QMediaPlayer por su cuenta: avisar de la posición, la duración y el fin de la canción."""
        try:
            info = self.last_info = self.session.tick()
        except Exception as e:                  # la sesión no debe romper el bucle de eventos
            self._timer.stop()
            self.errorOccurred.emit(QMediaPlayer.ResourceError, f"Motor de mezcla: {e}")
            return
        if info.get("error") and info.get("state") == "stopped":
            self._timer.stop()
            self._set_state(QMediaPlayer.StoppedState)
            self.errorOccurred.emit(QMediaPlayer.ResourceError, info["error"])
            return
        if info["state"] != "loading" and not self._announced_loaded and info.get("path"):
            self._announced_loaded = True
            self._status = QMediaPlayer.LoadedMedia
            self.mediaStatusChanged.emit(QMediaPlayer.LoadedMedia)
        duration = int(info["duration_s"] * 1000)
        if duration != self._duration_ms and duration > 0:
            self._duration_ms = duration
            self.durationChanged.emit(duration)
        if info["state"] in ("playing", "paused"):
            pos = int(info["position_s"] * 1000)
            self._position_ms = pos
            if abs(pos - self._last_emitted_pos) >= POSITION_STEP_MS and self._state != QMediaPlayer.StoppedState:
                self._last_emitted_pos = pos
                self.positionChanged.emit(pos)
        if info.get("advanced") or info.get("ended"):
            self._position_ms = 0 if info.get("ended") else self._position_ms
            self._status = QMediaPlayer.EndOfMedia
            self.mediaStatusChanged.emit(QMediaPlayer.EndOfMedia)       # la aplicación llama a play_next() y a setSource()
            if info.get("ended") and self._state == QMediaPlayer.PlayingState and self._status == QMediaPlayer.EndOfMedia:
                self._set_state(QMediaPlayer.StoppedState)
