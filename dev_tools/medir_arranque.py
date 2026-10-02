"""Mide cuánto tarda en arrancar la ventana y cuánta memoria gasta (ayuda a comprobar las mejoras de consumo).
Se ejecuta desde la carpeta del proyecto:  python dev_tools/medir_arranque.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ctypes
from ctypes import wintypes

from PySide6.QtWidgets import QApplication

app = QApplication([])


def ram_mb() -> float:
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1048576


def cpu_s() -> float:
    return time.process_time()


t0, c0, r0 = time.time(), cpu_s(), ram_mb()
from ui.main_window import MainWindow
t1, c1, r1 = time.time(), cpu_s(), ram_mb()
w = MainWindow()
w.audio_output.setVolume(0)
w.show()
t2, c2, r2 = time.time(), cpu_s(), ram_mb()
end = time.time() + float(os.environ.get("MEDIR_SEGUNDOS", "12"))
while time.time() < end:
    app.processEvents()
    time.sleep(0.01)
t3, c3, r3 = time.time(), cpu_s(), ram_mb()
print(f"importar módulos : {t1 - t0:5.2f} s  CPU {c1 - c0:5.2f} s  RAM {r1:6.0f} MB")
print(f"crear la ventana : {t2 - t1:5.2f} s  CPU {c2 - c1:5.2f} s  RAM {r2:6.0f} MB")
print(f"arranque (segundos indicados) : {t3 - t2:5.2f} s  CPU {c3 - c2:5.2f} s  RAM {r3:6.0f} MB")
print(f"TOTAL CPU {c3 - c0:.2f} s · RAM final {r3:.0f} MB")
sys.stdout.flush()
os._exit(0)
