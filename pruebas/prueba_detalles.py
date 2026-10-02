"""Pruebas de detalles: fecha 'añadida', rueda lateral del carrusel, géneros y ausencia de ventanas sueltas.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_detalles.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QObject, QEvent, QPointF, QPoint, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

app = QApplication([])
from ui.formatting import format_added
from ui.home_shelves import make_shelf
from ui.main_window import MainWindow


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


# ---- fecha 'añadida'
now = time.time()
cases = {30: "Ahora", 5 * 60: "5 min", 59 * 60: "59 min", 60 * 60: "1 h", 3 * 3600: "3 h", 23 * 3600: "23 h",
         24 * 3600: "1 día", 3 * 86400: "3 días", 7 * 86400: "1 semana", 15 * 86400: "2 semanas", 21 * 86400: "3 semanas"}
check("textos de 'añadida'", all(format_added(now - sec) == text for sec, text in cases.items()))
old = format_added(now - 90 * 86400)
check(f"pasado un mes sale la fecha ({old})", len(old.split()) == 3 and old.split()[2].isdigit())

# ---- ventanas sueltas
strays = []


class Watcher(QObject):
    def eventFilter(self, o, e):
        if e.type() == QEvent.Show and isinstance(o, QWidget) and o.isWindow() and type(o).__name__ != "MainWindow":
            strays.append(type(o).__name__)
        return False


watcher = Watcher()
app.installEventFilter(watcher)
w = MainWindow()
w.audio_output.setVolume(0)
w.show()
pump(1.5)
w.open_list("downloads")
pump(2.0)
w.open_list("favorites")
pump(0.8)
check(f"sin ventanas sueltas al abrir listas {strays}", not strays)

# ---- rueda lateral del carrusel
box, row = make_shelf("Prueba", 120)
for i in range(30):
    b = QPushButton(str(i))
    b.setFixedSize(150, 80)
    row.addWidget(b)
box.resize(600, 200)
box.show()
pump(0.3)
bar = box.scroll.horizontalScrollBar()


def wheel(dx, dy=0):
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(dx, dy), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    ev.setAccepted(True)
    box.scroll.wheelEvent(ev)
    return ev.isAccepted()


check("rueda lateral (derecha) mueve el carrusel", wheel(-120) and (pump(0.4) or bar.value() > 0))
v = bar.value()
check("rueda lateral (izquierda) lo devuelve", wheel(120) and (pump(0.4) or bar.value() < v))
check("rueda vertical no se consume (la página baja)", wheel(0, -120) is False)
box.scroll.scroll_page(1)
pump(0.1)
mid = bar.value()
pump(0.6)
check("las flechas animan el movimiento", 0 <= mid <= bar.value() and bar.value() > 0)

# ---- géneros
tracks = [{"id": f"g{i}", "title": f"Tema {i}", "uploader": "X", "album": "A", "url": "ytsearch1:x",
           "duration_secs": 180, "duration_str": "3:00", "thumbnail": ""} for i in range(5)]
w._show_genre({"id": 132, "name": "Pop", "index": 3}, tracks)
pump(0.6)
pg = w.page_playlist
check("género: cabecera con su tipo y nombre", pg.badge.text() == "GÉNERO" and pg.title_lbl.text() == "Pop")
check("género: se puede guardar como lista", not pg.btn_save.isHidden())
print("FIN")
