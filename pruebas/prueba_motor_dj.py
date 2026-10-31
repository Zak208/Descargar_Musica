"""Sesión del DJ sobre el motor de audio (dj_engine.EngineSession): arranque, transición colocada a la muestra, paso a la
siguiente, posición, corte, saltos, seek, replan, pausa, canciones que faltan, fin, stop, memoria y errores. Sin sonido: el
motor no abre el flujo (se avanza con `pull`) y las canciones son sintéticas (cargador falso). Al final, si hay FFmpeg, un
caso con el cargador real y dos mp3 generados aquí, que mide lo que tarda en sonar y en tener la transición lista.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_dj.py"""
import gc
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import weakref

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import dj_dsp, dj_engine
from services.audio_engine import MixEngine
from services.deck_gain import deck_gain
from services.dj_engine import EngineSession
from services.mix_types import KIND_BLEND, KIND_CUT, SAMPLE_RATE, BeatGrid

SR = SAMPLE_RATE
TICK = 2205                     # 50 ms de audio entre tick y tick
FADE = round(SR * 0.015)        # fundido del motor
CLICK = 0.05                    # salto máximo admitido entre dos muestras seguidas (la senoide más rápida salta ~0,013)
logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)      # los fallos de las pruebas son a propósito


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


class FakeLoader:
    """Canciones sintéticas: senoide (frecuencia propia de cada una) con un bombo suave de 60 Hz en cada golpe. Con
    tempo_ratio distinto de 1 se remuestrea (cambia el tono, da igual aquí): el instante t del original cae en (t - start) / ratio."""

    def __init__(self, songs):
        self.songs = songs              # ruta -> {"dur", "freq", "bpm"}
        self.calls = []
        self.refs = []                  # weakrefs de las canciones enteras entregadas
        self.raise_on = set()
        self.delay = {}

    def full(self, path):
        s = self.songs[path]
        t = np.arange(int(s["dur"] * SR)) / SR
        ph = t % (60.0 / s["bpm"])
        env = np.where(ph < 0.15, np.sin(np.pi * ph / 0.15) ** 2, 0.0)
        v = (0.3 * np.sin(2 * np.pi * s["freq"] * t) + 0.2 * env * np.sin(2 * np.pi * 60.0 * t)).astype(np.float32)
        return np.stack([v, v], axis=1)

    def __call__(self, path, tempo_ratio=1.0, start_s=0.0, duration_s=None):
        self.calls.append((path, tempo_ratio, start_s, duration_s, threading.current_thread().name))
        if path in self.raise_on:
            raise RuntimeError("archivo roto a propósito")
        if path in self.delay:
            time.sleep(self.delay[path])
        if path not in self.songs:
            return None
        full = self.full(path)
        if tempo_ratio == 1.0 and not start_s and duration_s is None:
            self.refs.append(weakref.ref(full))
            return full
        s0 = start_s * SR
        m = round(duration_s / tempo_ratio * SR)
        idx = s0 + np.arange(m) * tempo_ratio
        out = np.empty((m, 2), np.float32)
        for ch in range(2):
            out[:, ch] = np.interp(idx, np.arange(len(full)), full[:, ch])
        return out

    def alive(self):
        return sum(r() is not None for r in self.refs)


def info_of(songs, path):
    s = songs.get(path)
    if s is None:
        return {}
    return {"duration_ms": s["dur"] * 1000, "intro_ms": 8000, "outro_ms": 16000, "bpm": s["bpm"],
            "beatgrid": BeatGrid(0.0, s["bpm"])}


LUFS = {"A": -17.0, "B": -11.0, "C": -14.0}


