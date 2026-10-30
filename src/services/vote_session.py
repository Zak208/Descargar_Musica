"""Sesión de votos con aprendizaje activo (fase 27): se preparan muchas transiciones candidatas de la biblioteca y solo se
enseñan las que más dudas le crean al modelo de gusto (`taste_model`), para que cada voto enseñe lo máximo.

Pasos (sin Qt; la ventana está en ui/vote_dialog.py):
  * `build_candidates(fichas, n)`: parejas de canciones (sobre todo las que el planificador mezclaría, y una parte al azar
    para que el modelo también vea lo claramente malo) y, para cada una, variaciones de duración (4, 8 y 16 compases, lo que
    el planificador dé con cada una) y de tipo (blend, corte en el compás, eco de salida y filtro; un plan que ya es un corte
    se queda en corte). Solo planes: nada de audio todavía.
  * `select_next(candidatas, modelo, historial, epsilon)`: con modelo (entrenado con 60 votos o más), la que más duda
    (probabilidad más cerca de 0,5); sin modelo o con uno de menos votos, la que más cobertura añade (tipos, parejas, canciones y duraciones menos vistas). Siempre con diversidad (nunca
    la misma pareja en las últimas 8, ni el mismo tipo ni una canción de la anterior justo detrás, si hay otras) y con un
    `epsilon` (10 %) de elección al azar para no encerrarse en una zona.
  * `render_clip(candidata)`: el clip con `mix_recorder.render_transition_clip` (la misma sesión del motor que toca en
    directo) y, si el tipo no es blend, la mezcla se rehace con `transition_types.render_typed` sobre los MISMOS trozos que
    usó el motor (con su volumen igualado y su estiramiento: se recogen con un cargador espía). Se mide con
    `transition_scorer.score_audio` y se guarda en un wav temporal (caché pequeña: se borran los viejos).
  * `record_vote(candidata, voto, motivos)`: `transition_votes.add_vote(..., source="clip")` más el detalle para el modelo.

Qué no se sabe: el plan dice que con aprendizaje activo hacen falta «más o menos la mitad» de votos. La prueba
(pruebas/prueba_sesion_votos.py) lo MIDE con un gusto sintético conocido y da la cifra que sale; con votos reales puede ser
otra (la duda del modelo con pocos votos es mala guía, y el usuario no es una función con ruido gaussiano)."""
import logging
import math
import os
import random
import time
import uuid
import wave
from dataclasses import replace

from config import APP_DATA_DIR
from services import camelot, dj_planner, mix_planner, taste_model, transition_scorer, transition_types, transition_votes
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid

logger = logging.getLogger(__name__)

BARS_OPTIONS = (4, 8, 16)
KINDS = transition_types.TYPES
REASONABLE_SHARE = 0.7          # parte de las parejas que el planificador mezclaría; el resto, al azar (para ver lo malo)
ENERGY_REASONABLE = 0.35        # salto de energía máximo de una pareja «razonable»
RECENT_PAIRS = 8                # la misma pareja no vuelve a salir hasta pasadas tantas
EPSILON = 0.1                   # parte de elecciones al azar
ACTIVE_FROM = 60                # con un modelo de menos votos, su duda es mala guía (medido en la simulación: con 30 a 60
                                # votos elegir por duda aprendía PEOR que al azar); hasta entonces, cobertura
CLIP_CONTEXT_S = 6.0            # segundos de antes y de después de la mezcla en el clip
CACHE_DIR = APP_DATA_DIR / "clips_votos"
CACHE_KEEP = 4                  # clips que se quedan en la caché (el que suena, el siguiente y algún margen)
RETRAIN_EVERY = 10              # votos entre un reentrenamiento y el siguiente
BREAK_AFTER_S = 35 * 60         # el plan: sesiones de 30 a 40 min (cansado se vota distinto)
MAX_PAIR_TRIES = 40


def _path(info) -> str:
    return (info.get("path") or info.get("local_path") or "") if isinstance(info, dict) else ""


def _key(path) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


def _title(info) -> str:
    title = str(info.get("title") or "").strip()
    return title or os.path.splitext(os.path.basename(_path(info)))[0]


