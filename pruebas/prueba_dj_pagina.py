"""Página DJ con la ventana de verdad y canciones de verdad (tonos WAV): empezar la sesión desde la página, saltar,
«esta no», bloquear, volver a barajar, desbloquear, cuenta atrás de la mezcla y fin de la sesión al poner otra lista.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_dj_pagina.py"""
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


root = tempfile.mkdtemp(prefix="descargador_dj_")


def make_wav(rel, freq, seconds=40):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rate = 22050
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * freq * i / rate)))
                               for i in range(int(rate * seconds))))
    return path


paths = [make_wav(os.path.join(sub, f"tono{i}.wav"), 330 + 55 * i)
         for i, sub in enumerate(["Reguetón", "Reguetón", "Drill", "Drill", "Pop", "Pop"])]

from services import dj_service, tempo
from ui.main_window import MainWindow
from ui.pages import Page

dj_service.set_root(root)
w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(1.0)

page = w.page_dj
check("la página DJ está en su sitio dentro de la ventana", w.stacked_widget.indexOf(page) == Page.DJ)

# Abrir la página: lee la carpeta en segundo plano y dice de dónde salen las canciones
w.open_dj_page()
check("se abre la página DJ", w.stacked_widget.currentIndex() == Page.DJ)
check("la carpeta se lee", wait(lambda: w._dj_summary is not None))
check("sin sesión se explica qué hacer", page.empty.isVisible() and not page.session.isVisible())
check("dice cuántas canciones hay", "6 canciones" in page.source.text())

# Empezar
page.btn_start.click()
check("empieza a sonar algo de la carpeta", wait(lambda: w.dj_session_active()))
check("la sesión se ve en la página", page.session.isVisible() and not page.empty.isVisible())
check("el botón pasa a «Empezar de nuevo»", page.btn_start.toolTip() == "Empezar de nuevo")
check("la página cabe en el ancho mínimo del contenido",
      page.minimumSizeHint().width() <= w.CONTENT_MIN_WIDTH - 56)          # 56 = márgenes del contenido
w.set_now_playing_visible(True)
w.resize(w.minimumWidth(), 860)
pump(0.5)
check("estrecha y con el panel abierto: los botones se quedan solo con el icono",
      page.btn_shuffle.text() == "" and page.btn_start.text() == "")
check("y su nombre sigue en la ayuda", "orden" in page.btn_shuffle.toolTip())
w.set_now_playing_visible(False)
w.resize(1360, 860)
pump(0.5)
check(f"ancha: vuelven los textos (página de {page.width()} px)",
      "Barajar" in page.btn_shuffle.text() and "Empezar de nuevo" in page.btn_start.text())
w.set_now_playing_visible(True)
pump(0.3)
check("se ve lo que suena", page.now_title.text() != "")
check("se ve lo que viene", page.next_title.text() != "" and page.upcoming.count() == 5)
check("la cuenta atrás de la mezcla aparece", wait(lambda: page.countdown.text().startswith("La mezcla empieza en"), 10))
check("el fundido está encendido", w._fade_ms > 0)
check("las canciones de la carpeta se analizan solas", wait(lambda: len(w._dj_analysis) >= 6, 120))
w.refresh_dj_page()
check("la página enseña el análisis (estos tonos no tienen pulso)", "sin pulso claro" in page.now_detail.text()
      and "sin pulso claro" in page.upcoming.item(0).text())
check("al terminar el análisis se quita el aviso de progreso", wait(lambda: page.progress.isHidden(), 10))

# Corregir el BPM (los tonos de prueba no tienen pulso: no hay tempo calculado)
import ui.dj_mixin as dj_mixin_module
cur = w.current_item_info["local_path"]
check("al empezar, los botones de BPM están activos", all(b.isEnabled() for b in page.bpm_buttons))
check("sin tempo calculado, ÷2 avisa y no inventa nada", (w.dj_bpm(cur, "half"), dj_service.get_bpm_override(cur))[1] is None)
dj_mixin_module.ask_text = lambda *a, **k: ("95", True)
page.bpm_buttons[2].click()                                            # Escribir BPM…
check("escribir 95 a mano se guarda y se ve «(a mano)»", dj_service.get_bpm_override(cur) == 95.0
      and "95 BPM (a mano)" in page.now_detail.text())
check("el fundido usa ese tempo", tempo.get(cur) == 95.0)
page.bpm_buttons[1].click()                                            # ×2
check("×2: 190", dj_service.get_bpm_override(cur) == 190.0 and "190 BPM (a mano)" in page.now_detail.text()
      and tempo.get(cur) == 190.0)
