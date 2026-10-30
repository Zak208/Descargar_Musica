"""Sesión de votos con aprendizaje activo (fase 27), sin ventana: candidatas de la biblioteca (sin audio), elección de la
siguiente (la que más duda, con diversidad y algo de azar; sin modelo, por cobertura), clips de verdad con canciones wav
sintéticas (cada tipo de transición, caché que borra los viejos), voto guardado con origen «clip», y una SIMULACIÓN que mide
cuántos votos hacen falta con selección activa frente a aleatoria con un gusto sintético conocido.

La simulación mide, no demuestra: el plan dice «con aprendizaje activo hace falta más o menos la mitad»; aquí sale la cifra
que sale con un gusto que es una fórmula con ruido. Con votos de una persona puede ser otra.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_sesion_votos.py"""
import logging
import math
import os
import random
import sys
import tempfile
import time
import wave

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import taste_model as tm
from services import transition_votes, vote_session
from services.mix_types import BeatGrid

logging.disable(logging.CRITICAL)


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def info(msg):
    print("     " + msg, flush=True)


def library(n, seed):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        family = rng.choice((92, 96, 124, 128, 172))
        bpm = family * rng.uniform(0.97, 1.03)
        grid = BeatGrid(0.12, bpm, 4, 0, rng.uniform(0.2, 0.95)) if rng.random() < 0.8 else None
        out.append({"path": f"C:/musica/cancion_{seed}_{i}.mp3", "title": f"Canción {i}", "bpm": bpm, "beatgrid": grid,
                    "tone": f"{rng.randint(1, 12)}{rng.choice('AB')}", "tone_conf": rng.uniform(0.3, 1.0),
                    "energy": rng.uniform(0.1, 0.95), "duration_s": rng.uniform(150, 240), "intro_s": rng.uniform(4, 30),
                    "outro_s": rng.uniform(6, 40)})
    return out


NAMES = tm.PLAN_FEATURES


def true_p(c, bias=1.5):
    f = dict(zip(NAMES, tm.features(c)))
    gap = f["bpm_gap"] if f["bpm_gap"] == f["bpm_gap"] else 4.0
    key = f["key_score"] if f["key_score"] == f["key_score"] else 0.5
    grid = f["grid_conf"] if f["grid_conf"] == f["grid_conf"] else 0.3
    z = 2.0 * (bias - 0.35 * gap - 2.0 * (key <= 0.0) + 1.0 * f["kind_blend"] - 0.5 * f["kind_cut_bar"] - 1.5 * f["kind_cut"]
               - 2.5 * f["energy_abs"] + 1.5 * (grid - 0.5))
    return 1.0 / (1.0 + math.exp(-z))


# ------------------------------------------------------------------ candidatas
check("con menos de dos canciones no hay candidatas", vote_session.build_candidates([]) == []
      and vote_session.build_candidates(library(1, 0)) == [] and vote_session.build_candidates([None, "x", {}]) == [])
lib = library(60, 4)
cands = vote_session.build_candidates(lib, 500, random.Random(1))
check(f"da hasta n candidatas ({len(cands)} de 500)", 0 < len(cands) <= 500)
kinds = {c["kind"] for c in cands}
check(f"con los cuatro tipos y los cortes del planificador ({sorted(kinds)})", {"blend", "cut_bar", "echo_out", "filter", "cut"} <= kinds)
check("con varias duraciones (4, 8 y 16 compases)", {4, 8, 16} <= {c["bars"] for c in cands})
check("ninguna mezcla una canción consigo misma", all(c["a_path"] != c["b_path"] for c in cands))
share = sum(c["reasonable"] for c in cands) / len(cands)
info(f"parejas razonables según el planificador: {share * 100:.0f} % (el resto, al azar, para que el modelo vea lo malo)")
check("la mayoría son parejas razonables, pero no todas", 0.45 < share < 0.95)
check("sin audio: solo planes (nada de clips todavía)", all("clip_path" not in c and c["plan"] is not None for c in cands))
check("los cortes del planificador solo salen como «cut»",
      all(c["kind"] == "cut" for c in cands if c["plan"].kind == "cut") and all(c["plan"].kind == "cut" for c in cands if c["kind"] == "cut"))

# ------------------------------------------------------------------ elegir sin modelo: cobertura y diversidad
rng = random.Random(5)
hist = []
for _ in range(40):
    c = vote_session.select_next(cands, None, hist, epsilon=0.0, rng=rng)
    hist.append(c)
