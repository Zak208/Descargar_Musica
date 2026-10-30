"""Estructura de la canción (fases 18 y 19, versión ligera): subidas, drops, breaks, partes y voz estimada, con canciones
sintéticas de estructura conocida, casos que no deben dar drops, las funciones de mezcla con casos hechos a mano, JSON y
velocidad. Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_estructura.py
Con  --reales [carpeta]  hace además una pasada INFORMATIVA (no es una prueba) por tus canciones: eventos por canción y si
caen cerca de comienzos de compás de la rejilla (no hay verdad de referencia, solo coherencia)."""
import glob
import os
import sys
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import structure
from services.mix_types import BeatGrid

SR = structure.SAMPLE_RATE
BPM, T0 = 128.0, 0.3
GRID = BeatGrid(first_beat_s=T0, bpm=BPM, beats_per_bar=4, downbeat_offset=0, confidence=0.9)
BAR = GRID.bar_s


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def bar(k):
    return GRID.bar_time(k)


def lowpass(x, cutoff):
    spec = np.fft.rfft(x)
    spec[np.fft.rfftfreq(len(x), 1.0 / SR) > cutoff] = 0
    return np.fft.irfft(spec, len(x)).astype(np.float32)


def highpass(x, cutoff):
    spec = np.fft.rfft(x)
    spec[np.fft.rfftfreq(len(x), 1.0 / SR) < cutoff] = 0
    return np.fft.irfft(spec, len(x)).astype(np.float32)


def kick_hit():
    t = np.arange(int(0.3 * SR)) / SR
    freq = 50.0 + 100.0 * np.exp(-t / 0.03)
    return (0.8 * np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / 0.12)).astype(np.float32)


def hat_hit(rng):
    n = int(0.05 * SR)
    return (0.25 * highpass(rng.standard_normal(4096).astype(np.float32), 4000.0)[:n] * np.exp(-np.arange(n) / (0.012 * SR)))


def place(out, hit, times):
    for t in times:
        i = int(round(t * SR))
        if 0 <= i < len(out):
            j = min(len(out), i + len(hit))
            out[i:j] += hit[:j - i]


def pad(n, amp=0.04):
    t = np.arange(n) / SR
    return (amp * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277.2 * t) + np.sin(2 * np.pi * 329.6 * t))).astype(np.float32)


def song(layout, seed=0):
    """Canción sintética: `layout` = [(tipo, compases)] con tipo intro, build, drop, break u outro; empieza en el compás 0 de
    GRID (con T0 s de colchón delante). Devuelve (muestras, {tipo: [compás de inicio, ...]})."""
    rng = np.random.default_rng(seed)
    total_bars = sum(b for _k, b in layout)
    n = int((bar(total_bars) + 1.0) * SR)
    out = pad(n)
    kick, starts, k = kick_hit(), {}, 0
    beat = GRID.beat_s
    for kind, bars in layout:
        starts.setdefault(kind, []).append(k)
        a, b = bar(k), bar(k + bars)
        ia, ib = int(a * SR), int(b * SR)
        if kind == "build":
            m = ib - ia
            p = np.linspace(0.0, 1.0, m, dtype=np.float32)
            noise = rng.standard_normal(m).astype(np.float32)
            bright = (1 - p) * lowpass(noise, 800.0) + p * noise
            out[ia:ib] += 0.25 * 10 ** ((-24.0 + 24.0 * p) / 20.0) * bright
        elif kind == "drop":
            beats = a + beat * np.arange(bars * 4)
            place(out, kick, beats)
            place(out, hat_hit(rng), beats + beat / 2)
            t = np.arange(ib - ia) / SR
            out[ia:ib] += (0.3 * np.sin(2 * np.pi * 55 * t) + 0.1 * np.sin(2 * np.pi * 110 * t)).astype(np.float32)
        elif kind == "outro":
            place(out, hat_hit(rng), a + beat * np.arange(bars * 4) + beat / 2)
        k += bars
    return out.astype(np.float32), starts


