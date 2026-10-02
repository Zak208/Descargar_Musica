"""Una sola ventana de la aplicación a la vez.

Dos copias abiertas compartirían (y pisarían) las mismas listas, ajustes y base de datos. Si se abre una segunda, avisa a
la primera para que se muestre y se cierra. Al reiniciarse la propia aplicación, la nueva espera unos segundos a que la
vieja termine de cerrar."""
import hashlib

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from config import APP_DATA_DIR

# el nombre depende de la carpeta de datos: dos copias con datos distintos (pruebas, otro usuario) no se molestan entre sí
SERVER_NAME = "DescargadorMusica-" + hashlib.sha1(str(APP_DATA_DIR).lower().encode("utf-8", "ignore")).hexdigest()[:12]


class SingleInstance(QObject):
    activated = Signal()            # otra copia intentó abrirse: hay que mostrar esta ventana

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = QLockFile(str(APP_DATA_DIR / "app.lock"))
        self._lock.setStaleLockTime(15000)          # si la copia anterior se cerró a la fuerza, el bloqueo caduca
        self._server = None

    def acquire(self, wait_ms: int = 0) -> bool:
        """True si somos la única copia. Si ya hay otra, le avisa y devuelve False."""
        if self._lock.tryLock(wait_ms):
            self._listen()
            return True
        self._notify_other()
        return False

    def _listen(self):
        QLocalServer.removeServer(SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(SERVER_NAME)

    def _on_connection(self):
        while self._server is not None and self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readAll()
            sock.disconnectFromServer()
            self.activated.emit()

    @staticmethod
    def _notify_other():
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(1000):
            sock.write(b"mostrar")
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()

    def release(self):
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()
