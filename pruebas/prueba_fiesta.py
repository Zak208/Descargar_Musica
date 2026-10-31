"""Modo fiesta (fase 30) con la ventana de verdad, en silencio (volumen a 0) y canciones WAV sintéticas de duraciones distintas:
la pantalla, sus botones y sus teclas, «más / menos energía» (`dj_planner.retarget`), el VIGILANTE con fallos simulados (sesión
del motor parada, posición congelada con el motor y sin él, una canción que no se puede abrir), que una pausa o una canción
cargando NO lo disparan, y los votos del público conectados a la pantalla (en 127.0.0.1). Tarda unos dos minutos: el motor
toca en tiempo real y el vigilante espera 5 s antes de dar por perdida la música.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_fiesta.py"""
import http.client
import os
import random
import sys
import tempfile
import time
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
DURATIONS = [44, 36, 30, 40, 34, 38, 42, 32, 46, 35, 39, 33, 41, 37]       # distintas a propósito
ENERGIES = [0.15, 0.85, 0.35, 0.65, 0.25, 0.95, 0.55, 0.45, 0.75, 0.05, 0.6, 0.3, 0.9, 0.5]


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)
    return cond


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


# ---- 1. retarget sin ventana ----------------------------------------------------------------------------------------------
from services import dj_planner  # noqa: E402

rng = random.Random(5)
pool = [dj_planner.Track(i, rng.choice([92, 95, 126, 128]), rng.choice(["8A", "9A", "3B"]), 0.8, rng.random(), "urbano",
                         f"artista{i % 7}") for i in range(40)]
current = dj_planner.Track("ahora", 126, "8A", 0.8, 0.45, "urbano", "otro")
rank = dj_planner.energy_ranker([current.energy] + [t.energy for t in pool])


def mean_rank(tracks, n=4):
    return sum(rank(t.energy) for t in tracks[:n]) / n


def cuts(tracks, n=12):
    seq = [current] + list(tracks[:n])
    return sum(not dj_planner.mixable(a.bpm, b.bpm) for a, b in zip(seq, seq[1:]))


up = dj_planner.retarget(pool, current, 1, random.Random(1))
down = dj_planner.retarget(pool, current, -1, random.Random(1))
check(f"retarget: «más energía» sube lo que viene ({mean_rank(up):.2f}) y «menos» lo baja ({mean_rank(down):.2f}) respecto a la que "
      f"suena ({rank(current.energy):.2f})", mean_rank(up) > rank(current.energy) > mean_rank(down))
check(f"retarget: sin cortes por tempo nuevos en las 12 primeras (más {cuts(up)}, menos {cuts(down)}, antes {cuts(pool)})",
      cuts(up) <= 1 and cuts(down) <= 1)
check("retarget: no pierde ni repite canciones", sorted(t.ref for t in up) == sorted(t.ref for t in pool) == sorted(t.ref for t in down))
check("retarget: lo que no entra en las 12 primeras sigue en su orden de antes",
      [t.ref for t in up[12:]] == [t.ref for t in pool if t.ref not in {u.ref for u in up[:12]}])
check("retarget: dirección 0 o lista vacía no cambian nada", [t.ref for t in dj_planner.retarget(pool, current, 0)] == [t.ref for t in pool]
      and dj_planner.retarget([], current, 1) == [])
unknown = [t._replace(energy=None) for t in pool[:5]] + pool[5:]
check("retarget: las de energía desconocida van detrás de las conocidas",
      all(t.energy is not None for t in dj_planner.retarget(unknown, current, 1, random.Random(2))[:8]))

# ---- 2. la ventana ----------------------------------------------------------------------------------------------------------
root = tempfile.mkdtemp(prefix="descargador_fiesta_")


def make_wav(name, freq, seconds, bpm=120):
    rate = 22050
    t = np.arange(rate * seconds) / rate
    beat = (t % (60.0 / bpm))
    kick = 0.45 * np.exp(-beat * 40) * np.sin(2 * np.pi * 60 * beat)
    tone = 0.1 * np.sin(2 * np.pi * freq * t)
    data = (np.clip(kick + tone, -1, 1) * 32000).astype("<i2")
    path = os.path.join(root, name)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(data.tobytes())
    return path


