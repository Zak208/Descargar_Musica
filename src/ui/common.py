"""Utilidades compartidas: registro de hilos activos y rutas de recursos."""
import os
import sys

import subprocess

from PySide6.QtCore import QThread

_ACTIVE_THREADS = set()
_original_start = QThread.start


def _safe_start(self, *args, **kwargs):
    _ACTIVE_THREADS.add(self)
    self.finished.connect(lambda: _ACTIVE_THREADS.discard(self))
    _original_start(self, *args, **kwargs)


QThread.start = _safe_start


def resource_path(relative_path):
    """Obtiene ruta absoluta a un recurso, tanto en desarrollo como en PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # la carpeta src
    return os.path.join(base_path, relative_path)


def hide_subprocess_windows():
    """En Windows, cada llamada a ffmpeg o a otro programa abría un instante una ventana negra de consola.
    Esto hace que todos los procesos que lance la aplicación arranquen sin ventana."""
    if sys.platform != "win32" or getattr(subprocess.Popen, "_sin_ventana", False):
        return
    original_init = subprocess.Popen.__init__

    def init_sin_ventana(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        if not flags & (subprocess.HIGH_PRIORITY_CLASS | subprocess.IDLE_PRIORITY_CLASS | subprocess.REALTIME_PRIORITY_CLASS):
            flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS     # ffmpeg y compañía ceden ante lo que estés usando
        kwargs["creationflags"] = flags
        original_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = init_sin_ventana
    subprocess.Popen._sin_ventana = True


hide_subprocess_windows()
