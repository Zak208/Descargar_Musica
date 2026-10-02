"""Pruebas del reproductor: volumen igualado, temporizador, velocidad, repetir tramo, fundidos, control multimedia y bandeja.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_reproductor.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

app = QApplication([])
from services import library_db, loudness_service


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


def wait(cond, timeout=30):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.03)
        if cond():
            return True
    return False


# ---- cálculo del volumen igualado
check("canción fuerte: se baja el volumen", abs(loudness_service.gain_for(-9.0) - 10 ** (-5 / 20)) < 0.001)
check("canción suave: no se sube", loudness_service.gain_for(-20.0) == 1.0)
check("nunca se baja más de 12 dB", abs(loudness_service.gain_for(0.0) - 10 ** (-12 / 20)) < 0.001)
check("sin medida: volumen normal", loudness_service.gain_for(None) == 1.0)
sample = "Summary:\n  Integrated loudness:\n    I:         -9.3 LUFS\n    Threshold: -19.5 LUFS\n"
check("se lee el resultado de FFmpeg", loudness_service.parse_integrated(sample) == -9.3)

from ui.main_window import MainWindow

w = MainWindow()
w.resize(1360, 860)
w.show()
pump(2.5)
w.volume_slider.setValue(50)
check("volumen: el control manda", abs(w.audio_output.volume() - 0.5) < 0.01)
items = w.library_items()

# ---- medir de verdad una canción y aplicarla al reproducirla
path = items[0]["local_path"]
lufs = loudness_service.measure(path)
check(f"FFmpeg mide el volumen de una canción ({lufs} LUFS)", lufs is not None and -40 < lufs < 0)
w.set_context(items)
w.play_local_file(path)
check("se mide y se guarda en segundo plano", wait(lambda: loudness_service.stored(path) is not None, 40))
pump(0.6)
expected = 0.5 * loudness_service.gain_for(loudness_service.stored(path))
check("al sonar, el volumen se ajusta a la medida", abs(w.audio_output.volume() - expected) < 0.01)
w.set_normalize(False)
check("sin igualar el volumen, vuelve al del control", abs(w.audio_output.volume() - 0.5) < 0.01)
w.set_normalize(True)

# ---- temporizador para dormir
w.player.play()
w.set_sleep_timer(1)
check("temporizador: se activa", w._sleep_deadline and w._sleep_timer.isActive() and w.btn_options.toolTip().count("detendrá"))
w._sleep_deadline = time.time() + 5
w._sleep_tick()
check("temporizador: el volumen baja al final", 0.2 < w._sleep_factor < 0.3 and w.audio_output.volume() < expected)
w._sleep_deadline = time.time() - 1
w._sleep_tick()
check("temporizador: pausa la música y se desactiva", w.player.playbackState() == QMediaPlayer.PausedState
      and not w._sleep_timer.isActive() and w._sleep_factor == 1.0)
w.set_sleep_end_of_track()
check("temporizador «al terminar la canción»: para en vez de pasar a la siguiente", w.on_end_of_track() is True
      and not w._sleep_end_of_track)
check("sin temporizador el fin de canción avanza", w.on_end_of_track() is False and w._natural_advance)
w.cancel_sleep_timer(quiet=True)

# ---- velocidad
w.set_playback_rate(1.5)
check("velocidad: 1,5×", abs(w.player.playbackRate() - 1.5) < 0.01)
w.set_playback_rate(1.0)
check("velocidad: vuelve a normal", abs(w.player.playbackRate() - 1.0) < 0.01)

# ---- repetir un tramo
w.player.setPosition(3000)
pump(0.3)
w.mark_ab("b")
check("tramo: no se puede marcar el final sin inicio", w._ab == [None, None])
w.mark_ab("a")
w.player.setPosition(8000)
pump(0.3)
w.mark_ab("b")
check("tramo: inicio y final marcados", w._ab[0] is not None and w._ab[1] > w._ab[0])
w.playback_tick(w._ab[1] + 20)
pump(0.4)
check("tramo: al llegar al final vuelve al inicio", abs(w.player.position() - w._ab[0]) < 1500)
w.clear_ab()
check("tramo: se puede quitar", w._ab == [None, None])

# ---- fundido entre canciones (sin canción siguiente: solo baja el volumen; el fundido cruzado tiene su propia prueba)
w.set_context([])
w.set_fade_seconds(2)
w.player.duration = lambda: 60000
w.player.playbackState = lambda: QMediaPlayer.PlayingState
w.playback_tick(59000)
check("fundido: empieza a bajar el volumen al final de la canción", w._fading_out and w._fade_anim.state() == w._fade_anim.State.Running)
w.playback_tick(10000)
check("fundido: si se retrocede, se cancela", not w._fading_out and w._fade_factor == 1.0)
w._natural_advance = True
w.on_track_started()
check("fundido: la canción siguiente entra poco a poco", w._fade_factor < 0.5 and w._fade_anim.state() == w._fade_anim.State.Running)
w._fade_anim.stop()
w.set_fade_seconds(0)

# ---- control multimedia de Windows y bandeja
check("control multimedia de Windows disponible", w.media_controls.available)
calls = []
w.play_next = lambda: calls.append("next")
w.play_previous = lambda: calls.append("prev")
w.media_controls.button.emit("next")
w.media_controls.button.emit("previous")
pump(0.2)
check("los botones del sistema controlan la reproducción", calls == ["next", "prev"])
actions = [a.text() for a in w.tray_icon.contextMenu().actions() if a.text()]
check("bandeja: menú con controles", "Siguiente" in actions and "Anterior" in actions and "Salir" in actions)
check("bandeja: por defecto cerrar la ventana cierra la aplicación", w.should_close_to_tray() is False)
print("FIN")
