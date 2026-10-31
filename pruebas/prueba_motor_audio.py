"""Motor de audio propio del modo DJ: cola de segmentos a precisión de muestra, pausa y salto sin clic, ganancia con rampa,
notificaciones fuera de la llamada de audio y, si hay tarjeta de sonido, un flujo real de 3 s SIEMPRE en silencio
(ganancia maestra 0 y contenido a -80 dB: no sale nada por los altavoces).
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_audio.py"""
import logging
import math
import os
import random
import sys
import threading
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import audio_engine
from services.audio_engine import EV_QUEUE_EMPTY, EV_SEGMENT_START, MixEngine
from services.mix_types import SAMPLE_RATE


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def numbered(start, n):
    """Segmento cuyas muestras son su propio número (izquierda) y su negativo (derecha): así se ve si falta o sobra alguna."""
    v = np.arange(start, start + n, dtype=np.float32)
    return np.stack([v, -v], axis=1)


def sine(n, freq=440.0, amp=0.8, phase=0.0):
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    v = (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)
    return np.stack([v, v], axis=1)


def pull_irregular(eng, total, rng, max_block=700):
    parts, done = [], 0
    while done < total:
        k = min(total - done, rng.randint(1, max_block))
        parts.append(eng.pull(k))
        done += k
    return np.concatenate(parts)


rng = random.Random(1234)
FADE = round(SAMPLE_RATE * audio_engine.FADE_MS / 1000.0)
SINE_STEP = 2 * math.pi * 440.0 / SAMPLE_RATE * 0.8          # salto máximo natural entre muestras de la senoide de prueba

# ---- concatenación exacta ----------------------------------------------------------------------------------------------
eng = MixEngine(limit=False)     # muestras numeradas (>1): sin limitador, para comparar exacto
lengths = [5000, 1, 2, 3, 777, 1, 4096, 1024, 1, 9999]
expected, start, ids = [], 0, []
for i, n in enumerate(lengths):
    ids.append(eng.queue(numbered(start, n), f"s{i}"))
    expected.append(numbered(start, n))
    start += n
total = start
expected = np.concatenate(expected)
check("encolar un array vacío no encola nada", eng.queue(np.zeros((0, 2), np.float32)) is None and eng.queued_count == len(lengths))
check("antes de play() solo sale silencio y la posición no avanza", not eng.pull(512).any() and eng.position_frames == 0)
eng.play(fade=False)
out = pull_irregular(eng, total, rng)
check(f"{len(lengths)} segmentos (con longitudes 1, 2, 3...) salen seguidos muestra a muestra, sin huecos ni duplicados",
      out.shape == (total, 2) and np.array_equal(out, expected))
check("la posición es exactamente lo tocado", eng.position_frames == total and abs(eng.position_s - total / SAMPLE_RATE) < 1e-12)
ev = eng.poll_events()
starts = [e for e in ev if e[0] == EV_SEGMENT_START]
cum = np.concatenate([[0], np.cumsum(lengths)[:-1]]).tolist()
check("una notificación de inicio por segmento, con su etiqueta, su número y la muestra exacta en que empieza",
      [(e[1], e[2], e[3]) for e in starts] == [(f"s{i}", ids[i], cum[i]) for i in range(len(lengths))])
check("y una sola de cola vacía, al final", [e for e in ev if e[0] == EV_QUEUE_EMPTY] == [(EV_QUEUE_EMPTY, total)]
      and ev[-1][0] == EV_QUEUE_EMPTY)
tail = eng.pull(3000)
check("con la cola vacía: silencio (sin excepción) y la posición quieta", not tail.any() and eng.position_frames == total)
check("y no se repite la notificación de cola vacía", eng.poll_events() == [])
eng.queue(numbered(total, 10), "tarde")
late = eng.pull(20)
check("lo que se encola con el motor ya en silencio entra en el siguiente bloque",
      np.array_equal(late[:10], numbered(total, 10)) and not late[10:].any() and eng.position_frames == total + 10)

# segmentos de 1 muestra uno detrás de otro, sacados de uno en uno
e1 = MixEngine(limit=False)     # muestras numeradas (>1): sin limitador, para comparar exacto
for i in range(50):
    e1.queue(numbered(i, 1))
