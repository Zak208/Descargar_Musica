"""Pruebas de letras: coincidencia de artista, letras propias/generadas, estados de las frases y editor.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_letras.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtWidgets import QApplication

app = QApplication([])
from services import lyrics_store
from services.lyrics_service import _same_artist
from services.transcribe_service import clean_generated
from ui.lyric_line import LyricLine
from PySide6.QtCore import Qt


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

from services.transcribe_service import split_long_lines
from ui.lyrics_editor import parse_time, fmt_time

check("tiempos que entiende el editor", parse_time("1:23") == 83000 and parse_time("01:23.5") == 83500
      and parse_time("[00:05.25]") == 5250 and parse_time("83") == 83000 and parse_time("zz") is None and parse_time("1:75") is None)
check("formato de tiempo del editor", fmt_time(83500) == "01:23.50")
long_line = "Dime que enfaza el objeto que te deja rota el corazón en pedacito y no me dejes más"
parts = split_long_lines([(22000, long_line), (30000, "fin")])
check("las frases largas se parten en renglones cortos", len(parts) >= 3 and all(len(t) <= 42 for _m, t in parts[:-1])
      and [m for m, _t in parts] == sorted(m for m, _t in parts) and parts[0][0] == 22000)
check("las frases cortas no se tocan", split_long_lines([(0, "Una frase corta")]) == [(0, "Una frase corta")])

seen = []
line = LyricLine(1000, "frase", seen.append)
line.enterEvent(None)
check("al pasar el ratón se aclara", line._hover)
line.leaveEvent(None)
check("al salir se quita el resalte", not line._hover)
line.set_state("past")
check("la frase leída se apaga", abs(line._alpha - 0.34) < 0.01 or line._anim.state() == line._anim.State.Running)
line.mousePressEvent(type("E", (), {"button": lambda self: Qt.LeftButton, "accept": lambda self: None})())
check("pulsar una frase salta a su momento", seen == [1000])

# seguimiento de la letra: frase activa, barrido, atenuación y puntos de pausa
from PySide6.QtWidgets import QScrollArea, QWidget, QVBoxLayout
from ui.lyric_follow import LyricsFollower
from ui import motion
motion.force_level("none")
area = QScrollArea()
box = QWidget()
lay = QVBoxLayout(box)
area.setWidget(box)
area.setWidgetResizable(True)
area.resize(400, 300)
area.show()
times = [2000, 6000, 20000, 24000]
labels = [LyricLine(t, f"frase número {i} de la prueba", None, size=18) for i, t in enumerate(times)]
for l in labels:
    lay.addWidget(l)
fol = LyricsFollower(area)
fol.set_lines(list(zip(times, labels)))
fol.update(1000)
check("antes de la primera frase ninguna está activa", fol.active == -1 and labels[0].state == "idle")
check("antes de la primera frase se enseñan los puntos (intro de 2 s: no)", not fol.dots.isVisible())
fol.update(2500)
check("suena la primera frase", fol.active == 0 and labels[0].state == "active" and labels[1].state == "idle")
check("la que viene va menos apagada que la siguiente", labels[1]._falloff > labels[2]._falloff)
fol.update(4000)
check("el barrido avanza con el tiempo", 0.0 < labels[0]._fill <= 1.0)
fol.update(6500)
check("pasa a la segunda: la primera queda leída", fol.active == 1 and labels[0].state == "past" and labels[1].state == "active")
fol.update(14000)
check("en una pausa larga entre frases salen los puntos", fol.dots.isVisible() and 0 < fol.dots._progress < 1)
fol.update(20500)
check("al volver la voz, los puntos desaparecen", fol.active == 2 and not fol.dots.isVisible())
fol.update(5000)
check("al retroceder, se recoloca", fol.active == 0 and labels[2].state == "idle" and labels[0].state == "active")
motion.force_level(None)
print("FIN")
