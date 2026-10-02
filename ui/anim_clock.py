"""Un único reloj de animación para toda la aplicación.

En vez de un temporizador por animación (spinner, visualizador, barras de «sonando», esqueletos…), todas se suscriben
aquí. El reloj arranca con la primera suscripción y se detiene al quedar vacío (en reposo no hay ni un temporizador),
se pausa con la ventana minimizada y baja de velocidad si el equipo va justo."""
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal

BASE_MS = 33                    # 30 fotogramas por segundo como máximo
STEPS = (33, 66, 100)           # si el equipo va justo: 30 → 15 → 10 por segundo


class AnimClock(QObject):
    degraded = Signal(int)      # nuevo intervalo en ms (se avisa cuando se baja de velocidad)

    def __init__(self):
        super().__init__()
        self._subs = {}                         # token -> [callback, every_ms, acumulado_ms]
        self._next = 1
        self._paused = False
        self._step = 0
        self._last = None
        self._lag_run = 0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.CoarseTimer)       # agrupa despertares: la CPU duerme más
        self._timer.setInterval(STEPS[0])
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------ suscripciones
    def subscribe(self, callback, fps: int = 30) -> int:
        """Llama a `callback(dt_ms)` hasta `fps` veces por segundo. Devuelve el identificador para darse de baja."""
        token = self._next
        self._next += 1
        self._subs[token] = [callback, max(1, int(1000 / max(1, fps))), 0]
        self._update_timer()
        return token

    def unsubscribe(self, token) -> None:
        if self._subs.pop(token, None) is not None:
            self._update_timer()

    def count(self) -> int:
        return len(self._subs)

    def active(self) -> bool:
        return self._timer.isActive()

    # ------------------------------------------------------------------ control
    def set_paused(self, paused: bool) -> None:
        """Ventana minimizada u oculta: no se anima nada."""
        self._paused = bool(paused)
        self._update_timer()

    def _update_timer(self):
        want = bool(self._subs) and not self._paused
        if want and not self._timer.isActive():
            self._last = None
            self._timer.start()
        elif not want and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        now = time.perf_counter()
        dt = int((now - self._last) * 1000) if self._last is not None else self._timer.interval()
        self._last = now
        self._check_lag(dt)
        for token, sub in list(self._subs.items()):
            sub[2] += dt
            if sub[2] >= sub[1] - 4:
                step = sub[2]
                sub[2] = 0
                try:
                    sub[0](step)
                except RuntimeError:            # el widget ya no existe
                    self._subs.pop(token, None)
                except Exception:
                    self._subs.pop(token, None)
        if not self._subs:
            self._update_timer()

    def _check_lag(self, dt: int):
        """Si varios fotogramas seguidos tardan el doble de lo previsto, el equipo va justo: se baja la velocidad."""
        interval = self._timer.interval()
        if dt > interval * 2 + 20:
            self._lag_run += 1
        else:
            self._lag_run = max(0, self._lag_run - 1)
        if self._lag_run >= 6:
            self._lag_run = 0
            if self._step < len(STEPS) - 1:
                self._step += 1
                self._timer.setInterval(STEPS[self._step])
                self.degraded.emit(STEPS[self._step])
            else:
                from ui import motion
                motion.cap_session(motion.SOFT)
                self.degraded.emit(0)

    def reset_speed(self):
        self._step = 0
        self._timer.setInterval(STEPS[0])


_clock = None


def clock() -> AnimClock:
    global _clock
    if _clock is None:
        _clock = AnimClock()
    return _clock
