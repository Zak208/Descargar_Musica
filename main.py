import sys
import os
import multiprocessing

from ui.common import hide_subprocess_windows
hide_subprocess_windows()

if __name__ == "__main__":
    multiprocessing.freeze_support()

import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from ui.main_window import MainWindow

class DummyStream:
    def write(self, *args, **kwargs): pass
    def flush(self, *args, **kwargs): pass
    def isatty(self, *args, **kwargs): return False
    def read(self, *args, **kwargs): return ""
    def readline(self, *args, **kwargs): return ""

if sys.stdout is None: sys.stdout = DummyStream()
if sys.stderr is None: sys.stderr = DummyStream()
if sys.stdin is None: sys.stdin = DummyStream()


# Configurar logging a un archivo
log_path = os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__), "app_descargas.log")
from logging.handlers import RotatingFileHandler

_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[_handler])

def global_exception_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical("Excepción NO controlada atrapada por el sistema:", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = global_exception_hook

def selftest() -> int:
    """Comprobación del propio programa (útil tras compilar el .exe): iconos, tipografía, ffmpeg, librerías y
    ventanas sueltas. Escribe el resultado en 'selftest.log' junto al programa. Uso:  Descargar_Musica.exe --selftest"""
    import time
    from PySide6.QtCore import QObject, QEvent
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QWidget

    results = []

    def check(label, ok):
        results.append((label, bool(ok)))

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from ui.fonts import load_app_fonts
    from ui.icons import ICONS_DIR, icon
    check("tipografía Poppins", load_app_fonts(app))

    svgs = sorted(ICONS_DIR.glob("*.svg"))
    bad = [f.name for f in svgs if QIcon(str(f)).pixmap(24, 24).isNull() or icon(f.name, "#FFFFFF").pixmap(24, 24).isNull()]
    check(f"iconos SVG ({len(svgs)} archivos, fallan: {bad or 'ninguno'})", svgs and not bad)

    try:
        import yt_dlp, mutagen, requests  # noqa: F401
        check("librerías (yt-dlp, mutagen, requests)", True)
    except Exception as e:
        check(f"librerías: {e}", False)
    from services.ffmpeg_service import FFmpegService
    check("ffmpeg disponible", FFmpegService.is_ffmpeg_available())

    strays = []

    class Watcher(QObject):
        def eventFilter(self, o, e):
            if e.type() == QEvent.Show and isinstance(o, QWidget) and o.isWindow() and type(o).__name__ != "MainWindow":
                strays.append(type(o).__name__)
            return False

    watcher = Watcher()
    app.installEventFilter(watcher)
    window = MainWindow()
    window.show()

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)

    pump(2.0)
    window.open_list("downloads")
    pump(2.5)
    window.open_list("favorites")
    pump(1.0)
    check(f"sin ventanas sueltas al abrir listas {strays or ''}", not strays)
    window.close()

    out = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__), "selftest.log")
    with open(out, "w", encoding="utf-8") as f:
        for label, ok in results:
            f.write(("OK    " if ok else "FALLO ") + label + chr(10))
    return 0 if all(ok for _, ok in results) else 1


def main():
    logging.info("=== INICIANDO APLICACIÓN ===")
    
    # Soporte para pantallas de alta resolución (High DPI)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from ui.fonts import load_app_fonts
    load_app_fonts(app)
    app.setApplicationName("Descargador de Música YouTube Pro")
    app.setOrganizationName("Antigravity")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