def near_bar(t, k, tol=1.0):
    return t is not None and abs(t - bar(k)) <= tol * BAR + 1e-6


LAYOUT = [("intro", 8), ("build", 8), ("drop", 16), ("break", 8), ("drop", 16), ("outro", 8)]
x, starts = song(LAYOUT)

# ------------------------------------------------------------------ (a) canción sintética con rejilla
res = structure.analyse(x, GRID, SR)
ev = res["events"]
drops = [e for e in ev if e["type"] == "drop"]
builds = [e for e in ev if e["type"] == "buildup"]
breaks = [e for e in ev if e["type"] == "break"]
print("     eventos con rejilla:", [(e["type"], e["t"], e["end"], e["strength"]) for e in ev], flush=True)
check(f"dos drops ({len(drops)}), en el compás 16 y en el 40 (± 1 compás)",
      len(drops) == 2 and near_bar(drops[0]["t"], 16) and near_bar(drops[1]["t"], 40))
check(f"una subida ({len(builds)}) del compás 8 al 16 (± 1 compás)",
      len(builds) == 1 and near_bar(builds[0]["t"], 8) and near_bar(builds[0]["end"], 16))
check(f"un break ({len(breaks)}) del compás 32 al 40 (± 1 compás)",
      len(breaks) == 1 and near_bar(breaks[0]["t"], 32) and near_bar(breaks[0]["end"], 40))
on_bars = all(abs(GRID.bar_at(t) - round(GRID.bar_at(t))) < 1e-3 for e in ev for t in (e["t"], e["end"]) if t is not None)
check("con rejilla, todos los instantes caen en un comienzo de compás", on_bars and bool(ev))
check("las fuerzas están entre 0 y 1", all(0.0 <= e["strength"] <= 1.0 for e in ev))
kinds = [s["kind"] for s in res["sections"]]
print("     partes:", [(s["kind"], s["start"], s["end"]) for s in res["sections"]], flush=True)
check(f"partes en orden intro, build, drop, break, drop, outro ({kinds})", kinds == ["intro", "build", "drop", "break", "drop", "outro"])
secs = res["sections"]
check("las partes cubren la canción sin huecos", bool(secs) and secs[0]["start"] == 0.0
      and all(abs(a["end"] - b["start"]) < 1e-6 for a, b in zip(secs, secs[1:])) and abs(secs[-1]["end"] - len(x) / SR) < 1e-3)
dur = int(np.ceil(len(x) / SR))
check(f"energía, graves y voz: un valor por segundo ({len(res['energy'])}, {len(res['bass'])}, {len(res['vocal'])} de {dur}) y de 0 a 1",
      len(res["energy"]) == len(res["bass"]) == len(res["vocal"]) == dur
      and all(0.0 <= v <= 1.0 for key in ("energy", "bass", "vocal") for v in res[key]))
in_intro, in_drop = int(bar(2)), int(bar(20))
check(f"graves en el drop ({res['bass'][in_drop]:.2f}) muy por encima de la intro ({res['bass'][in_intro]:.2f})",
      res["bass"][in_drop] - res["bass"][in_intro] > 0.3)

# ------------------------------------------------------------------ (b) sin rejilla, otra semilla y otro reparto
res_free = structure.analyse(x, None, SR)
d_free = [e for e in res_free["events"] if e["type"] == "drop"]
b_free = [e for e in res_free["events"] if e["type"] == "buildup"]
check(f"sin rejilla: los mismos drops a menos de 1 compás ({[e['t'] for e in d_free]})",
      len(d_free) == 2 and near_bar(d_free[0]["t"], 16) and near_bar(d_free[1]["t"], 40))
check(f"sin rejilla: la subida a menos de 1 compás ({[(e['t'], e['end']) for e in b_free]})",
      len(b_free) == 1 and near_bar(b_free[0]["t"], 8) and near_bar(b_free[0]["end"], 16))
