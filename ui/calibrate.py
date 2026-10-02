"""«Probar animaciones»: durante unos segundos se ejecuta lo más exigente (transiciones entre páginas y animaciones
continuas), se mide cuánto procesador gasta la aplicación y se elige el nivel de movimiento que mejor le va al equipo."""
from PySide6.QtCore import QTimer

from ui import motion, perf
from ui.anim_clock import clock

DURATION_MS = 3000
LIMITS = ((15.0, motion.FULL), (35.0, motion.SOFT))      # % de un procesador → nivel que aguanta


def level_for(cpu_percent: float) -> str:
    for limit, key in LIMITS:
        if cpu_percent < limit:
            return key
    return motion.NONE


def run_calibration(window, done):
    """Mide 3 s con las animaciones al máximo. Al terminar guarda el nivel y llama a `done(nivel, cpu)`."""
    previous = motion._override
    motion.force_level(motion.FULL)
    meter = perf.CpuMeter()
    meter.read()
    state = {"page": 0, "ticks": 0}
    tokens = []

    def churn(_dt):
        state["ticks"] += 1
        try:
            window.player_bar.update()
            window.stacked_widget.currentWidget().update()
        except Exception:
            pass

    tokens.append(clock().subscribe(churn, 30))
    page_timer = QTimer(window)
    page_timer.setInterval(450)

    def flip():
        state["page"] = 5 if state["page"] == 0 else 0
        try:
            window.switch_to_page(state["page"])
        except Exception:
            pass

    page_timer.timeout.connect(flip)
    page_timer.start()
    flip()
    start_page = window.stacked_widget.currentIndex()

    def finish():
        page_timer.stop()
        page_timer.deleteLater()
        for t in tokens:
            clock().unsubscribe(t)
        cpu = meter.read()
        motion.force_level(previous)
        try:
            window.switch_to_page(0 if start_page != 0 else start_page)
        except Exception:
            pass
        chosen = level_for(cpu)
        motion.set_level(chosen)
        done(chosen, cpu)

    QTimer.singleShot(DURATION_MS, finish)
