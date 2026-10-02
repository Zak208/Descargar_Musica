"""Pruebas de consumo: sesión web compartida, límite de memoria de imágenes, tareas pesadas de una en una,
prioridad baja de los procesos hijos, equipo modesto y ahorro de batería. Desde la carpeta del proyecto:
python pruebas/prueba_consumo.py"""
import os
import subprocess
import sys
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication([])
from services import heavy, http, network_service
from ui import imageloader, perf


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


# ---- sesión web compartida
s1, s2 = http.session(), http.session()
check("una sola sesión web para toda la aplicación", s1 is s2)
check("no se guardan cookies", len(s1.cookies) == 0)
try:
    t0 = time.process_time()
    http.get("https://api.deezer.com/genre", timeout=8)
    http.get("https://itunes.apple.com/search?term=a&limit=1", timeout=8)
    http.get("https://api.deezer.com/genre", timeout=8)
    cpu = time.process_time() - t0
    check(f"3 peticiones web con poca CPU ({cpu:.2f} s)", cpu < 0.6)
except Exception as e:
    print("(sin internet: se omite la medición)", type(e).__name__)

# ---- caché de imágenes con tope de memoria
imageloader.clear_memory_cache()
big = QPixmap(500, 500)          # ≈ 1 MB cada una
for i in range(120):
    with imageloader._lock:
        imageloader._memory_put(("x", i), big)
budget = imageloader.MEMORY_BYTES_ECO if perf.eco() else imageloader.MEMORY_BYTES
check("la caché de imágenes respeta su tope de memoria", imageloader._memory_bytes <= budget
      and len(imageloader._memory) <= imageloader.MEMORY_ENTRIES)
imageloader.clear_memory_cache()
check("se puede vaciar la caché de imágenes", imageloader._memory_bytes == 0 and not imageloader._memory)

# ---- tareas pesadas de una en una
order = []


def job(name):
    with heavy.heavy_task():
        order.append(("in", name))
        time.sleep(0.15)
        order.append(("out", name))


threads = [threading.Thread(target=job, args=(n,)) for n in "abc"]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("las tareas pesadas no se solapan", all(order[i][0] == "in" and order[i + 1][0] == "out" and order[i][1] == order[i + 1][1]
                                              for i in range(0, 6, 2)))

# ---- procesos hijos con prioridad baja y sin ventana
from ui import common  # noqa: F401  (instala el parche de Popen)
captured = {}
orig = subprocess.Popen.__init__


class _Flags:
    pass


p = subprocess.Popen([sys.executable, "-c", "pass"])
p.wait()
check("los procesos hijos arrancan sin ventana y con prioridad baja", getattr(subprocess.Popen, "_sin_ventana", False))

# ---- equipo y batería
check("RAM total detectada", perf.total_ram_gb() > 0.5)
check("descargas en paralelo según el equipo", perf.default_parallel_downloads() in (1, 3))
perf._modest = True
check("equipo modesto: visualizador apagado por defecto", perf.visualizer_enabled() is False)
perf._modest = False
check("equipo normal: visualizador encendido por defecto", perf.visualizer_enabled() is True)
perf.set_visualizer(False)
check("el usuario puede cambiar el visualizador", perf.visualizer_enabled() is False)
perf.set_visualizer(True)


class FakeNet:
    def __init__(self, metered):
        self._m = metered

    def is_metered(self):
        return self._m


orig_battery = perf.battery_saving
perf.battery_saving = lambda: True
check("batería baja: se pide ahorrar", perf.saving_reason(FakeNet(False)) == "batería baja")
perf.battery_saving = lambda: False
check("datos medidos: se pide ahorrar", perf.saving_reason(FakeNet(True)) == "conexión de uso medido")
check("sin motivos: no se ahorra", perf.saving_reason(FakeNet(False)) == "")
perf.battery_saving = orig_battery
perf.trim_memory()
check("limpiar memoria no falla", True)
print("FIN")
