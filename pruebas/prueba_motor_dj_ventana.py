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
DURATIONS = [44, 36, 30, 40]        # distintas a propósito: con la misma duración no se ve que la barra recorte su valor al cambiar de rango


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


def make_wav(rel, freq, bpm=120, seconds=SECONDS):
    """Golpes graves a `bpm` (un bombo corto) sobre un tono: algo con ritmo para que haya rejilla."""
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rate = 22050
    period = int(rate * 60 / bpm)
    frames = []
    for i in range(rate * seconds):
        t = i % period
        kick = 14000 * math.exp(-t / 500) * math.sin(2 * math.pi * 60 * t / rate) if t < 4000 else 0
        frames.append(int(kick + 3000 * math.sin(2 * math.pi * freq * i / rate)))
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", max(-32000, min(32000, s))) for s in frames))
    return path


paths = [make_wav(f"cancion{i}.wav", 330 + 55 * i, seconds=DURATIONS[i]) for i in range(4)]
outside = make_wav(os.path.join("..", os.path.basename(root) + "_fuera", "fuera.wav"), 880)

from services import dj_service
from ui.engine_player import EnginePlayer
from ui.main_window import MainWindow

dj_service.set_root(root.replace(os.sep, "/"))      # como la devuelve el diálogo de Qt: barras mezcladas con las del sistema
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

# La barra de progreso al cambiar de rango (la causa de que pasara por varias canciones seguidas): no es «buscar»
asked = []
_real_set = w.player.setPosition
w.player.setPosition = lambda ms: asked.append(ms)
w.is_updating_seek = True
w.seek_slider.setRange(0, 300000)
w.seek_slider.setValue(250000)          # la canción anterior iba por el 4:10...
w.is_updating_seek = False
w.update_duration(100000)               # ...y la nueva dura 1:40: la barra recorta su valor
check("cambiar la duración (la barra recorta su valor) no se lee como que el usuario busca", asked == [])
w.player.setPosition = _real_set


class FakeSession:
    """Una sesión que avanza a otra canción más corta: la señal de posición tiene que llegar antes que la de duración."""
    current_path = "x.wav"

    def __init__(self):
        self.infos = [
            {"path": "a.wav", "position_s": 240.0, "duration_s": 262.0, "state": "playing", "advanced": None, "ended": False,
             "error": None, "plan": None, "next_path": None},
            {"path": "b.wav", "position_s": 1.0, "duration_s": 207.0, "state": "playing", "advanced": "b.wav", "ended": False,
             "error": None, "plan": None, "next_path": None}]

    def tick(self):
        return self.infos.pop(0)


events = []
fake_player = EnginePlayer(FakeSession())
fake_player.positionChanged.connect(lambda v: events.append(("posicion", v)))
fake_player.durationChanged.connect(lambda v: events.append(("duracion", v)))
fake_player._state = QMediaPlayer.PlayingState
fake_player._on_tick()
fake_player._on_tick()
names = [e[0] for e in events]
check("al pasar a una canción nueva se avisa de su posición ANTES que de su duración",
      names[-2:] == ["posicion", "duracion"] and events[-2][1] == 1000 and events[-1][1] == 207000)
fake_player.deleteLater()

check("el motor se quiere por defecto", w.dj_engine_wanted())
real_player = w.player
w.open_dj_page()
check("la carpeta se lee", wait(lambda: w._dj_summary is not None))
check("el análisis en segundo plano termina", wait(lambda: w._dj_an_worker is None, 120))
scanned = dj_service.tracks_for(w._dj_summary, w._dj_source())      # las rutas como las escanea la ventana (con barras mezcladas)
check("la ventana conoce las 4 canciones", len(scanned) == 4)
for p in scanned:                    # un análisis fijado a mano (tempo, intro, final y rejilla) para que la mezcla sea la de siempre
    i = next(k for k, q in enumerate(paths) if os.path.basename(q) == os.path.basename(p))
    w._dj_analysis[p] = {"bpm": 120.0, "intro_ms": 2000, "outro_ms": 12000, "duration_ms": DURATIONS[i] * 1000, "energy": 0.5,
                         "tone": "8A", "beat_first_s": 0.0, "beat_bpm": 120.0, "beat_downbeat": 0, "beat_conf": 0.9}

calls = []
_orig_next = w.play_next


def counted_next(*a, **k):
    calls.append(w.current_item_info["local_path"] if w.current_item_info else None)
    return _orig_next(*a, **k)


w.play_next = counted_next
w.start_dj_session()
check("empieza la sesión", wait(lambda: w.dj_session_active()))
check("el reproductor de la ventana es el del motor", w.dj_engine_on() and isinstance(w.player, EnginePlayer))
check("la sesión del motor conoce la primera canción con la ruta de la ventana (y así encuentra su análisis)",
      w._dj_engine_session.current_path == w.current_item_info["local_path"]
      and w._dj_engine_info(w._dj_engine_session.current_path).get("bpm") == 120.0)
check("suena (estado Reproduciendo)", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState, 10))
check("conoce la duración de la que suena", wait(lambda: any(abs(w.player.duration() - d * 1000) < 1500 for d in DURATIONS), 10))
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

# Quitar la siguiente: el motor rehace la mezcla hacia la que toca ahora
before = w.peek_next()["local_path"]
w.dj_drop_next()
after_drop = w.peek_next()["local_path"]
check("quitar la siguiente cambia la que toca", after_drop != before)
check("el motor rehace la mezcla hacia la nueva siguiente (sin que nadie lo pida)",
      wait(lambda: os.path.normcase(os.path.normpath(w.player.last_info.get("next_path") or "")) == os.path.normcase(os.path.normpath(after_drop)), 10))
nxt = after_drop

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
n_calls = len(calls)
w.player.setPosition(max(0, int((plan.a_start_s - 3) * 1000)))
check("pasa solo a la siguiente canción con la mezcla (sin que nadie pulse nada)",
      wait(lambda: w.current_item_info["local_path"] != current, plan.length_s + 40))
check("y es la que estaba planificada", planned_next is None or w.current_item_info["local_path"] == planned_next)
check("sigue el motor y sigue sonando", w.dj_engine_on() and w.player.playbackState() == QMediaPlayer.PlayingState)
q0 = w.player.position()
check("la canción nueva no se reinició al tomar el relevo (la posición sigue avanzando)",
      wait(lambda: w.player.position() > q0 + 800, 10))
check("la sesión sigue activa", w.dj_session_active())
arrived = w.current_item_info["local_path"]
pump(6.0)
check("tras el paso solo hubo UN cambio de canción (sin saltar varias seguidas) y sigue la misma",
      len(calls) - n_calls == 1 and w.current_item_info["local_path"] == arrived and w.player.playbackState() == QMediaPlayer.PlayingState)
check("y la barra de progreso está dentro del rango de la canción nueva", 0 <= w.seek_slider.value() <= w.seek_slider.maximum()
      and abs(w.seek_slider.maximum() - w.player.duration()) < 50)

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
