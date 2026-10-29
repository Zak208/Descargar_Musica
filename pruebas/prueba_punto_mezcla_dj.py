"""Punto de mezcla en una sesión DJ (fase 8) con la ventana de verdad y tonos WAV de 40 s, todo en silencio: el fundido
cruzado empieza donde dice el plan (el principio del final de la que suena), dura lo planificado, la que entra arranca
desde su punto, el volumen pasa de una a otra sin saltos ni huecos y la cuenta atrás de la página usa el mismo punto.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_punto_mezcla_dj.py"""
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


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def wait(cond, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.02)
        if cond():
            return True
    return False


def pump(s=0.3):
    wait(lambda: False, s)


root = tempfile.mkdtemp(prefix="descargador_punto_mezcla_")


def make_wav(name, freq, seconds=40):
    path = os.path.join(root, name)
    rate = 22050
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / rate)))
                               for i in range(int(rate * seconds))))
    return path


paths = [make_wav(f"tono{i}.wav", 330 + 110 * i) for i in range(3)]

from services import dj_service
from services.mix_types import KIND_BLEND
from ui.main_window import MainWindow

dj_service.set_root(root)
from config import update_settings  # noqa: E402
update_settings(dj_engine=False)       # estas pruebas son del reproductor de siempre (el motor propio tiene la suya)
w = MainWindow()
w._set_output_volume(w.audio_output, 0)
w.change_volume(0)                  # el volumen general a cero: también el reproductor de la mezcla queda en silencio
w.resize(1360, 860)
w.show()
pump(0.8)

page = w.page_dj
w.open_dj_page()
check("la carpeta se lee", wait(lambda: w._dj_summary is not None))
page.btn_start.click()
check("empieza la sesión DJ", wait(lambda: w.dj_session_active()))
check("suena la primera canción", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState
                                       and w.player.duration() > 30000, 20))
# el análisis de verdad de estos tonos no tiene ni intro ni final: se para y se pone uno a medida para cada prueba
if w._dj_an_worker is not None:
    w._dj_an_worker.cancel()
check("el análisis en segundo plano se para", wait(lambda: w._dj_an_worker is None, 60))
w.change_volume(0)


def analysis(intro_s=0.0, outro_s=0.0):
    return {"bpm": None, "confidence": 0.0, "energy": None, "intro_ms": int(intro_s * 1000), "outro_ms": int(outro_s * 1000),
            "duration_ms": 40000, "tone": None, "tone_conf": 0.0}


def sample_crossfade(seconds):
    """Niveles (la que entra, la que sale) durante el fundido, cada ~20 ms, sin depender del volumen general."""
    levels = []
    t = time.time()
    while time.time() - t < seconds and w._xf_active:
        app.processEvents()
        levels.append((w._fade_factor, w._out_factor))
        time.sleep(0.02)
    return levels


# ------------------------------------------------------------- 1. final de 12 s, intro de 15 s
a_path = w.current_item_info["local_path"]
b_path = w.peek_next()["local_path"]
w._dj_analysis[a_path] = analysis(outro_s=12)
w._dj_analysis[b_path] = analysis(intro_s=15)
w.dj_forget_mix()
mix = w.dj_mix_plan()
duration = w.player.duration()
check("hay plan para la que suena y la siguiente", mix is not None and mix[0] == b_path)
plan = mix[1]
check(f"plan: la mezcla empieza al principio del final ({plan.a_start_s} s de {duration / 1000:.2f}), dura 12 s y la "
      f"que entra arranca en su segundo 3 ({plan.b_start_s})", plan.kind == KIND_BLEND
      and abs(plan.a_start_s - (duration / 1000 - 12)) < 0.01 and plan.length_s == 12 and abs(plan.b_start_s - 3) < 0.01)
start_ms = int(plan.a_start_s * 1000)
outgoing = w.player
w.player.setPosition(start_ms - 4000)                    # 4 s antes del punto de mezcla
check("la cuenta atrás de la página usa el mismo punto",
      wait(lambda: page.countdown.text().startswith("La mezcla empieza en 00:0") and "dura 12 s" in page.countdown.text(), 5))
text = page.countdown.text()
left_shown = int(text.split("00:0")[1][0])
left_real = (start_ms - w.player.position()) / 1000
check(f"y dice lo que falta de verdad («{text}», faltan {left_real:.1f} s)", abs(left_shown - left_real) <= 1.2)
check("antes del punto no se mezcla", not w._xf_active)
check("el fundido empieza al llegar al punto", wait(lambda: w._xf_active, 10))
a_pos = outgoing.position()
t_start = time.time()
check(f"empieza donde dice el plan (la que sale iba por {a_pos / 1000:.2f} s; plan {plan.a_start_s} s)",
      start_ms - 50 <= a_pos <= start_ms + 700)