paths = [make_wav(f"fiesta{i}.wav", 330 + 45 * i, d) for i, d in enumerate(DURATIONS)]

from services import crowd_server, dj_service, transition_votes  # noqa: E402
from ui import party_mixin  # noqa: E402
from ui.engine_player import EnginePlayer  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.pages import Page  # noqa: E402

dj_service.set_root(root)
w = MainWindow()
w.resize(1360, 860)
w.show()
pump(1.0)
w.volume_slider.setValue(0)
pump(0.2)
page = w.page_party
reason = w.dj_engine_unavailable_reason()
engine_ok = not reason
print(f"      motor propio: {'disponible' if engine_ok else 'NO disponible (' + reason + '): se prueban los escalones sin él'}")

check("la página de la fiesta está en su sitio", w.stacked_widget.indexOf(page) == Page.PARTY)
w.open_party_page()
check("se abre la pantalla de la fiesta y el vigilante empieza", w.stacked_widget.currentWidget() is page and w.party_active()
      and w._party_timer.isActive())
check("sin sesión ofrece empezarla", page.empty.isVisible() and not page.session.isVisible())
check(f"la página cabe en el ancho mínimo del contenido ({page.minimumSizeHint().width()} px)",
      page.minimumSizeHint().width() <= w.CONTENT_MIN_WIDTH - 56)
check("los votos del público empiezan apagados", not w._party_crowd_running() and not page.btn_crowd.isChecked())
check("la carpeta se lee", wait(lambda: w._dj_summary is not None))
check("el análisis en segundo plano termina", wait(lambda: w._dj_an_worker is None, 180))
scanned = dj_service.tracks_for(w._dj_summary, w._dj_source())
for p in scanned:                     # análisis fijado a mano: tempo y rejilla iguales, energías distintas
    i = next(k for k, q in enumerate(paths) if os.path.basename(q) == os.path.basename(p))
    w._dj_analysis[p] = {"bpm": 120.0, "intro_ms": 2000, "outro_ms": 10000, "duration_ms": DURATIONS[i] * 1000,
                         "energy": ENERGIES[i], "loudness_db": -10.0, "tone": "8A", "tone_conf": 0.9,
                         "beat_first_s": 0.0, "beat_bpm": 120.0, "beat_downbeat": 0, "beat_conf": 0.9}

page.btn_start.click()
check("«Empezar la fiesta» empieza la sesión DJ", wait(lambda: w.dj_session_active(), 15))
check("y se vuelve a la pantalla de la fiesta", wait(lambda: w.stacked_widget.currentWidget() is page, 5))
if engine_ok:
    check("con el motor propio", w.dj_engine_on() and isinstance(w.player, EnginePlayer))
check("suena", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState and w.player.position() > 500, 15))
pump(1.2)
check("se ve lo que suena, lo que viene y la energía", page.now_title.text() != "" and page.next_title.text() != ""
      and page.energy.text().startswith("Energía "))
check("indicador «Todo bien»", page.status.text() == "Todo bien")
check("las teclas van a la pantalla (tiene el foco)", page.hasFocus() or page.isAncestorOf(QApplication.focusWidget()))


def failures():
    return [e for e in w.party_events() if e.startswith("Fallo")]


# Siguiente (botón y tecla)
cur = w.current_item_info["local_path"]
page.btn_next.click()
check("«Siguiente» pasa a la siguiente", wait(lambda: w.current_item_info["local_path"] != cur, 10))
check("y sigue sonando", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState, 10))
pump(1.5)
cur = w.current_item_info["local_path"]
QTest.keyClick(page, Qt.Key_Right)
check("la tecla → hace lo mismo", wait(lambda: w.current_item_info["local_path"] != cur, 10))
check("sigue el motor" if engine_ok else "sigue sonando", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState
                                                                and (w.dj_engine_on() or not engine_ok), 10))