e1.play(fade=False)
ones = np.concatenate([e1.pull(1) for _ in range(50)] + [e1.pull(5)])
check("50 segmentos de 1 muestra sacados de uno en uno", np.array_equal(ones[:50], numbered(0, 50)) and not ones[50:].any())
mono = MixEngine()
mono.queue(np.array([0.1, 0.2, 0.3], np.float32))
mono.play(fade=False)
m = mono.pull(3)
check("un segmento mono se toca igual por los dos lados", np.allclose(m[:, 0], [0.1, 0.2, 0.3]) and np.array_equal(m[:, 0], m[:, 1]))
try:
    mono.queue(np.zeros((10, 3), np.float32))
    check("un array de 3 canales se rechaza", False)
except ValueError:
    check("un array de 3 canales se rechaza", True)
check("pull(0) devuelve un array vacío sin fallar", mono.pull(0).shape == (0, 2))

# ---- sustitución de la cola y salto ---------------------------------------------------------------------------------------
q = MixEngine(limit=False)     # muestras numeradas (>1): sin limitador, para comparar exacto
q.queue(numbered(0, 3000), "A")
q.queue(numbered(100000, 3000), "B")
q.play(fade=False)
first = q.pull(1000)
new_ids = q.replace_queue([(numbered(200000, 2000), "C")])
rest = q.pull(5000)
check("replace_queue: lo que suena sigue entero y después viene lo nuevo, sin hueco (B ya no suena)",
      np.array_equal(np.concatenate([first, rest[:4000]]), np.concatenate([numbered(0, 3000), numbered(200000, 2000)]))
      and not rest[4000:].any() and len(new_ids) == 1)
q2 = MixEngine(limit=False)     # muestras numeradas (>1): sin limitador, para comparar exacto
q2.queue(numbered(0, 3000))
q2.queue(numbered(9000, 3000))
q2.play(fade=False)
q2.pull(100)
check("clear_queue quita lo que venía y deja acabar lo que suena", q2.clear_queue() == 1 and q2.remaining_frames == 2900)
r2 = q2.pull(3000)
check("después, silencio", np.array_equal(r2[:2900], numbered(100, 2900)) and not r2[2900:].any())

j = MixEngine()
a, b = sine(SAMPLE_RATE, 440.0), sine(SAMPLE_RATE, 440.0, phase=math.pi)    # la nueva, en contrafase: el peor caso
j.queue(a, "A")
j.play(fade=False)
pre = j.pull(25)                             # justo en una cresta de la senoide: el peor momento para cortar
j.replace([(b, "B")])
post = j.pull(4000)
seam = np.concatenate([pre, post])
d = np.abs(np.diff(seam[:, 0])).max()
check(f"saltar (replace) con fundido de 15 ms no hace clic aunque la nueva entre en contrafase (salto máximo {d:.4f})",
      d <= SINE_STEP * 1.6)
check("pasado el fundido suena exactamente la nueva", np.array_equal(post[FADE:4000], b[FADE:4000]))
hard = MixEngine()
hard.queue(a)
hard.play(fade=False)
hpre = hard.pull(25)
hard.replace([b], fade=False)
hd = np.abs(np.diff(np.concatenate([hpre[-1:], hard.pull(10)])[:, 0])).max()
check(f"(sin fundido sí habría clic: salto de {hd:.3f})", hd > 0.5)
z = MixEngine()
z.queue(a)
z.play(fade=False)
z.pull(500)
z.replace([])
zz = z.pull(FADE + 500)
check("replace([]) se funde a silencio y avisa de cola vacía",
      not zz[FADE:].any() and np.abs(np.diff(zz[:, 0])).max() <= SINE_STEP * 1.6
      and any(e[0] == EV_QUEUE_EMPTY for e in z.poll_events()))

# ---- pausa y reanudación con fundido -----------------------------------------------------------------------------------
p = MixEngine()
s = sine(SAMPLE_RATE * 2)
p.queue(s)
p.play(fade=False)
before = p.pull(4410)
p.pause()
fading = p.pull(2048)
frozen = p.position_frames
silent = p.pull(4096)
check("la pausa se apaga en 15 ms y deja silencio", not fading[FADE + 1:].any() and not silent.any())
dpause = np.abs(np.diff(np.concatenate([before[-10:], fading])[:, 0])).max()
check(f"sin clic al pausar (salto máximo {dpause:.4f}, el de la senoide es {SINE_STEP:.4f})", dpause <= SINE_STEP * 1.05)
check("la posición avanza solo hasta donde acaba el fundido y se queda quieta",
      frozen == 4410 + FADE and p.position_frames == frozen)
