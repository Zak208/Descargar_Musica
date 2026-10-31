"""Sesión de votos (fase 27) con la ventana de verdad y canciones wav sintéticas, en silencio (volumen 0): se abre desde el menú
DJ, renderiza y reproduce el clip con su propio reproductor (sin tocar el de la ventana), se vota con teclas y con los motivos,
el voto se guarda con origen «clip», se salta, se repite, avisa del descanso y se cierra sin dejar hilos colgando.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_sesion_votos_ventana.py"""
import logging
import os
import sys
import tempfile
import time
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

app = QApplication([])
logging.disable(logging.CRITICAL)


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def wait(cond, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


root = tempfile.mkdtemp(prefix="descargador_votos_clip_")
SR = 44100


def make_song(name, freq, seconds=40, bpm=120.0):
    t = np.arange(int(seconds * SR)) / SR
    x = 0.12 * np.sin(2 * np.pi * freq * t)
    beat = 60.0 / bpm
    for k in range(int(seconds / beat)):
        s = int((0.1 + k * beat) * SR)
        n = min(int(0.12 * SR), len(x) - s)
        if n > 0:
            tt = np.arange(n) / SR
            x[s:s + n] += 0.5 * np.sin(2 * np.pi * 55 * tt) * np.exp(-tt * 30)
    pcm = (np.clip(np.stack([x, x], 1), -1, 1) * 32767).astype("<i2")
    path = os.path.join(root, name)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(pcm.tobytes())
    return path


paths = [make_song(f"cancion{i}.wav", 220 + 40 * i) for i in range(4)]

from config import update_settings
from services import dj_service, ffmpeg_service, transition_votes
from services.transition_votes import TAGS
from ui.main_window import MainWindow

update_settings(dj_engine=False)
dj_service.set_root(root)
w = MainWindow()
w.audio_output.setVolume(0)
w.vote_session_volume = lambda: 0.0          # la sesión de votos, también en silencio
w.show()
wait(lambda: False, 1.0)
w.open_dj_page()
wait(lambda: w._dj_summary is not None)
wait(lambda: w._dj_an_worker is None, 120)

if not ffmpeg_service.FFmpegService.get_ffmpeg_path():
    check("no hay FFmpeg: se salta esta prueba", True)
    print("FIN")
    sys.exit(0)

notes = []
w.notify = lambda text, *a, **k: notes.append(text)
w._dj_analysis.clear()
check("sin canciones analizadas no se abre (y avisa)", w.open_vote_session() is None and w._vote_dialog is None and notes
      and "analizadas" in notes[-1])
tones = ("8A", "9A", "8B", "3B")
for i, p in enumerate(paths):
    w._dj_analysis[p] = {"bpm": 120.0, "beat_bpm": 120.0, "beat_conf": 0.9, "beat_first_s": 0.1, "beat_downbeat": 0, "intro_ms": 8000,
                         "outro_ms": 12000, "duration_ms": 40000, "energy": 0.4 + 0.1 * i, "loudness_db": -12.0, "tone": tones[i],
                         "tone_conf": 0.9}
check("las fichas de la sesión salen del análisis, con su rejilla", len(w.vote_session_infos()) == 4
      and all(i["beatgrid"] is not None for i in w.vote_session_infos()))

# abrir desde el menú DJ: mientras el menú está abierto se lee y se elige la entrada (como haría el ratón)
entries = []


def pick_from_menu():
    menu = QApplication.activePopupWidget()
    if not isinstance(menu, QMenu):
        QTimer.singleShot(50, pick_from_menu)
        return
    target = None
    for act in menu.actions():
        entries.append(act.text())
        if act.text().startswith("Sesión de votos"):
            target = act
    menu.close()
    if target is not None:
        target.trigger()


QTimer.singleShot(200, pick_from_menu)
w.open_dj_menu()
check("el menú DJ tiene «Sesión de votos (escuchar mezclas y votar)…»", "Sesión de votos (escuchar mezclas y votar)…" in entries)
dlg = w._vote_dialog
check("y abre la ventana de la sesión", dlg is not None and dlg.isVisible())
before_player = (w.player.source().toString(), w.player.playbackState())
check("renderiza el primer clip y lo reproduce", wait(lambda: dlg.current is not None, 90)
      and wait(lambda: dlg.player.playbackState() == QMediaPlayer.PlayingState, 20))
check("con su propio reproductor, el clip y en silencio", dlg.player is not w.player and dlg.audio.volume() == 0.0
      and dlg.player.source().toLocalFile().lower() == dlg.current["clip_path"].replace("\\", "/").lower())
check("el reproductor de la ventana no se toca", (w.player.source().toString(), w.player.playbackState()) == before_player)
check("enseña la pareja, el tipo y dónde va la mezcla", "»" in dlg.pair_label.text() and dlg.detail_label.text()
      and ("mezcla" in dlg.time_label.text() or "corte" in dlg.time_label.text()))
check("el contador dice por qué voto va y el estado del modelo", dlg.counter_label.text().startswith("Voto 1 de unos 100")
      and "Sin modelo" in dlg.counter_label.text())
check("mientras suena, prepara el siguiente en segundo plano", wait(lambda: dlg._next is not None, 90))

# votar con la tecla 1
first = dlg.current
QTest.keyClick(dlg, Qt.Key_1)
row = transition_votes.last_vote()
check("la tecla 1 guarda «buena» con origen «clip», su tipo y su nota", row is not None and row["vote"] == 1 and row["source"] == "clip"
      and row["kind"] == first["kind"] and row["auto_score"] is not None and dlg.last_vote_id == row["id"])
check("y pasa al momento al siguiente (ya preparado)", dlg.current is not None and dlg.current["id"] != first["id"])
check("el contador avanza", dlg.counter_label.text().startswith("Voto 2 de unos 100"))

# «mala» con motivo desde el menú del botón
second = dlg.current
tag_action = next(a for a in dlg.btn_down.menu().actions() if a.text() and a.text() != "Sin motivo")
tag_action.trigger()
row = transition_votes.last_vote()
check("«mala» con motivo desde el menú: se guarda con su etiqueta", row["vote"] == -1 and row["tags"] == [TAGS[0]]
      and row["a_path"] == second["a_path"])

# saltar, repetir, pausa
check("llega el siguiente clip", wait(lambda: dlg.current is not None, 90))
total = transition_votes.count()["total"]
third = dlg.current
QTest.keyClick(dlg, Qt.Key_S)
check("saltar no guarda nada y pasa a otro", transition_votes.count()["total"] == total
      and (dlg.current is None or dlg.current["id"] != third["id"]))
check("llega otro clip", wait(lambda: dlg.current is not None and dlg.player.playbackState() == QMediaPlayer.PlayingState, 90))
wait(lambda: dlg.player.position() > 600, 10)
dlg.repeat()
check("repetir vuelve al principio", wait(lambda: dlg.player.position() < 500, 5))
QTest.keyClick(dlg, Qt.Key_Space)
check("el espacio pausa el clip", wait(lambda: dlg.player.playbackState() == QMediaPlayer.PausedState, 5))
QTest.keyClick(dlg, Qt.Key_Space)
check("y lo reanuda", wait(lambda: dlg.player.playbackState() == QMediaPlayer.PlayingState, 5))
pos_main = w.player.position()
check("el espacio no llega al reproductor de la ventana (allí pausa o reanuda la música)",
      (w.player.source().toString(), w.player.playbackState()) == before_player and w.player.position() == pos_main)
QTest.keyClick(dlg, Qt.Key_2)
check("la tecla 2 guarda «mala» sin motivo", transition_votes.last_vote()["vote"] == -1 and transition_votes.last_vote()["tags"] == []
      and transition_votes.count()["total"] == total + 1)

# descanso
from services import vote_session  # noqa: E402

check("antes de 35 minutos no pide descanso", (dlg.check_break(), dlg.break_label.isHidden())[1])
dlg.session.started -= vote_session.BREAK_AFTER_S + 1
dlg.check_break()
check("a los 35 minutos avisa de que conviene descansar", not dlg.break_label.isHidden())

# otra vez el menú con la sesión abierta
notes.clear()
check("con la sesión abierta no se abre otra", w.open_vote_session() is None and notes and "ya está abierta" in notes[-1])

# cerrar mientras renderiza
from ui import vote_dialog  # noqa: E402

wait(lambda: dlg.current is not None, 90)
QTest.keyClick(dlg, Qt.Key_S)                # pide otro render si no había uno preparado
busy = dlg.is_busy() or vote_dialog.running_workers() > 0
dlg.accept()
check("al cerrar se suelta el clip y se olvida la ventana", w._vote_dialog is None and dlg.player.source().isEmpty())
check("los hilos de render acaban solos (sin colgarse)", vote_dialog.wait_workers(60000) and vote_dialog.running_workers() == 0)
wait(lambda: False, 0.5)
check(f"(había un render en marcha al cerrar: {'sí' if busy else 'no'}) y no queda ninguno registrado", not vote_dialog._RUNNING)
check("al cerrar avisa de cuántos votos se dieron", any("Sesión de votos terminada: 3 votos" in n for n in notes))
check("en total, 3 votos con origen «clip»", transition_votes.summary()["by_source"].get("clip", {}).get("total") == 3)
w.vote_session_shutdown()
w.player.pause()
w.shutdown_playback_options()
w.close()
app.processEvents()
print("FIN")
