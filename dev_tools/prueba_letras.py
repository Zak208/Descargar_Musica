"""Pruebas de letras: coincidencia de artista, letras propias/generadas, estados de las frases y editor.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_letras.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication([])
from services import lyrics_store
from services.lyrics_service import _same_artist
from services.transcribe_service import clean_generated
from ui.lyric_line import LyricLine


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


check("mismo artista con colaboraciones", _same_artist("Quevedo & Bizarrap", "Bizarrap, Quevedo"))
check("otro artista con el mismo título se rechaza", not _same_artist("Dib", "Maluma"))
check("«y» dentro de un nombre no lo parte", not _same_artist("Rey", "Maluma"))

lines, synced = lyrics_store.parse_text("[00:01.50] hola\nsin tiempo\n[00:05] fin")
check("texto con tiempos", synced and lines == [(1500, "hola"), (1500, "sin tiempo"), (5000, "fin")])
lines, synced = lyrics_store.parse_text("uno\n\ndos")
check("texto sin tiempos", not synced and [t for _m, t in lines] == ["uno", "dos"])
check("formato de tiempo", lyrics_store.format_ms(65500) == "[01:05.50]")

key = lyrics_store.key_for("Prueba", "Nadie")
lyrics_store.delete(key)
lyrics_store.save(key, "[00:01.00] a", "auto")
check("la letra generada se guarda", lyrics_store.load(key)["source"] == "auto")
lyrics_store.save(key, "[00:01.00] b", "user")
lyrics_store.delete(key, "auto")
check("borrar «auto» no borra la del usuario", lyrics_store.load(key) is not None)
lyrics_store.delete(key, "user")
check("borrar la del usuario", lyrics_store.load(key) is None)

cleaned = clean_generated([(0, "[Música]"), (1000, "hola"), (2000, "hola"), (3000, "hola"), (4000, "hola"), (5000, "adiós")])
check("se quitan marcas y bucles del reconocedor", [t for _m, t in cleaned] == ["hola", "hola", "adiós"])

seen = []
line = LyricLine(1000, "frase", seen.append)
check("al pasar el ratón se subraya", (line.enterEvent(None) or True) and line.font().underline())
line.leaveEvent(None)
check("al salir se quita el subrayado", not line.font().underline())
line.set_state("past")
check("la frase leída se apaga", "0.34" in line.styleSheet())
print("FIN")
