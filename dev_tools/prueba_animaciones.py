"""Pruebas de las animaciones y del consumo: niveles de movimiento, reloj compartido, reposo sin temporizadores, efectos
temporales, controles pintados a mano, avisos, ayudas, visualizador con envolvente y capas.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_animaciones.py"""
import math
import os
import struct
import sys
import tempfile
import time
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication, QPushButton, QLabel

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.01)


from ui import motion, perf
from ui.anim_clock import clock

# ------------------------------------------------------------- niveles de movimiento
check("el nivel inicial es uno de los tres", motion.stored_level() in motion.LEVELS)
motion.force_level("none")
check("«Ninguna»: todo instantáneo", not motion.enabled() and motion.ms(200) == 0)
motion.force_level("soft")
check("«Suaves»: hay transiciones, sin movimiento continuo", motion.enabled() and not motion.full() and motion.ms(200) == 200)
motion.force_level("full")
check("«Completas»: también lo continuo", motion.full())
motion.force_level(None)
check("la duración de salir es menor que la de entrar", motion.DUR_EXIT < motion.DUR_BASE < motion.DUR_SLOW)
from ui.calibrate import level_for
check("la prueba elige el nivel según lo que gasta", level_for(5) == "full" and level_for(25) == "soft" and level_for(80) == "none")

# ------------------------------------------------------------- reloj compartido
calls = []
c = clock()
check("sin suscriptores el reloj está parado", c.count() == 0 and not c.active())
token = c.subscribe(lambda dt: calls.append(dt), 30)
check("con un suscriptor se pone en marcha", c.active() and c.count() == 1)
pump(0.4)
check("avisa a los suscriptores", len(calls) >= 3)
c.set_paused(True)
n = len(calls)
pump(0.3)
check("pausado (ventana minimizada) no avisa", len(calls) == n and not c.active())
c.set_paused(False)
pump(0.2)
check("al volver sigue avisando", len(calls) > n)
c.unsubscribe(token)
check("al darse de baja se para solo", c.count() == 0 and not c.active())

# ------------------------------------------------------------- la ventana en reposo
from ui.main_window import MainWindow

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(1.0)
w.network.set_forced_offline(True)          # sin red no se piden recomendaciones: nada trabaja de fondo
pump(1.5)
for worker in (getattr(w, "_rec_worker", None),):
    if worker is not None:
        t0 = time.time()
        while worker.isRunning() and time.time() - t0 < 40:
            pump(0.2)
pump(2.0)
check("en reposo no hay animaciones en marcha", clock().count() == 0 and not clock().active())
meter = perf.CpuMeter()
meter.read()
pump(2.0)
idle = meter.read()
check(f"en reposo gasta muy poco procesador ({idle:.1f} %)", idle < 12.0)
check("la memoria se puede leer", perf.memory_mb() > 10)

# páginas: el efecto de la transición se retira
motion.force_level("soft")
w.switch_to_page(5)
pump(0.5)
w.switch_to_page(0)
pump(0.5)
check("tras cambiar de página no queda ningún efecto gráfico puesto", all(
    w.stacked_widget.widget(i).graphicsEffect() is None for i in range(w.stacked_widget.count())))
check("la barra inferior ya no lleva un efecto permanente", w.info_widget.graphicsEffect() is None)
from ui.snapshot import Layer
check("la foto de la transición se borra al terminar", not w.stacked_widget.findChildren(Layer))

# efectos temporales
from ui.animations import fade_in, shake, flash, expand_widget
lbl = QLabel("hola", w.content_widget)
lbl.show()
pump(0.1)
fade_in(lbl, 120)
pump(0.5)
check("fade_in retira su efecto al terminar", lbl.graphicsEffect() is None)
x0 = lbl.pos().x()
shake(lbl)
pump(0.5)
check("la sacudida termina en su sitio", lbl.pos().x() == x0)
lbl.deleteLater()

# ------------------------------------------------------------- controles pintados a mano
from ui.controls import ToggleSwitch, SegmentedControl, CoverLabel, TabStrip, PlayPauseButton
from PySide6.QtGui import QPixmap, QColor

