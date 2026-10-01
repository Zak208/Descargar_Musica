"""Filas de canción estilo Spotify, menú, panel «En reproducción» y ecualizador siempre activo.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_filas.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication([])
from services.equalizer_service import active_bands, load_eq_settings
from ui.main_window import MainWindow
from ui.track_row import TrackRow


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


def wait(cond, timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.03)
        if cond():
            return True
    return False


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


settings = load_eq_settings()
check("ecualizador siempre activo y en 0 por defecto",
      settings["enabled"] and (settings["bass"], settings["mid"], settings["treble"]) == (0, 0, 0)
      and active_bands(settings) is None)
check("con un ajuste distinto de 0 se procesa el audio", active_bands(dict(settings, bass=4)) is not None)

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(1.0)
wait(lambda: w._lib_items is not None)
w.open_list("downloads")
check("filas de la lista", wait(lambda: len(w.page_playlist.tracks_widget.findChildren(TrackRow)) > 1))
rows = sorted(w.page_playlist.tracks_widget.findChildren(TrackRow), key=lambda r: r.y())
first, second = rows[0], rows[1]
check("numeración 1, 2...", first.idx_label.text() == "1" and second.idx_label.text() == "2")
check("sin botón de play suelto en la fila", not hasattr(first, "preview_btn"))

first._hot = True
first.refresh_state()
check("al pasar el ratón el número se cambia por el símbolo de play", first.idx_label.pixmap() is not None and not first.idx_label.pixmap().isNull())
first._hot = False
first.refresh_state()
check("sin ratón vuelve el número", first.idx_label.text() == "1")

check("sin seleccionar no hay tres puntitos", first.more_btn.icon().isNull())
w.select_row(first)
check("un clic marca la fila y muestra los tres puntitos", first.property("selected") is True and not first.more_btn.icon().isNull())
w.select_row(second)
check("solo una fila marcada", first.property("selected") is False and second.property("selected") is True)

ev = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
second.mouseDoubleClickEvent(ev)
check("doble clic reproduce la canción", wait(lambda: w.current_item_info and w.current_item_info.get("local_path") == second.item_info["local_path"]))
check("la fila que suena se marca", wait(lambda: second._playing and not first._playing))
check("el contexto es toda la lista", len(w._context) == len(w.page_playlist._visible_items()))

# menú de la fila
captured = []


def grab_menu():
    from PySide6.QtWidgets import QMenu
    m = QApplication.activePopupWidget()

    def walk(menu, depth=0):
        for act in menu.actions():
            captured.append(act.text())
            if act.menu():
                walk(act.menu(), depth + 1)
    walk(m)
    m.close()


info = dict(second.item_info, uploader="Milo j & Yahritza Y Su Esencia", album="Álbum de prueba")
QTimer.singleShot(400, grab_menu)
w.open_track_menu(info, w.mapToGlobal(w.rect().center()), [("Quitar de esta lista", lambda: None)])
text = " | ".join(captured)
check("menú: ir al artista (con varios artistas) y al álbum",
      "Ir al artista" in text and "Milo j" in text and "Yahritza Y Su Esencia" in text and "Ir al álbum" in text)
check("menú: quitar de la lista y quitar de favoritos", "Quitar de esta lista" in text and "Canciones que te gustan" in text)

# panel «En reproducción»
w.toggle_now_playing()
pump(0.5)
check("panel lateral derecho visible", w.now_panel.isVisible())
check("panel: título de la canción que suena", w.now_panel.title.text() == w.current_item_info["title"])
check("panel: tiene sitio (el mínimo de la ventana creció)", w.minimumWidth() >= 1000)
w.toggle_now_playing()
check("panel se cierra", not w.now_panel.isVisible())
print("FIN")