check("sin modelo, las 5 primeras cubren los 5 tipos", len({c["kind"] for c in hist[:5]}) == 5)
check("nunca el mismo tipo dos veces seguidas", all(a["kind"] != b["kind"] for a, b in zip(hist, hist[1:])))
check("ni una canción de la anterior justo detrás", all(not vote_session._shares_track(a, b) for a, b in zip(hist, hist[1:])))
check("ni la misma pareja en las 8 anteriores",
      all(vote_session.pair_key(c) not in {vote_session.pair_key(h) for h in hist[max(0, i - 8):i]} for i, c in enumerate(hist)))
check("ni se repite una ya enseñada", len({c["id"] for c in hist}) == len(hist))
tracks = {vote_session._key(p) for c in hist for p in (c["a_path"], c["b_path"])}
check(f"y reparte canciones ({len(tracks)} distintas en 40)", len(tracks) >= 30)
small = cands[:3]
h2 = []
for _ in range(3):
    h2.append(vote_session.select_next(small, None, h2, epsilon=0.0, rng=rng))
check("cuando se acaban, devuelve None (y antes no se atasca por la diversidad)",
      None not in h2 and vote_session.select_next(small, None, h2, rng=rng) is None)

# ------------------------------------------------------------------ elegir con modelo: la que más duda
votes = []
r = random.Random(6)
for c in cands[:200]:
    votes.append(dict(c, vote=1 if r.random() < true_p(c) else -1))
model = tm.TasteModel().fit(votes)
pick = vote_session.select_next(cands, model, [], epsilon=0.0, rng=random.Random(7))
p_all = model.predict_proba(cands)
check("con modelo elige la que más duda (probabilidad más cerca de 0,5)",
      abs(model.predict_proba(pick) - 0.5) <= float(np.min(np.abs(p_all - 0.5))) + 1e-9)
draws = {vote_session.select_next(cands, model, [], epsilon=1.0, rng=random.Random(i))["id"] for i in range(30)}
check("con epsilon = 1 elige al azar (salen muchas distintas)", len(draws) > 15)
check("la caché de características no se cuela en la copia renderizable", "_x" in pick and "_x" not in vote_session._clean_copy(pick))


# ------------------------------------------------------------------ simulación: activa frente a aleatoria
def simulate(strategy, pool, test, seed, checkpoints, bias):
    """(coincidencia con el gusto real sin ruido, AUC) en cada punto de control. «activa» es la sesión de verdad
    (`select_next` con el modelo reentrenado cada 10 votos); «aleatoria», una candidata no enseñada al azar."""
    rng = random.Random(seed)
    vrng = random.Random(seed + 1000)
    hist, rows, model, out = [], [], None, {}
    X_test = tm.matrix(test)
    truth = np.array([c["_tp"][bias] for c in test])
    while len(rows) < checkpoints[-1]:
        if strategy == "activa":
            c = vote_session.select_next(pool, model, hist, epsilon=vote_session.EPSILON, rng=rng)
        else:
            shown = {h["id"] for h in hist}
            c = rng.choice([x for x in pool if x["id"] not in shown])
        hist.append(c)
        rows.append(dict(c, vote=1 if vrng.random() < c["_tp"][bias] else -1))
        n = len(rows)
        if n % vote_session.RETRAIN_EVERY == 0:
            try:
                model = tm.TasteModel().fit(rows)
            except tm.NotEnoughData:
                model = None
        if n in checkpoints:
            if model is None:
                out[n] = (float("nan"), float("nan"))
            else:
                p = model.predict_proba(X_test)
                out[n] = (float(((p >= 0.5) == (truth >= 0.5)).mean()), tm.auc(truth >= 0.5, p))
    return out


sim_lib = library(80, 1)
pool_all = vote_session.build_candidates(sim_lib, 4000, random.Random(2))
random.Random(3).shuffle(pool_all)
sim_pool, sim_test = pool_all[:2400], pool_all[2400:]
points = (40, 60, 80, 100, 150, 200, 300)
reps = 6


def votes_to_reach(curve, target):
    return next((n for n in points if curve[n][0] >= target), None)