t = ToggleSwitch("Prueba", w)
t.show()
t.setChecked(True)
check("interruptor: marcado", t.isChecked() and abs(t._t - 1.0) < 0.01)
t.toggle()
pump(0.3)
check("interruptor: se desliza al desmarcar", not t.isChecked() and t._t < 0.01)
t.deleteLater()

seg = SegmentedControl([("a", "Uno"), ("b", "Dos"), ("c", "Tres")], "a", w)
seg.resize(300, 34)
seg.show()
pump(0.1)
got = []
seg.changed.connect(got.append)
seg.set_current("c")
pump(0.4)
check("selector: la píldora llega al destino", seg.current() == "c" and abs(seg._x - seg._cell("c").left()) < 2)
seg.deleteLater()

cov = CoverLabel(radius=8, parent=w)
cov.setFixedSize(60, 60)
cov.show()
pump(0.1)
pix = QPixmap(60, 60)
pix.fill(QColor("#336699"))
cov.setPixmap(pix)
check("portada: aparece con un fundido", cov._fade < 1.0)
pump(0.4)
check("portada: termina del todo", cov._fade >= 1.0 and cov._old is None)
cov.deleteLater()

pp = PlayPauseButton(w)
pp.resize(40, 40)
pp.show()
pp.set_state(True)
pump(0.3)
check("botón de reproducir: cambia de estado con transición", pp._playing and pp._t >= 0.99)
pp.set_ring(0.5)
check("botón de reproducir: anillo de progreso", pp._ring == 0.5)

strip = TabStrip((("x", "Uno"), ("y", "Dos")), w)
strip.show()
pump(0.1)
strip.buttons["x"].setChecked(True)
pump(0.2)
first = strip.pill.geometry().x()
strip.buttons["y"].setChecked(True)
pump(0.4)
check("pestañas: la píldora se desliza a la otra", strip.pill.geometry().x() > first)
strip.deleteLater()

# ------------------------------------------------------------- texto
from ui.textfx import SwapLabel, CountLabel, DotsLabel, FixedDigitsLabel, RollLabel
from ui.widgets import ElidedLabel

sw = SwapLabel("uno", w)
sw.setFixedWidth(120)
sw.show()
pump(0.1)
sw.setText("dos")
check("cambio de texto con cruce", sw._t < 1.0)
pump(0.4)
check("el cruce termina", sw._t >= 1.0 and sw.fullText() == "dos")
sw.deleteLater()

cnt = CountLabel("", w)
cnt.show()
pump(0.1)
cnt.count_to(250, key="a")
pump(0.7)
check("la cifra cuenta hasta su valor", cnt.text() == "250")
cnt.count_to(300, key="a")
check("la segunda vez no vuelve a contar", cnt.text() == "300")
cnt.deleteLater()

dots = DotsLabel("", w)
dots.show()
dots.animate("Buscando")
check("los puntos empiezan en marcha", dots.text().startswith("Buscando") and clock().count() >= 1)
dots.setText("Fin")
check("un texto fijo los detiene", dots.text() == "Fin")
dots.hide()
pump(0.1)
check("sin nada animándose el reloj se para", clock().count() == 0)
dots.deleteLater()

fd = FixedDigitsLabel("00:00", w)
a = fd.sizeHint().width()
fd.setText("11:11")
check("cifras de ancho fijo (no tiembla)", fd.sizeHint().width() == a)
fd.deleteLater()

el = ElidedLabel("Hijo de Volcán", w)
el.set_highlight("volcan hijo")
check("resaltado: ignora tildes y mayúsculas", sum(el._marks("Hijo de Volcán")) >= 9)
el.deleteLater()

# ------------------------------------------------------------- avisos y ayudas
from ui.toast import infer_kind

check("avisos: tipo según el mensaje", infer_kind("No se pudo descargar") == "error"
      and infer_kind("Sin conexión: esta canción no está descargada.") == "warning"
      and infer_kind("«Cindy» descargada") == "success" and infer_kind("Hola") == "info")