p.play()
resumed = p.pull(4096)
dres = np.abs(np.diff(np.concatenate([silent[-5:], resumed])[:, 0])).max()
ramp = np.minimum(np.arange(1, 4097, dtype=np.float32) / FADE, 1.0)[:, None]
check(f"al reanudar, fundido de entrada sin clic (salto máximo {dres:.4f})", dres <= SINE_STEP * 1.05)
check("y sigue justo donde se quedó", np.allclose(resumed, s[frozen:frozen + 4096] * ramp, atol=1e-6)
      and p.position_frames == frozen + 4096)
p.pause()
p.pull(10)
p.play()                                     # pausar y reanudar a mitad del fundido
mid = p.pull(2000)
check("pausar y reanudar a mitad de fundido tampoco hace clic", np.abs(np.diff(mid[:, 0])).max() <= SINE_STEP * 1.05)

# ---- ganancia maestra con rampa ----------------------------------------------------------------------------------------
g = MixEngine(limit=False)     # unos (>0,9): sin limitador, para ver la rampa exacta
g.queue(np.ones((SAMPLE_RATE, 2), np.float32))
g.play(fade=False)
g.pull(100)
g.set_master_gain(0.5)                       # 50 ms de 0 a 1: de 1 a 0,5 tarda 25 ms (1103 muestras)
gr = g.pull(3000)[:, 0]
step = 1.0 / (SAMPLE_RATE * audio_engine.GAIN_RAMP_MS / 1000.0)
check("la ganancia baja en rampa (sin escalón) y se queda en 0,5",
      gr[0] < 1.0 and gr[0] > 0.99 and np.all(np.diff(gr) <= 1e-7) and np.abs(np.diff(gr)).max() <= step * 1.01
      and np.allclose(gr[1110:], 0.5) and gr[1000] > 0.5)
g.set_master_gain(0.0, ramp_ms=0)
check("con ramp_ms=0 cambia al momento", not g.pull(100).any() and g.master_gain == 0.0)
g.set_master_gain(7.0)
check("la ganancia se limita a 0..1", g.master_gain == 1.0)

# ---- llamada de audio sin dispositivo: contadores y errores ----------------------------------------------------------------
class _Status:
    def __init__(self, underflow):
        self.output_underflow = underflow

    def __bool__(self):
        return True


c = MixEngine(limit=False)     # muestras numeradas (>1): sin limitador, para comparar exacto
c.queue(numbered(0, 3000))
c.play(fade=False)
buf = np.empty((1024, 2), np.float32)
c._callback(buf, 1024, None, None)
check("la llamada de audio escribe en el búfer del dispositivo lo mismo que pull", np.array_equal(buf, numbered(0, 1024)))
c._callback(buf, 1024, None, _Status(True))
c._callback(buf, 1024, None, _Status(False))
st = c.stats()
check("cuenta subdesbordamientos, otros avisos, llamadas y su duración", st["underflows"] == 1 and st["other_status"] == 1
      and st["callbacks"] == 3 and st["max_ms"] > 0 and st["mean_ms"] > 0)
c._lock = None                               # rompe el render a propósito
c._callback(buf, 1024, None, None)
check("si algo falla dentro de la llamada de audio, sale silencio y se cuenta (nunca una excepción)",
      not buf.any() and c.stats()["errors"] == 1)

# ---- notificaciones: se recogen fuera, en el hilo que llama a dispatch_events --------------------------------------------
n = MixEngine()
seen, where = [], []
n.on_segment_start = lambda label, seg_id, start: (seen.append((label, start)), where.append(threading.current_thread()))
n.on_queue_empty = lambda pos: seen.append(("vacía", pos))
n.queue(numbered(0, 100), "x")
n.queue(numbered(0, 50), "y")
n.play(fade=False)
n.pull(500)
check("la llamada de audio no ejecuta las notificaciones (solo las apunta)", seen == [])
check("dispatch_events las ejecuta en el hilo que lo llama", n.dispatch_events() == 3 and seen == [("x", 0), ("y", 100), ("vacía", 150)]
      and where == [threading.current_thread()] * 2)
