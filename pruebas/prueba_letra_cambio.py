"""La letra del panel lateral se ve al cambiar de canción (antes, con la letra llegando de internet, las frases quedaban con
altura 0 y no se veía nada). Necesita ventana real (plataforma «windows»), por eso es una prueba aparte.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_letra_cambio.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "windows"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

app = QApplication([])
app.setStyle("Fusion")


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.005)


import ui.now_playing as np_mod
from ui.fonts import load_app_fonts
from ui.main_window import MainWindow

load_app_fonts(app)


class SlowLyrics(QThread):
    """Letra que tarda en llegar (como la de internet) y trae muchas frases largas."""
    lyrics_ready = Signal(dict)
    lyrics_error = Signal(str)

    def __init__(self, title, artist, store_key="", local_path=""):
        super().__init__()

    def run(self):
        time.sleep(0.4)
        lines = [(2000 + i * 3000, f"Frase número {i} de la letra de prueba, bastante larga para que ocupe dos renglones") for i in range(80)]
        self.lyrics_ready.emit({"is_synced": True, "synced_lines": lines, "plain_text": "", "source": "online"})


np_mod.LyricsWorker = SlowLyrics
w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(3.0)
w.network.set_forced_offline(True)
pump(1.0)
items = w.library_items()
w.set_context(items)
w.play_local_file(items[0]["local_path"])
pump(1.5)
box = w.now_panel.lyrics
check("primera canción: la letra se ve", len(box._lines) == 80 and min(l.height() for _, l in box._lines) >= 20)
for saltos in (1, 3):
    for _ in range(saltos):
        w.play_next()
        pump(0.2)
    pump(2.0)
    heights = [l.height() for _, l in box._lines]
    check(f"tras {saltos} salto(s) de canción la letra se ve (alto mínimo de una frase: {min(heights) if heights else 0})",
          len(heights) == 80 and min(heights) >= 20)
print("FIN", flush=True)
os._exit(0)
