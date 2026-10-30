"""Banco de pruebas compartido de la sesión del DJ (dj_engine.EngineSession) sin sonido: cargador falso de canciones sintéticas y
un «Rig» que saca audio del motor a bloques y llama a tick() cada 50 ms de audio. Lo usan las pruebas del motor posteriores a
prueba_motor_dj.py (que tiene su propia copia, más antigua). Con la variable de entorno PRUEBA_SRC se puede apuntar a otra copia
del código (para comprobar que una prueba falla sin un arreglo)."""
import os
import sys
import threading
import time
import weakref

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.environ.get("PRUEBA_SRC") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np  # noqa: E402

from services.audio_engine import MixEngine  # noqa: E402
from services.deck_gain import deck_gain  # noqa: E402
from services.dj_engine import EngineSession  # noqa: E402
from services.mix_types import SAMPLE_RATE, BeatGrid  # noqa: E402

SR = SAMPLE_RATE
TICK = 2205                     # 50 ms de audio entre tick y tick
FADE = round(SR * 0.015)        # fundido del motor
CLICK = 0.05                    # salto máximo admitido entre dos muestras seguidas


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)
    return bool(cond)


class FakeLoader:
    """Canciones sintéticas: senoide (frecuencia propia) con un bombo suave de 60 Hz en cada golpe. Con tempo_ratio distinto
    de 1 se remuestrea. `cap` (segundos): el cargador solo entrega eso (como el tope de pcm_loader)."""

    def __init__(self, songs):
        self.songs = songs
        self.calls = []
        self.refs = []
        self.raise_on = set()
        self.delay = {}

    def full(self, path):
        s = self.songs[path]
        dur = min(s["dur"], s.get("cap", s["dur"]))
        t = np.arange(int(dur * SR)) / SR
        ph = t % (60.0 / s["bpm"])
        env = np.where(ph < 0.15, np.sin(np.pi * ph / 0.15) ** 2, 0.0)
        amp = s.get("amp", 0.3)
        v = (amp * np.sin(2 * np.pi * s["freq"] * t) + 0.2 * env * np.sin(2 * np.pi * 60.0 * t)).astype(np.float32)
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
    """Ficha como la del análisis: duración, intro de 8 s, final de 16 s, rejilla en 0 con la confianza y el tono de la canción
    (por defecto 0,9 y «8A»: datos fiables)."""
    s = songs.get(path)
    if s is None:
        return {}
    if "info" in s:
        return dict(s["info"])
    info = {"duration_ms": s["dur"] * 1000, "intro_ms": s.get("intro", 8) * 1000, "outro_ms": s.get("outro", 16) * 1000,
            "bpm": s["bpm"], "beatgrid": BeatGrid(0.0, s["bpm"], confidence=s.get("conf", 0.9)), "tone": s.get("tone", "8A")}
    info.update(s.get("extra", {}))
    return info


LUFS = {"A": -17.0, "B": -11.0, "C": -14.0}


class Rig:
    """Motor sin dispositivo + sesión + cargador falso; saca audio a bloques de 1024 y llama a tick() cada 50 ms de audio."""

    def __init__(self, songs, order, info=None, **kw):
        self.songs, self.order = songs, dict(order)
        self.fake = FakeLoader(songs)
        self.eng = MixEngine()
        self.asked = []
        self.info = info or (lambda p: info_of(songs, p))
        self.sess = EngineSession(self.eng, lambda p: self.info(p), self._next_after, loader=self.fake,
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
        return next((s for s in self.states if s.get(key)), None)

    def gained(self, path):
        x = self.fake.full(path)
        x *= deck_gain(LUFS.get(path), max(float(x.max()), -float(x.min())))
        return x

    def start(self, path="A"):
        """play(path) y espera a que suene y a que llegue el plan (o None si no llega)."""
        self.sess.play(path)
        self.wait(lambda x: x["state"] == "playing")
        return self.wait(lambda x: x["plan"] is not None)


def max_jump(x):
    return float(np.abs(np.diff(x[:, 0])).max()) if len(x) > 1 else 0.0