x2, _ = song([("intro", 4), ("build", 16), ("drop", 16), ("break", 4), ("build", 8), ("drop", 8), ("outro", 4)], seed=5)
ev2 = structure.analyse(x2, GRID, SR)["events"]
got2 = [(e["type"], round(GRID.bar_at(e["t"]))) for e in ev2]
print("     otro reparto:", got2, flush=True)
want2 = [("buildup", 4), ("drop", 20), ("break", 36), ("buildup", 40), ("drop", 48)]
check("otro reparto (subida de 16 compases, break corto y segunda subida): eventos en su compás (± 1)",
      len(got2) == len(want2) and all(a[0] == b[0] and abs(a[1] - b[1]) <= 1 for a, b in zip(got2, want2)))

# ------------------------------------------------------------------ (c) lo que no debe dar drops
t = np.arange(60 * SR) / SR
cases = {"tono constante de 440 Hz": (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32),
         "tono grave constante de 55 Hz": (0.3 * np.sin(2 * np.pi * 55 * t)).astype(np.float32),
         "ruido blanco": (0.2 * np.random.default_rng(1).standard_normal(len(t))).astype(np.float32),
         "silencio": np.zeros(len(t), np.float32)}
loop = np.zeros(len(t), np.float32)
place(loop, kick_hit(), np.arange(0, 60, GRID.beat_s))
cases["bombo constante a 128"] = loop
for name, sig in cases.items():
    r = structure.analyse(sig, GRID, SR)
    check(f"{name}: ningún evento ({[(e['type'], e['t']) for e in r['events']]})", r["events"] == [])
odd = {"None": None, "lista vacía": [], "2 s de audio": np.zeros(2 * SR, np.float32),
       "con NaN": np.where(np.arange(30 * SR) % 7 == 0, np.nan, 0.1).astype(np.float32), "enteros": [0, 1, 2] * 100000}
fine = True
for name, sig in odd.items():
    try:
        r = structure.analyse(sig, GRID, SR)
        fine = fine and isinstance(r, dict) and set(r) == {"energy", "bass", "events", "vocal", "sections"}
        structure.vocal_activity(sig, SR)
    except Exception as e:
        print(f"     {name}: {type(e).__name__}: {e}", flush=True)
        fine = False
check("entradas raras (None, vacía, 2 s, NaN, enteros) no lanzan y devuelven el dict completo", fine)
check("audio vacío devuelve las listas vacías", structure.analyse([], None, SR) == structure.empty())

# ------------------------------------------------------------------ (d) drops_overlap con casos hechos a mano
A_DROP = [{"t": 100.0, "type": "drop", "end": None, "strength": 0.8}]
A_BUILD = [{"t": 90.0, "type": "buildup", "end": 106.0, "strength": 0.6}, {"t": 106.0, "type": "drop", "end": None, "strength": 0.8}]
B_DROP10 = [{"t": 10.0, "type": "drop", "end": None, "strength": 0.8}]
ov = structure.drops_overlap
check("drop de A y drop de B dentro de la mezcla: se solapan", ov(95.0, 16.0, 1.0, 0.0, A_DROP, B_DROP10))
check("drop de A fuera de la mezcla y el de B dentro: no se solapan", not ov(60.0, 16.0, 1.0, 0.0, A_DROP, B_DROP10))
check("el drop de B justo al final de la mezcla no choca con la subida de A (A ya se ha ido)",
      not ov(90.0, 16.0, 1.0, 4.0, A_BUILD[:1], [{"t": 20.0, "type": "drop"}]))
check("el drop de B en plena subida de A: se solapan", ov(90.0, 16.0, 1.0, 2.0, A_BUILD[:1], B_DROP10))
check("con el tempo: B a 1,0 deja su drop al final (no choca) y a 1,25 lo adelanta a la subida de A (choca)",
      not ov(90.0, 16.0, 1.0, 4.0, A_BUILD[:1], [{"t": 20.0, "type": "drop"}])
      and ov(90.0, 16.0, 1.25, 4.0, A_BUILD[:1], [{"t": 20.0, "type": "drop"}]))