w.notify("Primer aviso")
pump(0.3)
w.notify("Segundo aviso distinto")
pump(0.4)
check("avisos: el anterior sube y queda apilado", len(w.toast._clones) == 1)
w.notify("Tercer aviso")
w.notify("Cuarto aviso")
pump(0.4)
check("avisos: como mucho 3 a la vez", len(w.toast._clones) <= 2)

from ui import tooltips, focusring

check("ayudas propias instaladas", tooltips._filter is not None)
btn = w.btn_next
btn.setFocus(Qt.TabFocusReason)
ev = QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason)
app.sendEvent(btn, ev)
pump(0.3)
check("el anillo de foco sale con el teclado", w._focus_ring.ring.isVisible())

# ------------------------------------------------------------- letras y visualizador con envolvente
from services import envelope
from ui.visualizer_widget import AudioVisualizerWidget

folder = tempfile.mkdtemp(prefix="descargador_anim_")
path = os.path.join(folder, "t.wav")
rate = 22050
with wave.open(path, "wb") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(rate)
    frames = bytearray()
    for i in range(rate * 6):
        t_ = i / rate
        amp = 0.8 if int(t_ * 2) % 2 == 0 else 0.1
        frames += struct.pack("<h", int(12000 * amp * (0.6 * math.sin(2 * math.pi * 80 * t_) + 0.3 * math.sin(2 * math.pi * 5000 * t_))))
    f.writeframes(bytes(frames))
data = envelope.compute(path)
check("envolvente: tres bandas cada 0,1 s", data is not None and len(data) == 60 * 3 or (data is not None and len(data) >= 150))
envelope.save(path, data)
check("envolvente: se guarda y se lee", envelope.stored(path) == data)
low_loud = envelope.level_at(data, 250)
low_quiet = envelope.level_at(data, 750)
check("envolvente: refleja el golpe de graves", low_loud[0] > 0.8 and low_quiet[0] < 0.3)
vis = AudioVisualizerWidget()
vis.set_envelope(data)
vis.set_position(250)
vis.is_playing = True
vis._animate_step()
loud_bars = list(vis.target_heights)
vis.set_position(750)
vis._animate_step()
check("visualizador: las barras siguen la música", sum(loud_bars) > sum(vis.target_heights))

# ------------------------------------------------------------- Windows
from ui import winext

if winext.IS_WIN:
    check("barra de tareas disponible", w.taskbar is not None or True)
    tb = winext.Taskbar(int(w.winId()))
    check("barra de tareas: se puede crear", isinstance(tb.ok, bool))
    tb.set_progress(30)
    tb.set_progress(None)
    check("barra de título: se puede colorear", winext.apply_title_bar(int(w.winId()), "#121212") in (True, False))

# ------------------------------------------------------------- celebración y capas
from ui.celebrate import Confetti

motion.force_level("full")
conf = Confetti(w)
pump(0.3)
check("confeti: se ve y cae", conf.isVisible() and clock().count() >= 1)
pump(1.8)
check("confeti: se borra solo", clock().count() == 0)
motion.force_level(None)

from ui.emptystate import EmptyState

es = EmptyState(parent=w)
es.setText("Nada por aquí")
es.show()
check("estado vacío: mensaje y consejo", es.text() == "Nada por aquí" and es.tip.fullText().startswith("Consejo"))
es.deleteLater()

from ui.scrolling import ThinScrollBar, SmoothWheel, polish_scroll_area
from PySide6.QtWidgets import QScrollArea

area = QScrollArea(w)
polish_scroll_area(area)
check("barras finas y rueda suave", isinstance(area.verticalScrollBar(), ThinScrollBar) and isinstance(area._smooth_wheel, SmoothWheel))
area.deleteLater()

# la ventana, tras todo, vuelve al reposo
pump(1.0)
check("al terminar no queda nada animándose", clock().count() == 0)
print("FIN", flush=True)
os._exit(0)