w.dj_bpm(cur, "double")
check("×2 otra vez se sale de lo razonable (380) y no cambia", dj_service.get_bpm_override(cur) == 190.0)
page.bpm_buttons[0].click()                                            # ÷2
page.bpm_buttons[0].click()
check("÷2 dos veces: 47,5", dj_service.get_bpm_override(cur) == 47.5)
w.dj_bpm(cur, "half")
check("÷2 por debajo de 40 no se acepta", dj_service.get_bpm_override(cur) == 47.5)
dj_mixin_module.ask_text = lambda *a, **k: ("rápido", True)
w.dj_bpm(cur, "set")
check("un texto que no es un número no cambia nada", dj_service.get_bpm_override(cur) == 47.5)
dj_mixin_module.ask_text = lambda *a, **k: ("", False)
w.dj_bpm(cur, "set")
check("cancelar el diálogo no cambia nada", dj_service.get_bpm_override(cur) == 47.5)
page.bpm_buttons[3].click()                                            # Automático
check("«Automático» quita la corrección", dj_service.get_bpm_override(cur) is None
      and "sin pulso claro" in page.now_detail.text() and tempo.get(cur) is None)

# lo mismo desde la lista (botón derecho) con la siguiente canción
nxt_path = w.peek_next()["local_path"]
page.bpm_requested.emit(nxt_path, "set")
check("desde la lista también: la siguiente cambia", dj_service.get_bpm_override(nxt_path) is None)   # el diálogo estaba cancelado
dj_mixin_module.ask_text = lambda *a, **k: ("120", True)
page.bpm_requested.emit(nxt_path, "set")
check("se ve en «A continuación» y en la lista", "120 BPM (a mano)" in page.next_title.text()
      and "120 BPM (a mano)" in page.upcoming.item(0).text())
check("la ruta de cada fila se guarda para el menú", page._upcoming_paths[0] == nxt_path)
dj_service.clear_bpm_override(nxt_path)
w.dj_bpm(nxt_path, "auto")
check("«auto» sin corrección no da error", dj_service.get_bpm_override(nxt_path) is None)

# Detalles de las correcciones
check("el valor que se enseña al editar conserva el decimal", w._bpm_text(92.5) == "92.5" and w._bpm_text(95.0) == "95"
      and w._bpm_text(None) == "")
tempo.remember("sin_decidir.mp3", b"")
w._dj_apply_bpm("sin_decidir.mp3")
check("sin análisis ni corrección, el fundido calcula el tempo él (no se queda en «sin pulso»)", not tempo.known("sin_decidir.mp3"))
dj_service.set_bpm_override(paths[0], 100)
tempo.forget(paths[0])
w._dj_reapply_overrides(paths)
check("al abrir, las correcciones ya valen para el fundido sin esperar al análisis", tempo.get(paths[0]) == 100.0)
dj_service.clear_bpm_override(paths[0])
w._dj_apply_bpm(paths[0])

# Saltar
before = w.current_item_info["local_path"]
page.btn_skip.click()
check("«Saltar» pasa a la siguiente", wait(lambda: w.current_item_info["local_path"] != before))
check("después de saltar, quedan 4", wait(lambda: page.upcoming.count() == 4, 5))

# Esta no
dropped = w.peek_next()
page.btn_drop.click()
check("«Esta no» quita la siguiente de la sesión", w.peek_next() is not dropped and page.upcoming.count() == 3)
check("y ya no está en la lista de la sesión",
      all(t["local_path"] != dropped["local_path"] for t in w._dj_context))

# Bloquear
blocked = w.current_item_info["local_path"]
page.btn_block.click()
check("«Bloquear» pasa a la siguiente", wait(lambda: w.current_item_info["local_path"] != blocked))
check("la bloqueada se guarda", os.path.normcase(os.path.abspath(blocked)) in dj_service.get_blocked())
check("se ofrece desbloquear", not page.btn_unblock.isHidden() and "(1)" in page.btn_unblock.text())
check("la sesión sigue activa", w.dj_session_active())

# Volver a barajar: las mismas canciones, con la que suena delante
pos = w._context_position()
played = [t["local_path"] for t in w._dj_context[:pos + 1]]
order = sorted(t["local_path"] for t in w._dj_context)
page.btn_shuffle.click()
check("volver a barajar no quita ni añade canciones", sorted(t["local_path"] for t in w._dj_context) == order)
check("lo que ya sonó y la que suena se quedan donde estaban",
      [t["local_path"] for t in w._dj_context[:pos + 1]] == played and w._context_position() == pos)