def _bpm(info):
    grid = info.get("beatgrid")
    value = info.get("bpm") or (grid.bpm if isinstance(grid, BeatGrid) else None)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def pair_key(c) -> tuple:
    """La pareja sin importar el orden (A a B y B a A cuentan como la misma para no repetir). Se guarda en la candidata."""
    found = c.get("_pair")
    if found is None:
        a, b = _key(c.get("a_path")), _key(c.get("b_path"))
        found = c["_pair"] = (a, b) if a <= b else (b, a)
    return found


def _features_of(c, use_audio: bool):
    """Las características de una candidata para el modelo, calculadas una vez y guardadas en ella (`_x`)."""
    cache = c.get("_x")
    if cache is None or cache[0] != use_audio:
        cache = c["_x"] = (use_audio, taste_model.features(c, use_audio))
    return cache[1]


def _clean_copy(c) -> dict:
    """Copia de una candidata sin las cachés internas (que dejarían de valer si cambia el plan o el tipo)."""
    return {k: v for k, v in c.items() if k not in ("_x", "_pair")}


def reasonable(a: dict, b: dict) -> bool:
    """¿La mezclaría el planificador sin dudar? Tempo mezclable (±8 % con mitad y doble), tonos que no chocan y energía cercana
    (lo que no se sabe no descarta)."""
    if not dj_planner.mixable(_bpm(a), _bpm(b)):
        return False
    ta, tb = camelot.normalize(a.get("tone")), camelot.normalize(b.get("tone"))
    if ta and tb and camelot.score(ta, tb) <= camelot.SCORE_BAD:
        return False
    ea, eb = _num(a.get("energy")), _num(b.get("energy"))
    return ea is None or eb is None or abs(ea - eb) <= ENERGY_REASONABLE


# ----------------------------------------------------------------------------------------------- candidatas
def _candidate(idx, a, b, plan, bars, kind, rule_kind, is_reasonable) -> dict:
    return {"id": f"c{idx}", "a_path": _path(a), "b_path": _path(b), "a_info": a, "b_info": b, "a_title": _title(a), "b_title": _title(b),
            "a_bpm": _bpm(a), "b_bpm": _bpm(b), "a_tone": a.get("tone"), "b_tone": b.get("tone"),
            "a_energy": _num(a.get("energy")), "b_energy": _num(b.get("energy")), "bars": bars, "kind": kind, "rule_kind": rule_kind,
            "plan": plan, "length_s": plan.length_s, "tempo_ratio_b": plan.tempo_ratio_b, "reasonable": is_reasonable}


def build_candidates(library_infos, n: int = 300, rng=None, bars_options=BARS_OPTIONS, kinds=KINDS,
                     reasonable_share: float = REASONABLE_SHARE) -> list:
    """Hasta `n` transiciones candidatas (dicts) de las fichas `library_infos` (cada una con `path` o `local_path` y lo que
    se sepa: duración, intro, final, bpm, beatgrid, tono, energía). Sin audio. Lista vacía con menos de dos canciones."""
    rng = rng or random.Random()
    infos = [i for i in (library_infos or []) if isinstance(i, dict) and _path(i)]
    seen_paths, unique = set(), []
    for info in infos:
        if _key(_path(info)) not in seen_paths:
            seen_paths.add(_key(_path(info)))
            unique.append(info)
    infos = unique
    if len(infos) < 2:
        return []
    variants = max(1, len(bars_options)) * max(1, len(kinds))
    want_pairs = max(1, math.ceil(n / max(1, variants * 0.6)))
    max_pairs = len(infos) * (len(infos) - 1)
    pairs, out, idx = set(), [], 0
    tries = 0
    while len(pairs) < min(want_pairs, max_pairs) and tries < want_pairs * MAX_PAIR_TRIES:
        tries += 1
        a = rng.choice(infos)
        if rng.random() < reasonable_share:
            sample = rng.sample(infos, min(len(infos), 40))
            good = [b for b in sample if b is not a and reasonable(a, b)]
            if not good:
                continue
            b = rng.choice(good)
        else:
            b = rng.choice(infos)
            if b is a:
                continue
        key = (_key(_path(a)), _key(_path(b)))
        if key in pairs:
            continue
        pairs.add(key)
        is_reasonable = reasonable(a, b)
        plans = {}
        for bars in bars_options:
            plan = mix_planner.plan_transition(a, b, bars)
            sig = (plan.kind, round(plan.length_s, 2), round(plan.a_start_s, 2))
            plans.setdefault(sig, (plan, bars))
        for plan, bars in plans.values():
            rule_kind = transition_types.choose_type(a, b, plan)[0]
            for kind in (("cut",) if plan.kind == KIND_CUT or plan.length_s <= 0 else kinds):
                out.append(_candidate(idx, a, b, plan, bars, kind, rule_kind, is_reasonable))
                idx += 1
    if len(out) > n:
        out = rng.sample(out, n)
    return out