n.on_segment_start = lambda *a: 1 / 0
n.queue(numbered(0, 10), "z")
n.pull(20)
logging.getLogger("services.audio_engine").setLevel(logging.CRITICAL)     # el fallo es a propósito: no se escribe
check("una notificación que falla no rompe las demás", n.dispatch_events() == 2 and seen[-1] == ("vacía", 160))
logging.getLogger("services.audio_engine").setLevel(logging.NOTSET)

# ---- dos hilos a la vez: uno encola mientras el otro saca ------------------------------------------------------------------
t = MixEngine(limit=False)     # muestras numeradas (>1): sin limitador, para comparar exacto
t.play(fade=False)
TOTAL = 400000
feed_done = threading.Event()


def feeder():
    r, k = random.Random(7), 0
    while k < TOTAL:
        m = min(TOTAL - k, r.randint(1, 3000))
        t.queue(numbered(k, m))
        k += m
        if r.random() < 0.3:
            time.sleep(0.0005)
    feed_done.set()


th = threading.Thread(target=feeder)
th.start()
got, have = [], 0
while have < TOTAL:
    blk = t.pull(512)
    k = 0 if t.position_frames <= have else t.position_frames - have
    got.append(blk[:k])
    have += k
th.join()
cat = np.concatenate(got)
check("con un hilo encolando y otro sacando a la vez, todo sale en orden y exacto", np.array_equal(cat, numbered(0, TOTAL)))

# ---- sin sounddevice ------------------------------------------------------------------------------------------------------
saved = (audio_engine._sd_module, audio_engine._sd_checked, sys.modules.get("sounddevice"))
sys.modules["sounddevice"] = None            # hace que `import sounddevice` lance ImportError
audio_engine._sd_module, audio_engine._sd_checked = None, False
check("sin sounddevice, _sounddevice() devuelve None sin excepción", audio_engine._sounddevice() is None)
nos = MixEngine(limit=False)     # muestras numeradas (>1): sin limitador, para comparar exacto
check("available() es False y start() devuelve False con el motivo", not audio_engine.available() and not nos.start()
      and "sounddevice" in nos.last_error)
nos.queue(numbered(0, 10))
nos.play(fade=False)
check("y pull sigue funcionando igual", np.array_equal(nos.pull(10), numbered(0, 10)))
nos.stop()
if saved[2] is None:
    del sys.modules["sounddevice"]
else:
    sys.modules["sounddevice"] = saved[2]
audio_engine._sd_module, audio_engine._sd_checked = saved[0], saved[1]

# ---- humo con el dispositivo real, SIEMPRE en silencio ---------------------------------------------------------------------
info = audio_engine.output_device_info()
if info is None:
    print("AVISO no hay dispositivo de salida (o falta sounddevice): se salta la parte con tarjeta de sonido", flush=True)
else:
    print(f"INFO dispositivo: {info['name']} (frecuencia propia {info['default_samplerate']:.0f} Hz)", flush=True)
    for bs in (1024, 512):
        dev = MixEngine(blocksize=bs, master_gain=0.0, meter=True)
        quiet = sine(SAMPLE_RATE * 4, amp=1e-4)       # -80 dB y además por ganancia 0: no se oye nada
        dev.queue(quiet, "humo")
        if not dev.start():
            check(f"se abre el flujo de audio (bloque {bs}): {dev.last_error}", False)
            continue
        dev.play()
        t0 = time.monotonic()
        while time.monotonic() - t0 < 3.0:
            if dev.remaining_frames < SAMPLE_RATE:
                dev.queue(quiet, "humo")
            dev.dispatch_events()
            time.sleep(0.05)
        dev.set_master_gain(0.0)
        dev.stop()
        st = dev.stats()
        print(f"INFO bloque {bs}: {st['callbacks']} llamadas, máxima {st['max_ms']:.3f} ms, media {st['mean_ms']:.3f} ms "
              f"(presupuesto {st['budget_ms']:.1f} ms), latencia {st['latency_s'] * 1000:.0f} ms, "
              f"subdesbordamientos {st['underflows']}, otros avisos {st['other_status']}", flush=True)
        check(f"bloque {bs}: el flujo corre 3 s ({st['callbacks']} llamadas) sin subdesbordamientos ni errores",
              st["callbacks"] >= 0.8 * 3.0 * SAMPLE_RATE / bs and st["underflows"] == 0 and st["errors"] == 0)
        check(f"bloque {bs}: la llamada más larga cabe de sobra en su presupuesto (menos de la mitad)",
              st["max_ms"] < st["budget_ms"] / 2)
        check(f"bloque {bs}: no ha salido ni una muestra con sonido (pico {st['peak_out']})", st["peak_out"] == 0.0)
        check(f"bloque {bs}: la posición avanzó unos 3 s", 2.5 < dev.position_s < 4.0)