check("el drop de A en plena subida de B: se solapan",
      ov(95.0, 16.0, 1.0, 0.0, A_DROP, [{"t": 2.0, "type": "buildup", "end": 14.0}, {"t": 14.0, "type": "drop"}]))
check("sin eventos, longitud 0 o datos rotos: no se solapan (y no lanza)",
      not ov(0, 16, 1, 0, [], []) and not ov(0, 0, 1, 0, A_DROP, B_DROP10) and not ov("x", 16, 1, 0, [None, 3], {"a": 1}))

# ------------------------------------------------------------------ (e) drop_aligned_b_start
B_EV = [{"t": bar(32), "type": "drop", "end": None, "strength": 0.9}]
al = structure.drop_aligned_b_start
start = al([], B_EV, 50.0, 16.0, 1.0, GRID)
u = None if start is None else (bar(32) - start) / 1.0
check(f"B entra en {start} s: comienzo de compás de B, y su drop cae a menos de medio compás del final de la mezcla (u = {u})",
      start is not None and abs(GRID.bar_at(start) - round(GRID.bar_at(start))) < 1e-6 and abs(u - 16.0) <= BAR / 2 + 1e-6)
start_r = al([], B_EV, 50.0, 8 * BAR, 1.25, GRID)
check(f"con tempo 1,25 y 8 compases de mezcla, B entra 10 compases antes de su drop ({start_r} = {bar(22):.3f})",
      start_r is not None and abs(start_r - bar(22)) < 1e-6)
check("sin drops en B: None", al([], [{"t": 30.0, "type": "break", "end": 40.0}], 50.0, 16.0, 1.0, GRID) is None)
check("solo un drop demasiado pronto (habría que empezar antes del principio): None",
      al([], [{"t": 5.0, "type": "drop"}], 50.0, 16.0, 1.0, None) is None)
check("un drop demasiado pronto y otro más tarde: se usa el segundo",
      al([], [{"t": 5.0, "type": "drop"}, {"t": 70.0, "type": "drop"}], 50.0, 16.0, 1.0, None) == 54.0)
start_a = al([{"t": 50.0, "type": "buildup", "end": 65.0}], [{"t": 70.0, "type": "drop"}], 50.0, 16.0, 1.0, None)
check(f"si la subida de A acaba en el último cuarto de la mezcla, el drop de B cae al final de esa subida ({start_a} = 55)",
      start_a == 55.0)
start_ok = al([], B_EV, 50.0, 16.0, 1.0, GRID)
check("lo que propone no da drops solapados con una A sin drops en la mezcla",
      not ov(50.0, 16.0, 1.0, start_ok, A_DROP, B_EV))
check("datos rotos: None sin lanzar", al(None, [{"t": "x", "type": "drop"}], "a", 16, 1, None) is None)

# ------------------------------------------------------------------ (f) actividad de voz
rng = np.random.default_rng(7)
secs = 20
n = secs * SR
voice = np.zeros(n, np.float32)
pos = 0
while pos < n:                                                     # sílabas de 0,12 a 0,3 s, con pausas cortas y tono que cambia
    length = int(rng.uniform(0.12, 0.3) * SR)
    f0 = rng.uniform(170, 260)
    tt = np.arange(length) / SR
    pitch = f0 * (1 + 0.02 * np.sin(2 * np.pi * 5.5 * tt))
    phase = 2 * np.pi * np.cumsum(pitch) / SR
    syl = sum((1.0 / h) * np.sin(h * phase) * (1.6 if 2 <= h <= 5 else 1.0) for h in range(1, 16))
    syl *= np.hanning(length)
    end = min(n, pos + length)
    voice[pos:end] = 0.15 * syl[:end - pos]
    pos = end + int(rng.uniform(0.02, 0.1) * SR)
