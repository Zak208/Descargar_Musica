"""Sesión DJ con el motor de mezcla propio dentro de la ventana de verdad (en silencio: volumen a 0): el motor entra al empezar
la sesión, suena, pausa, busca, salta con «siguiente», pasa solo a la siguiente canción con su mezcla y se apaga al salir de la
sesión (volviendo al reproductor de siempre). Tarda un minuto: el motor toca en tiempo real.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_dj_ventana.py"""
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

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

app = QApplication([])
SECONDS = 40


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


root = tempfile.mkdtemp(prefix="descargador_motor_")


def make_wav(rel, freq, bpm=120):
    """Golpes graves a `bpm` (un bombo corto) sobre un tono: algo con ritmo para que haya rejilla."""
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rate = 22050
    period = int(rate * 60 / bpm)
    frames = []
    for i in range(rate * SECONDS):
        t = i % period
        kick = 14000 * math.exp(-t / 500) * math.sin(2 * math.pi * 60 * t / rate) if t < 4000 else 0
        frames.append(int(kick + 3000 * math.sin(2 * math.pi * freq * i / rate)))
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", max(-32000, min(32000, s))) for s in frames))
    return path


paths = [make_wav(f"cancion{i}.wav", 330 + 55 * i) for i in range(3)]
outside = make_wav(os.path.join("..", os.path.basename(root) + "_fuera", "fuera.wav"), 880)

from services import dj_service
from ui.engine_player import EnginePlayer
from ui.main_window import MainWindow

dj_service.set_root(root)
w = MainWindow()
w.resize(1360, 860)
w.show()
pump(1.0)
w.volume_slider.setValue(0)         # el motor recibe el volumen de la ventana: todo en silencio
pump(0.2)

reason = w.dj_engine_unavailable_reason()
if reason:
    check(f"el motor propio no está disponible aquí ({reason}): se salta esta prueba", True)
    print("FIN")
    sys.exit(0)

check("el motor se quiere por defecto", w.dj_engine_wanted())
real_player = w.player
w.open_dj_page()
check("la carpeta se lee", wait(lambda: w._dj_summary is not None))
check("el análisis en segundo plano termina", wait(lambda: w._dj_an_worker is None, 120))
for p in paths:                      # un análisis fijado a mano (tempo, intro, final y rejilla) para que la mezcla sea la de siempre
    w._dj_analysis[p] = {"bpm": 120.0, "intro_ms": 2000, "outro_ms": 12000, "duration_ms": SECONDS * 1000, "energy": 0.5,
                         "tone": "8A", "beat_first_s": 0.0, "beat_bpm": 120.0, "beat_downbeat": 0, "beat_conf": 0.9}

w.start_dj_session()
check("empieza la sesión", wait(lambda: w.dj_session_active()))
check("el reproductor de la ventana es el del motor", w.dj_engine_on() and isinstance(w.player, EnginePlayer))
check("suena (estado Reproduciendo)", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState, 10))
check("conoce la duración (unos 40 s)", wait(lambda: abs(w.player.duration() - SECONDS * 1000) < 1500, 10))
p0 = 0
check("la posición avanza", wait(lambda: w.player.position() > 800, 10))
first = w.current_item_info["local_path"]
check("el motor no está tocando el QMediaPlayer de siempre", real_player.playbackState() == QMediaPlayer.StoppedState)

# Pausa y reanudar
w.toggle_play_pause()
pump(0.4)
p0 = w.player.position()
pump(0.8)
check("en pausa la posición no avanza", w.player.playbackState() == QMediaPlayer.PausedState and abs(w.player.position() - p0) < 150)
w.toggle_play_pause()
check("al reanudar vuelve a avanzar", wait(lambda: w.player.position() > p0 + 400, 10))

# Buscar dentro de la canción
w.player.setPosition(15000)
check("buscar lleva a ese punto", wait(lambda: 14500 <= w.player.position() <= 17500, 10))

# La mezcla planificada se ve en la página
planned = wait(lambda: w.dj_engine_plan() is not None, 15)
check("hay una mezcla planificada con la siguiente", planned)
if not planned:
    print("      diagnóstico:", w.player.last_info, "| siguiente según la ventana:", w.peek_next() and w.peek_next().get("local_path"),
          "| next_after:", w._dj_engine_next(first), "| error:", w.player.session.tick().get("error"))
    print("FIN")
    sys.exit(1)
plan = w.dj_engine_plan()
nxt = w.peek_next()["local_path"]
print(f"      plan: empieza en {plan.a_start_s:.1f} s, dura {plan.length_s:.1f} s, tempo B x{plan.tempo_ratio_b:.3f}, {plan.reason}")
check("la página DJ dice cuándo empieza la mezcla", wait(lambda: "La mezcla empieza" in w.page_dj.countdown.text()
                                                        or "Mezclando" in w.page_dj.countdown.text(), 5))

# «Siguiente» a mano
w.dj_skip()
check("«siguiente» cambia la canción", wait(lambda: w.current_item_info["local_path"] == nxt, 10))
check("sigue el motor y sigue sonando", w.dj_engine_on() and wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState
                                                                  and 0 < w.player.position() < 8000, 10))

# Paso natural: se coloca justo antes de la mezcla y se espera a que la canción siguiente tome el relevo
wait(lambda: w.dj_engine_plan() is not None, 15)
plan = w.dj_engine_plan()
planned_next = w.peek_next()["local_path"] if w.peek_next() else None
current = w.current_item_info["local_path"]
w.player.setPosition(max(0, int((plan.a_start_s - 3) * 1000)))
check("pasa solo a la siguiente canción con la mezcla (sin que nadie pulse nada)",
      wait(lambda: w.current_item_info["local_path"] != current, plan.length_s + 40))
check("y es la que estaba planificada", planned_next is None or w.current_item_info["local_path"] == planned_next)
check("sigue el motor y sigue sonando", w.dj_engine_on() and w.player.playbackState() == QMediaPlayer.PlayingState)
q0 = w.player.position()
check("la canción nueva no se reinició al tomar el relevo (la posición sigue avanzando)",
      wait(lambda: w.player.position() > q0 + 800, 10))
check("la sesión sigue activa", w.dj_session_active())

# Salir de la sesión: suena otra lista con el reproductor de siempre
other = w._local_track_info(outside, {})
w.set_context([other])
w._play_entry(other)
check("al salir de la sesión se apaga el motor", wait(lambda: not w.dj_engine_on(), 10))
check("y vuelve el reproductor de siempre", w.player is real_player)
w.player.pause()
pump(0.3)

# Apagarlo en el menú: la próxima sesión usa el fundido de siempre
w.set_dj_engine_wanted(False)
w.start_dj_session()
check("con el motor apagado, la sesión usa el reproductor de siempre", wait(lambda: w.dj_session_active())
      and not w.dj_engine_on() and w.player is real_player)
w.set_dj_engine_wanted(True)
w.player.pause()
w.shutdown_playback_options()
print("FIN")