for bias, what in ((1.5, "equilibrado (le gusta un 40 %)"), (0.3, "exigente (le gusta un 14 %)")):
    for c in sim_pool + sim_test:
        c.setdefault("_tp", {})[bias] = true_p(c, bias)
    t0 = time.perf_counter()
    curves = {}
    for strategy in ("aleatoria", "activa"):
        runs = [simulate(strategy, sim_pool, sim_test, 100 + k, points, bias) for k in range(reps)]
        curves[strategy] = {n: (float(np.nanmean([r[n][0] for r in runs])), float(np.nanmean([r[n][1] for r in runs]))) for n in points}
    info(f"simulación, gusto {what}: {reps} repeticiones por estrategia, {len(sim_pool)} candidatas, {len(sim_test)} para medir "
         f"({time.perf_counter() - t0:.1f} s)")
    info("votos   coincide con el gusto real (aleatoria / activa)   AUC (aleatoria / activa)")
    for n in points:
        a, b = curves["aleatoria"][n], curves["activa"][n]
        info(f"{n:>5}   {a[0] * 100:5.1f} % / {b[0] * 100:5.1f} %                          {a[1]:.3f} / {b[1]:.3f}")
    final_random = curves["aleatoria"][points[-1]][0]
    for target in (final_random - 0.03, final_random - 0.01, final_random):
        na, nb = votes_to_reach(curves["aleatoria"], target), votes_to_reach(curves["activa"], target)
        info(f"votos para llegar al {target * 100:.1f} % de coincidencia: aleatoria {na or 'más de 300'}, activa {nb or 'más de 300'}")
    check(f"gusto {what}: las dos estrategias aprenden (más del 75 % de coincidencia con 300 votos)",
          curves["aleatoria"][300][0] > 0.75 and curves["activa"][300][0] > 0.75)

# ------------------------------------------------------------------ clips de verdad (necesita FFmpeg)
from services import ffmpeg_service  # noqa: E402

if not ffmpeg_service.FFmpegService.get_ffmpeg_path():
    check("no hay FFmpeg: se saltan los clips de verdad", True)
    print("FIN")
    sys.exit(0)

root = tempfile.mkdtemp(prefix="descargador_sesion_votos_")
SR = 44100


def make_song(name, freq, seconds=40, bpm=120.0):
    t = np.arange(int(seconds * SR)) / SR
    x = 0.12 * np.sin(2 * np.pi * freq * t)
    beat = 60.0 / bpm
    for k in range(int(seconds / beat)):
        s = int((0.1 + k * beat) * SR)
        n = min(int(0.12 * SR), len(x) - s)
        if n > 0:
            tt = np.arange(n) / SR
            x[s:s + n] += 0.5 * np.sin(2 * np.pi * 55 * tt) * np.exp(-tt * 30)
    pcm = (np.clip(np.stack([x, x], 1), -1, 1) * 32767).astype("<i2")
    path = os.path.join(root, name)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(pcm.tobytes())
    return path


def song_info(path, tone):
    return {"path": path, "title": os.path.splitext(os.path.basename(path))[0], "duration_s": 40.0, "intro_s": 8.0, "outro_s": 12.0,
            "bpm": 120.0, "beatgrid": BeatGrid(0.1, 120.0, 4, 0, 0.9), "tone": tone, "tone_conf": 0.9, "energy": 0.5}


songs = [song_info(make_song(f"cancion{i}.wav", 220 + 40 * i), tone) for i, tone in enumerate(("8A", "9A", "3B"))]
real = vote_session.build_candidates(songs, 200, random.Random(8), bars_options=(8,))
by_kind = {}
for c in real:
    if c["a_path"] == songs[0]["path"] and c["b_path"] == songs[1]["path"]:
        by_kind.setdefault(c["kind"], c)
check("candidatas reales de la canción 0 a la 1 con los cuatro tipos", set(by_kind) == {"blend", "cut_bar", "echo_out", "filter"})
cache = os.path.join(root, "cache")
clips = {}
t0 = time.perf_counter()
for kind in ("blend", "cut_bar", "echo_out", "filter"):
    try:
        clips[kind] = vote_session.render_clip(by_kind[kind], cache_dir=cache)
    except Exception as e:
        info(f"{kind}: {e}")
info(f"4 clips renderizados en {time.perf_counter() - t0:.1f} s")
check("se renderizan los cuatro tipos", len(clips) == 4)
blend = clips.get("blend")
if blend:
    with wave.open(blend["clip_path"], "rb") as fh:
        frames, rate, chans = fh.getnframes(), fh.getframerate(), fh.getnchannels()
    expected = blend["mix_end_s"] + vote_session.CLIP_CONTEXT_S
    check(f"el wav es estéreo a 44.100 Hz y dura lo esperado ({frames / rate:.1f} s, mezcla de {blend['plan'].length_s:.1f} s)",
          rate == 44100 and chans == 2 and abs(frames / rate - expected) < 0.2)
    check("con la mezcla dentro, tras el contexto de A", abs(blend["mix_start_s"] - vote_session.CLIP_CONTEXT_S) < 0.05)
    check("con nota del puntuador y sus medidas de audio", 0.0 <= blend["auto_score"] <= 1.0 and "beat_offset_ms" in blend["metrics"])
    info(f"blend: nota {blend['auto_score']:.2f} ({blend['verdict']}); " + "; ".join(blend["reasons"][:3]))