# ----------------------------------------------------------------------------------------------- elegir la siguiente
def _shares_track(c, other) -> bool:
    mine = {_key(c.get("a_path")), _key(c.get("b_path"))}
    return bool(mine & {_key(other.get("a_path")), _key(other.get("b_path"))})


def select_next(candidates, model=None, history=(), epsilon: float = EPSILON, rng=None):
    """La candidata que conviene enseñar ahora (o None si no queda ninguna sin enseñar). Ver la explicación del módulo.
    `history`: las candidatas ya enseñadas, en orden (dicts con id, a_path, b_path, kind y bars)."""
    rng = rng or random.Random()
    history = list(history or [])
    shown = {h.get("id") for h in history}
    pool = [c for c in candidates if c.get("id") not in shown]
    if not pool:
        return None
    recent = {pair_key(h) for h in history[-RECENT_PAIRS:]}
    last = history[-1] if history else None
    allowed = [c for c in pool if pair_key(c) not in recent
               and (last is None or (c.get("kind") != last.get("kind") and not _shares_track(c, last)))]
    allowed = allowed or [c for c in pool if pair_key(c) not in recent] or pool
    if rng.random() < epsilon:
        return rng.choice(allowed)
    if model is not None and getattr(model, "fitted", False) and getattr(model, "n_train", 0) >= ACTIVE_FROM:
        import numpy as np
        X = np.vstack([_features_of(c, model.use_audio) for c in allowed])
        u = np.atleast_1d(taste_model.uncertainty(model.predict_proba(X)))
        top = float(u.max())
        best = [c for c, x in zip(allowed, u) if x >= top - 1e-9]
        return rng.choice(best)
    # sin modelo: cobertura (lo menos visto de cada cosa)
    kinds, tracks, pairs, bars = {}, {}, {}, {}
    for h in history:
        kinds[h.get("kind")] = kinds.get(h.get("kind"), 0) + 1
        pairs[pair_key(h)] = pairs.get(pair_key(h), 0) + 1
        bars[h.get("bars")] = bars.get(h.get("bars"), 0) + 1
        for p in (_key(h.get("a_path")), _key(h.get("b_path"))):
            tracks[p] = tracks.get(p, 0) + 1

    def cost(c):
        return (kinds.get(c.get("kind"), 0) + 2 * pairs.get(pair_key(c), 0) + 0.5 * bars.get(c.get("bars"), 0)
                + 0.5 * (tracks.get(_key(c.get("a_path")), 0) + tracks.get(_key(c.get("b_path")), 0)))
    costs = [cost(c) for c in allowed]
    low = min(costs)
    return rng.choice([c for c, x in zip(allowed, costs) if x <= low + 1e-9])


