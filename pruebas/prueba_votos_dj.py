"""Votos 👍 / 👎 de las mezclas en la página DJ con la ventana de verdad (con el reproductor de siempre, en silencio): sin mezcla no se
puede votar, la última mezcla se vota con los botones, votar otra vez la misma cambia el voto (no lo duplica), los motivos se
guardan y cada mezcla nueva es un voto nuevo.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_votos_dj.py"""
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

from PySide6.QtWidgets import QApplication

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def wait(cond, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.03)
        if cond():
            return True
    return False


def pump(s=0.3):
    wait(lambda: False, s)


root = tempfile.mkdtemp(prefix="descargador_votos_")


def make_wav(name, freq, seconds=40):
    path = os.path.join(root, name)
    rate = 22050
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(rate * seconds)))
    return path


paths = [make_wav(f"cancion{i}.wav", 330 + 55 * i) for i in range(4)]

from config import update_settings
from services import dj_service, transition_votes
from ui.main_window import MainWindow

update_settings(dj_engine=False)       # esta prueba es del reproductor de siempre
dj_service.set_root(root)
w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(1.0)
w.open_dj_page()
wait(lambda: w._dj_summary is not None)
wait(lambda: w._dj_an_worker is None, 120)
for p in paths:
    w._dj_analysis[p] = {"bpm": 120.0, "intro_ms": 2000, "outro_ms": 12000, "duration_ms": 40000, "energy": 0.5, "tone": "8A"}
page = w.page_dj

check("al empezar la base de votos está vacía", transition_votes.count()["total"] == 0)
w.start_dj_session()
check("empieza la sesión", wait(lambda: w.dj_session_active()))
w.refresh_dj_page()
check("sin ninguna mezcla todavía, los botones de votar están apagados", not page.btn_up.isEnabled() and not page.btn_down.isEnabled())
w.dj_vote(1)
check("votar sin mezcla no guarda nada y avisa", transition_votes.count()["total"] == 0)

first = w.current_item_info["local_path"]
planned = w.dj_mix_plan()
check("la mezcla de la que suena con la siguiente está planificada", planned is not None)
w.dj_skip()
check("«siguiente» pasa a la planificada", wait(lambda: planned is not None and w.current_item_info["local_path"] == planned[0]))
w.refresh_dj_page()
check("ahora hay una mezcla que votar y los botones se encienden", w.dj_vote_target() is not None and page.btn_up.isEnabled()
      and page.btn_down.isEnabled())
check("la página dice cuál se vota", os.path.splitext(os.path.basename(first))[0] in page.vote_caption.text()
      and os.path.splitext(os.path.basename(planned[0]))[0] in page.vote_caption.text())

page.btn_up.click()
rows = transition_votes.votes()
check("el botón 👍 guarda un voto", len(rows) == 1 and rows[0]["vote"] == 1)
check("con las canciones y el plan de la mezcla", rows[0]["a_path"] == first and rows[0]["b_path"] == planned[0]
      and abs(rows[0]["length_s"] - planned[1].length_s) < 1e-6 and rows[0]["source"] == "live" and rows[0]["session"])
check("con el análisis de las canciones (BPM y tono)", rows[0]["a_bpm"] == 120.0 and rows[0]["a_tone"] == "8A")
check("la página confirma el voto", "👍" in page.vote_status.text() and "1 voto" in page.vote_status.text())

page.vote_requested.emit(-1, ["graves"])
rows = transition_votes.votes()
check("votar otra vez la misma mezcla cambia el voto (sigue habiendo uno) y guarda el motivo",
      len(rows) == 1 and rows[0]["vote"] == -1 and rows[0]["tags"] == ["graves"])
check("el menú de 👎 tiene un motivo por etiqueta más «Sin motivo»", len(page.btn_down.menu().actions()) == len(transition_votes.TAGS) + 2)

# otra mezcla: voto nuevo
planned2 = w.dj_mix_plan()
w.dj_skip()
check("la siguiente mezcla", planned2 is not None and wait(lambda: w.current_item_info["local_path"] == planned2[0]))
w.refresh_dj_page()
page.btn_down.menu().actions()[0].trigger()
rows = transition_votes.votes()
check("la mezcla nueva es un voto nuevo (2 en total) y es de ella", len(rows) == 2 and rows[0]["a_path"] == planned[0]
      and rows[0]["b_path"] == planned2[0] and rows[0]["vote"] == -1 and rows[0]["session"] == rows[1]["session"])

# mover una canción conserva sus votos
moved = os.path.join(root, "movida.wav")
transition_votes.rename_path(first, moved)
check("renombrar la canción actualiza sus votos", any(r["a_path"] == moved for r in transition_votes.votes()))

# fuera de la sesión no hay mezcla que votar
w.set_context([w._local_track_info(paths[0], {})])
w._play_entry(w._local_track_info(paths[0], {}))
pump(0.5)
w.dj_vote(1)
check("al salir de la sesión DJ no se puede votar (no se guardan votos de otra cosa)",
      w.dj_vote_target() is None and transition_votes.count()["total"] == 2)
w.player.pause()
w.shutdown_playback_options()
print("FIN")