# Pausa (tecla espacio y botón): el vigilante no la confunde con un fallo
pump(2.0)
before = len(failures())
QTest.keyClick(page, Qt.Key_Space)
check("espacio = pausa", wait(lambda: w.player.playbackState() == QMediaPlayer.PausedState, 5))
check("la pantalla lo dice y el botón pasa a «Seguir»", wait(lambda: "PAUSA" in page.play_state.text() and "Seguir" in page.btn_pause.text(), 3))
pump(party_mixin.STALL_S + 3)
check(f"{party_mixin.STALL_S + 3:.0f} s en pausa: el vigilante NO lo toma por un fallo", len(failures()) == before
      and w.player.playbackState() == QMediaPlayer.PausedState and page.status.text() == "Todo bien")
page.btn_pause.click()
check("el botón «Seguir» reanuda", wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState, 5))
pump(2.0)
check("y al reanudar tampoco salta el vigilante", len(failures()) == before)

# Una canción cargando no es un fallo (se simula: «cargando» y la posición quieta)
real_loading = w._party_loading
frozen_at = w.player.position()
w._party_loading = lambda: True
w.player.position = lambda: frozen_at
pump(party_mixin.STALL_S + 2)
check("cargando con la posición quieta: el vigilante espera (no es un fallo)", len(failures()) == before)
w._party_loading = real_loading
del w.player.position
pump(1.5)


# Más / menos energía
def energy_of(info):
    return w._dj_analysis.get(info["local_path"], {}).get("energy")


def press(key, n=3):
    """Pulsa la tecla y devuelve (energía media de las n que se reordenaron, energía de referencia, todas las que quedan)."""
    locked = w._party_next_locked()                  # si la siguiente ya está fija, se reordena lo de después
    QTest.keyClick(page, key)
    ups = w.upcoming_tracks(30)
    first = 1 if locked else 0
    ref = energy_of(ups[0]) if locked else energy_of(w.current_item_info)
    vals = [energy_of(t) for t in ups[first:first + n]]
    return sum(vals) / len(vals), ref, [energy_of(t) for t in ups[first:]]


low, ref_low, rest = press(Qt.Key_Down)
order_low = [t["local_path"] for t in w.upcoming_tracks(10)]
high, ref_high, _rest = press(Qt.Key_Up)
order_high = [t["local_path"] for t in w.upcoming_tracks(10)]
extreme = ref_high <= min(rest) or ref_high >= max(rest)     # la de referencia ya es la más suave o la más fuerte
check(f"«más energía» (↑) cambia lo que viene y sube la energía (menos: {low:.2f}, más: {high:.2f}, referencia {ref_high:.2f})",
      order_low != order_high and (high > low or (extreme and high >= low)))
check("queda apuntado en Eventos", any(e.startswith("Más energía") for e in w.party_events())
      and any(e.startswith("Menos energía") for e in w.party_events()))
check("la pantalla enseña hacia dónde va", "subiendo" in page.energy.text())
page.btn_down.click()
check("el botón «Menos energía» también", w.party_events()[-1].startswith("Menos energía"))
if engine_ok:
    locked = w._party_next_locked()
    check("el motor prepara la mezcla hacia la siguiente que toca ahora (o la deja si ya no da tiempo)",
          locked or wait(lambda: os.path.normcase(w.player.last_info.get("next_path") or "") ==
                         os.path.normcase((w.peek_next() or {}).get("local_path") or "-"), 10))
check("sin fallos hasta aquí", len(failures()) == before)


# ---- 3. el vigilante: fallos simulados ---------------------------------------------------------------------------------------
def playing_and_moving(timeout=15):
    if not wait(lambda: w.player.playbackState() == QMediaPlayer.PlayingState, timeout):
        return False
    p0 = w.player.position()
    return wait(lambda: w.player.position() > p0 + 600, timeout)