# ---- limitador suave de salida ---------------------------------------------------------------------------------------------
lim = MixEngine()
loud = sine(SAMPLE_RATE, freq=97.0, amp=1.8)                 # picos de 1,8 (dos canciones sumadas al límite)
loud[1000:1010] = np.nan                                     # y algo roto
lim.queue(loud)
lim.play(fade=False)
lo = lim.pull(SAMPLE_RATE)
check(f"limitador: picos de 1,8 salen con |x| <= 1,0 y sin NaN (pico {np.nanmax(np.abs(lo)):.4f})",
      np.isfinite(lo).all() and np.abs(lo).max() <= 1.0)
ref = sine(SAMPLE_RATE, freq=97.0, amp=1.8)[:, 0].astype(np.float64)
y = lo[:, 0].astype(np.float64)
ok_idx = np.r_[2000:SAMPLE_RATE]
check("limitador: la forma sigue a la original (mismo signo, crece con ella y sin saltos)",
      np.all(np.sign(y[ok_idx]) == np.sign(ref[ok_idx]))
      and np.all(np.diff(y[ok_idx])[np.diff(ref[ok_idx]) > 0] >= -1e-6)
      and np.abs(np.diff(y[ok_idx])).max() <= np.abs(np.diff(ref[ok_idx])).max() + 1e-6)
t_ = audio_engine.LIMIT_THRESHOLD
check("limitador: por debajo del umbral no toca nada (muestras de hasta 0,9 idénticas)",
      np.array_equal(y[ok_idx][np.abs(ref[ok_idx]) <= t_ - 1e-3], ref[ok_idx][np.abs(ref[ok_idx]) <= t_ - 1e-3].astype(np.float32)))
small = MixEngine()
quiet_sig = sine(SAMPLE_RATE, freq=440.0, amp=0.89)
small.queue(quiet_sig)
small.play(fade=False)
check("limitador: una señal de 0,89 sale idéntica muestra a muestra", np.array_equal(small.pull(SAMPLE_RATE), quiet_sig)
      and small.stats()["limited_blocks"] == 0)
# continuidad en las uniones de bloques (bloques irregulares): el limitador no tiene memoria, así que da lo mismo
lim2 = MixEngine()
lim2.queue(sine(SAMPLE_RATE, freq=97.0, amp=1.8))
lim2.play(fade=False)
irregular = pull_irregular(lim2, SAMPLE_RATE, rng)
check("limitador: igual con bloques irregulares que con uno solo (sin saltos en las uniones de bloques)",
      np.allclose(irregular[2000:], lo[2000:], atol=1e-7))
# coste en la llamada de audio: con señal que no pasa del umbral y con señal que pasa todo el rato
costs = {}
for name, amp in (("bajo el umbral", 0.5), ("todo por encima", 1.8)):
    e = MixEngine()
    e.queue(sine(SAMPLE_RATE * 20, freq=97.0, amp=amp))
    e.play(fade=False)
    buf = np.empty((1024, 2), np.float32)
    for _ in range(400):
        e._callback(buf, 1024, None, None)
    costs[name] = e.stats()
e = MixEngine(limit=False)
e.queue(sine(SAMPLE_RATE * 20, freq=97.0, amp=1.8))
e.play(fade=False)
for _ in range(400):
    e._callback(buf, 1024, None, None)
costs["sin limitador"] = e.stats()
print("INFO coste de la llamada de audio (bloque 1024, sin dispositivo): " + "; ".join(
    f"{k}: media {v['mean_ms']:.4f} ms, máxima {v['max_ms']:.3f} ms" for k, v in costs.items()), flush=True)
check("limitador: la llamada de audio sigue muy por debajo del presupuesto (media < 0,2 ms de 23,2 ms)",
      all(v["mean_ms"] < 0.2 for v in costs.values()))

print("FIN", flush=True)