def mix_of(clip):
    with wave.open(clip["clip_path"], "rb") as fh:
        data = np.frombuffer(fh.readframes(fh.getnframes()), dtype="<i2").reshape(-1, 2).astype(float) / 32767
    s = int(round(clip["mix_start_s"] * SR))
    n = int(round(clip["plan"].length_s * SR))
    return data[:s], data[s:s + n], data[s + n:]


if len(clips) == 4:
    parts = {k: mix_of(v) for k, v in clips.items()}
    differ = all(np.abs(parts[k][1] - parts["blend"][1]).max() > 0.05 for k in ("cut_bar", "echo_out", "filter"))
    same_ctx = all(np.abs(parts[k][0] - parts["blend"][0]).max() < 1e-3 for k in ("cut_bar", "echo_out", "filter"))
    check("cada tipo cambia la mezcla y deja igual el contexto de antes", differ and same_ctx)
    cut_mix = parts["cut_bar"][1][:, 0]
    half = int(round(clips["cut_bar"]["plan"].bass_swap_at * SR))

    def amp(x, freq):
        t = np.arange(len(x)) / SR
        return abs(np.dot(x, np.exp(-2j * np.pi * freq * t))) / max(1, len(x))
    pre, post = cut_mix[: half - 2000], cut_mix[half + 2000:]
    check("el corte en el compás: antes del corte suena A sola (220 Hz) y después B sola (260 Hz)",
          amp(pre, 220) > 10 * amp(pre, 260) and amp(post, 260) > 10 * amp(post, 220))
    check("el tipo queda en el resultado", all(clips[k]["kind"] == k for k in clips))

cut_c = next((c for c in vote_session.build_candidates(songs, 200, random.Random(9)) if c["kind"] == "cut"), None)
if cut_c is None:
    far = dict(song_info(make_song("lenta.wav", 300, bpm=90.0), "8A"), bpm=90.0, beatgrid=BeatGrid(0.1, 90.0, 4, 0, 0.9))
    cut_c = next(c for c in vote_session.build_candidates([songs[0], far], 50, random.Random(9)) if c["kind"] == "cut")
cut_clip = vote_session.render_clip(cut_c, cache_dir=cache)
check("un corte del planificador también se renderiza (kind «cut», sin mezcla)", cut_clip["kind"] == "cut"
      and abs(cut_clip["mix_end_s"] - cut_clip["mix_start_s"]) < 1e-6)
left = [f for f in os.listdir(cache) if f.endswith(".wav")]
check(f"la caché se queda pequeña ({len(left)} clips de 5 renderizados)", len(left) <= vote_session.CACHE_KEEP)
try:
    vote_session.render_clip(dict(by_kind["blend"], a_path=os.path.join(root, "no_existe.wav")), cache_dir=cache)
    falla = False
except RuntimeError:
    falla = True
check("una canción que no existe: RuntimeError (la sesión la salta)", falla)

# ------------------------------------------------------------------ votar
before = transition_votes.count()["total"]
if blend:
    vid = vote_session.record_vote(clips["filter"], -1, ["tono"], session="prueba")
    row = transition_votes.last_vote()
    check("el voto se guarda con origen «clip», su tipo, su motivo y la nota del puntuador",
          vid is not None and row["source"] == "clip" and row["kind"] == "filter" and row["tags"] == ["tono"]
          and row["auto_score"] is not None and transition_votes.count()["total"] == before + 1)
    extra = tm.load_extras().get(str(vid), {})
    check("con el detalle para el modelo (rejillas y medidas de audio)", "a_grid_conf" in extra and "metrics" in extra)
    rec = tm.training_records()[0]
    check("y el modelo lo lee igual que una candidata (mismas características de plan)",
          np.allclose(np.nan_to_num(tm.features(rec)), np.nan_to_num(tm.features(clips["filter"])), atol=1e-3))

# ------------------------------------------------------------------ la sesión
sess = vote_session.VoteSession(songs, 100, random.Random(10), load_saved_model=False)
first = sess.take_next()
check("VoteSession da candidatas y las apunta en el historial", first is not None and sess.history == [first])
check("el contador dice por qué voto va y la meta", sess.progress_text().startswith(f"Voto {transition_votes.count()['total'] + 1} de unos 100"))
check("el estado del modelo es honesto (sin modelo con tan pocos votos)", sess.status["level"] == "sin_modelo")
sess.started -= vote_session.BREAK_AFTER_S + 1
check("a los 35 minutos pide descanso", sess.needs_break())
print("FIN")
