"""Pruebas del karaoke por palabras: reparto por sílabas, ritmo de la canción, tiempos medidos con la voz, guardado y
barrido por píxeles. Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_palabras.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget, QVBoxLayout

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


from services import word_timing as W

check("sílabas: «canción» tiene 2, «a» tiene 1", W.syllables("canción") == 2 and W.syllables("a") == 1)
check("un diptongo cuenta como una sílaba", W.syllables("cuando") == 2)

LINES = [(1000, "Yo te quiero mucho"), (5000, "pero no me atrevo a decirlo"), (9000, "hoy"), (20000, "otra vez sola")]
est = W.estimate(LINES)
check("hay una lista de palabras por frase", len(est) == len(LINES) and len(est[0]) == 4)
check("cada frase empieza en su tiempo y termina antes de la siguiente",
      all(est[i][0][0] == LINES[i][0] and est[i][-1][1] <= LINES[i + 1][0] for i in range(len(LINES) - 1)))
check("las palabras van seguidas y sin retroceder", all(est[0][k][1] <= est[0][k + 1][0] + 1 for k in range(3)))
check("una palabra larga dura más que una corta", est[1][5][1] - est[1][5][0] > est[1][1][1] - est[1][1][0])
check("la frase corta antes de una pausa larga no se estira hasta la siguiente", est[2][-1][1] - est[2][0][0] < 3000)

text = LINES[0][1]
frac = lambda ms: W.fraction_at(est[0], len(text), ms)
check("antes de cantar la frase no hay nada relleno", frac(900) == 0.0)
check("al terminar la frase está toda rellena", frac(est[0][-1][1] + 50) == 1.0)
vals = [frac(1000 + k * 100) for k in range(0, 25)]
check("el relleno solo avanza", all(b >= a for a, b in zip(vals, vals[1:])))
mid_first = (est[0][0][0] + est[0][0][1]) // 2
check("a mitad de la primera palabra el relleno está dentro de esa palabra", 0 < frac(mid_first) <= est[0][0][1] / 1 and frac(mid_first) * len(text) <= est[0][0][3])

# tiempos reales: «mucho» se canta muy alargada y «quiero» muy rápido
rec = [("yo", 1100), ("te", 1250), ("quiero", 1400), ("mucho", 1700)]
ref = W.refine(LINES[:1], rec)[0]
check("con la voz medida cada palabra empieza donde se cantó", [w[0] for w in ref] == [1100, 1250, 1400, 1700])
check("la última palabra no pasa de su límite", ref[-1][1] - ref[-1][0] <= W.MAX_WORD_MS)
partial = W.refine(LINES[:1], [("yo", 1100), ("mucho", 2000)])[0]
check("las palabras que no se oyeron se reparten entre las que sí", partial[0][0] == 1100 and partial[3][0] == 2000
      and partial[0][0] < partial[1][0] < partial[2][0] < partial[3][0])
check("sin nada reconocido se queda con la estimación", W.refine(LINES, []) == est)

# guardado
key = "prueba_palabras"
spans = W.refine(LINES, [("yo", 1100), ("te", 1250), ("quiero", 1400), ("mucho", 1700)])
W.save_spans(key, LINES, spans)
back = W.load_spans(key, LINES)
check("los tiempos medidos se guardan y se vuelven a leer", back == [[tuple(w) for w in line] for line in spans])
check("si la letra cambia, los tiempos guardados se descartan", W.load_spans(key, LINES[:2] + [(9000, "otra cosa")]) is None)

# el seguidor y el barrido por píxeles
from ui.lyric_follow import LyricsFollower
from ui.lyric_line import LyricLine

area = QScrollArea()
holder = QWidget()
lay = QVBoxLayout(holder)
labels = []
for ms, t in LINES:
    lbl = LyricLine(ms, t, None, size=19)
    lay.addWidget(lbl)
    labels.append((ms, lbl))
area.setWidget(holder)
area.setWidgetResizable(True)
area.resize(420, 300)
area.show()
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)

fol = LyricsFollower(area)
fol.set_lines(labels)
check("el seguidor calcula los tiempos de las palabras al recibir la letra", len(fol.spans) == 4 and len(fol.spans[0]) == 4)
fol.update(1000 + 50)
f0 = labels[0][1]._fill
fol.update(est[0][2][0] + 10)          # justo al empezar la 3.ª palabra
f_third = labels[0][1]._fill
check("el relleno llega al inicio de la palabra que se está cantando", abs(f_third - est[0][2][2] / len(text)) < 0.08)
check("el seguidor admite tiempos medidos de las mismas frases", fol.set_spans(spans) and fol.spans[0][0][0] == 1100)
check("y rechaza los que no encajan", not fol.set_spans(spans[:2]))
fol.update(1500)
check("con la voz medida, a 1,5 s ya va por «quiero»", labels[0][1]._fill * len(text) >= spans[0][2][2])

# la posición en píxeles crece con el texto (no es un reparto uniforme por carácter)
from PySide6.QtGui import QTextLayout, QFont
from ui.lyric_line import _x_at

f = QFont()
f.setPixelSize(19)
tl = QTextLayout("Wiiiii mmmmm", f)
tl.beginLayout()
ln = tl.createLine()
ln.setLineWidth(400)
tl.endLayout()
x_half = _x_at(ln, 3.5)
check("la posición en píxeles se mide con el ancho real de las letras", _x_at(ln, 0) == 0 and 0 < x_half < _x_at(ln, 6) < _x_at(ln, 12))
check("las letras anchas ocupan más que las estrechas", (_x_at(ln, 12) - _x_at(ln, 6)) > (_x_at(ln, 5) - _x_at(ln, 0)) * 0.9)

print("FIN", flush=True)
os._exit(0)