# Volver a empezar: la bloqueada ya no entra
page.btn_start.click()
check("al volver a empezar suena otra vez", wait(lambda: w.dj_session_active()))
check("la bloqueada no entra en la sesión nueva", all(t["local_path"] != blocked for t in w._dj_context)
      and len(w._dj_context) == 5)

# Pausa (primero se espera a que la canción suene de verdad: mientras carga, el botón no pausa)
from PySide6.QtMultimedia import QMediaPlayer
check("la canción nueva ya suena", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState
                                         and w.player.position() > 300, 15))
w.toggle_play_pause()
check("en pausa se dice", wait(lambda: page.countdown.text() == "En pausa", 15))
w.toggle_play_pause()
check("y al seguir vuelve la cuenta atrás", wait(lambda: page.countdown.text() != "En pausa", 15))

# Desbloquear
page.btn_unblock.click()
check("desbloquear vacía la lista de bloqueadas", not dj_service.get_blocked() and page.btn_unblock.isHidden())

# Bloquear también la quita del historial: «anterior» no la vuelve a poner
page.btn_skip.click()
check("se pasa a otra para tener historial", wait(lambda: len(w._history) >= 1))
blocked = w.current_item_info["local_path"]
page.btn_block.click()
check("bloqueada y pasa a la siguiente", wait(lambda: w.current_item_info["local_path"] != blocked))
check("la bloqueada ya no está en el historial", all(e["info"].get("local_path") != blocked for e in w._history))
dj_service.unblock_all()

# Un archivo borrado desde que se leyó la carpeta se salta solo
gone = w.peek_next()["local_path"]
os.replace(gone, gone + ".apartado")
page.btn_skip.click()
check("«Saltar» no se atasca con un archivo borrado", wait(lambda: w.current_item_info["local_path"] != gone
                                                         and w.dj_session_active()))
check("y el borrado sale de la sesión", all(t["local_path"] != gone for t in w._dj_context))
os.replace(gone + ".apartado", gone)

# Algo de fuera (de la cola o «Reproducir» en otra lista) entra en la sesión y la sesión sigue después
outside = make_wav(os.path.join("..", os.path.basename(root) + "_fuera", "fuera.wav"), 880)
w._dj_context[:] = ([t for t in w._dj_context if w._dj_is(t, w.current_item_info)]
                    + [t for t in w._dj_context if not w._dj_is(t, w.current_item_info)])   # que quede alguna detrás
after = w.peek_next()
w._play_entry(w._local_track_info(outside, {}))
check("suena la de fuera", wait(lambda: w.current_item_info["local_path"] == outside))
check("la sesión DJ sigue activa", w.dj_session_active())
check("y después sigue con la sesión donde iba", after is not None and w.peek_next() is not None
      and w.peek_next()["local_path"] == after["local_path"])

# Con el aleatorio del reproductor y una sesión enorme, la ventana no se congela
w.toggle_shuffle()
big = list(w._dj_context) + [{"local_path": os.path.join(root, f"falsa{i}.mp3"), "title": f"falsa{i}", "id": f"f{i}"}
                             for i in range(3000)]
w._dj_context[:] = big
t0 = time.time()
w.dj_queue_changed()
w.upcoming_tracks(30)
check(f"con 3000 canciones y el aleatorio, poner al día la página es rápido ({time.time() - t0:.2f} s)",
      time.time() - t0 < 1.0)
w.toggle_shuffle()

# La última canción: bloquearla para la sesión
w._dj_context[:] = [t for t in w._dj_context if w._dj_is(t, w.current_item_info)]
w.dj_queue_changed()
check("sin siguiente se dice que es la última", wait(lambda: page.countdown.text() == "Es la última canción de la sesión", 5))
page.btn_block.click()
check("bloquear la última para la música", wait(lambda: w.current_item_info is None))
dj_service.unblock_all()
page.btn_start.click()
check("y se puede empezar otra vez", wait(lambda: w.dj_session_active()))

# Poner otra lista termina la sesión DJ
w.set_context([w._local_track_info(paths[0], {})])
w.refresh_dj_page()
check("al poner otra lista la sesión DJ termina", not w.dj_session_active() and page.empty.isVisible())
check("y los botones ya no tocan nada", (w.dj_drop_next(), w.dj_skip(), w.dj_reshuffle()) == (None, None, None))

# Otras páginas siguen funcionando
w.switch_to_page(Page.LIBRARY)
check("se puede ir a la biblioteca", w.stacked_widget.currentIndex() == Page.LIBRARY)
w.switch_to_page(Page.HOME)
check("y volver a Inicio", w.stacked_widget.currentIndex() == Page.HOME)

w.stop_player()
w.close()
pump(0.5)
print("FIN")