kicks = np.zeros(n, np.float32)
place(kicks, kick_hit(), np.arange(0, secs, GRID.beat_s))
hats = np.zeros(n, np.float32)
for tt in np.arange(0, secs, GRID.beat_s / 2):
    place(hats, hat_hit(rng), [tt])
v_voice, v_kick, v_hat = (float(np.mean(structure.vocal_activity(s, SR))) for s in (voice, kicks, hats))
v_mix = float(np.mean(structure.vocal_activity(voice + 0.5 * kicks, SR)))
v_tone = float(np.mean(structure.vocal_activity(cases["tono constante de 440 Hz"], SR)))
print(f"     voz media: tono tipo voz {v_voice:.2f}, bombo {v_kick:.2f}, hi-hat {v_hat:.2f}, voz con bombo {v_mix:.2f}, "
      f"tono fijo {v_tone:.2f}", flush=True)
check(f"el tono modulado tipo voz da voz ({v_voice:.2f} >= 0,5)", v_voice >= 0.5)
check(f"el bombo no da voz ({v_kick:.2f} <= 0,15)", v_kick <= 0.15)
check(f"el hi-hat no da voz ({v_hat:.2f} <= 0,15)", v_hat <= 0.15)
check(f"un tono fijo, sin sílabas, da bastante menos que la voz ({v_tone:.2f})", v_tone <= v_voice - 0.3)
check(f"voz con bombo sigue por encima del bombo solo ({v_mix:.2f})", v_mix >= v_kick + 0.2)
check("silencio: sin voz (lista vacía o todo a 0)", not any(structure.vocal_activity(np.zeros(n, np.float32), SR)))
check(f"un valor por segundo ({len(structure.vocal_activity(voice, SR))} de {secs})", len(structure.vocal_activity(voice, SR)) == secs)

# ------------------------------------------------------------------ (g) vocal_overlap
vo = structure.vocal_overlap
check(f"voz en A siempre y en B desde su segundo 10: 6 de 16 s ({vo(0.0, 16.0, 1.0, 0.0, [1.0] * 100, [0.0] * 10 + [1.0] * 100)})",
      abs(vo(0.0, 16.0, 1.0, 0.0, [1.0] * 100, [0.0] * 10 + [1.0] * 100) - 6 / 16) < 0.02)
check(f"con B a tempo 2,0 la voz de B llega antes: 11 de 16 s ({vo(0.0, 16.0, 2.0, 0.0, [1.0] * 100, [0.0] * 10 + [1.0] * 100)})",
      abs(vo(0.0, 16.0, 2.0, 0.0, [1.0] * 100, [0.0] * 10 + [1.0] * 100) - 11 / 16) < 0.02)
check("sin voz en una de las dos: 0", vo(0.0, 16.0, 1.0, 0.0, [1.0] * 100, [0.2] * 100) == 0.0)
check("datos que faltan o rotos: 0 sin lanzar", vo(0, 16, 1, 0, [], [1.0]) == 0.0 and vo("x", 16, 1, 0, [1], [1]) == 0.0)

# ------------------------------------------------------------------ (h) JSON
text = structure.to_json(res)
back = structure.from_json(text)
check(f"to_json / from_json conserva el resultado ({len(text)} bytes para {dur} s)",
      back is not None and back["events"] == res["events"] and back["sections"] == res["sections"]
      and np.allclose(back["energy"], res["energy"]) and np.allclose(back["vocal"], res["vocal"]))
check("from_json de texto roto, de otra versión o None: None sin lanzar",
      structure.from_json("basura") is None and structure.from_json('{"v": -1}') is None and structure.from_json(None) is None)
check("to_json de algo roto no lanza y da un JSON válido", structure.from_json(structure.to_json({"events": [1, 2]})) is not None)

# ------------------------------------------------------------------ (i) velocidad
long_song, _ = song([("intro", 16), ("build", 8), ("drop", 32), ("break", 16), ("build", 8), ("drop", 32), ("outro", 12)], seed=3)
long_song = long_song[:240 * SR] if len(long_song) >= 240 * SR else np.concatenate(
    (long_song, np.zeros(240 * SR - len(long_song), np.float32)))
