"""¿Hay internet? Detección sin gastar recursos: Qt avisa cuando cambia el estado de la red (no se sondea).

Si Qt no puede saberlo, la aplicación se entera porque una petición falla; entonces comprueba una vez y, mientras no
haya conexión, vuelve a intentarlo cada 20 segundos (solo en ese caso). El usuario también puede forzar el modo sin
conexión en Ajustes.
"""
import logging
import socket

from PySide6.QtCore import QMetaObject, QObject, QThread, QTimer, Qt, Signal

from config import load_settings, save_settings

logger = logging.getLogger(__name__)

NETWORK_ERROR_HINTS = ("getaddrinfo", "urlopen", "connection", "timed out", "timeout", "network", "name or service",
                       "temporary failure", "unreachable", "max retries", "ssl", "no hay conexión", "winerror 10")
PROBE_HOSTS = (("1.1.1.1", 443), ("8.8.8.8", 53))
RETRY_MS = 20_000


def is_network_error(raw) -> bool:
    """¿Este error técnico significa «no hay internet»?"""
    text = str(raw or "").lower()
    return any(k in text for k in NETWORK_ERROR_HINTS)


def _probe() -> bool:
    for host, port in PROBE_HOSTS:
        try:
            with socket.create_connection((host, port), timeout=2.5):
                return True
        except OSError:
            continue
    # algunos cortafuegos y proxys bloquean estas conexiones directas pero dejan pasar la web: se prueba con HTTPS
    # (respeta el proxy del sistema) antes de dar la conexión por perdida
    try:
        from services import http
        return http.get("https://www.youtube.com/generate_204", timeout=4).status_code < 500
    except Exception:
        return False


class _ProbeThread(QThread):
    result = Signal(bool)

    def run(self):
        self.result.emit(_probe())


class NetworkMonitor(QObject):
    """Estado de la conexión. `changed(online)` se emite solo cuando cambia el resultado final."""
    changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe_online = True
        self._forced_offline = bool(load_settings().get("offline_mode", False))
        self._last = self._effective()
        self._probe_thread = None
        self._retry = QTimer(self)
        self._retry.setInterval(RETRY_MS)
        self._retry.timeout.connect(self.check_now)
        self._info = None
        try:
            from PySide6.QtNetwork import QNetworkInformation
            if QNetworkInformation.loadDefaultBackend():
                self._info = QNetworkInformation.instance()
                self._info.reachabilityChanged.connect(self._on_reachability)
                self._on_reachability(self._info.reachability())
        except Exception as e:
            logger.info(f"Sin detección de red de Qt ({e}); se detectará por fallos.")

    # ------------------------------------------------------------ estado
    def _effective(self) -> bool:
        return self._probe_online and not self._forced_offline

    def is_online(self) -> bool:
        return self._effective()

    def is_metered(self) -> bool:
        """¿Conexión de uso medido (datos móviles, tarifa limitada)? Solo si Windows lo indica."""
        try:
            from PySide6.QtNetwork import QNetworkInformation as Q
            return bool(self._info is not None and self._info.supports(Q.Feature.Metered) and self._info.isMetered())
        except Exception:
            return False

    @property
    def forced_offline(self) -> bool:
        return self._forced_offline

    def _emit_if_changed(self):
        now = self._effective()
        if now != self._last:
            self._last = now
            if now:
                self._retry.stop()
            elif not self._forced_offline:
                self._retry.start()
            self.changed.emit(now)

    # ------------------------------------------------------- eventos de Qt
    def _on_reachability(self, reach):
        """Qt avisa de un cambio: si dice «conectado» se confía; si dice lo contrario, se confirma con una comprobación
        (así nunca se anuncia «sin conexión» por un falso aviso)."""
        try:
            from PySide6.QtNetwork import QNetworkInformation as Q
            online = reach in (Q.Reachability.Online, Q.Reachability.Unknown)
        except Exception:
            online = True
        if online:
            self._probe_online = True
            self._emit_if_changed()
        else:
            self.check_now()

    # --------------------------------------------------- modo manual y fallos
    def set_forced_offline(self, forced: bool):
        self._forced_offline = bool(forced)
        settings = load_settings()
        settings["offline_mode"] = self._forced_offline
        save_settings(settings)
        if not forced:
            self._probe_online = True
            self.check_now()
        self._emit_if_changed()

    def check_now(self):
        if self._forced_offline:
            return
        if self._probe_thread is not None and self._probe_thread.isRunning():
            return
        self._probe_thread = _ProbeThread(self)
        self._probe_thread.result.connect(self._on_probe)
        self._probe_thread.start()

    def _on_probe(self, online: bool):
        self._probe_online = online
        self._emit_if_changed()
        if not online and not self._forced_offline and not self._retry.isActive():
            self._retry.start()


_monitor: NetworkMonitor | None = None


def monitor() -> NetworkMonitor:
    """Monitor único de toda la aplicación (se crea la primera vez que se pide)."""
    global _monitor
    if _monitor is None:
        _monitor = NetworkMonitor()
    return _monitor


def note_failure() -> None:
    """Para avisar desde cualquier hilo de que una petición falló por la red (se comprobará en el hilo principal)."""
    if _monitor is not None:
        QMetaObject.invokeMethod(_monitor, "report_failure", Qt.QueuedConnection)


def private_mode() -> bool:
    """Modo privado: la aplicación no consulta por su cuenta letras, recomendaciones ni datos de artistas (solo lo que tú
    pides: buscar, descargar, escuchar adelantos)."""
    return bool(load_settings().get("private_mode", False))


def is_online() -> bool:
    """Seguro desde cualquier hilo: si el monitor aún no existe, se supone que hay conexión."""
    return _monitor.is_online() if _monitor is not None else True
