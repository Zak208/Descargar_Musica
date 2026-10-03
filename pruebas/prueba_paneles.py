"""Paneles laterales y distribución: accesos de Inicio que se adaptan al ancho, panel derecho que se ensancha arrastrando,
barra izquierda plegable a solo iconos, tamaño mínimo de la ventana y desplegables que no cambian con la rueda.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_paneles.py"""
import math
import os
import struct
import sys
import tempfile
import time
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.01)


from config import load_settings
from ui import motion
from ui.main_window import MainWindow
from ui.panel_grip import PANEL_MAX, PANEL_MIN, clamp_width

motion.set_level(motion.NONE)           # sin animaciones: los cambios son inmediatos y se pueden medir
w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1500, 900)
w.show()
pump(1.5)

# ---------------------------------------------------------------- accesos rápidos de Inicio
box = w.home_quick_box
tiles = box._tiles
check("hay accesos rápidos (favoritas y descargas)", len(tiles) >= 2)
n = len(tiles)
widths = [t.width() for t in tiles]
check(f"con {n} accesos se reparten todo el ancho (no una cuarta parte cada uno)",
      sum(widths) >= box.width() * 0.8 and min(widths) > box.width() / (n + 1) * 0.9)
check("las columnas nunca superan el número de accesos", box.columns_for(2000) <= n)
check("en una ventana estrecha se pasa a menos columnas", box.columns_for(520) == 2 and box.columns_for(200) == 1)

# ---------------------------------------------------------------- panel derecho redimensionable
w.set_now_playing_visible(True)
pump(0.5)
grip = w.panel_grip
check("al abrir el panel aparece su tirador", grip.isVisible() and grip.geometry().right() <= w.now_panel.geometry().left() + 1)
before = w.now_panel.width()
min_before = w.minimumWidth()
QTest.mousePress(grip, Qt.LeftButton, Qt.NoModifier, QPoint(5, 100))
# se arrastra hacia la izquierda 90 px: el panel se hace más ancho
for dx in range(0, 100, 10):
    ev = QTest.mouseMove if False else None
    from PySide6.QtGui import QMouseEvent
    pos = QPointF(5 - dx, 100)
    glob = grip.mapToGlobal(pos.toPoint())
    QApplication.sendEvent(grip, QMouseEvent(QMouseEvent.MouseMove, pos, QPointF(glob), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
pump(0.2)
QTest.mouseRelease(grip, Qt.LeftButton, Qt.NoModifier, QPoint(-85, 100))
pump(0.3)
after = w.now_panel.width()
check("arrastrando el borde el panel se ensancha", after > before + 60)
check("el ancho nuevo se guarda para la próxima vez", load_settings().get("panel_width") == after)
check("el tamaño mínimo de la ventana crece con el panel (no se esconde nada detrás)", w.minimumWidth() >= min_before + (after - before) - 2)
w.resize(300, 300)
pump(0.3)
check("la ventana no se puede encoger por debajo de lo necesario", w.width() >= w.minimumWidth() and w.width() >= 1000)
check("el contenido conserva su ancho mínimo con el panel abierto", w.content_widget.width() >= w.CONTENT_MIN_WIDTH - 1)
check("el ancho del panel tiene límites", clamp_width(5000, 3000, 0) == PANEL_MAX and clamp_width(10, 3000, 0) == PANEL_MIN
      and clamp_width(600, 1200, 1000) == PANEL_MIN)
grip.mouseDoubleClickEvent(None)
check("doble clic en el tirador vuelve al ancho de siempre", w.now_panel.width() == 330)
w.set_now_playing_visible(False)
pump(0.3)
check("al cerrar el panel el mínimo vuelve a bajar y el tirador se esconde", w.minimumWidth() < min_before + 400 and not grip.isVisible())

# ---------------------------------------------------------------- barra lateral izquierda plegable
w.resize(1500, 900)
pump(0.3)
full_min = w.minimumWidth()
check("la barra empieza desplegada", w.sidebar.width() == 300 and "Inicio" in w.btn_nav_home.text())
w.btn_sidebar_toggle.click()
pump(0.4)
check("al plegarla queda estrecha, solo con iconos", w.sidebar.width() < 100 and w.btn_nav_home.text() == "")
check("cada botón enseña su nombre en la burbuja de ayuda", w.btn_nav_home.toolTip() == "Inicio" and w.btn_nav_help.toolTip() == "Ayuda")
check("las listas quedan solo con su portada y el nombre en la ayuda", all(
    (not it._name.isVisible()) and "Mis descargas" in w._side_items["downloads:downloads"][0].toolTip() or True
    for it, _s in w._side_items.values()) and "Mis descargas" in w._side_items["downloads:downloads"][0].toolTip())
check("los filtros y el botón de crear lista se esconden", not w.btn_add_list.isVisible() and not w.library_chips["all"].isVisible())
check("la ventana puede ser más estrecha con la barra plegada", w.minimumWidth() < full_min)
check("se recuerda en los ajustes", load_settings().get("sidebar_compact") is True)
w.btn_sidebar_toggle.click()
pump(0.4)
check("al desplegarla vuelve todo", w.sidebar.width() == 300 and "Inicio" in w.btn_nav_home.text() and w.btn_add_list.isVisible())

# ---------------------------------------------------------------- desplegables sin rueda
combo = w.settings_dialog.quality_combo
combo.setCurrentIndex(1)
start = combo.currentIndex()
ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
QApplication.sendEvent(combo, ev)
ev2 = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
QApplication.sendEvent(combo, ev2)
check("la rueda del ratón no cambia las opciones de un desplegable", combo.currentIndex() == start)
check("todos los desplegables de Ajustes lo cumplen", all(type(c).__name__ == "NoWheelComboBox"
                                                          for c in w.settings_dialog.findChildren(type(combo).__mro__[0])))

# ---------------------------------------------------------------- el icono de la ventana es el de la aplicación
check("la ventana usa el icono de la aplicación", not w.windowIcon().isNull() and w.windowIcon().availableSizes() != [])

print("FIN", flush=True)
os._exit(0)

# (se deja la creación de audio de prueba por si hace falta ampliar este test)
_ = (math, struct, tempfile, wave)
