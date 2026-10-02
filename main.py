import sys
import os
import multiprocessing

if "--selftest" in sys.argv:     # la autocomprobación trabaja con datos temporales: nunca toca los del usuario
    import tempfile
    if not os.environ.get("DESCARGADOR_DATA_DIR"):      # (vacía también cuenta como «sin indicar»)
        os.environ["DESCARGADOR_DATA_DIR"] = tempfile.mkdtemp(prefix="descargador_selftest_")

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
from config import APP_DATA_DIR
log_path = str(APP_DATA_DIR / "app_descargas.log")   # junto a tus datos (no en la carpeta del programa)
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

    # Seguridad: si algo se queda esperando (por ejemplo un cuadro de diálogo que nadie puede pulsar), se termina solo.
    import threading

    def _watchdog():
        out_path = os.path.join(os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__), "selftest.log")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("FALLO tiempo agotado: la autocomprobación se quedó esperando" + chr(10))
        os._exit(2)

    _timer = threading.Timer(240, _watchdog)
    _timer.daemon = True
    _timer.start()
    # sin primer uso: el asistente de bienvenida es un cuadro de diálogo y la autocomprobación no tiene quien lo cierre
    from config import load_settings, save_settings
    _settings = load_settings()
    _settings["first_run_done"] = True
    save_settings(_settings)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from ui.fonts import load_app_fonts
    from ui.icons import ICONS_DIR, icon
    check("tipografía Poppins", load_app_fonts(app))

    svgs = sorted(ICONS_DIR.glob("*.svg"))
    bad = [f.name for f in svgs if QIcon(str(f)).pixmap(24, 24).isNull() or icon(f.name, "#FFFFFF").pixmap(24, 24).isNull()]
    check(f"iconos SVG ({len(svgs)} archivos, fallan: {bad or 'ninguno'})", svgs and not bad)

    try:
        import mutagen, requests  # noqa: F401
        check("librerías (mutagen, requests)", True)
    except Exception as e:
        check(f"librerías: {e}", False)
    try:
        from services import library_db, http, ytdlp_loader
        with library_db.connect() as con:
            con.execute("SELECT 1")
        http.session()
        ytdlp_loader.get()
        check(f"índice SQLite, sesión web y yt-dlp {ytdlp_loader.active_version()}", True)
    except Exception as e:
        check(f"índice SQLite / web / yt-dlp: {e}", False)
    try:
        from services.smtc_service import MediaControls
        controls = MediaControls()
        check("control multimedia de Windows" + ("" if controls.available else " (no disponible; es opcional)"), True)
        controls.shutdown()
    except Exception as e:
        check(f"control multimedia de Windows: {e}", False)
    try:
        import importlib
        for name in ("ui.nowplaying_full", "ui.calibrate", "ui.keep_change", "ui.celebrate", "ui.winext", "ui.emptystate",
                     "ui.continue_card", "ui.focusring", "ui.tooltips", "services.envelope", "services.app_updater", "services.word_timing"):
            importlib.import_module(name)
        check("módulos de las animaciones y de la pantalla completa", True)
    except Exception as e:
        check(f"módulos de las animaciones: {e}", False)
    from services.ffmpeg_service import FFmpegService
    if os.environ.get("SELFTEST_SIN_FFMPEG"):      # la compilación automática no incluye FFmpeg (se descarga al usarlo)
        check("ffmpeg: se descarga al primer uso", True)
    else:
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


def _make_splash():
    """Pantalla de arranque sencilla (una imagen estática: no gasta nada)."""
    from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
    from PySide6.QtWidgets import QSplashScreen
    from ui.icons import icon
    from ui.styles import accent
    pix = QPixmap(420, 220)
    pix.fill(QColor("#121212"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor("#2A2A2A"))
    p.drawRoundedRect(0, 0, 419, 219, 14, 14)
    p.drawPixmap(174, 40, icon("music.svg", accent(), 64).pixmap(72, 72))
    font = QFont("Poppins")
    font.setBold(True)
    font.setPixelSize(22)
    p.setFont(font)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(pix.rect().adjusted(0, 120, 0, 0), Qt.AlignHCenter | Qt.AlignTop, "Descargador de Música")
    font.setBold(False)
    font.setPixelSize(13)
    p.setFont(font)
    p.setPen(QColor("#B3B3B3"))
    p.drawText(pix.rect().adjusted(0, 160, 0, 0), Qt.AlignHCenter | Qt.AlignTop, "Abriendo…")
    p.end()
    return QSplashScreen(pix, Qt.WindowStaysOnTopHint)


def main():
    logging.info("=== INICIANDO APLICACIÓN ===")

    # Tamaño de la interfaz elegido en Ajustes → Accesibilidad (1,0 / 1,15 / 1,3)
    try:
        from config import load_settings
        scale = float(load_settings().get("ui_scale", 1.0) or 1.0)
        if abs(scale - 1.0) > 0.01 and "QT_SCALE_FACTOR" not in os.environ:
            os.environ["QT_SCALE_FACTOR"] = f"{scale:.2f}"
    except Exception:
        pass
    
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

    splash = _make_splash()
    splash.show()
    app.processEvents()                  # se ve al instante, mientras se construye la ventana principal

    window = MainWindow()
    from ui import motion
    fade = motion.enabled()
    if fade:
        window.setWindowOpacity(0.0)
    window.show()
    splash.finish(window)
    if fade:
        from PySide6.QtCore import QVariantAnimation
        anim = QVariantAnimation(window)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(160)
        anim.valueChanged.connect(lambda v: window.setWindowOpacity(float(v)))
        anim.finished.connect(lambda: window.setWindowOpacity(1.0))
        window._fade_in_anim = anim
        anim.start()

    sys.exit(app.exec())

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _code = selftest()
        logging.shutdown()
        os._exit(_code)         # salida directa: ningún hilo pendiente puede dejar el proceso colgado
    main()