if engine_ok:
    cur = w.current_item_info["local_path"]
    t0 = time.time()
    w._dj_engine_session.stop(wait=False)            # la sesión del motor se para sola (sin que la ventana lo sepa)
    check("sesión del motor parada: el vigilante lo ve y aplica el escalón 1", wait(lambda: w._party_step == 1, 15))
    print(f"      detectado y recuperado en {time.time() - t0:.1f} s; eventos: {w.party_events()[-2:]}")
    check("escalón 1: sigue el motor, en la siguiente canción, y suena", w.dj_engine_on()
          and wait(lambda: w.current_item_info["local_path"] != cur, 5) and playing_and_moving())
    check("el indicador dice «Recuperándose»", page.status.text() == "Recuperándose")
    pump(party_mixin.GRACE_S + 1)
    cur = w.current_item_info["local_path"]
    frozen = w.player.position()
    w.player.position = lambda: frozen               # el motor sigue «reproduciendo» pero la música no avanza
    t0 = time.time()
    check("vuelve a fallar en menos de 2 minutos (posición congelada): escalón 2", wait(lambda: w._party_step == 2, 20))
    print(f"      detectado en {time.time() - t0:.1f} s")
    check("escalón 2: motor apagado y sigue el reproductor de siempre con la siguiente", not w.dj_engine_on()
          and not isinstance(w.player, EnginePlayer) and w.current_item_info["local_path"] != cur)
    check("y suena (la posición avanza)", playing_and_moving())
    pump(party_mixin.GRACE_S + 1)

# Sin motor: la posición del reproductor de siempre se congela
deck = w.player
cur = w.current_item_info["local_path"]
frozen = deck.position()
deck.position = lambda: frozen
expected = 3
check(f"sin motor, posición congelada: escalón {expected} (saltar a la siguiente)", wait(lambda: w._party_step == expected, 20))
del deck.position
check("salta a la siguiente y suena", w.current_item_info["local_path"] != cur and playing_and_moving())
pump(party_mixin.GRACE_S + 1)

# La siguiente no se puede abrir: escalón 4
nxt = w.peek_next()["local_path"]
with open(nxt, "wb") as f:
    f.write(os.urandom(4096))                        # un archivo roto con extensión .wav
cur = w.current_item_info["local_path"]
frozen = w.player.position()
w.player.position = lambda: frozen
deck = w.player
check("otro fallo: salta a la siguiente, que está rota", wait(lambda: w._party_step == 3, 20))
del deck.position
check("la rota no carga: escalón 4, la siguiente", wait(lambda: w._party_step == 4, 20))
check("y acaba sonando una canción que no es la rota", wait(lambda: w.current_item_info["local_path"] not in (nxt, cur), 10)
      and playing_and_moving())
print("      eventos del vigilante:", [e for e in w.party_events() if e.startswith(("Fallo", "Escalón"))])
check("ninguna excepción salió del vigilante", not any("Fallo interno" in e or "No se pudo aplicar" in e for e in w.party_events()))

# Pasados 2 minutos sin fallos se vuelve a empezar por abajo; y una pausa larga sigue sin ser un fallo
w._party_clock = lambda: time.monotonic() + 300
before = len(failures())
step = w._party_step
w.party_pause()
pump(party_mixin.STALL_S + 2)
check("pausa larga tras los fallos: tampoco dispara el vigilante", len(failures()) == before and w._party_step == step)
w.party_pause()
check("y vuelve a sonar", playing_and_moving())
check("pasado el tiempo de recuperación, «Todo bien»", wait(lambda: page.status.text() == "Todo bien", 5))