structure.analyse(long_song[:30 * SR], GRID, SR)                     # calentamiento
t0 = time.perf_counter()
r_long = structure.analyse(long_song, GRID, SR)
elapsed = time.perf_counter() - t0
check(f"analyse de 4 minutos ya decodificados tarda {elapsed:.2f} s (< 1 s) y encuentra drops ({len(r_long['events'])} eventos)",
      elapsed < 1.0 and any(e["type"] == "drop" for e in r_long["events"]))


# ------------------------------------------------------------------ (j) canciones reales (informativo, con --reales)
def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def real_songs(folder):
    from services import beatgrid, envelope, key_detect, tempo
    files = sorted(glob.glob(os.path.join(folder, "*.mp3")))
    print(f"     INFORMATIVO (no es una prueba; no hay verdad de referencia, solo coherencia): {len(files)} canciones de {folder}",
          flush=True)
    print("     desfase = distancia del evento SIN ajustar a la rejilla al comienzo de compás más cercano, en golpes (al azar, "
          "solo 1 de cada 4 caería a menos de medio golpe)", flush=True)
    offsets, times, counts, vocal_means, errors = [], [], {"drop": 0, "buildup": 0, "break": 0}, [], 0
    for path in files:
        name = os.path.basename(path)[:34]
        try:
            samples = key_detect.decode(path)
            if samples is None:
                print(f"     {name:34s} no se pudo decodificar", flush=True)
                continue
            data = envelope.compute(path)
            hint = tempo.estimate_bpm(data) if data else None
            grid = beatgrid.compute(samples, hint)
            t = time.perf_counter()
            res_g = structure.analyse(samples, grid, SR)
            times.append(time.perf_counter() - t)
            raw = structure.analyse(samples, None, SR)
            for e in res_g["events"]:
                counts[e["type"]] += 1
            song_off = []
            if grid is not None:
                for e in raw["events"]:
                    beats = grid.bar_at(e["t"]) * 4
                    song_off.append(abs(beats - 4 * round(beats / 4)))
            offsets += song_off
            vocal_means.append(float(np.mean(res_g["vocal"])) if res_g["vocal"] else 0.0)

            def listed(kind):
                return " ".join(mmss(e["t"]) for e in res_g["events"] if e["type"] == kind) or "-"

            grid_txt = f"{grid.bpm:6.1f} BPM c{grid.confidence:.2f}" if grid else "sin rejilla      "
            off_txt = f"desfase medio {np.mean(song_off):.2f} golpes" if song_off else "desfase -"
            print(f"     {name:34s} {grid_txt} | drops {listed('drop'):18s} | subidas {listed('buildup'):12s} | breaks "
                  f"{listed('break'):12s} | {off_txt} | voz media {vocal_means[-1]:.2f} | {times[-1]:.2f} s", flush=True)
        except Exception as e:
            errors += 1
            print(f"FALLO {name}: excepción {type(e).__name__}: {e}", flush=True)
    check("canciones reales: ninguna da excepción", errors == 0)
    if times:
        near = float(np.mean(np.array(offsets) <= 0.5)) if offsets else float("nan")
        print(f"     total: {counts['drop']} drops, {counts['buildup']} subidas, {counts['break']} breaks en {len(times)} canciones; "
              f"eventos a menos de medio golpe de un compás (sin ajustar): {near:.0%} de {len(offsets)} (al azar ~25 %); "
              f"tiempo de analyse medio {np.mean(times):.2f} s, máximo {max(times):.2f} s; voz media {np.mean(vocal_means):.2f}",
              flush=True)


if "--reales" in sys.argv:
    rest = sys.argv[sys.argv.index("--reales") + 1:]
    real_songs(rest[0] if rest else r"C:\Users\juego\Music\Canciones_YouTube")
print("FIN", flush=True)
