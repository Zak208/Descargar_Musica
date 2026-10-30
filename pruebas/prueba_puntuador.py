"""Puntuador automático de transiciones (fase 25) con casos sintéticos de respuesta conocida: golpes alineados y desfasados,
graves dobles, salto de volumen, recorte, hueco de silencio, clic, voces solapadas, tonos lejanos y vecinos, entradas raras
y velocidad. Comprueba que cada medida da el valor físico esperado y que el veredicto cambia como debe; NO comprueba que
coincida con el oído (eso solo se puede escuchando).
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_puntuador.py
Con  --reales [carpeta]  además puntúa (informativo, no es una prueba) las transiciones que el planificador propone entre
4 canciones de la carpeta (por omisión ~/Music/Canciones_YouTube; solo se leen)."""
import os
import sys
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import dj_dsp, transition_scorer as ts
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid, TransitionPlan

SR = SAMPLE_RATE


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def song(secs, bpm=120.0, kick_hz=55.0, bass_hz=82.0, pads=(440.0, 660.0), seed=0, offset_s=0.0, level=1.0):
    """Canción de mentira: bombo en cada golpe (con barrido de tono, como uno de verdad), bajo corto a contratiempo, un
    colchón de dos notas y hi-hat de ruido a contratiempo. Estéreo con los canales algo distintos."""
    n = int(secs * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    beat = 60.0 / bpm
    seg = int(0.35 * SR)
    ts_ = np.arange(seg) / SR
    kick = 0.45 * np.exp(-ts_ / 0.12) * np.sin(2 * np.pi * (kick_hz * ts_ + 60.0 * 0.03 * (1 - np.exp(-ts_ / 0.03))))
    bass = 0.18 * np.exp(-ts_ / 0.15) * np.sin(2 * np.pi * bass_hz * ts_) * np.minimum(1.0, ts_ / 0.004)
    hat = 0.05 * np.exp(-ts_ / 0.02) * np.diff(rng.standard_normal(seg + 1))
    k = 0
    while True:
        start = offset_s + k * beat
        if start >= secs:
            break
        for piece, at in ((kick, start), (bass, start + beat / 2), (hat, start + beat / 2)):
            i = int(round(at * SR))
            if 0 <= i < n:
                m = min(seg, n - i)
                x[i:i + m] += piece[:m]
        k += 1
    pad = sum(0.06 * np.sin(2 * np.pi * f * t) for f in pads)
    left = x + pad
    right = x + sum(0.06 * np.sin(2 * np.pi * f * t + 0.7) for f in pads)
    return (level * np.stack([left, right], axis=1)).astype(np.float32)


def blend_plan(length=16.0, swap=8.0):
    return TransitionPlan(a_start_s=0.0, b_start_s=0.0, length_s=length, tempo_ratio_b=1.0, bass_swap_s=swap)


L = 16.0
N = int(L * SR)
A = song(L, seed=1)
B = song(L, kick_hz=48.0, bass_hz=98.0, pads=(523.0, 784.0), seed=2)
PLAN = blend_plan()
GRID = BeatGrid(0.0, 120.0, 4, 0, 0.9)
MIX = dj_dsp.render_transition(A, B, PLAN)

# ------------------------------------------------------------------ (1) bien alineadas con render_transition
r1 = ts.score_audio(MIX, A, B, PLAN, GRID, GRID)
m1 = r1["metrics"]
check(f"(1) mezcla bien hecha: «ok» (da {r1['verdict']}, nota {r1['score']}; {r1['reasons']})", r1["verdict"] == "ok")
check(f"(1) desfase de golpes casi 0 (da {m1['beat_offset_ms']['value']} ms)",
      m1["beat_offset_ms"]["value"] is not None and m1["beat_offset_ms"]["value"] < 3.0)
check(f"(1) sin graves dobles (da {m1['bass_clash']['value']})", m1["bass_clash"]["value"] < 0.02)
check(f"(1) sin salto de volumen (da {m1['loudness_step_db']['value']} dB)", m1["loudness_step_db"]["value"] < 3.0)
check(f"(1) sin recorte, hueco ni clic (recorte {m1['clipping']['value']}, hueco {m1['silence_gap_ms']['value']} ms, "
      f"clic {m1['click']['value']} veces)",
      m1["clipping"]["value"] == 0 and m1["silence_gap_ms"]["value"] == 0 and m1["click"]["note"] == 1.0)
r1b = ts.score_audio(MIX, A, B, PLAN)
off1b = r1b["metrics"]["beat_offset_ms"]["value"]
check(f"(1) sin rejillas da el mismo desfase (da {off1b} ms)", off1b is not None and abs(off1b - m1["beat_offset_ms"]["value"]) < 1)

# ------------------------------------------------------------------ (2) B desfasada 80 ms (y 20 ms, que no galopa)
for shift, expect in ((0.080, ("descartar", "dudosa")), (0.020, ("ok", "dudosa")), (-0.040, ("descartar", "dudosa"))):
    Bs = song(L, kick_hz=48.0, bass_hz=98.0, pads=(523.0, 784.0), seed=2, offset_s=max(shift, 0.0) or (0.5 + shift))
    mix_s = dj_dsp.render_transition(A, Bs, PLAN)
    r = ts.score_audio(mix_s, A, Bs, PLAN, GRID, GRID)
    got = r["metrics"]["beat_offset_ms"]
    want = shift * 1000.0
    check(f"(2) B desfasada {want:+.0f} ms: mide {got.get('signed_ms')} ms y queda «{r['verdict']}»",
          got["value"] is not None and abs(got["signed_ms"] - want) <= 3.0 and r["verdict"] in expect)
r20 = ts.score_audio(dj_dsp.render_transition(A, song(L, kick_hz=48.0, bass_hz=98.0, pads=(523.0, 784.0), seed=2,
                                                       offset_s=0.08), PLAN), A,
                     song(L, kick_hz=48.0, bass_hz=98.0, pads=(523.0, 784.0), seed=2, offset_s=0.08), PLAN)
check(f"(2) con 80 ms la nota baja respecto a la alineada ({r20['score']} < {r1['score']})", r20["score"] < r1["score"])
half = song(L, kick_hz=48.0, bass_hz=98.0, pads=(523.0, 784.0), seed=2, offset_s=0.25)
r_half = ts.score_audio(dj_dsp.render_transition(A, half, PLAN), A, half, PLAN, GRID, GRID)
check(f"(2) B a medio golpe (250 ms, bombo en el contratiempo): desfase de 100 ms o más (da "
      f"{r_half['metrics']['beat_offset_ms']['signed_ms']} ms) y «{r_half['verdict']}»",
      (r_half["metrics"]["beat_offset_ms"]["value"] or 0) >= 100 and r_half["verdict"] == "descartar")
stretched_grid = BeatGrid(0.0, 120.0 / 1.05, 4, 0, 0.9)          # rejilla de B en su tempo original (5 % más lenta)
r_st = ts.score_audio(MIX, A, B, TransitionPlan(0.0, 0.0, L, 1.05, 8.0), None, stretched_grid)
check(f"(2) solo con la rejilla de B (en su tempo original, estirada un 5 %): mismo desfase 0 (da "
      f"{r_st['metrics']['beat_offset_ms']['value']} ms)", r_st["metrics"]["beat_offset_ms"]["value"] is not None
      and r_st["metrics"]["beat_offset_ms"]["value"] < 3.0)
calm_a = np.stack([0.1 * np.sin(2 * np.pi * 220 * np.arange(N) / SR)] * 2, axis=1).astype(np.float32)
calm_b = np.stack([0.1 * np.sin(2 * np.pi * 330 * np.arange(N) / SR)] * 2, axis=1).astype(np.float32)
r_calm = ts.score_audio(dj_dsp.render_transition(calm_a, calm_b, PLAN), calm_a, calm_b, PLAN)
check(f"(2) dos colchones sin golpes: no se inventa un desfase (da {r_calm['metrics']['beat_offset_ms']['value']}) y no se "
      f"descarta por eso («{r_calm['verdict']}»)", r_calm["metrics"]["beat_offset_ms"]["value"] is None and r_calm["verdict"] == "ok")

# ------------------------------------------------------------------ (3) graves de las dos a la vez
ang = (np.arange(N) + 0.5) / N * (np.pi / 2)
hand = (np.cos(ang)[:, None] * A + np.sin(ang)[:, None] * B).astype(np.float32)     # fundido sin cambio de graves
r3 = ts.score_audio(hand, A, B, PLAN, GRID, GRID)
c3 = r3["metrics"]["bass_clash"]["value"]
check(f"(3) fundido a mano sin cambio de graves: graves dobles en buena parte (da {c3}; tiempo de solape ~0,68, menos los "
      f"tramos entre golpes)", 0.45 <= c3 <= 0.75)
check(f"(3) y se descarta (da {r3['verdict']})", r3["verdict"] == "descartar")
both = (A + B).astype(np.float32) * 0.7
r3b = ts.score_audio(both, A, B, PLAN)
check(f"(3) las dos enteras toda la mezcla: más graves dobles todavía (da {r3b['metrics']['bass_clash']['value']})",
      r3b["metrics"]["bass_clash"]["value"] > c3 + 0.1)
late = ts.score_audio(dj_dsp.render_transition(A, B, blend_plan(swap=15.0)), A, B, blend_plan(swap=15.0))
check(f"(3) un cambio de graves tardío pero hecho con render_transition no crea graves dobles (da "
      f"{late['metrics']['bass_clash']['value']})", late["metrics"]["bass_clash"]["value"] < 0.02)

# ------------------------------------------------------------------ (4) salto de +9 dB en mitad de la mezcla
quiet_a, quiet_b = A * 0.25, B * 0.25
mix4 = dj_dsp.render_transition(quiet_a, quiet_b, PLAN).astype(np.float64)
ramp = int(0.02 * SR)
gain = np.ones(N)
gain[N // 2:N // 2 + ramp] = np.linspace(1.0, 10 ** (9 / 20), ramp)
gain[N // 2 + ramp:] = 10 ** (9 / 20)
mix4 = (mix4 * gain[:, None]).astype(np.float32)
r4 = ts.score_audio(mix4, quiet_a, quiet_b, PLAN, GRID, GRID)
s4 = r4["metrics"]["loudness_step_db"]
check(f"(4) salto de +9 dB: mide {s4['value']} dB a los {s4['at_s']} s (esperado ~9 a los 8 s)",
      abs(s4["value"] - 9.0) <= 1.0 and abs(s4["at_s"] - 8.0) <= 0.5)
check(f"(4) sin recorte ni clic que lo confundan (recorte {r4['metrics']['clipping']['value']}, clic "
      f"{r4['metrics']['click']['note']})", r4["metrics"]["clipping"]["value"] == 0 and r4["metrics"]["click"]["note"] == 1.0)
check(f"(4) y se descarta (da {r4['verdict']})", r4["verdict"] == "descartar")
before4 = song(4, seed=1, level=0.25)
after4 = song(4, kick_hz=48.0, bass_hz=98.0, pads=(523.0, 784.0), seed=2, level=0.25)
low_mix = (dj_dsp.render_transition(quiet_a, quiet_b, PLAN) * 10 ** (-9 / 20)).astype(np.float32)
alone = ts.score_audio(low_mix, quiet_a, quiet_b, PLAN)["metrics"]["loudness_step_db"]["value"]
ctx = ts.score_audio(low_mix, quiet_a, quiet_b, PLAN, a_before=before4, b_after=after4)["metrics"]["loudness_step_db"]
check(f"(4) una mezcla entera 9 dB más floja que lo que la rodea: sin contexto no se ve ({alone} dB) y con los 2 s de antes "
      f"y de después sí, en un extremo (da {ctx['value']} dB a los {ctx['at_s']} s)",
      alone < 3.0 and abs(ctx["value"] - 9.0) <= 1.5 and min(abs(ctx["at_s"]), abs(ctx["at_s"] - L)) <= 0.5)
grow_b = np.concatenate([after4[:SR], after4[SR:] * 10 ** (9 / 20)])
nat_b = ts.score_audio(dj_dsp.render_transition(quiet_a, quiet_b, PLAN), quiet_a, quiet_b, PLAN, a_before=before4,
                       b_after=grow_b)["metrics"]["loudness_step_db"]["value"]
check(f"(4) un salto que ya trae B (sube 9 dB 1 s después de acabar la mezcla) no se le cobra a la mezcla (da {nat_b} dB)",
      nat_b < 3.0)
loud_b = song(L, kick_hz=48.0, bass_hz=98.0, pads=(523.0, 784.0), seed=2, level=0.25 * 10 ** (12 / 20))
fade_hand = (np.cos(ang)[:, None] * quiet_a + np.sin(ang)[:, None] * loud_b).astype(np.float32)
nat = ts.score_audio(fade_hand, quiet_a, loud_b, PLAN)["metrics"]["loudness_step_db"]["value"]
check(f"(4) una B 12 dB más fuerte con un fundido continuo de 16 s no es un salto (da {nat} dB)", nat < 3.0)
swap_jump = ts.score_audio(dj_dsp.render_transition(quiet_a, loud_b, PLAN), quiet_a, loud_b, PLAN)["metrics"]["loudness_step_db"]
check(f"(4) pero con cambio de graves sí: los graves de B, 12 dB más fuertes, entran de golpe (da {swap_jump['value']} dB a los "
      f"{swap_jump['at_s']} s)", swap_jump["value"] >= 5.0 and abs(swap_jump["at_s"] - 8.0) <= 0.5)
cut_plan = TransitionPlan(0.0, 0.0, 0.0, kind=KIND_CUT)
a_cut, b_cut = A[:4 * SR] * 0.5, B[:4 * SR] * 0.5 * 10 ** (-12 / 20)
r_cut = ts.score_audio(dj_dsp.render_transition(a_cut, b_cut, cut_plan), a_cut, b_cut, cut_plan)
check(f"(4) corte de A a una B 12 dB más floja: salto de ~12 dB (da {r_cut['metrics']['loudness_step_db']['value']}) y "
      f"«{r_cut['verdict']}»", abs(r_cut["metrics"]["loudness_step_db"]["value"] - 12.0) <= 1.5 and r_cut["verdict"] == "descartar")
b_cut2 = B[:4 * SR] * 0.5
r_cut2 = ts.score_audio(dj_dsp.render_transition(a_cut, b_cut2, cut_plan), a_cut, b_cut2, cut_plan)
check(f"(4) corte entre dos del mismo volumen: «ok» (da {r_cut2['verdict']}, salto "
      f"{r_cut2['metrics']['loudness_step_db']['value']} dB; {r_cut2['reasons']})", r_cut2["verdict"] == "ok")

# ------------------------------------------------------------------ (5) recorte
mix5 = (MIX * 3.0).astype(np.float32)
r5 = ts.score_audio(mix5, A, B, PLAN, GRID, GRID)
c5 = r5["metrics"]["clipping"]
check(f"(5) mezcla que pasa de 1,0: recorte {c5['value']} (pico {c5['peak']}) y «{r5['verdict']}»",
      c5["value"] > 1e-3 and r5["verdict"] == "descartar")
hot = (A * 3.0).astype(np.float32)
r5b = ts.score_audio(np.concatenate([hot[:N // 2], MIX[N // 2:]]), hot, B, PLAN)
check(f"(5) el recorte que ya traía A no se le cobra a la mezcla (recorte añadido {r5b['metrics']['clipping']['added']})",
      r5b["metrics"]["clipping"]["added"] < 1e-4)

# ------------------------------------------------------------------ (6) hueco de 300 ms
mix6 = MIX.copy()
g0, g1 = int(7.5 * SR), int(7.8 * SR)
r = int(0.005 * SR)
mix6[g0 - r:g0] *= np.linspace(1, 0, r, dtype=np.float32)[:, None]
mix6[g0:g1] = 0.0
mix6[g1:g1 + r] *= np.linspace(0, 1, r, dtype=np.float32)[:, None]
r6 = ts.score_audio(mix6, A, B, PLAN, GRID, GRID)
gap = r6["metrics"]["silence_gap_ms"]["value"]
check(f"(6) hueco de 300 ms: mide {gap} ms y queda «{r6['verdict']}»", abs(gap - 300) <= 20 and r6["verdict"] != "ok")

# ------------------------------------------------------------------ (7) clic
mix7 = MIX.copy()
k7 = int(5.0 * SR) + 17
mix7[k7] += 0.5
r7 = ts.score_audio(mix7, A, B, PLAN, GRID, GRID)
c7 = r7["metrics"]["click"]
check(f"(7) un clic de 0,5: {c7['value']} veces lo normal a los {c7['at_s']} s (las canciones: {c7['parts']}) y «{r7['verdict']}»",
      c7["note"] == 0.0 and abs(c7["at_s"] - k7 / SR) < 0.001 and r7["verdict"] == "descartar")
mix7b = MIX.copy()
mix7b[k7:] += 0.1                                    # escalón de continua de 0,1 (-20 dBFS): un clic más flojo
r7b = ts.score_audio(mix7b, A, B, PLAN)
check(f"(7) un escalón de 0,1 también es clic (da {r7b['metrics']['click']['value']} veces)", r7b["metrics"]["click"]["note"] == 0.0)
check(f"(7) sin clic, la mezcla buena se queda por debajo del umbral (da {m1['click']['value']} veces; las canciones "
      f"{m1['click']['parts']})", m1["click"]["value"] < ts.CLICK_RATIO)

# ------------------------------------------------------------------ voces
ones, zeros = [1.0] * 16, [0.0] * 16
rv = ts.score_audio(MIX, A, B, PLAN, a_vocal=ones, b_vocal=ones)
vo = rv["metrics"]["vocal_overlap"]
check(f"voces en las dos toda la mezcla: solapadas donde suenan las dos (da {vo['value']}, teórico ~0,69) y «{rv['verdict']}»",
      0.6 <= vo["value"] <= 0.75 and rv["verdict"] == "descartar")
rv2 = ts.score_audio(MIX, A, B, PLAN, a_vocal=ones[:8] + zeros[:8], b_vocal=zeros[:9] + ones[:7])
check(f"voces que se relevan (A hasta el 8, B desde el 9): sin solape (da {rv2['metrics']['vocal_overlap']['value']})",
      rv2["metrics"]["vocal_overlap"]["value"] == 0.0)
check("sin curvas de voz, la medida es None", r1["metrics"]["vocal_overlap"]["value"] is None)

# ------------------------------------------------------------------ (8) tonos en score_plan
dur = {"duration_s": 200.0, "energy": 0.6}
grid_a = BeatGrid(1.0, 124.0, 4, 0, 0.85)
grid_b = BeatGrid(0.5, 124.0, 4, 0, 0.8)
plan8 = TransitionPlan(150.0, 10.0, 15.48, 1.0, 7.74)


def info(tone, conf=0.9, grid=grid_a, **extra):
    return {**dur, "tone": tone, "tone_conf": conf, "beatgrid": grid, "bpm": 124.0, **extra}


near = ts.score_plan(info("8A"), info("9A", grid=grid_b), plan8)
same = ts.score_plan(info("8A"), info("8A", grid=grid_b), plan8)
far = ts.score_plan(info("8A"), info("2B", grid=grid_b), plan8)
far_doubt = ts.score_plan(info("8A"), info("2B", conf=0.3, grid=grid_b), plan8)
check(f"(8) tonos vecinos (8A y 9A): «ok» (nota {near['score']})", near["verdict"] == "ok")
check(f"(8) mismo tono: nota igual o mayor que vecinos ({same['score']} >= {near['score']})", same["score"] >= near["score"])
check(f"(8) tonos lejanos (8A y 2B): «dudosa» y nota más baja ({far['score']}; {far['reasons']})",
      far["verdict"] == "dudosa" and far["score"] < near["score"])
check(f"(8) lejanos pero con un tono dudoso: pesa menos (nota {far_doubt['score']} entre {far['score']} y {near['score']})",
      far["score"] < far_doubt["score"] <= near["score"])
check("(8) el tono también vale escrito como «Am» y «C#»",
      ts.score_plan(info("Am"), info("C#", grid=grid_b), plan8)["metrics"]["tone_clash"]["value"] == 1.0)
fast = ts.score_plan(info("8A"), info("8A", grid=grid_b), TransitionPlan(150.0, 10.0, 15.48, 1.12, 7.74))
check(f"(8) cambio de tempo del 12 %: «descartar» (da {fast['verdict']})", fast["verdict"] == "descartar")
nofit = ts.score_plan(info("8A"), info("8A", grid=grid_b), TransitionPlan(190.0, 10.0, 15.48, 1.0, 7.74))
check(f"(8) mezcla que no cabe en A: «descartar» ({nofit['reasons']})", nofit["verdict"] == "descartar")
nogrid = ts.score_plan(info("8A", grid=None), info("8A", grid=None), plan8)
check(f"(8) sin rejillas y mezcla de 15 s: «dudosa» (da {nogrid['verdict']})", nogrid["verdict"] == "dudosa")
jump = ts.score_plan(info("8A", energy=0.1), info("8A", grid=grid_b, energy=0.9), plan8)
check(f"(8) salto de energía de 0,1 a 0,9 baja la nota ({jump['score']} < {same['score']})", jump["score"] < same["score"])
raw = ts.score_plan({"duration_ms": 200000, "tone": "8A", "tone_conf": 0.9, "beat_conf": 0.8, "beat_bpm": 124.0, "energy": 0.6},
                    {"duration_ms": 200000, "tone": "9A", "tone_conf": 0.9, "beat_conf": 0.8, "beat_bpm": 124.0, "energy": 0.6},
                    plan8)
check(f"(8) acepta el análisis tal cual (en ms y con beat_conf): «ok» (da {raw['verdict']})", raw["verdict"] == "ok")
cut8 = ts.score_plan(info("8A"), info("2B", grid=grid_b), TransitionPlan(150.0, 10.0, 0.0, kind=KIND_CUT))
check(f"(8) en un corte, tonos lejanos no impiden «ok» (da {cut8['verdict']}, nota {cut8['score']})", cut8["verdict"] == "ok")

# ------------------------------------------------------------------ (9) entradas raras
odd = []
cases = [
    ("todo vacío", (np.zeros((0, 2)), np.zeros((0, 2)), np.zeros((0, 2)), PLAN)),
    ("None", (None, None, None, None)),
    ("mono", (MIX[:, 0], A[:, 0], B[:, 0], PLAN)),
    ("listas", (MIX[:1000].tolist(), A[:1000].tolist(), B[:1000].tolist(), PLAN)),
    ("muy corta", (MIX[:50], A[:50], B[:50], PLAN)),
    ("una muestra", (MIX[:1], A[:1], B[:1], PLAN)),
    ("NaN en todo", (np.full((1000, 2), np.nan), np.full((1000, 2), np.nan), np.full((1000, 2), np.inf), PLAN)),
    ("3 dimensiones y texto", (np.zeros((4, 4, 4)), "hola", 7, PLAN)),
    ("silencio", (np.zeros((N, 2)), np.zeros((N, 2)), np.zeros((N, 2)), PLAN)),
    ("plan raro", (MIX, A, B, "no es un plan")),
    ("corte vacío", (np.zeros((0, 2)), np.zeros((0, 2)), np.zeros((0, 2)), cut_plan)),
    ("más canales", (np.zeros((5000, 6)), np.zeros((5000, 6)), np.zeros((5000, 6)), PLAN)),
]
for name, args in cases:
    try:
        res = ts.score_audio(*args, a_vocal=[float("nan")] * 3, b_vocal="x", sample_rate=float("nan"),
                             tone_a="zz", tone_b=None, a_before=np.full((10, 2), np.nan))
        if res.get("verdict") not in ("ok", "dudosa", "descartar") or not 0 <= res.get("score", -1) <= 1:
            odd.append(f"{name}: {res}")
    except Exception as e:
        odd.append(f"{name}: {type(e).__name__} {e}")
for name, args in (("nada", (None, None, None)), ("raro", ("x", 3, object())), ("sin plan", ({}, {}, None)),
                   ("NaN", ({"duration_s": float("nan"), "energy": float("nan"), "tone": 5},
                            {"beatgrid": "x", "tone_conf": "y"}, TransitionPlan(float("nan"), 0, 16)))):
    try:
        res = ts.score_plan(*args)
        if res.get("verdict") not in ("ok", "dudosa", "descartar"):
            odd.append(f"plan {name}: {res}")
    except Exception as e:
        odd.append(f"plan {name}: {type(e).__name__} {e}")
check(f"(9) entradas vacías, mono, NaN, muy cortas o raras no lanzan excepciones ({odd or 'ninguna'})", not odd)
nan_mix = MIX.copy()
nan_mix[100] = np.nan
check("(9) una mezcla con NaN se descarta", ts.score_audio(nan_mix, A, B, PLAN)["verdict"] == "descartar")
check("(9) una mezcla vacía se descarta", ts.score_audio(np.zeros((0, 2)), A, B, PLAN)["verdict"] == "descartar")
check("(9) score_plan sin plan descarta", ts.score_plan({}, {}, None)["verdict"] == "descartar")

# ------------------------------------------------------------------ rendimiento
L32 = 32.0
A32, B32 = song(L32, seed=3), song(L32, kick_hz=48.0, bass_hz=98.0, pads=(523.0, 784.0), seed=4)
P32 = blend_plan(L32, 16.0)
M32 = dj_dsp.render_transition(A32, B32, P32)
ts.score_audio(M32[:SR * 3], A32[:SR * 3], B32[:SR * 3], blend_plan(3.0, 1.5))          # calentar
t0 = time.perf_counter()
r32 = ts.score_audio(M32, A32, B32, P32, GRID, GRID, a_vocal=[0.0] * 32, b_vocal=[1.0] * 32,
                     a_before=song(2, seed=3), b_after=song(2, seed=4))
el = time.perf_counter() - t0
check(f"una mezcla de 32 s se puntúa en menos de 1 s (tarda {el:.2f} s; «{r32['verdict']}»)", el < 1.0 and r32["verdict"] == "ok")
t0 = time.perf_counter()
for _ in range(1000):
    ts.score_plan(info("8A"), info("9A", grid=grid_b), plan8)
check(f"score_plan es barato (1000 en {time.perf_counter() - t0:.3f} s)", time.perf_counter() - t0 < 1.0)


# ------------------------------------------------------------------ informativo con canciones reales
def informativo(folder):
    """Puntúa las transiciones que propone el planificador entre 4 canciones reales. No es una prueba: solo enseña cifras."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from services import mix_planner, pcm_loader, track_analysis
    import itertools
    names = sorted(f for f in os.listdir(folder) if f.lower().endswith(".mp3"))
    print(f"analizando {len(names)} canciones (datos aislados; puede tardar un par de minutos)...", flush=True)
    every = []
    for name in names:
        path = os.path.join(folder, name)
        res = track_analysis.analyze(path) or {}
        info_ = dict(res)
        info_["beatgrid"] = track_analysis.grid_from(res)
        info_["path"] = path
        every.append(info_)
    # 4 canciones en el orden con más pares que se pueden mezclar (tempo a menos del 8 %), para ver mezclas y no solo cortes

    def mixable(x, y):
        r = mix_planner.tempo_ratio(x.get("bpm"), y.get("bpm"))
        return r is not None and abs(r - 1) <= mix_planner.MAX_TEMPO_CHANGE

    best = max(itertools.permutations(range(len(every)), min(4, len(every))),
               key=lambda p: sum(mixable(every[i], every[j]) for i, j in zip(p, p[1:])))
    infos = [every[i] for i in best]
    for info_ in infos:
        print(f"   {os.path.basename(info_['path'])[:50]:50} bpm={info_.get('bpm')} tono={info_.get('tone')} "
              f"({info_.get('tone_conf')}) energía={info_.get('energy')} rejilla={info_.get('beat_conf')}", flush=True)
    for a_i, b_i in zip(infos, infos[1:]):
        plan = mix_planner.plan_transition(a_i, b_i)
        print(f"\n== {os.path.basename(a_i['path'])[:40]} -> {os.path.basename(b_i['path'])[:40]}", flush=True)
        print(f"   plan: {plan.kind} desde {plan.a_start_s} s, {plan.length_s} s, B desde {plan.b_start_s} s, "
              f"tempo x{plan.tempo_ratio_b}; {plan.reason}", flush=True)
        p = ts.score_plan(a_i, b_i, plan)
        print(f"   score_plan: {p['score']} «{p['verdict']}» {p['reasons']}", flush=True)
        print("      " + "; ".join(f"{k}={m['value']} (nota {m['note']})" for k, m in p["metrics"].items()), flush=True)
        ratio = plan.tempo_ratio_b or 1.0
        if plan.kind == KIND_CUT or plan.length_s <= 0:
            a_part = pcm_loader.load(a_i["path"], start_s=max(0.0, plan.a_start_s - 0.5), duration_s=0.5)
            b_part = pcm_loader.load(b_i["path"], start_s=plan.b_start_s, duration_s=0.5)
            before = after = None
        else:
            a_part = pcm_loader.load(a_i["path"], start_s=plan.a_start_s, duration_s=plan.length_s)
            b_part = pcm_loader.load(b_i["path"], tempo_ratio=ratio, start_s=plan.b_start_s, duration_s=plan.length_s * ratio)
            before = pcm_loader.load(a_i["path"], start_s=max(0.0, plan.a_start_s - 2.0), duration_s=2.0)
            after = pcm_loader.load(b_i["path"], start_s=plan.b_start_s + plan.length_s * ratio, duration_s=2.0)
        if a_part is None or b_part is None:
            print("   no se pudo cargar el audio", flush=True)
            continue
        mix = dj_dsp.render_transition(a_part, b_part, plan)
        t0 = time.perf_counter()
        r = ts.score_audio(mix, a_part, b_part, plan, a_i["beatgrid"], b_i["beatgrid"], tone_a=a_i.get("tone"),
                           tone_b=b_i.get("tone"), tone_conf_a=a_i.get("tone_conf"), tone_conf_b=b_i.get("tone_conf"),
                           a_before=before, b_after=after)
        print(f"   score_audio ({time.perf_counter() - t0:.2f} s): {r['score']} «{r['verdict']}» {r['reasons']}", flush=True)
        print("      " + "; ".join(f"{k}={m['value']} (nota {m['note']})" for k, m in r["metrics"].items()), flush=True)


if "--reales" in sys.argv:
    rest = sys.argv[sys.argv.index("--reales") + 1:]
    informativo(rest[0] if rest else os.path.expanduser("~/Music/Canciones_YouTube"))
print("FIN", flush=True)