if engine_ok:                                        # otra sesión con el motor: la salida de audio se cierra
    w.start_dj_session()
    check("otra sesión con el motor propio", wait(lambda: w.dj_session_active() and w.dj_engine_on(), 10) and playing_and_moving())
    w.open_party_page()
    pump(party_mixin.GRACE_S + 1)
    w._party_clock = lambda: time.monotonic() + 900   # el último fallo queda lejos: se empieza por el escalón 1
    before = len(failures())
    w._dj_engine.stop(fade=False)                    # como si PortAudio cerrara el flujo (sin aviso)
    check("salida de audio del motor cerrada: escalón 1, el flujo se vuelve a abrir y suena",
          wait(lambda: len(failures()) > before and w._party_step == 1, 10) and w.dj_engine_on()
          and w._dj_engine.stream_active and playing_and_moving())
    pump(party_mixin.GRACE_S + 1)
    w.party_pause()
    check("en pausa", wait(lambda: w.player.playbackState() == QMediaPlayer.PausedState, 5))
    before = len(failures())
    w._dj_engine_lost("simulado")                    # el aviso de flujo perdido llega con la música en pausa
    pump(party_mixin.STALL_S + 2)
    check("flujo perdido en pausa: no se quita la pausa (reproductor de siempre, en pausa) ni cuenta como fallo",
          not w.dj_engine_on() and w.player.playbackState() == QMediaPlayer.PausedState and len(failures()) == before)
    w.party_pause()
    check("y al seguir, suena", playing_and_moving())

# ---- 4. votos del público en la pantalla ---------------------------------------------------------------------------------
crowd_server.local_ip = lambda: "127.0.0.1"
page.btn_crowd.click()
check("el interruptor enciende los votos del público", w._party_crowd_running() and page.crowd_box.isVisible())
srv = w._party_crowd
check("la pantalla enseña el enlace con el token y el aviso de que no hay cifrado",
      srv.token in page.crowd_url.text() and "cifrado" in page.crowd_warn.text() and "cortafuegos" in page.crowd_warn.text())
con = http.client.HTTPConnection(srv.host, srv.port, timeout=5)
con.request("GET", f"/{srv.token}/")
check("el móvil abre la página", con.getresponse().status == 200)
con.close()
srv.box.min_votes = 1                                # un solo invitado (127.0.0.1) basta para la prueba
w._party_track_t = float("-inf")                     # la canción ya no «acaba de empezar»
cur = w.current_item_info["local_path"]
con = http.client.HTTPConnection(srv.host, srv.port, timeout=5)
con.request("POST", f"/{srv.token}/vote", body="v=skip", headers={"Content-Type": "application/x-www-form-urlencoded"})
check("votar «Pasar» = 200", con.getresponse().status == 200)
con.close()
check("el umbral de «Pasar» salta a la siguiente, como el botón", wait(lambda: w.current_item_info["local_path"] != cur, 10))
check("queda en Eventos que lo pidió el público", any("público" in e for e in w.party_events()))
pump(1.2)
check("el conteo en vivo se ve en la pantalla", "conectados" in page.crowd_counts.text())
w._party_track_t = w._party_clock()                  # un 👍 justo después de una mezcla
w._party_on_crowd(crowd_server.LIKE, srv.counts())
crowd_rows = [v for v in transition_votes.votes() if str(v.get("session", "")).startswith("publico-")]
if w.dj_vote_target() is not None:
    check(f"el 👍 del público tras una mezcla se guarda como voto de esa mezcla ({len(crowd_rows)})", len(crowd_rows) >= 1)
check("los votos del público no se mezclan con los tuyos: sesión «publico-…», «público» en la nota y origen permitido",
      all(v.get("source") in transition_votes.SOURCES and "público" in (v.get("note") or "") for v in crowd_rows))
port = srv.port
QTest.keyClick(page, Qt.Key_V)
check("la tecla V los apaga y el puerto se cierra", not w._party_crowd_running() and not srv.running)
page.btn_crowd.click()
check("se pueden volver a encender", w._party_crowd_running())
srv2 = w._party_crowd

# Salir de la fiesta (Esc)
QTest.keyClick(page, Qt.Key_Escape)
check("Esc sale de la fiesta: vigilante parado y vuelve la página DJ", not w.party_active() and not w._party_timer.isActive()
      and w.stacked_widget.currentIndex() == Page.DJ)
check("al salir de la fiesta los votos del público se apagan solos", not srv2.running and not w._party_crowd_running())
check("la música sigue", w.player.playbackState() == QMediaPlayer.PlayingState)
w.player.pause()
w.party_shutdown()
w.shutdown_playback_options()
print("FIN")
