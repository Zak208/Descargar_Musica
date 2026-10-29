"""Diagnóstico (no es una prueba): una sesión DJ con el motor propio y TUS canciones de verdad, en silencio, saltando cerca de
cada mezcla y apuntando cada 100 ms qué hay sonando: la canción de la ventana, la del motor, lo que queda en la cola, si el
reproductor de siempre suena también y cuántas veces cambia la canción. Sirve para ver si el paso de una canción a la siguiente
es limpio (una sola canción cada vez, una sola vez, y es la que toca).
Uso:  python pruebas/medir_mezcla_real.py [carpeta] [número de transiciones]"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

app = QApplication([])
folder = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Music/Canciones_YouTube")
transitions = int(sys.argv[2]) if len(sys.argv) > 2 else 3

from services import dj_service
from ui.main_window import MainWindow


def pump(s):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


def wait(cond, timeout):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents()
        time.sleep(0.03)
        if cond():
            return True
    return False


dj_service.set_root(folder.replace(os.sep, "/"))
w = MainWindow()
w.show()
pump(1.0)
w.volume_slider.setValue(0)
pump(0.3)
real = w.player
w.open_dj_page()
wait(lambda: w._dj_summary is not None, 30)
print("leyendo y analizando la carpeta (puede tardar un minuto)...", flush=True)
wait(lambda: w._dj_an_worker is None, 600)
w.start_dj_session()
wait(lambda: w.dj_session_active(), 30)
print("motor propio activo:", w.dj_engine_on(), flush=True)

calls = {"play_next": 0}
orig_next = w.play_next


def counted_next(*a, **k):
    calls["play_next"] += 1
    return orig_next(*a, **k)


w.play_next = counted_next
T_START = time.time()
sess = w._dj_engine_session
orig_after = sess._next_after


def logged_after(path):
    res = orig_after(path)
    print(f"   [{time.time() - T_START:7.1f}s] next_after({os.path.basename(path)[:22]}) con la ventana en «{title()[:22]}» -> "
          f"{os.path.basename(res)[:22] if res else None}", flush=True)
    return res


sess._next_after = logged_after
orig_replan = sess.replan


def logged_replan():
    print(f"   [{time.time() - T_START:7.1f}s] replan() pedido por la ventana", flush=True)
    return orig_replan()


sess.replan = logged_replan
orig_play = sess.play


def logged_play(path, start_s=0.0, autoplay=True):
    print(f"   [{time.time() - T_START:7.1f}s] session.play({os.path.basename(path)[:22]}, {start_s})", flush=True)
    return orig_play(path, start_s, autoplay)


sess.play = logged_play


def title():
    return os.path.basename((w.current_item_info or {}).get("local_path") or "-")[:34]


def snap(t0):
    s = w._dj_engine_session
    eng = w._dj_engine
    return (f"{time.time() - t0:6.1f}s  ventana={title():34} pos={w.player.position() / 1000:6.1f}  motor={s.current_path and os.path.basename(s.current_path)[:24]!s:24} "
            f"cola={eng.queued_count if eng else '-'} resta={eng.remaining_frames / 44100 if eng else 0:6.1f}s  "
            f"siempre={'SUENA' if real.playbackState() == QMediaPlayer.PlayingState else '-'}  play_next={calls['play_next']}")


problems = []
for n in range(transitions):
    wait(lambda: w.dj_engine_plan() is not None and w.player.last_info.get("state") == "playing", 40)
    plan = w.dj_engine_plan()
    a = title()
    nxt = w.peek_next()
    nxt_title = os.path.basename(nxt["local_path"])[:34] if nxt else "-"
    print(f"\n=== transición {n + 1}: «{a}» -> «{nxt_title}»", flush=True)
    if plan is None:
        print("   sin plan (no hay siguiente o no se pudo preparar)", flush=True)
        problems.append(f"{n + 1}: sin plan")
        break
    print(f"   plan: {plan.kind} empieza {plan.a_start_s:.1f} s, dura {plan.length_s:.1f} s, B desde {plan.b_start_s:.1f} s, "
          f"tempo B x{plan.tempo_ratio_b:.3f}; {plan.reason}", flush=True)
    w.player.setPosition(max(0, int((plan.a_start_s - 6) * 1000)))
    pump(1.0)
    t0 = time.time()
    before = calls["play_next"]
    last_title = a
    end = time.time() + plan.length_s + 25
    changes = []
    both = 0
    while time.time() < end:
        pump(0.1)
        if title() != last_title:
            changes.append((round(time.time() - t0, 1), title()))
            last_title = title()
        if real.playbackState() == QMediaPlayer.PlayingState:
            both += 1
        if int((time.time() - t0) * 10) % 20 == 0:
            print("  ", snap(t0), flush=True)
    print(f"   cambios de canción en la ventana: {changes}", flush=True)
    print(f"   llamadas a play_next: {calls['play_next'] - before}; veces que sonaba también el reproductor de siempre: {both}", flush=True)
    if len(changes) != 1:
        problems.append(f"{n + 1}: {len(changes)} cambios en vez de 1")
    elif changes[0][1] != nxt_title:
        problems.append(f"{n + 1}: pasó a «{changes[0][1]}» y tocaba «{nxt_title}»")
    if both:
        problems.append(f"{n + 1}: sonaba el reproductor de siempre a la vez")
print("\nPROBLEMAS:", problems or "ninguno", flush=True)
w.player.pause()
w.shutdown_playback_options()