# ----------------------------------------------------------------------------------------------- renderizar
def _write_wav(path, audio, sample_rate=SAMPLE_RATE):
    import numpy as np
    pcm = (np.clip(np.nan_to_num(audio, nan=0.0), -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(os.fspath(path), "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(int(sample_rate))
        fh.writeframes(pcm.tobytes())


def prune_cache(cache_dir=None, keep: int = CACHE_KEEP, protect=()):
    """Deja en la caché solo los `keep` clips más nuevos (y los de `protect`). Los que no se pueden borrar (abiertos por el
    reproductor) se dejan para la próxima vez."""
    folder = os.fspath(cache_dir or CACHE_DIR)
    try:
        files = [os.path.join(folder, f) for f in os.listdir(folder) if f.startswith("clip_") and f.endswith(".wav")]
    except OSError:
        return
    files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
    keep_set = {_key(p) for p in protect if p}
    for path in files[max(0, int(keep)):]:
        if _key(path) in keep_set:
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def render_clip(candidate: dict, cache_dir=None, context_s: float = CLIP_CONTEXT_S, protect=()) -> dict:
    """El clip de una candidata en un wav temporal. Devuelve una copia de la candidata con `clip_path`, `clip_s`, `plan` (el
    que usó el motor de verdad), `kind` (el tipo que suena: «cut» si el motor acabó cortando), `mix_start_s` / `mix_end_s`
    (dentro del clip), `metrics` (valores de `score_audio`, o de `score_plan` en un corte), `auto_score`, `verdict` y
    `reasons`. Tarda unos segundos (decodificar y estirar): llamar desde un hilo que no sea el de la interfaz. Lanza
    RuntimeError si no se pudo preparar."""
    import numpy as np

    from services import mix_recorder, pcm_loader
    captured_full, captured_pieces = {}, []

    def spy(path, tempo_ratio=1.0, start_s=0.0, duration_s=None, **kw):
        data = pcm_loader.load(path, tempo_ratio=tempo_ratio, start_s=start_s, duration_s=duration_s, **kw)
        if data is not None:
            if tempo_ratio == 1.0 and not start_s and duration_s is None:
                captured_full[_key(path)] = data           # el motor le aplica la ganancia en el sitio: queda igual que suena
            else:
                captured_pieces.append((_key(path), data))
        return data

    a_path, b_path = candidate["a_path"], candidate["b_path"]
    a_info, b_info = candidate.get("a_info") or {}, candidate.get("b_info") or {}
    clip = mix_recorder.render_transition_clip(a_path, b_path, a_info, b_info, context_s=context_s,
                                               bars=int(candidate.get("bars") or 16), loader=spy)
    audio = np.array(clip.audio, dtype=np.float32, copy=True)
    plan, sr = clip.plan, clip.sample_rate
    kind = candidate.get("kind") or transition_types.TYPE_BLEND
    is_cut = plan.kind == KIND_CUT or plan.length_s <= 0
    result = _clean_copy(candidate)
    if is_cut:
        kind = "cut"
        scored = transition_scorer.score_plan(a_info, b_info, plan)
    else:
        a_data, b_data = captured_full.get(_key(a_path)), captured_full.get(_key(b_path))
        if a_data is None or b_data is None:
            raise RuntimeError("no se pudieron recoger los trozos de la mezcla")
        n = int(round(plan.length_s * sr))
        a_mix = int(round(plan.a_start_s * sr))
        a_part = a_data[a_mix:a_mix + n]
        ratio = float(plan.tempo_ratio_b or 1.0)
        if abs(ratio - 1.0) < 1e-6:
            bs = int(round(plan.b_start_s * sr))
            b_part = b_data[bs:bs + n]
        else:
            pieces = [d for p, d in captured_pieces if p == _key(b_path)]
            if not pieces:
                raise RuntimeError("no se pudo recoger el tramo estirado de la que entra")
            b_part = pieces[-1][:n]
        start = int(round(clip.mix_start_s * sr))
        if kind != transition_types.TYPE_BLEND:
            mix = transition_types.render_typed(a_part, b_part, plan, kind, bpm=_bpm(a_info))
            k = max(0, min(len(mix), len(audio) - start))
            audio[start:start + k] = mix[:k]
        mix_now = audio[start:start + n]
        before = a_data[max(0, a_mix - int(2 * sr)):a_mix]
        after = audio[start + n:start + n + int(2 * sr)]
        grid_a, grid_b = a_info.get("beatgrid"), b_info.get("beatgrid")
        scored = transition_scorer.score_audio(mix_now, a_part, b_part, plan, grid_a if isinstance(grid_a, BeatGrid) else None,
                                               grid_b if isinstance(grid_b, BeatGrid) else None, sample_rate=sr,
                                               tone_a=a_info.get("tone"), tone_b=b_info.get("tone"),
                                               tone_conf_a=a_info.get("tone_conf"), tone_conf_b=b_info.get("tone_conf"),
                                               a_before=before, b_after=after)
    captured_full.clear()                                  # las canciones enteras ya no hacen falta (dos de 3 min: 120 MB)
    captured_pieces.clear()
    folder = os.fspath(cache_dir or CACHE_DIR)
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, f"clip_{uuid.uuid4().hex[:12]}.wav")
    _write_wav(out, audio, sr)
    prune_cache(folder, protect=(out, *protect))
    result.update(clip_path=out, clip_s=len(audio) / sr, plan=replace(plan), kind=kind, mix_start_s=clip.mix_start_s,
                  mix_end_s=clip.mix_end_s, length_s=plan.length_s, tempo_ratio_b=plan.tempo_ratio_b,
                  metrics={k: v.get("value") for k, v in scored["metrics"].items() if isinstance(v, dict)},
                  auto_score=scored["score"], verdict=scored["verdict"], reasons=list(scored["reasons"]))
    return result


# ----------------------------------------------------------------------------------------------- votar
def record_vote(candidate: dict, vote: int, tags=None, session: str = "", note: str = ""):
    """Guarda el voto de un clip (`source="clip"`) con su plan, su tipo y la nota del puntuador, y el detalle que la tabla
    no guarda (para el modelo). Devuelve el id del voto, o None si falla la base. Lanza ValueError con argumentos inválidos."""
    plan = taste_model.plan_dict(candidate.get("plan"))
    if not plan:
        plan = {"a_start_s": 0.0, "b_start_s": 0.0, "length_s": candidate.get("length_s") or 0.0,
                "tempo_ratio_b": candidate.get("tempo_ratio_b") or 1.0}
    plan["kind"] = candidate.get("kind") or plan.get("kind") or "blend"
    infos = {}
    for side in ("a", "b"):
        infos[side] = {"title": candidate.get(f"{side}_title"), "bpm": candidate.get(f"{side}_bpm"),
                       "tone": candidate.get(f"{side}_tone"), "energy": candidate.get(f"{side}_energy")}
    vote_id = transition_votes.add_vote(plan, candidate["a_path"], candidate["b_path"], vote, source="clip", session=session,
                                        tags=tags, note=note, a_info=infos["a"], b_info=infos["b"],
                                        auto_score=candidate.get("auto_score"))
    if vote_id is not None:
        taste_model.save_extra(vote_id, candidate)
    return vote_id


# ----------------------------------------------------------------------------------------------- la sesión
class VoteSession:
    """Lleva una sesión de votos: candidatas, historial, modelo, contador y aviso de descanso. Sin Qt ni hilos: quien la usa
    decide en qué hilo renderiza (`render_clip`) y llama a `take_next`, `vote` y `skip` desde el suyo."""

    def __init__(self, library_infos, n_candidates: int = 400, rng=None, session_id: str = None, model=None,
                 epsilon: float = EPSILON, info_for=None, load_saved_model: bool = True):
        self.rng = rng or random.Random()
        self.candidates = build_candidates(library_infos, n_candidates, self.rng)
        self.history = []                # candidatas enseñadas (o pedidas para renderizar), en orden
        self.failed = set()
        self.model = model if model is not None else (taste_model.load_model() if load_saved_model else None)
        self.session_id = session_id or time.strftime("clip-%Y%m%d-%H%M%S")
        self.epsilon = epsilon
        self.info_for = info_for
        self.started = time.monotonic()
        self.votes_here = 0
        self.skips_here = 0
        self.status = taste_model.status(self.total_votes(), self.model.cv if self.model is not None else None)

    def total_votes(self) -> int:
        return transition_votes.count()["total"]

    def take_next(self):
        """La siguiente candidata que conviene enseñar (ya queda en el historial), o None si no quedan."""
        c = select_next(self.candidates, self.model, self.history, self.epsilon, self.rng)
        if c is not None:
            self.history.append(c)
        return c

    def mark_failed(self, candidate):
        """No se pudo renderizar: no vuelve a salir."""
        self.failed.add(candidate.get("id"))

    def vote(self, candidate, vote, tags=None):
        vote_id = record_vote(candidate, vote, tags, session=self.session_id)
        if vote_id is not None:
            self.votes_here += 1
            if self.votes_here % RETRAIN_EVERY == 0:
                self.retrain()
        return vote_id

    def skip(self, candidate):
        self.skips_here += 1

    def retrain(self):
        """Vuelve a entrenar con todos los votos (si hay bastantes) y pone al día el estado."""
        model, status, _cv = taste_model.train_from_db(self.info_for)
        if model is not None:
            self.model = model
        self.status = status
        return model

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    def needs_break(self) -> bool:
        return self.elapsed_s() >= BREAK_AFTER_S

    def progress_text(self) -> str:
        total = self.total_votes()
        goal = next((g for g in taste_model.GOALS if g > total), taste_model.GOALS[-1])
        here = f" ({self.votes_here} en esta sesión)" if self.votes_here else ""
        return f"Voto {total + 1} de unos {goal:,}".replace(",", ".") + here
