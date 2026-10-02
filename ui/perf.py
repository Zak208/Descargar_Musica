"""Ahorro de recursos: modo ahorro, detección de equipo modesto, batería baja / conexión medida y limpieza de memoria."""
import ctypes
import gc
import os
import sys
from ctypes import wintypes

from config import load_settings, save_settings

_eco = None
_modest = None


def eco() -> bool:
    """True si el modo ahorro está activado (por defecto lo está)."""
    global _eco
    if _eco is None:
        _eco = bool(load_settings().get("eco_mode", True))
    return _eco


def set_eco(enabled: bool) -> None:
    global _eco
    _eco = bool(enabled)
    settings = load_settings()
    settings["eco_mode"] = _eco
    save_settings(settings)


def image_scale() -> int:
    """Factor de resolución de las imágenes en memoria: 1 en modo ahorro, 2 para máxima nitidez."""
    return 1 if eco() else 2


# ------------------------------------------------------------ el equipo
class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def total_ram_gb() -> float:
    if sys.platform != "win32":
        return 8.0
    try:
        status = _MemStatus()
        status.dwLength = ctypes.sizeof(_MemStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.ullTotalPhys / (1024 ** 3)
    except Exception:
        return 8.0


def is_modest_machine() -> bool:
    """Equipo con poca memoria o pocos núcleos (4 GB o menos, o 2 núcleos o menos)."""
    global _modest
    if _modest is None:
        _modest = total_ram_gb() <= 4.6 or (os.cpu_count() or 4) <= 2
    return _modest


def default_parallel_downloads() -> int:
    return 1 if is_modest_machine() else 3


def visualizer_enabled() -> bool:
    """El visualizador animado de la barra de reproducción: activado salvo en equipos modestos (ahí empieza apagado)."""
    value = load_settings().get("visualizer")
    return (not is_modest_machine()) if value is None else bool(value)


def set_visualizer(enabled: bool) -> None:
    settings = load_settings()
    settings["visualizer"] = bool(enabled)
    save_settings(settings)


# ------------------------------------------------------------ batería
class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wintypes.DWORD),
                ("BatteryFullLifeTime", wintypes.DWORD)]


def battery_saving() -> bool:
    """True si el portátil va con batería baja (25 % o menos) o con el ahorro de batería de Windows activado."""
    if sys.platform != "win32":
        return False
    try:
        st = _PowerStatus()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
            return False
        on_battery = st.ACLineStatus == 0
        if on_battery and st.SystemStatusFlag == 1:        # ahorro de batería activado
            return True
        return on_battery and st.BatteryLifePercent != 255 and st.BatteryLifePercent <= 25
    except Exception:
        return False


def saving_reason(network=None) -> str:
    """Motivo por el que conviene no hacer trabajo opcional (recomendaciones, descargas en paralelo...), o ''."""
    if battery_saving():
        return "batería baja"
    try:
        if network is not None and network.is_metered():
            return "conexión de uso medido"
    except Exception:
        pass
    return ""


# ------------------------------------------------------------ memoria
def trim_memory() -> None:
    """Devuelve a Windows la memoria que la aplicación ya no usa (se nota en el Administrador de tareas)."""
    gc.collect()
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
        kernel32.SetProcessWorkingSetSize(kernel32.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception:
        pass


# ------------------------------------------------------------ medidor de consumo (Ajustes → Rendimiento)
class _FileTime(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


class _MemCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def cpu_seconds() -> float:
    """Tiempo de procesador que ha gastado la aplicación desde que arrancó (núcleo + usuario)."""
    if sys.platform != "win32":
        import time
        return time.process_time()
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        c, e, k, u = _FileTime(), _FileTime(), _FileTime(), _FileTime()
        kernel32.GetProcessTimes(kernel32.GetCurrentProcess(), ctypes.byref(c), ctypes.byref(e), ctypes.byref(k),
                                 ctypes.byref(u))
        to_s = lambda ft: ((ft.hi << 32) | ft.lo) / 1e7
        return to_s(k) + to_s(u)
    except Exception:
        import time
        return time.process_time()


def memory_mb() -> float:
    """Memoria que ocupa ahora la aplicación (la que se ve en el Administrador de tareas)."""
    if sys.platform != "win32":
        return 0.0
    try:
        counters = _MemCounters()
        counters.cb = ctypes.sizeof(_MemCounters)
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MemCounters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        return 0.0


class CpuMeter:
    """Porcentaje de un procesador que ha usado la aplicación entre una lectura y la siguiente."""

    def __init__(self):
        import time
        self._t = time.perf_counter()
        self._c = cpu_seconds()

    def read(self) -> float:
        import time
        now, cpu = time.perf_counter(), cpu_seconds()
        span = max(1e-3, now - self._t)
        pct = 100.0 * (cpu - self._c) / span
        self._t, self._c = now, cpu
        return max(0.0, pct)