left_a = duration - a_pos
check(f"y dura lo planificado, no el fundido de los Ajustes ({w._xf_anim.duration()} ms, Ajustes {w._fade_ms} ms; nunca más "
      f"de lo que le queda a la que sale, {left_a} ms)", w._xf_anim.duration() == min(12000, left_a)
      and w._xf_anim.duration() > 11300)
incoming = w.player
check("la que entra es la planificada y suena en el otro reproductor", incoming is not outgoing
      and w.current_item_info["local_path"] == b_path and w._out_deck is not None and w._out_deck[0] is outgoing)
check("la que entra arranca desde su punto (3 s), no desde el principio",
      wait(lambda: incoming.position() >= 2900, 5) and incoming.position() < 3000 + (time.time() - t_start) * 1000 + 800)
check("la espera de su punto de entrada ya no queda pendiente", w._incoming_seek is None)
levels = sample_crossfade(16)
ins, outs = [x[0] for x in levels], [x[1] for x in levels]
check(f"el fundido termina solo ({len(levels)} medidas en {time.time() - t_start:.1f} s)",
      wait(lambda: not w._xf_active, 6) and 10.5 <= time.time() - t_start <= 15)
check("la que sale se para al terminar y sigue sonando la que entra",
      outgoing.playbackState() == QMediaPlayer.StoppedState and incoming.playbackState() == QMediaPlayer.PlayingState)
jump = max(max(abs(a - b) for a, b in zip(ins, ins[1:])), max(abs(a - b) for a, b in zip(outs, outs[1:])))
check(f"sin saltos de volumen: el mayor cambio entre dos medidas seguidas es {jump:.3f}", jump < 0.08)
check("la que entra solo sube y la que sale solo baja", all(b >= a - 1e-9 for a, b in zip(ins, ins[1:]))
      and all(b <= a + 1e-9 for a, b in zip(outs, outs[1:])))
gap = min(math.hypot(i, o) for i, o in levels[3:])
check(f"sin hueco: la suma de las dos nunca baja de casi una canción entera (mínimo {gap:.2f})", gap > 0.9)
check("al acabar, la que entra a volumen completo", w._fade_factor == 1.0 and w._out_deck is None)

# ------------------------------------------------------------- 2. sin análisis: el fundido de los Ajustes, como siempre
a1 = w.current_item_info["local_path"]
w._dj_analysis.pop(a1, None)
w.dj_forget_mix()
check("sin el análisis de la que suena no hay plan (vale el fundido de los Ajustes)", w.dj_mix_plan() is None)
w.player.setPosition(15000)
check("y la cuenta atrás es la de siempre", wait(lambda: page.countdown.text().startswith("La mezcla empieza en")
                                                 and "dura" not in page.countdown.text(), 5))

# ------------------------------------------------------------- 3. sin final ni intro claros: mezcla corta de 6 s
a2 = w.current_item_info["local_path"]
nxt = w.peek_next()
check("queda una siguiente", nxt is not None)
b2 = nxt["local_path"]
w._dj_analysis[a2] = analysis()
w._dj_analysis[b2] = analysis()
w.dj_forget_mix()
plan2 = w.dj_mix_plan()[1]
dur2 = w.player.duration()
check(f"sin final ni intro: mezcla corta de 6 s al acabar, la que entra desde el principio ({plan2.reason})",
      plan2.length_s == 6 and abs(plan2.a_start_s - (dur2 / 1000 - 6)) < 0.01 and plan2.b_start_s == 0)
outgoing = w.player
w.player.setPosition(int(plan2.a_start_s * 1000) - 1500)
check("el fundido empieza en su punto", wait(lambda: w._xf_active, 8))
a_pos = outgoing.position()
check(f"a {a_pos / 1000:.2f} s (plan {plan2.a_start_s} s) y dura 6 s ({w._xf_anim.duration()} ms)",
      int(plan2.a_start_s * 1000) - 50 <= a_pos <= int(plan2.a_start_s * 1000) + 700
      and w._xf_anim.duration() == min(6000, dur2 - a_pos) and w._xf_anim.duration() > 5300)
incoming = w.player
check("la que entra empieza desde el principio (no hay salto pendiente)", w._incoming_seek is None
      and wait(lambda: incoming.position() > 0, 5) and incoming.position() < 2500)
w._finish_crossfade()

# ------------------------------------------------------------- 4. fuera de la sesión DJ no cambia nada
w.set_context([w._local_track_info(p, {}) for p in paths])
w.dj_track_changed()
check("con otra lista la sesión termina y no hay plan de mezcla", not w.dj_session_active() and w.dj_mix_plan() is None)
check("la reproducción normal no pasa por el plan", w._planned_tick(w.player.position()) is False)

w.stop_player()
w.close()
pump(0.5)
print("FIN")
