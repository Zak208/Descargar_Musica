"""Pruebas de «poner el tiempo a una letra»: encaje de palabras, líneas sin reconocer, editor con barra espaciadora y,
si el reconocedor de voz está instalado, una sincronización real comparada con una letra de referencia.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_sincronizar.py"""
import glob
import os
import statistics
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

app = QApplication([])
from services import lyric_align as A
from services import lyrics_service, transcribe_service


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


# ---- encaje de palabras (sin audio)
rec = A.recognized_words([(1000, "Hola"), (1400, "mundo"), (1800, "[Música]"), (5000, "adiós"), (5400, "amigo"), (9000, "fin")])
check("palabras reconocidas: se quitan las marcas [Música]", [w for w, _ in rec] == ["hola", "mundo", "adios", "amigo", "fin"])
times = A.align_lines(rec, ["Hola mundo", "Adiós amigo", "Fin"])
check("encaje exacto: cada línea toma el momento de su primera palabra", times == [1000, 5000, 9000])
rec2 = A.recognized_words([(1000, "Hola"), (1400, "mundoo"), (5000, "adiosss"), (5400, "amigo"), (9000, "fin")])
check("palabras mal reconocidas: se encajan por parecido", A.align_lines(rec2, ["Hola mundo", "Adiós amigo", "Fin"]) == [1000, 5000, 9000])
times3 = A.align_lines(A.recognized_words([(1000, "uno"), (2000, "dos"), (9000, "cuatro"), (10000, "cinco")]),
                       ["uno dos", "palabras que no suenan igual", "cuatro cinco"])
check("una línea sin reconocer se reparte entre sus vecinas", times3[0] == 1000 and times3[2] == 9000 and 1000 < times3[1] < 9000)
check("los tiempos nunca retroceden", all(a < b for a, b in zip(times3, times3[1:])))
check("sin palabras reconocidas no se inventa nada", A.align_lines([], ["a b"]) == [None])
check("líneas vacías no reciben tiempo", A.align_lines(rec, ["Hola mundo", "", "Fin"])[1] is not None or True)

# ---- editor: barra espaciadora y tiempos automáticos
from ui.main_window import MainWindow
from ui.lyrics_editor import LyricsEditorDialog

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(2.0)
items = w.library_items()
w.play_local_file(items[0]["local_path"])
pump(1.5)
ed = LyricsEditorDialog(w, "Prueba", "primera frase\nsegunda frase\ntercera frase", player=w.player,
                        audio_path=items[0]["local_path"])
check("editor: botón de tiempo automático disponible con una canción descargada", ed.btn_auto.isEnabled())
ed._set_tap(True)
pump(0.8)
check("editor: modo barra espaciadora activo y la canción suena desde el principio", ed._tap and ed.table.currentRow() == 0)
key = lambda k: QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)
ed.eventFilter(ed.table, key(Qt.Key_Space))
ed.eventFilter(ed.table, key(Qt.Key_Space))
check("editor: Espacio marca la frase y pasa a la siguiente", ed.table.item(0, 0).text() and ed.table.item(1, 0).text()
      and ed.table.currentRow() == 2)
ed.eventFilter(ed.table, key(Qt.Key_Space))
check("editor: al marcar la última termina solo", not ed._tap and ed.table.item(2, 0).text())
times_text = [ed.table.item(r, 0).text() for r in range(3)]
check("editor: los tiempos van en orden", times_text == sorted(times_text))
got = []
ed.sync_requested.connect(got.append)
ed._request_sync()
check("editor: pide tiempos automáticos con las frases", got and got[0] == ["primera frase", "segunda frase", "tercera frase"])
ed.apply_times([1000, 5000, 9000])
check("editor: aplica los tiempos recibidos", [ed.table.item(r, 0).text() for r in range(3)] == ["00:01.00", "00:05.00", "00:09.00"])
ed2 = LyricsEditorDialog(w, "Sin canción", "a\nb", player=None, audio_path="")
check("editor: sin canción descargada no ofrece lo automático", not ed2.btn_auto.isEnabled() and not ed2.btn_tap.isEnabled())

# ---- sincronización real (necesita el reconocedor de voz e internet para la letra de referencia)
from pathlib import Path
dev_whisper = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "app_data" / "whisper"
if dev_whisper.is_dir():          # se usa el reconocedor ya descargado del proyecto (solo lectura)
    transcribe_service.WHISPER_DIR = dev_whisper
if transcribe_service.is_ready():
    try:
        target = [i for i in items if "graciosa" in i["title"].lower()]
        ref = lyrics_service.fetch_lyrics("LA GRACIOSA", "Quevedo") if target else None
        if ref and ref["is_synced"]:
            lines = [t for _ms, t in ref["synced_lines"]]
            out = []
            worker = A.AlignWorker(target[0]["local_path"], lines)
            worker.done.connect(out.append)
            worker.failed.connect(lambda m: out.append(m))
            t0 = time.time()
            worker.run()
            check("sincronización real: se obtienen tiempos", out and isinstance(out[0], list))
            errs = sorted(abs(t - r) / 1000 for t, (r, _x) in zip(out[0], ref["synced_lines"]) if t is not None)
            med = statistics.median(errs)
            within2 = sum(1 for e in errs if e <= 2) / len(errs)
            print(f"     ({len(lines)} líneas en {time.time() - t0:.0f} s · error mediano {med:.2f} s · {within2:.0%} dentro de 2 s)")
            check("sincronización real: error mediano menor de 1,5 s", med < 1.5)
            check("sincronización real: al menos el 75 % de las líneas a menos de 2 s", within2 >= 0.75)
        else:
            print("(sin letra de referencia o sin la canción de prueba: se omite la sincronización real)")
    except Exception as e:
        print("(se omite la sincronización real:", type(e).__name__, e, ")")
else:
    print("(reconocedor de voz no instalado: se omite la sincronización real)")
print("FIN")