class Rig:
    """Motor sin dispositivo + sesión + cargador falso; saca audio a bloques de 1024 y llama a tick() cada 50 ms de audio."""

    def __init__(self, songs, order, **kw):
        self.songs, self.order = songs, dict(order)
        self.fake = FakeLoader(songs)
        self.eng = MixEngine()
        self.asked = []                 # (ruta pedida, ruta actual de la sesión, número de tick, hilo)
        kw.setdefault("typed", False)  # la mezcla clásica, comparada muestra a muestra; los tipos: prueba_motor_tipos.py
        self.sess = EngineSession(self.eng, lambda p: info_of(songs, p), self._next_after, loader=self.fake,
                                  lufs_stored=lambda p: LUFS.get(p), lufs_measure=lambda p: LUFS.get(p), **kw)
        self.out, self.frames, self.since, self.ticks = [], 0, 0, 0
        self.states, self.max_alive = [], 0

    def _next_after(self, path):
        self.asked.append((path, self.sess.current_path, self.ticks, threading.current_thread()))
        return self.order.get(path)

    def tick(self):
        self.ticks += 1
        st = self.sess.tick()
        st["_frames"], st["_tick"] = self.frames, self.ticks
        self.states.append(st)
        self.max_alive = max(self.max_alive, self.fake.alive())
        return st

    def pull(self, k, block=1024):
        while k > 0:
            m = min(block, k)
            self.out.append(self.eng.pull(m))
            self.frames += m
            self.since += m
            k -= m
            if self.since >= TICK:
                self.since = 0
                self.tick()

    def pull_to(self, frame):
        self.pull(max(0, frame - self.frames))

    def wait(self, cond, timeout=15.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            st = self.tick()
            if cond(st):
                return st
            time.sleep(0.005)
        return None

    def audio(self):
        return np.concatenate(self.out) if self.out else np.zeros((0, 2), np.float32)

    def first(self, key):
        """Primer estado con `key` verdadero."""
        return next((s for s in self.states if s.get(key)), None)

    def gained(self, path):
        x = self.fake.full(path)
        x *= deck_gain(LUFS.get(path), max(float(x.max()), -float(x.min())))
        return x


def max_jump(x):
    return float(np.abs(np.diff(x[:, 0])).max()) if len(x) > 1 else 0.0


SONGS = {"A": {"dur": 70, "freq": 220.0, "bpm": 120.0}, "B": {"dur": 70, "freq": 330.0, "bpm": 124.0},
         "C": {"dur": 50, "freq": 440.0, "bpm": 120.0}}

# ---- 1. arranque, mezcla con cambio de tempo, paso a la siguiente, posición, memoria, fin -----------------------------------
r = Rig(SONGS, {"A": "B", "B": "C", "C": None})
s = r.sess
s.play("A")
st = r.tick()
check("tras play(): estado «loading» con la ruta y sin duración todavía", st["state"] == "loading" and st["path"] == "A"
      and s.current_path == "A" and not s.has_audio_ready())
st = r.wait(lambda x: x["state"] == "playing")
check("A suena en cuanto está decodificada (sin esperar a B)", st is not None and s.has_audio_ready()
      and abs(st["duration_s"] - 70.0) < 1e-9 and st["position_s"] == 0.0)
check("la carga se hace en el hilo de trabajo", r.fake.calls[0][4] == "dj-engine")
r.pull(5 * SR)
st = r.wait(lambda x: x["plan"] is not None)
plan = st["plan"]
check(f"la transición llega con A ya sonando: mezcla con tempo de B {plan.tempo_ratio_b:.4f} ({plan.reason[:60]}...)",
      plan.kind == KIND_BLEND and abs(plan.tempo_ratio_b - 120 / 124) < 1e-5 and st["next_path"] == "B")
check("next_after se pidió en un tick, en el hilo de la interfaz y con la ruta actual",
      r.asked[0][:2] == ("A", "A") and r.asked[0][3] is threading.current_thread())
stretch = [c for c in r.fake.calls if c[0] == "B" and c[1] != 1.0]
check("el tramo de B se pide estirado, desde b_start y con duration = (length + empalme) * ratio",
      len(stretch) == 1 and abs(stretch[0][2] - plan.b_start_s) < 1e-9
      and abs(stretch[0][3] - (plan.length_s + dj_engine.JOIN_S) * plan.tempo_ratio_b) < 1e-9)
a_mix, n = round(plan.a_start_s * SR), round(plan.length_s * SR)
JOIN = round((plan.length_s + dj_engine.JOIN_S) * SR) - n         # muestras del empalme (el tramo estirado sigue un poco más)
half = n // 2
ratio = plan.tempo_ratio_b
b_body = round((plan.b_start_s + plan.length_s * ratio) * SR)
r.pull_to(a_mix - 3000)
st = r.tick()
check("posición en A exacta (tiempo original, latencia 0 sin flujo)", abs(st["position_s"] - (a_mix - 3000) / SR) < 1e-9)
r.pull_to(a_mix + half - 5000)
st = r.tick()
check("en la primera mitad de la mezcla: sigue siendo A y la posición va en tiempo de A (sin estirar)",
      st["path"] == "A" and abs(st["position_s"] - (a_mix + half - 5000) / SR) < 1e-9 and r.first("advanced") is None)
r.pull_to(a_mix + half + 7000)
adv = r.first("advanced")
check("advanced = B en el primer tick tras empezar la segunda mitad",
      adv is not None and adv["advanced"] == "B" and a_mix + half <= adv["_frames"] < a_mix + half + TICK + 1024)
st = r.tick()
check("en la segunda mitad: posición en tiempo de B, b_start + (mitad + tocado) * ratio",
      st["path"] == "B" and abs(st["position_s"] - (plan.b_start_s + (half + 7000) * ratio / SR)) < 1e-9
      and abs(st["duration_s"] - 70.0) < 1e-9)
check("adopt(B) es True una vez (la sesión avanzó sola) y luego False", s.adopt("B") and not s.adopt("B") and not s.adopt("A"))
r.pull_to(a_mix + n + 3 * SR)
st = r.tick()
check("en el cuerpo de B: posición desde b_start + length * ratio, en su tiempo original",
      abs(st["position_s"] - (b_body + 3 * SR) / SR) < 1e-9)
out = r.audio()
A, B = r.gained("A"), r.gained("B")
gb = deck_gain(LUFS["B"], max(float(r.fake.full("B").max()), -float(r.fake.full("B").min())))
piece = r.fake("B", tempo_ratio=ratio, start_s=plan.b_start_s, duration_s=plan.length_s * ratio)
piece *= gb
x = dj_dsp.render_transition(A[a_mix:a_mix + n], piece, plan)
check("A suena idéntica (con su ganancia de volumen igualado) hasta la muestra exacta del punto de mezcla",
      np.array_equal(out[FADE:a_mix], A[FADE:a_mix]))
check("la mezcla empieza en esa muestra y sale entera (las dos mitades seguidas)",
      np.allclose(out[a_mix:a_mix + n], x, atol=1e-6))
check("después del empalme, el cuerpo de B (con su ganancia) desde b_start + length * ratio (+ lo que duró el empalme)",
      np.array_equal(out[a_mix + n + JOIN:a_mix + n + 3 * SR], B[b_body + JOIN:b_body + 3 * SR]))
seam = np.abs(np.diff(out[a_mix + n - 300:a_mix + n + JOIN + 300, 0]))
normal = np.abs(np.diff(out[a_mix + n + JOIN + 1000:a_mix + n + SR, 0]))
check(f"sin clic en el empalme del tramo estirado con el cuerpo de B (salto {seam.max():.4f}, normal {normal.max():.4f})",
      JOIN > 100 and seam.max() < 2.5 * normal.max() + 1e-4)
check("la ganancia se aplicó: A se subió +3 dB y B se bajó -3 dB",
      abs(float(np.abs(out[SR:2 * SR]).max()) / float(np.abs(r.fake.full("A")[SR:2 * SR]).max()) - 10 ** (3 / 20)) < 1e-3
      and abs(gb - 10 ** (-3 / 20)) < 1e-9)
adv_tick = adv["_tick"]
st = r.wait(lambda x: x["plan"] is not None and x["next_path"] == "C")
asked_b = [a for a in r.asked if a[0] == "B"]
check("next_after(B) se pide en un tick posterior al de advanced, con B ya como actual",
      len(asked_b) == 1 and asked_b[0][1] == "B" and asked_b[0][2] > adv_tick)
r.pull(120 * SR)
ends = [x for x in r.states if x["ended"]]
check("tras C (sin siguiente) llega ended una sola vez y el estado queda «stopped»",
      len(ends) == 1 and r.states[-1]["state"] == "stopped" and r.states[-1]["path"] is None)
check("advanced: B y luego C, nada más", [x["advanced"] for x in r.states if x["advanced"]] == ["B", "C"])
check("next_after siempre con la canción actual", all(a[0] == a[1] for a in r.asked) and [a[0] for a in r.asked] == ["A", "B", "C"])
check(f"memoria: nunca más de 2 canciones enteras vivas (máximo visto {r.max_alive})", r.max_alive <= 2)
gc.collect()
check("al acabar, la sesión ya no retiene ninguna canción", r.fake.alive() == 0)
audio = r.audio()
check(f"sin clics en toda la sesión A, B, C (salto máximo {max_jump(audio):.4f})", max_jump(audio) < CLICK)
check("la latencia de salida se resta y la posición nunca es negativa", all(x["position_s"] >= 0 for x in r.states))
s.stop()

# ---- 2. corte limpio por tempos lejanos ------------------------------------------------------------------------------------
songs2 = {"A": {"dur": 60, "freq": 220.0, "bpm": 120.0}, "B": {"dur": 40, "freq": 330.0, "bpm": 150.0}}
r = Rig(songs2, {"A": "B"})
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
st = r.wait(lambda x: x["plan"] is not None)
plan = st["plan"]
check(f"tempos lejanos: corte limpio ({plan.reason})", plan.kind == KIND_CUT and "lejos" in plan.reason)
check("en el corte no se estira nada", all(c[1] == 1.0 for c in r.fake.calls))
c = round(plan.a_start_s * SR)
bs = round(plan.b_start_s * SR)
piece = int(dj_engine.CUT_PIECE_S * SR)
r.pull_to(c + 2 * SR)
out = r.audio()
A, B = r.gained("A"), r.gained("B")
xc = dj_dsp.render_transition(A[c - piece:c], B[bs:bs + piece], plan)
check("A exacta hasta el corte, luego las piezas con rampa y luego B desde su entrada",
      np.array_equal(out[FADE:c - piece], A[FADE:c - piece]) and np.allclose(out[c - piece:c + piece], xc, atol=1e-7)
      and np.array_equal(out[c + piece:c + 2 * SR], B[bs + piece:bs + 2 * SR]))
check("el corte cae en un comienzo de compás de A", abs((plan.a_start_s / 2.0) - round(plan.a_start_s / 2.0)) < 1e-6)
adv = r.first("advanced")
check("advanced sale cuando empieza a sonar B (primer tick tras la muestra del corte)",
      adv is not None and c <= adv["_frames"] < c + TICK + 1024)
check(f"sin clic en el corte (salto máximo {max_jump(out[c - 3000:c + 3000]):.4f})", max_jump(out[c - 3000:c + 3000]) < CLICK)
r.sess.stop()

# ---- 3. salto con play() a otra canción ------------------------------------------------------------------------------------
r = Rig(SONGS, {"A": "B", "C": None})
r.sess.play("A")
r.wait(lambda x: x["plan"] is not None)
r.pull(10 * SR)
mark = r.frames
r.sess.play("C")
st = r.tick()
check("play() de otra: carga sin cortar todavía (estado loading, ruta nueva)", st["state"] == "loading" and st["path"] == "C")
r.wait(lambda x: x["state"] == "playing")
r.pull(3 * SR)
out = r.audio()
check(f"el salto se funde con el motor, sin clic (salto máximo {max_jump(out[mark - 2000:]):.4f})", max_jump(out[mark - 2000:]) < CLICK)
st = r.tick()
check("suena C desde 0 y no hubo advanced (lo pidió la interfaz)", st["path"] == "C" and not any(x["advanced"] for x in r.states)
      and 2.5 < st["position_s"] < 3.5)
gc.collect()
check(f"tras el salto solo queda C en memoria ({r.fake.alive()} canciones vivas)", r.fake.alive() == 1)
check("play() de la misma canción: reinicia desde start_s sin volver a decodificarla",
      (lambda k: (r.sess.play("C", start_s=20.0), r.tick())[1]["position_s"] == 20.0
       and len([q for q in r.fake.calls if q[0] == "C"]) == k)(len([q for q in r.fake.calls if q[0] == "C"])))
r.sess.stop()

# ---- 4. seek ----------------------------------------------------------------------------------------------------------------
r = Rig(SONGS, {"A": "B", "B": None})
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
st = r.wait(lambda x: x["plan"] is not None)
plan = st["plan"]
r.pull(2 * SR)
r.sess.seek(10.0)
st = r.tick()
check("seek(10): la posición pasa a 10 s exactos", st["position_s"] == 10.0 and st["path"] == "A")
mark = r.frames
r.pull(SR)
out = r.audio()
A = r.gained("A")
check("y suena A desde 10 s (tras el fundido de 15 ms del motor), sin clic",
      np.array_equal(out[mark + FADE:mark + SR], A[10 * SR + FADE:11 * SR]) and max_jump(out[mark - 500:]) < CLICK)
a_mix = round(plan.a_start_s * SR)
r.sess.seek(a_mix / SR - 2.0)
r.pull(2 * SR + 1000)
st = r.tick()
check("seek justo antes de la mezcla: la mezcla vuelve a estar en su sitio (sigue sonando A en su primera mitad)",
      st["path"] == "A" and abs(st["position_s"] - (a_mix + 1000) / SR) < 1e-9)
r.sess.seek(plan.a_start_s + 1.0)
st = r.tick()
b_body = round((plan.b_start_s + plan.length_s * plan.tempo_ratio_b) * SR)
JOIN = round((plan.length_s + dj_engine.JOIN_S) * SR) - n
b_body += JOIN                                           # el cuerpo empieza tras el empalme
check("seek dentro de la mezcla: salta al inicio del cuerpo de B, con advanced = B",
      st["path"] == "B" and st["advanced"] == "B" and abs(st["position_s"] - b_body / SR) < 1e-9)
mark = r.frames
r.pull(SR)
B = r.gained("B")
check("y suena el cuerpo de B desde ahí", np.array_equal(r.audio()[mark + FADE:mark + SR], B[b_body + FADE:b_body + SR]))
r.sess.seek(5.0)
st = r.tick()
check("seek dentro de B (ya actual)", st["path"] == "B" and st["position_s"] == 5.0)
r.sess.stop()

# ---- 5. replan ----------------------------------------------------------------------------------------------------------------
r = Rig(SONGS, {"A": "B", "B": None, "C": None})
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
r.wait(lambda x: x["plan"] is not None)
loads = len(r.fake.calls)
r.sess.replan()
r.tick()
r.tick()
check("replan con la misma siguiente: no se rehace nada", len(r.fake.calls) == loads and r.tick()["next_path"] == "B")
r.sess.replan(force=True)
st = r.wait(lambda x: len(r.fake.calls) > loads and x["plan"] is not None)
check("replan(force=True) con la misma siguiente rehace la mezcla (llegó un análisis nuevo) y sigue siendo B",
      st is not None and st["next_path"] == "B")
r.order["A"] = "C"
r.sess.replan()
st = r.wait(lambda x: x["plan"] is not None and x["next_path"] == "C")
check("replan con otra siguiente: se prepara C", st is not None)
r.pull(80 * SR)
check("y se pasa a C (B no llega a sonar)", [x["advanced"] for x in r.states if x["advanced"]] == ["C"])
check(f"sin clics (salto máximo {max_jump(r.audio()):.4f})", max_jump(r.audio()) < CLICK)
r.sess.stop()
r = Rig(SONGS, {"A": "B"})
r.sess.play("A")
r.wait(lambda x: x["plan"] is not None)
r.order["A"] = None
r.sess.replan()
st = r.wait(lambda x: x["plan"] is None)
check("replan y next_after ya da None: se quita la transición", st is not None and st["next_path"] is None)
r.pull(75 * SR)
ends = [x for x in r.states if x["ended"]]
check("A suena entera y luego ended (una vez)", len(ends) == 1 and ends[0]["_frames"] >= 70 * SR
      and np.array_equal(r.audio()[FADE:70 * SR], r.gained("A")[FADE:]))
r.sess.stop()

# ---- 6. pausa, y transporte mientras carga ---------------------------------------------------------------------------------
r = Rig(SONGS, {"A": None})
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
r.pull(3 * SR)
r.sess.pause()
r.pull(SR)
st1 = r.tick()
r.pull(SR)
st2 = r.tick()
quiet = r.audio()[3 * SR + FADE + 2:]
check("pausa: estado «paused», la posición no avanza y sale silencio tras el fundido",
      st1["state"] == "paused" and st1["position_s"] == st2["position_s"] and not quiet.any()
      and abs(st1["position_s"] - (3 * SR + FADE) / SR) < 1e-3)
r.sess.resume()
r.pull(SR)
st = r.tick()
check("resume: sigue donde estaba", st["state"] == "playing" and abs(st["position_s"] - (4 * SR + FADE) / SR) < 1e-3)
check(f"sin clics al pausar y reanudar (salto máximo {max_jump(r.audio()):.4f})", max_jump(r.audio()) < CLICK)
r.sess.stop()
r = Rig(SONGS, {"A": None})
r.fake.delay["A"] = 0.2
r.sess.play("A", autoplay=False)
r.sess.resume()
r.sess.seek(12.0)
r.sess.set_volume(0.5)
st = r.tick()
check("resume() y seek() durante la carga se apuntan (estado loading, posición pedida)",
      st["state"] == "loading" and st["position_s"] == 12.0)
st = r.wait(lambda x: x["state"] != "loading")
r.pull(SR)
st = r.tick()
A = r.gained("A")
check("y se aplican al cargar: suena desde 12 s, a media ganancia", st["state"] == "playing" and abs(st["position_s"] - 13.0) < 1e-9
      and np.allclose(r.audio()[SR // 2:SR], A[12 * SR + SR // 2:13 * SR] * 0.5, atol=1e-6))
r.sess.stop()
r = Rig(SONGS, {"A": None})
r.fake.delay["A"] = 0.2
r.sess.play("A")
r.sess.pause()
r.wait(lambda x: x["state"] != "loading")
r.pull(SR)
check("pause() durante la carga: carga pero no suena", r.tick()["state"] == "paused" and not r.audio().any())
r.sess.resume()
r.pull(SR)
check("y resume() la pone a sonar", r.tick()["state"] == "playing" and r.audio()[SR:].any())
r.sess.stop()

# ---- 7. siguiente que falta ------------------------------------------------------------------------------------------------
r = Rig(SONGS, {"A": "X", "X": "C", "C": None})
r.sess.play("A")
st = r.wait(lambda x: x["plan"] is not None)
check("B ausente: se salta y se prepara la que da next_after(B)", st is not None and st["next_path"] == "C"
      and any(c[0] == "X" for c in r.fake.calls) and [a[0] for a in r.asked] == ["A", "X"])
r.pull(80 * SR)
check("y se pasa a C", [x["advanced"] for x in r.states if x["advanced"]] == ["C"])
r.sess.stop()
r = Rig(SONGS, {"A": "X1", "X1": "X2", "X2": "X3", "X3": "X4", "X4": "X5", "X5": "X6"})
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
r.pull(75 * SR)
ends = [x for x in r.states if x["ended"]]
check("si fallan 5 seguidas, A suena entera y termina", len(ends) == 1 and [a[0] for a in r.asked] == ["A", "X1", "X2", "X3", "X4"]
      and np.array_equal(r.audio()[FADE:70 * SR], r.gained("A")[FADE:]))
r.sess.stop()

# ---- 8. lista de una sola canción ------------------------------------------------------------------------------------------
r = Rig(SONGS, {})
r.sess.play("C")
r.wait(lambda x: x["state"] == "playing")
r.pull(55 * SR)
ends = [x for x in r.states if x["ended"]]
check("sin siguiente: C suena entera (50 s) y ended una sola vez, después de su última muestra",
      len(ends) == 1 and ends[0]["_frames"] >= 50 * SR and np.array_equal(r.audio()[FADE:50 * SR], r.gained("C")[FADE:])
      and not r.audio()[50 * SR:].any())
r.sess.stop()

# ---- 9. stop --------------------------------------------------------------------------------------------------------------
r = Rig(SONGS, {"A": "B"})
r.sess.play("A")
r.wait(lambda x: x["plan"] is not None)
r.pull(SR)
worker = r.sess._worker
r.sess.stop()
r.pull(4096)
st = r.tick()
gc.collect()
check("stop: hilo de trabajo terminado, motor vacío, estado stopped y ninguna canción en memoria",
      not worker.is_alive() and r.eng.queued_count == 0 and st["state"] == "stopped" and r.fake.alive() == 0)
check(f"stop se funde a silencio sin clic (salto máximo {max_jump(r.audio()):.4f})", max_jump(r.audio()) < CLICK
      and not r.audio()[-3000:].any())
r.sess.play("C")
check("después de stop se puede volver a empezar", r.wait(lambda x: x["state"] == "playing") is not None)
r.sess.stop()

# ---- 10. excepciones ------------------------------------------------------------------------------------------------------
r = Rig(SONGS, {"A": "B", "B": "C"})
r.fake.raise_on.add("B")
r.sess.play("A")
st = r.wait(lambda x: x["plan"] is not None)
errs = [x["error"] for x in r.states if x["error"]]
check(f"si el cargador lanza una excepción con B: se informa ({errs[:1]}) y se salta a C",
      len(errs) == 1 and "B" in errs[0] and st["next_path"] == "C")
r.sess.stop()
r = Rig(SONGS, {})
r.fake.raise_on.add("A")
r.sess.play("A")
st = r.wait(lambda x: x["state"] != "loading")
check("si falla la canción que se pidió: error y estado stopped (la interfaz decide)", st["state"] == "stopped"
      and st["error"] and "A" in st["error"])
r = Rig(SONGS, {"A": "B"})
r.sess._info_for = lambda p: 1 / 0
r.sess.play("A")
st = r.wait(lambda x: x["plan"] is not None)
check("info_for que falla: se planifica con la duración real (corte o mezcla, sin romperse)", st is not None and st["next_path"] == "B")
r.sess.stop()
r = Rig(SONGS, {"A": "B"})
r.sess._next_after = lambda p: 1 / 0
r.sess.play("A")
st = r.wait(lambda x: x["error"] is not None)
check("next_after que falla: error y A sin siguiente", st is not None and "next_after" in st["error"])
r.sess.stop()

# ---- 11. plan tardío ------------------------------------------------------------------------------------------------------
r = Rig(SONGS, {"A": "B"})
r.fake.delay["B"] = 2.0                                        # de sobra para sacar 52 s de audio antes de que llegue
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
r.wait(lambda x: x["next_path"] == "B")
r.pull(int(52.3 * SR))                                         # pasado el punto de mezcla de antes de que llegue el plan
f_late = r.frames
st = r.wait(lambda x: x["plan"] is not None)
plan = st["plan"]
cur_end = (f_late // (15 * SR) + 1) * 15 * SR
print(f"INFO plan tardío: sonaba la muestra {f_late} ({f_late / SR:.2f} s), el trozo acaba en {cur_end / SR:.1f} s; "
      f"corte en {plan.a_start_s:.3f} s", flush=True)
check(f"plan tardío: corte limpio en el siguiente compás tras el trozo que sonaba ({plan.reason[:50]}...)",
      plan.kind == KIND_CUT and "ya había pasado" in plan.reason and plan.a_start_s * SR >= cur_end + dj_engine.CUT_PIECE_S * SR
      and abs(plan.a_start_s / 2.0 - round(plan.a_start_s / 2.0)) < 1e-6)
r.pull(20 * SR)
c = round(plan.a_start_s * SR)
out = r.audio()
check("A sigue entera hasta el corte y B entra en él, sin hueco ni clic",
      np.array_equal(out[FADE:c - SR // 2], r.gained("A")[FADE:c - SR // 2]) and max_jump(out) < CLICK
      and np.abs(out[c:c + SR]).max() > 0.1)
adv = r.first("advanced")
check("advanced cuando entra B", adv is not None and c <= adv["_frames"] < c + TICK + 1024)
r.sess.stop()

# ---- 12. carrera con la llamada de audio: un hilo saca audio sin parar mientras la interfaz cambia de planes ---------------
r = Rig(SONGS, {"A": "B", "B": "C", "C": "A"})
r.sess.play("A")
r.wait(lambda x: x["state"] == "playing")
outs, halt = [], threading.Event()


def audio_thread():
    while not halt.is_set():
        outs.append(r.eng.pull(512))       # unas 20 veces más deprisa que el tiempo real
        time.sleep(0.0005)


th = threading.Thread(target=audio_thread)
th.start()
t0, last, k, seeks, advs = time.monotonic(), 0.0, 0, 0, 0
while time.monotonic() - t0 < 30.0 and (advs < 3 or k < 20):
    advs += bool(r.tick()["advanced"])
    now = time.monotonic() - t0
    if now - last > 0.3:
        last, k = now, k + 1
        cur = r.sess.current_path
        if k % 4 == 0:                     # cambia la siguiente; las demás veces, replan con la misma (no rehace nada)
            r.order[cur] = "C" if r.order.get(cur) != "C" and cur != "C" else "B" if cur != "B" else "A"
        r.sess.replan()
        if k % 5 == 0 and seeks < 3:
            seeks += 1
            r.sess.seek(10.0 + k % 15)
    time.sleep(0.02)
halt.set()
th.join()
out = np.concatenate(outs)
advs = [x["advanced"] for x in r.states if x["advanced"]]
check(f"con la llamada de audio corriendo a la vez ({k} replan, {seeks} seek, {len(advs)} pasos a la siguiente, "
      f"{len(out) / SR:.0f} s de audio): sin huecos, repeticiones ni clics (salto máximo {max_jump(out):.4f})",
      max_jump(out) < CLICK and len(advs) >= 3 and not any(x["error"] for x in r.states))
check(f"y nunca más de 2 canciones enteras vivas (máximo visto {r.max_alive})", r.max_alive <= 2)
r.sess.stop()

# ---- 13. cargador real con FFmpeg ---------------------------------------------------------------------------------------------
from services import pcm_loader
from services.ffmpeg_service import FFmpegService

ffmpeg = FFmpegService.get_ffmpeg_path()
if not ffmpeg:
    print("AVISO no hay FFmpeg: se salta el caso con el cargador real", flush=True)
else:
    tmp = tempfile.mkdtemp(prefix="motor_dj_")
    try:
        paths = {}
        for name, freq, bpm in (("a", 220, 120.0), ("b", 330, 124.8)):
            p = os.path.join(tmp, f"{name}.mp3")
            beat = 60.0 / bpm
            src = f"sine=frequency={freq}:duration=180,volume='0.3+0.4*lt(mod(t\\,{beat:.6f})\\,0.1)':eval=frame"
            subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", src, "-ac", "2", "-ar", "44100",
                            "-b:a", "192k", p], check=True, timeout=120)
            paths[p] = {"duration_ms": 180000, "intro_ms": 8000, "outro_ms": 30000, "bpm": bpm, "beatgrid": BeatGrid(0.0, bpm)}
        pa, pb = list(paths)
        eng = MixEngine()
        sess = EngineSession(eng, lambda p: paths.get(p, {}), lambda p: pb if p == pa else None)
        t0 = time.monotonic()
        sess.play(pa)
        st, sound_wall = None, None
        while time.monotonic() - t0 < 60:
            st = sess.tick()
            if sound_wall is None and st["state"] == "playing":
                sound_wall = time.monotonic() - t0
            if st["plan"] is not None or st["error"]:
                break
            time.sleep(0.05)
        ready_wall = time.monotonic() - t0
        tm = sess.timings
        print(f"INFO cargador real (mp3 de 3 min): suena a los {tm.get('sound', -1):.2f} s del play() "
              f"(visto en tick a los {sound_wall or -1:.2f} s); transición lista a los {tm.get('ready', -1):.2f} s "
              f"(rubberband: {'sí' if pcm_loader.rubberband_available() else 'no'}); plan: {st['plan']}", flush=True)
        check("con el cargador real: A suena en menos de 1,5 s y la transición queda lista",
              st is not None and st["plan"] is not None and 0 < tm.get("sound", 99) < 1.5 and tm.get("ready", 0) > 0)
        a_mix = round(st["plan"].a_start_s * SR)
        eng.play(fade=False)
        got = eng.pull(SR)
        check("el audio decodificado sale por el motor (no es silencio)", float(np.abs(got).max()) > 0.02)
        sess.stop()
    except subprocess.SubprocessError as e:
        print(f"AVISO no se pudieron generar los mp3 de prueba ({e}): se salta el caso real", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# ---- 14. la misma ruta escrita de dos formas (Qt da «/», la ventana usa «\\») es la misma canción ----------------------------------
sess = Rig(SONGS, {"A": None}).sess
with sess._lock:
    sess._pending_adopt = r"C:\musica/Reggaeton\B.mp3"
check("adopt reconoce la misma ruta con otras barras y otras mayúsculas", sess.adopt(r"c:/MUSICA\reggaeton/b.mp3")
      and not sess.adopt(r"c:/musica/reggaeton/b.mp3"))
sess.stop(wait=False)
check("stop(wait=False) no espera al hilo y deja la sesión parada", sess.current_path is None)

print("FIN", flush=True)
