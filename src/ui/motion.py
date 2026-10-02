"""Movimiento de la interfaz: un único sitio decide cuánto se anima todo.

Tres niveles (Ajustes → Rendimiento):
  · «none»  Ninguna: todo cambia al instante.
  · «soft»  Suaves (por defecto): transiciones breves que solo ocurren al hacer algo; nada se mueve en reposo.
  · «full»  Completas: además, detalles continuos (fondos que respiran, marquesina…).

El nivel inicial sale de Windows («Efectos de animación» en Accesibilidad) y baja solo con la batería baja o si el
equipo va justo (ver `anim_clock`). Todas las duraciones salen de aquí, así hay un solo punto para apagarlas."""
import ctypes
import sys

from PySide6.QtCore import QEasingCurve

from config import load_settings, save_settings

NONE, SOFT, FULL = "none", "soft", "full"
LEVELS = (NONE, SOFT, FULL)
LEVEL_NAMES = {NONE: "Ninguna", SOFT: "Suaves", FULL: "Completas"}

# tokens: salir es más rápido que entrar
DUR_TAP = 90
DUR_FAST = 120
DUR_BASE = 200
DUR_SLOW = 320
DUR_EXIT = 120

EASE_IN = QEasingCurve.OutCubic          # lo que aparece
EASE_OUT = QEasingCurve.InCubic          # lo que se va
EASE_POP = QEasingCurve.OutBack          # solo para «latidos»

_session_cap = None          # si el equipo va justo, el nivel baja hasta que se reinicie la aplicación
_override = None


def system_reduces_motion() -> bool:
    """True si Windows tiene desactivados los efectos de animación (Accesibilidad → Efectos visuales)."""
    if sys.platform != "win32":
        return False
    try:
        flag = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)    # SPI_GETCLIENTAREAANIMATION
        return bool(ok) and flag.value == 0
    except Exception:
        return False


def _initial_level() -> str:
    return NONE if system_reduces_motion() else SOFT


def stored_level() -> str:
    value = load_settings().get("motion")
    return value if value in LEVELS else _initial_level()


def level() -> str:
    """Nivel efectivo ahora mismo: el elegido, bajado por batería baja o por equipo justo."""
    if _override is not None:
        return _override
    lv = stored_level()
    if lv == FULL:
        from ui import perf
        if perf.battery_saving():
            lv = SOFT
    if _session_cap is not None and LEVELS.index(lv) > LEVELS.index(_session_cap):
        lv = _session_cap
    return lv


def set_level(value: str) -> None:
    global _session_cap
    if value not in LEVELS:
        return
    settings = load_settings()
    settings["motion"] = value
    save_settings(settings)
    _session_cap = None


def force_level(value) -> None:
    """Solo para pruebas: fija el nivel sin tocar los ajustes (None lo quita)."""
    global _override
    _override = value


def cap_session(value: str) -> None:
    """El equipo va justo: durante esta sesión no se pasa de `value`."""
    global _session_cap
    if value in LEVELS and (_session_cap is None or LEVELS.index(value) < LEVELS.index(_session_cap)):
        _session_cap = value


def enabled() -> bool:
    return level() != NONE


def full() -> bool:
    return level() == FULL


def ms(duration: int) -> int:
    """Duración efectiva: 0 en «Ninguna» (todo instantáneo)."""
    return 0 if level() == NONE else int(duration)


def visible_ok(widget) -> bool:
    """Solo se anima lo que se ve: el widget está visible y su zona no está vacía (fuera de pantalla, nada)."""
    try:
        return bool(widget.isVisible()) and not widget.visibleRegion().isEmpty()
    except RuntimeError:
        return False
