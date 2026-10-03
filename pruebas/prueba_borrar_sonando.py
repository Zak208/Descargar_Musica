"""Borrar o renombrar una canción que está cargada en el reproductor (en pausa a la mitad): Windows no deja si el reproductor
la tiene abierta. Se comprueba que el programa la suelta antes. Se ejecuta desde la carpeta del proyecto:
    python pruebas/prueba_borrar_sonando.py"""
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

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.01)


from ui.main_window import MainWindow

tmp = tempfile.mkdtemp(prefix="descargador_borrar_")
path = os.path.join(tmp, "Prueba - Canción.wav")
with wave.open(path, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(22050 * 4)))

win = MainWindow()
win.audio_output.setVolume(0)
win.resize(1360, 860)
win.show()
pump(1.0)

win.play_local_file(path)
pump(1.0)
win.player.setPosition(1500)
win.player.pause()
pump(0.5)
check("la canción está cargada y en pausa a la mitad", win.player.source().toLocalFile() != "" and
      win.player.playbackState() == QMediaPlayer.PausedState)

renamed = os.path.join(tmp, "Otro nombre.wav")
try:
    os.rename(path, renamed)
    bloquea = False
    os.rename(renamed, path)
except OSError:
    bloquea = True
print("INFO  el reproductor", "bloquea" if bloquea else "no bloquea", "el archivo abierto en este equipo", flush=True)

check("release_file suelta la canción cargada", win.release_file(path) is True)
check("el reproductor se queda sin archivo", win.player.source() == QUrl())
try:
    os.rename(path, renamed)
    ok = True
except OSError:
    ok = False
check("y ya se puede renombrar (o borrar) sin error", ok)
check("soltar un archivo que no está cargado no hace nada", win.release_file(renamed) is False)

# el aviso de «No se pudo borrar» no debe salir si se suelta antes: se prueba el camino completo sin tocar la papelera
win.play_local_file(renamed)
pump(0.8)
win.player.pause()
win.stop_player = lambda: None
from services import recycle

llamadas = []
recycle.move_to_recycle_bin = lambda p: (llamadas.append(p), os.remove(p), True)[2]
win.rescan_library = lambda: None
win.delete_file(renamed)
check("borrar la canción cargada funciona (primero se suelta)", llamadas == [renamed] and not os.path.exists(renamed))

print("FIN", flush=True)
os._exit(0)
