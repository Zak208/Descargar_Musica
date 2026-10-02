"""Pruebas del aleatorio (lo que se muestra como «siguiente» es lo que suena) y del fundido cruzado (la canción siguiente
empieza mientras la actual baja el volumen y las dos suenan a la vez).
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_fundido.py"""
import math
import os
import struct
import sys
import tempfile
import time
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


def wait(cond, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.03)
        if cond():
            return True
    return False


folder = tempfile.mkdtemp(prefix="descargador_fundido_")


def make_wav(name, freq, seconds):
    path = os.path.join(folder, name)
    rate = 22050
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / rate)))
                          for i in range(int(rate * seconds)))
        f.writeframes(frames)
    return path


paths = [make_wav(f"tono{i}.wav", 330 + 110 * i, 14) for i in range(6)]

from ui.main_window import MainWindow

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(1.0)
items = [w._local_track_info(p) for p in paths]

# ------------------------------------------------------------------ aleatorio
w.set_context(items)
w.play_local_file(paths[0])
pump(0.5)
w.toggle_shuffle()
check("aleatorio activado", w.is_shuffle_enabled)
w.toggle_play_pause()
shown = w.peek_next()
check("el panel «A continuación» enseña una canción de la lista", shown is not None and shown["local_path"] in paths[1:])
panel_next = w.upcoming_tracks(1)[0]
check("con el aleatorio, lo que se muestra es la primera de las que vienen", panel_next is shown)
same = all(w.peek_next() is shown for _ in range(5))
check("el «siguiente» no cambia cada vez que se mira", same)
order = [t["local_path"] for t in w.upcoming_tracks(10)]
check("se enseña el orden completo de lo que viene, sin repetir ni incluir la actual",
      len(order) == 5 and len(set(order)) == 5 and paths[0] not in order)
w.now_panel.setVisible(True)
w.now_panel.set_track(w.current_item_info)
pump(0.3)
check("el panel muestra el título de esa canción", w.now_panel.next_title.fullText() == shown["title"])
w.play_next()
pump(0.5)
check("al pulsar «siguiente» suena justo la que se había enseñado", w.current_item_info["local_path"] == shown["local_path"])
seen = [paths[0], shown["local_path"]]
for _ in range(4):
    expected = w.peek_next()
    w.play_next()
    pump(0.2)
    ok = w.current_item_info["local_path"] == expected["local_path"]
    seen.append(w.current_item_info["local_path"])
    if not ok:
        break
check("cada «siguiente» coincide con lo anunciado", ok)
check("no se repite ninguna hasta recorrer toda la lista", len(set(seen)) == 6)
w.toggle_shuffle()
check("sin aleatorio, lo siguiente vuelve a ser el orden de la lista",
      w.peek_next()["local_path"] == paths[(paths.index(w.current_item_info["local_path"]) + 1) % 6]
      if paths.index(w.current_item_info["local_path"]) < 5 else w.peek_next() is None)
w.toggle_shuffle()
w.playback_queue.append(items[3])
check("lo que añades a la cola manda sobre el aleatorio", w.peek_next() is items[3])
w.playback_queue.clear()
w.toggle_shuffle()

# ------------------------------------------------------------- fundido cruzado
w.set_context(items)
w.set_fade_seconds(4)
w.play_local_file(paths[0])
w.player.play()
check("empieza la primera canción", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState and w.player.duration() > 10000, 15))
first = w.player
w.audio_output.setVolume(0)
w.volume_slider.setValue(100)
w.player.setPosition(w.player.duration() - 5000)        # faltan 5 s: al llegar a 4 s empieza el fundido
check("antes del fundido solo hay un reproductor sonando", w._out_deck is None and not w._xf_active)
check("empieza el fundido al acercarse el final", wait(lambda: w._xf_active, 10))
second = w.player
check("la canción nueva suena en otro reproductor", second is not first and w.current_item_info["local_path"] == paths[1])
check("el fundido empieza sin cortar la canción anterior", w._out_deck is not None and w._out_deck[0] is first)
pump(0.8)
check("las dos canciones suenan a la vez",
      first.playbackState() == QMediaPlayer.PlayingState and second.playbackState() == QMediaPlayer.PlayingState)
v_in = w.audio_output.volume()
v_out = w._out_deck[1].volume() if w._out_deck else 0
pump(1.2)
v_in2 = w.audio_output.volume()
v_out2 = w._out_deck[1].volume() if w._out_deck else 0
check(f"la nueva sube ({v_in:.2f} a {v_in2:.2f})", v_in2 > v_in > 0)
check(f"la anterior baja ({v_out:.2f} a {v_out2:.2f})", v_out2 < v_out)
check("la interfaz ya muestra la canción nueva", w.player_title.text() == items[1]["title"])
check("el fundido termina y la anterior se detiene", wait(lambda: not w._xf_active and first.playbackState() == QMediaPlayer.StoppedState, 10))
check("al terminar, la nueva suena a todo el volumen", abs(w.audio_output.volume() - 1.0) < 0.01 and w._fade_factor == 1.0)
check("el reproductor libre queda listo para el próximo fundido", w._spare_deck is not None and w._spare_deck[0] is first)
check("la letra y los controles siguen al reproductor que suena", w.active_player.position() == w.player.position())

# el siguiente salto reutiliza los dos reproductores
w.player.setPosition(w.player.duration() - 4500)
check("segundo fundido con el mismo par de reproductores", wait(lambda: w._xf_active, 10) and w.player is first)
check("termina otra vez", wait(lambda: not w._xf_active, 10))

# saltar a mano con «siguiente» también se funde, más corto
n_before = w.current_item_info["local_path"]
w.play_next()
check("«siguiente» a mano: fundido corto", w._xf_active and w._xf_anim.duration() <= 1500)
check("termina", wait(lambda: not w._xf_active, 6))
check("ha cambiado de canción", w.current_item_info["local_path"] != n_before)

# pausar a mitad del fundido corta la canción que se apagaba
w.play_next()
pump(0.3)
w.player.pause()
pump(0.3)
check("pausar a mitad del fundido lo termina", not w._xf_active and w._out_deck is None)

# sin fundido (0 s) el salto es un corte normal
w.player.play()
w.set_fade_seconds(0)
before = w.player
w.play_next()
pump(0.4)
check("sin fundido no se usa un segundo reproductor", w.player is before and not w._xf_active)

# la última canción de la lista (sin siguiente): solo baja el volumen
w.set_fade_seconds(2)
w.set_context(items[:1])
w.play_local_file(paths[0])
w.player.play()
wait(lambda: w.player.duration() > 10000, 10)
w.player.setPosition(w.player.duration() - 1500)
check("sin siguiente canción solo baja el volumen", wait(lambda: w._fading_out, 6) and not w._xf_active)
w.player.stop()
print("FIN", flush=True)
os._exit(0)
