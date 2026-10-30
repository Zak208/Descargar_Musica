"""Modelo que aprende el gusto del usuario con sus votos 👍 / 👎 de transiciones (fase 26, versión ligera con numpy).

Qué hace: cada transición (una fila de `transition_votes`, o un plan con las fichas de las dos canciones) se convierte en un
vector de características físicas y un modelo pequeño aprende la probabilidad de que le guste. Sin PyTorch ni scikit-learn.

Características (`features`, las mismas al entrenar y al predecir, todas calculables ANTES de renderizar audio):
  * tempo: cambio necesario contando la mitad y el doble como el mismo ritmo (en %), estiramiento aplicado de verdad, si hubo
    que saltar de familia (70 contra 140), diferencia en bruto de BPM y tempo medio (familia: lentas o rápidas);
  * tonos: pasos en la rueda Camelot, la nota de `camelot.score`, cambio de mayor a menor y la confianza del tono más dudoso;
  * energía: diferencia con signo (sube o baja), diferencia absoluta y energía media;
  * tipo de transición en one-hot (blend, cut_bar, echo_out, filter y corte del planificador);
  * duración de la mezcla en segundos y en compases, parte de la canción más corta que se come, final de A;
  * confianza de las rejillas de golpes (la peor de las dos);
  * un indicador «falta» por grupo (tempo, tono, energía, rejilla): lo que no se sabe se rellena con la media al estandarizar.
Con `use_audio=True` se añaden las notas de `transition_scorer.score_audio` (desfase de golpes, graves, voces, salto de
volumen, recorte, huecos, clics y la nota global). Solo existen DESPUÉS de renderizar, así que el modelo por omisión no las usa
(el que elige qué clip enseñar o qué pareja tocar tiene que decidir antes de oír nada).

Modelo: regresión logística con regularización L2, entrenada con Newton (IRLS) sobre características estandarizadas. La fuerza
de la L2 se elige por validación cruzada interna (log-loss) y, con menos de 60 votos, se fija alta (el modelo se queda cerca de
la media). Opcional: un MLP de una capa oculta (tanh, Adam, L2) para gustos no lineales (`kind="mlp"`).

Honestidad (lo más importante de este módulo):
  * no entrena con menos de `MIN_VOTES` (30) votos ni con menos de `MIN_PER_CLASS` (5) de alguna clase (lanza NotEnoughData);
  * las probabilidades se recortan según cuántos votos hay (`max_confidence`): con menos de 100 votos nunca pasa de 0,75 ni
    baja de 0,25, aunque los datos parezcan clarísimos;
  * `status()` dice en qué punto está según la tabla «Cuántos votos harán falta» del plan y, si la validación cruzada dice que no
    acierta más que adivinar, lo dice aunque haya muchos votos;
  * la puerta de la fase 26 («acierta tus votos en más del 75 % de transiciones que no ha visto») SOLO se puede comprobar con
    votos reales: `cross_validate` da esa cifra, pero con votos sintéticos solo demuestra que el código aprende un gusto
    conocido, no que aprenda el tuyo.

Extensión documentada (no hecha): representaciones de audio ya entrenadas (MERT, CLAP) con PyTorch. Encajarían como otro
grupo de características (un vector por clip, reducido con PCA a 16 o 32 números) calculado en `vote_session.render_clip` y
guardado en el detalle del voto; el modelo de aquí no cambia (más columnas). Hace falta PyTorch y la tarjeta gráfica, y no
merece la pena hasta tener 300 votos o más: con menos, tantas columnas solo aprenden ruido.

Detalle de los votos: la tabla de votos no tiene columnas para la confianza de rejilla ni las notas de audio, así que
`save_extra` las guarda aparte (`votos_detalle.json` en la carpeta de datos), con el id del voto. Los votos sin detalle
(los del directo) se completan con `info_for` si se da, o quedan con esos datos «sin saber»."""
import json
import logging
import math
import os
import time
from dataclasses import asdict, is_dataclass

import numpy as np

from config import APP_DATA_DIR
from services import camelot, mix_planner, mix_points
from services.mix_types import BeatGrid

logger = logging.getLogger(__name__)

MODEL_PATH = APP_DATA_DIR / "modelo_gusto.json"
EXTRAS_PATH = APP_DATA_DIR / "votos_detalle.json"
FORMAT_VERSION = 1

MIN_VOTES = 30                  # por debajo no se entrena: con menos, cualquier cosa que «aprenda» es casualidad
MIN_PER_CLASS = 5               # y al menos 5 👍 y 5 👎 (con una sola clase no hay nada que separar)
SMALL_DATA = 60                 # con menos de esto no se elige la L2 por validación cruzada: se usa L2_SMALL (fuerte)
L2_SMALL = 30.0
L2_GRID = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0)
NEWTON_ITERS = 60
MLP_HIDDEN = 8
MLP_ITERS = 900
MLP_LR = 0.02
MLP_L2 = 3.0
# tope de confianza según los votos con que se entrenó: (votos mínimos, probabilidad máxima)
CONFIDENCE_CAPS = ((1000, 0.98), (300, 0.93), (100, 0.85), (0, 0.75))
# estados según la tabla «Cuántos votos harán falta» de docs/PLAN_DJ.md
LEVELS = ((1000, "bueno", "Bueno: elige parejas y duración de mezcla con criterio"),
          (300, "usable", "Usable: aprende tu gusto con tus canciones"),
          (100, "solo_malo", "Solo detecta lo claramente malo"),
          (MIN_VOTES, "aprendiendo", "Aprendiendo: con menos de 100 votos aún no es de fiar"),
          (0, "sin_modelo", "Sin modelo"))
GOALS = (100, 300, 1000, 1500)
GATE_ACCURACY = 0.75            # puerta de la fase 26 (con votos que no ha visto)

KINDS = ("blend", "cut_bar", "echo_out", "filter", "cut")
PLAN_FEATURES = (
    "bpm_gap", "stretch", "tempo_family", "bpm_raw_diff", "bpm_mean", "bpm_missing",
    "key_steps", "key_score", "key_mode_change", "key_conf", "key_missing",
    "energy_delta", "energy_abs", "energy_mean", "energy_missing",
    *(f"kind_{k}" for k in KINDS),
    "length_s", "length_bars", "mix_share", "outro_a",
    "grid_conf", "grid_missing",
)
AUDIO_METRICS = ("beat_offset_ms", "bass_clash", "vocal_overlap", "loudness_step_db", "clipping", "silence_gap_ms", "click")
AUDIO_FEATURES = ("auto_score", *AUDIO_METRICS, "audio_missing")

LABELS = {
    "bpm_gap": "cambio de tempo necesario", "stretch": "estiramiento de la que entra", "tempo_family": "salto de mitad o doble de tempo",
    "bpm_raw_diff": "diferencia de BPM", "bpm_mean": "tempo de las canciones", "bpm_missing": "tempo desconocido",
    "key_steps": "distancia de tonos en la rueda", "key_score": "encaje de tonos", "key_mode_change": "cambio de mayor a menor",
    "key_conf": "seguridad del tono", "key_missing": "tono desconocido",
    "energy_delta": "subida de energía", "energy_abs": "salto de energía", "energy_mean": "energía de las canciones",
    "energy_missing": "energía desconocida",
    "kind_blend": "tipo mezcla larga", "kind_cut_bar": "tipo corte en el compás", "kind_echo_out": "tipo eco de salida",
    "kind_filter": "tipo filtro", "kind_cut": "corte limpio del planificador",
    "length_s": "duración de la mezcla", "length_bars": "compases de mezcla", "mix_share": "parte de la canción que ocupa la mezcla",
    "outro_a": "final de la que suena", "grid_conf": "fiabilidad de las rejillas de golpes", "grid_missing": "sin rejilla de golpes",
    "auto_score": "nota del puntuador automático", "beat_offset_ms": "golpes desfasados", "bass_clash": "graves chocando",
    "vocal_overlap": "voces solapadas", "loudness_step_db": "salto de volumen", "clipping": "recorte", "silence_gap_ms": "hueco de silencio",
    "click": "clic", "audio_missing": "sin medidas de audio",
}


class NotEnoughData(ValueError):
    """No hay votos suficientes (o de las dos clases) para entrenar con honradez."""


# ----------------------------------------------------------------------------------------------- utilidades
def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -40.0, 40.0)))


def uncertainty(p):
    """Cuánto duda el modelo: 1 con p = 0,5 y 0 con p = 0 o 1 (vale con un número o con un array)."""
    p = np.asarray(p, dtype=float)
    u = 1.0 - np.abs(2.0 * p - 1.0)
    return float(u) if u.ndim == 0 else u


def max_confidence(n_votes) -> float:
    """La probabilidad más extrema que se permite con un modelo entrenado con `n_votes` votos."""
    n = int(n_votes or 0)
    return next(cap for votes, cap in CONFIDENCE_CAPS if n >= votes)


def label_of(vote) -> int:
    """+1 → 1 (le gusta), -1 (o 0) → 0. Lanza ValueError con cualquier otra cosa."""
    if not isinstance(vote, bool) and isinstance(vote, (int, float)):
        if vote == 1:
            return 1
        if vote in (-1, 0):
            return 0
    raise ValueError(f"voto desconocido: {vote!r}")


# ----------------------------------------------------------------------------------------------- características
def _info(record, side):
    info = record.get(f"{side}_info") if isinstance(record, dict) else None
    return info if isinstance(info, dict) else {}


def _first(*values):
    for v in values:
        x = _num(v)
        if x is not None:
            return x
    return None


def _grid_conf(record, side):
    info = _info(record, side)
    grid = info.get("beatgrid")
    if isinstance(grid, BeatGrid):
        return _num(grid.confidence)
    return _first(record.get(f"{side}_grid_conf"), info.get("beat_conf") if _num(info.get("beat_bpm")) else None)


def _bpm(record, side):
    info = _info(record, side)
    grid = info.get("beatgrid")
    value = _first(record.get(f"{side}_bpm"), info.get("bpm"), grid.bpm if isinstance(grid, BeatGrid) else None)
    return value if value and value > 0 else None


def _tone(record, side):
    tone = record.get(f"{side}_tone") or _info(record, side).get("tone")
    return camelot.normalize(tone) if isinstance(tone, str) and tone else None


def _seconds(record, side, name):
    value = _num(record.get(f"{side}_{name}_s"))
    return value if value is not None else mix_points.seconds(_info(record, side), name)


def _plan_value(record, key):
    plan = record.get("plan")
    if plan is not None:
        if is_dataclass(plan) and not isinstance(plan, type):
            value = getattr(plan, key, None)
        elif isinstance(plan, dict):
            value = plan.get(key)
        else:
            value = None
        if value is not None:
            return value
    return record.get(key)


def features(record, use_audio: bool = False) -> np.ndarray:
    """Vector de características (float, NaN donde no se sabe) de una transición. `record`: una fila de `transition_votes`
    (a_bpm, b_bpm, a_tone, b_tone, a_energy, b_energy, length_s, tempo_ratio_b, kind, auto_score...) o un candidato de
    `vote_session` (lo mismo más `a_info` / `b_info` con las fichas y `plan`), con el detalle de `save_extra` si lo hay.
    Nunca lanza: lo que no entiende cuenta como «no se sabe»."""
    record = record if isinstance(record, dict) else {}
    f = {}
    # tempo
    bpm_a, bpm_b = _bpm(record, "a"), _bpm(record, "b")
    ratio_b = _num(_plan_value(record, "tempo_ratio_b"))
    f["stretch"] = abs((ratio_b if ratio_b and ratio_b > 0 else 1.0) - 1.0) * 100.0
    if bpm_a and bpm_b:
        ratio = mix_planner.tempo_ratio(bpm_a, bpm_b)
        f["bpm_gap"] = abs(math.log(ratio)) * 100.0
        f["tempo_family"] = 0.0 if abs(math.log(bpm_a / bpm_b)) < math.log(1.25) else 1.0
        f["bpm_raw_diff"] = abs(bpm_a - bpm_b) / 10.0
        f["bpm_mean"] = (bpm_a + bpm_b) / 200.0
        f["bpm_missing"] = 0.0
    else:
        f["bpm_gap"] = f["tempo_family"] = f["bpm_raw_diff"] = f["bpm_mean"] = math.nan
        f["bpm_missing"] = 1.0
    # tonos
    tone_a, tone_b = _tone(record, "a"), _tone(record, "b")
    found = camelot.steps(tone_a, tone_b) if tone_a and tone_b else None
    if found is not None:
        f["key_steps"], f["key_score"], f["key_mode_change"] = float(found[0]), camelot.score(tone_a, tone_b), 0.0 if found[1] else 1.0
        f["key_missing"] = 0.0
    else:
        f["key_steps"] = f["key_score"] = f["key_mode_change"] = math.nan
        f["key_missing"] = 1.0
    confs = [_first(record.get(f"{s}_tone_conf"), _info(record, s).get("tone_conf")) for s in ("a", "b")]
    f["key_conf"] = min(confs) if found is not None and None not in confs else math.nan
    # energía
    e_a, e_b = _first(record.get("a_energy"), _info(record, "a").get("energy")), _first(record.get("b_energy"), _info(record, "b").get("energy"))
    if e_a is not None and e_b is not None:
        f["energy_delta"], f["energy_abs"], f["energy_mean"], f["energy_missing"] = e_b - e_a, abs(e_b - e_a), (e_a + e_b) / 2.0, 0.0
    else:
        f["energy_delta"] = f["energy_abs"] = f["energy_mean"] = math.nan
        f["energy_missing"] = 1.0
    # tipo y duración
    kind = str(record.get("kind") or _plan_value(record, "kind") or "")
    length = _num(_plan_value(record, "length_s"))
    if kind == "cut" or (length is not None and length <= 0):
        kind = "cut"
    for k in KINDS:
        f[f"kind_{k}"] = 1.0 if kind == k else 0.0
    length = max(0.0, length) if length is not None else math.nan
    f["length_s"] = length
    f["length_bars"] = length * bpm_a / 240.0 if bpm_a and length == length else math.nan
    durations = [d for d in (_seconds(record, "a", "duration"), _seconds(record, "b", "duration")) if d]
    f["mix_share"] = length / min(durations) if durations and length == length else math.nan
    outro = _seconds(record, "a", "outro")
    f["outro_a"] = min(outro, 60.0) / 10.0 if outro is not None else math.nan
    # rejillas
    grids = [_grid_conf(record, "a"), _grid_conf(record, "b")]
    if None in grids:
        f["grid_conf"], f["grid_missing"] = math.nan, 1.0
    else:
        f["grid_conf"], f["grid_missing"] = min(grids), 0.0
    values = [f[name] for name in PLAN_FEATURES]
    if use_audio:
        metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
        audio = [_audio_value(metrics, name) for name in AUDIO_METRICS]
        score = _num(record.get("auto_score"))
        missing = score is None and all(v is None for v in audio)
        values += [math.nan if score is None else score] + [math.nan if v is None else v for v in audio] + [1.0 if missing else 0.0]
    return np.array(values, dtype=float)


def _audio_value(metrics, name):
    """Valor físico de una métrica de `transition_scorer` (vale el dict entero de la métrica o el número suelto), escalado."""
    m = metrics.get(name)
    value = _num(m.get("value") if isinstance(m, dict) else m)
    if value is None:
        return None
    if name == "clipping":
        return math.log10(max(value, 1e-7))
    if name == "click":
        return min(value, 50.0) / 10.0
    if name == "beat_offset_ms":
        return value / 30.0
    if name == "silence_gap_ms":
        return value / 250.0
    return value


def feature_names(use_audio: bool = False) -> tuple:
    return PLAN_FEATURES + (AUDIO_FEATURES if use_audio else ())


def matrix(records, use_audio: bool = False) -> np.ndarray:
    """Matriz (n, d) con las características de varias transiciones."""
    rows = [features(r, use_audio) for r in records]
    return np.vstack(rows) if rows else np.zeros((0, len(feature_names(use_audio))))


def labels(records) -> np.ndarray:
    return np.array([label_of(r.get("vote")) for r in records], dtype=float)


# ----------------------------------------------------------------------------------------------- particiones y métricas
def _folds(y, k, seed):
    """Índices de k particiones estratificadas (las dos clases repartidas por igual)."""
    rng = np.random.default_rng(seed)
    folds = [[] for _ in range(k)]
    for cls in (0, 1):
        idx = np.flatnonzero(y == cls)
        rng.shuffle(idx)
        for i, j in enumerate(idx):
            folds[i % k].append(int(j))
    return [np.array(sorted(f), dtype=int) for f in folds]


def auc(y, p) -> float:
    """Área bajo la curva ROC (Mann-Whitney, con empates); 0,5 si solo hay una clase."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    if pos == 0 or neg == 0:
        return 0.5
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sorted_p = p[order]
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and sorted_p[j + 1] == sorted_p[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def calibration(y, p, bins: int = 5) -> dict:
    """Calibración: por tramos de probabilidad predicha, la media predicha y lo que pasó de verdad; `ece` = error medio pesado."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    table, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & ((p < hi) if hi < 1.0 else (p <= hi))
        count = int(mask.sum())
        if count:
            mean_p, observed = float(p[mask].mean()), float(y[mask].mean())
            ece += count / len(p) * abs(mean_p - observed)
            table.append({"from": round(float(lo), 2), "to": round(float(hi), 2), "count": count,
                          "predicted": round(mean_p, 3), "observed": round(observed, 3)})
    return {"bins": table, "ece": round(ece, 4)}


def _check_trainable(y):
    n, up = len(y), int((y == 1).sum())
    down = n - up
    if n < MIN_VOTES:
        raise NotEnoughData(f"hacen falta al menos {MIN_VOTES} votos para entrenar (hay {n})")
    if up < MIN_PER_CLASS or down < MIN_PER_CLASS:
        raise NotEnoughData(f"hacen falta al menos {MIN_PER_CLASS} votos buenos y {MIN_PER_CLASS} malos (hay {up} y {down})")


# ----------------------------------------------------------------------------------------------- el modelo
class TasteModel:
    """Probabilidad de que una transición le guste al usuario. Ver la explicación del módulo."""

    def __init__(self, kind: str = "logistic", use_audio: bool = False, l2: float = None, hidden: int = MLP_HIDDEN, seed: int = 0):
        if kind not in ("logistic", "mlp"):
            raise ValueError(f"tipo de modelo desconocido {kind!r}: «logistic» o «mlp»")
        self.kind, self.use_audio, self.l2, self.hidden, self.seed = kind, bool(use_audio), l2, int(hidden), int(seed)
        self.mean = self.std = None
        self.params = None
        self.n_train = self.n_up = self.n_down = 0
        self.l2_used = None
        self.trained_at = None
        self.cv = None

    # ---- datos
    @property
    def names(self) -> tuple:
        return feature_names(self.use_audio)

    @property
    def fitted(self) -> bool:
        return self.params is not None

    def _as_matrix(self, x):
        if isinstance(x, dict):
            return matrix([x], self.use_audio), True
        if isinstance(x, (list, tuple)) and x and isinstance(x[0], dict):
            return matrix(x, self.use_audio), False
        arr = np.asarray(x, dtype=float)
        if arr.ndim == 1:
            return arr.reshape(1, -1), True
        return arr, False

    def _standardize(self, X):
        Z = (X - self.mean) / self.std
        Z[~np.isfinite(Z)] = 0.0              # lo que no se sabe: la media
        return Z

    # ---- entrenar
    def fit(self, records, y=None):
        """Entrena con transiciones votadas (`records` con su `vote` +1 / -1, o una matriz y `y` con 1 / 0). Devuelve el modelo.
        Lanza NotEnoughData con menos de 30 votos o menos de 5 de alguna clase."""
        if y is None:
            X, y = matrix(records, self.use_audio), labels(records)
        else:
            X, y = np.asarray(records, dtype=float), np.asarray(y, dtype=float)
        _check_trainable(y)
        with np.errstate(all="ignore"):
            mean = np.nanmean(np.where(np.isfinite(X), X, np.nan), axis=0)
            std = np.nanstd(np.where(np.isfinite(X), X, np.nan), axis=0)
        self.mean = np.where(np.isfinite(mean), mean, 0.0)
        self.std = np.where(np.isfinite(std) & (std > 1e-9), std, 1.0)
        Z = self._standardize(X.copy())
        l2 = self.l2
        if l2 is None:
            l2 = (L2_SMALL if len(y) < SMALL_DATA else self._choose_l2(Z, y)) if self.kind == "logistic" else MLP_L2
        self.params = self._train(Z, y, l2)
        self.l2_used = float(l2)
        self.n_train, self.n_up = len(y), int((y == 1).sum())
        self.n_down = self.n_train - self.n_up
        self.trained_at = time.time()
        return self

    def _train(self, Z, y, l2):
        return _fit_logistic(Z, y, l2) if self.kind == "logistic" else _fit_mlp(Z, y, l2, self.hidden, self.seed)

    def _choose_l2(self, Z, y):
        folds = _folds(y, 5, self.seed + 1)
        best, best_loss = L2_GRID[0], math.inf
        for l2 in L2_GRID:
            loss = 0.0
            for test in folds:
                train = np.setdiff1d(np.arange(len(y)), test)
                w = _fit_logistic(Z[train], y[train], l2)
                p = np.clip(_sigmoid(_logit_logistic(w, Z[test])), 1e-6, 1 - 1e-6)
                loss -= float((y[test] * np.log(p) + (1 - y[test]) * np.log(1 - p)).sum())
            if loss < best_loss - 1e-9:
                best, best_loss = l2, loss
        return best

    # ---- predecir
    def _logit_z(self, Z):
        if self.kind == "logistic":
            return _logit_logistic(self.params, Z)
        return _logit_mlp(self.params, Z)

    def predict_proba(self, x):
        """Probabilidad de que le guste (0 a 1), recortada según los votos con que se entrenó (`max_confidence`). `x`: un
        registro (dict), una lista de registros, un vector o una matriz de características. Un número si se pasó uno solo."""
        if not self.fitted:
            raise RuntimeError("el modelo no está entrenado")
        X, single = self._as_matrix(x)
        if X.shape[1] != len(self.names):
            raise ValueError(f"se esperaban {len(self.names)} características y llegan {X.shape[1]}")
        p = _sigmoid(self._logit_z(self._standardize(X.astype(float))))
        cap = max_confidence(self.n_train)
        p = np.clip(p, 1.0 - cap, cap)
        return float(p[0]) if single else p

    def explain(self, x, top: int = 3) -> list:
        """Las `top` características que más pesan en la predicción de UNA transición: cuánto cambia el logit si esa
        característica valiera lo normal (la media). [{"feature", "label", "value", "effect", "text"}], de más a menos."""
        if not self.fitted:
            return []
        X, _ = self._as_matrix(x)
        raw = X[0].astype(float)
        z = self._standardize(raw.reshape(1, -1).copy())
        base = float(self._logit_z(z)[0])
        out = []
        for j, name in enumerate(self.names):
            if z[0, j] == 0.0:
                continue
            zz = z.copy()
            zz[0, j] = 0.0
            effect = base - float(self._logit_z(zz)[0])
            out.append((abs(effect), j, name, effect))
        out.sort(reverse=True)
        result = []
        for _mag, j, name, effect in out[:top]:
            value = raw[j]
            result.append({"feature": name, "label": LABELS.get(name, name), "value": None if not math.isfinite(value) else round(float(value), 3),
                           "effect": round(effect, 3),
                           "text": f"{LABELS.get(name, name)}: {'a favor' if effect > 0 else 'en contra'}"})
        return result

    def rank_candidates(self, candidates) -> list:
        """[(candidata, probabilidad)] de la que más le gustaría a la que menos."""
        candidates = list(candidates)
        if not candidates:
            return []
        p = np.atleast_1d(self.predict_proba(candidates))
        order = np.argsort(-p, kind="mergesort")
        return [(candidates[i], float(p[i])) for i in order]

    # ---- guardar y cargar
    def to_dict(self) -> dict:
        if not self.fitted:
            raise RuntimeError("el modelo no está entrenado")
        return {"format": "taste_model", "version": FORMAT_VERSION, "kind": self.kind, "use_audio": self.use_audio,
                "features": list(self.names), "mean": self.mean.tolist(), "std": self.std.tolist(), "hidden": self.hidden,
                "params": {k: np.asarray(v).tolist() for k, v in self.params.items()}, "l2": self.l2_used,
                "n_train": self.n_train, "n_up": self.n_up, "n_down": self.n_down, "trained_at": self.trained_at, "cv": self.cv}

    @classmethod
    def from_dict(cls, data: dict):
        """El modelo guardado, o None si el archivo no vale (otro formato, otras características, números estropeados)."""
        try:
            if data.get("format") != "taste_model" or data.get("version") != FORMAT_VERSION:
                return None
            model = cls(data["kind"], bool(data.get("use_audio")), hidden=int(data.get("hidden") or MLP_HIDDEN))
            if tuple(data["features"]) != model.names:
                return None                   # el código cambió de características: hay que volver a entrenar
            model.mean, model.std = np.array(data["mean"], dtype=float), np.array(data["std"], dtype=float)
            model.params = {k: np.array(v, dtype=float) for k, v in data["params"].items()}
            if len(model.mean) != len(model.names) or not all(np.isfinite(v).all() for v in model.params.values()):
                return None
            model.l2_used = data.get("l2")
            model.n_train, model.n_up, model.n_down = int(data["n_train"]), int(data["n_up"]), int(data["n_down"])
            model.trained_at, model.cv = data.get("trained_at"), data.get("cv")
            model.predict_proba(np.zeros(len(model.names)))      # que de verdad funcione
            return model
        except Exception as e:
            logger.warning("modelo de gusto guardado no válido: %s", e)
            return None

    def save(self, path=None) -> bool:
        try:
            _write_json(path or MODEL_PATH, self.to_dict())
            return True
        except Exception as e:
            logger.warning("no se pudo guardar el modelo de gusto: %s", e)
            return False


def load_model(path=None):
    """El modelo guardado en la carpeta de datos, o None si no hay o no vale."""
    path = path or MODEL_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            return TasteModel.from_dict(json.load(fh))
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning("no se pudo leer el modelo de gusto: %s", e)
        return None


# ----------------------------------------------------------------------------------------------- entrenamiento numérico
def _design(Z):
    return np.hstack((Z, np.ones((len(Z), 1))))


def _fit_logistic(Z, y, l2):
    """Regresión logística con L2 (sin penalizar el término independiente), por Newton. Devuelve {"w", "b"}."""
    A = _design(Z)
    d = A.shape[1]
    reg = np.full(d, float(l2))
    reg[-1] = 1e-6
    w = np.zeros(d)
    rate = float(np.clip(y.mean(), 1e-3, 1 - 1e-3))
    w[-1] = math.log(rate / (1 - rate))
    for _ in range(NEWTON_ITERS):
        p = _sigmoid(A @ w)
        grad = A.T @ (p - y) + reg * w
        hess = (A.T * (p * (1 - p))) @ A + np.diag(reg) + 1e-9 * np.eye(d)
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(hess, grad, rcond=None)[0]
        w -= step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return {"w": w[:-1].copy(), "b": np.array([w[-1]])}


def _logit_logistic(params, Z):
    return Z @ params["w"] + params["b"][0]


def _fit_mlp(Z, y, l2, hidden, seed):
    """Una capa oculta (tanh) y salida logística, con Adam sobre todo el lote y L2 en los pesos. Devuelve sus parámetros."""
    rng = np.random.default_rng(seed)
    n, d = Z.shape
    rate = float(np.clip(y.mean(), 1e-3, 1 - 1e-3))
    params = {"W1": rng.normal(0.0, 1.0 / math.sqrt(max(d, 1)), (d, hidden)), "b1": np.zeros(hidden),
              "w2": rng.normal(0.0, 1.0 / math.sqrt(hidden), hidden), "b2": np.array([math.log(rate / (1 - rate))])}
    m = {k: np.zeros_like(v) for k, v in params.items()}
    v = {k: np.zeros_like(v) for k, v in params.items()}
    b1m, b2m, eps = 0.9, 0.999, 1e-8
    for t in range(1, MLP_ITERS + 1):
        h = np.tanh(Z @ params["W1"] + params["b1"])
        p = _sigmoid(h @ params["w2"] + params["b2"][0])
        g_out = (p - y) / n
        grads = {"w2": h.T @ g_out + l2 / n * params["w2"], "b2": np.array([g_out.sum()])}
        g_h = np.outer(g_out, params["w2"]) * (1 - h * h)
        grads["W1"] = Z.T @ g_h + l2 / n * params["W1"]
        grads["b1"] = g_h.sum(axis=0)
        for k in params:
            m[k] = b1m * m[k] + (1 - b1m) * grads[k]
            v[k] = b2m * v[k] + (1 - b2m) * grads[k] ** 2
            params[k] = params[k] - MLP_LR * (m[k] / (1 - b1m ** t)) / (np.sqrt(v[k] / (1 - b2m ** t)) + eps)
    return params


def _logit_mlp(params, Z):
    return np.tanh(Z @ params["W1"] + params["b1"]) @ params["w2"] + params["b2"][0]


# ----------------------------------------------------------------------------------------------- validación cruzada
def cross_validate(records, k: int = 5, kind: str = "logistic", use_audio: bool = False, seed: int = 0, l2: float = None) -> dict:
    """Acierto con transiciones que el modelo NO ha visto: k particiones estratificadas; en cada una se entrena con el resto
    (eligiendo su propia L2) y se predice esa. Devuelve {"n", "k", "accuracy", "auc", "log_loss", "brier", "base_rate",
    "majority_accuracy", "calibration": {...}, "gate_75": bool}. Lanza NotEnoughData como `fit`."""
    X, y = matrix(records, use_audio), labels(records)
    _check_trainable(y)
    k = max(2, min(int(k), int(min((y == 1).sum(), (y == 0).sum()))))
    p = np.zeros(len(y))
    for i, test in enumerate(_folds(y, k, seed)):
        train = np.setdiff1d(np.arange(len(y)), test)
        model = TasteModel(kind, use_audio, l2=l2, seed=seed + i)
        try:
            model.fit(X[train], y[train])
            p[test] = model.predict_proba(X[test])
        except NotEnoughData:
            p[test] = float(y[train].mean())
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    acc = float(((p >= 0.5) == (y == 1)).mean())
    base = float(y.mean())
    return {"n": int(len(y)), "k": k, "accuracy": round(acc, 4), "auc": round(auc(y, p), 4),
            "log_loss": round(float(-(y * np.log(pc) + (1 - y) * np.log(1 - pc)).mean()), 4),
            "brier": round(float(((p - y) ** 2).mean()), 4), "base_rate": round(base, 4),
            "majority_accuracy": round(max(base, 1 - base), 4), "calibration": calibration(y, p),
            "gate_75": acc > GATE_ACCURACY, "kind": kind}


# ----------------------------------------------------------------------------------------------- estado honesto
def status(n_votes, cv: dict = None) -> dict:
    """En qué punto está el modelo según los votos (tabla del plan) y, si se da, la validación cruzada.
    {"level", "text", "votes", "next_goal", "missing", "max_confidence", "detail"}. Nunca promete más de lo que hay."""
    n = max(0, int(n_votes or 0))
    level, text = next((name, label) for votes, name, label in LEVELS if n >= votes)
    if level == "sin_modelo":
        text = f"Sin modelo: faltan {MIN_VOTES - n} votos para el primero"
    goal = next((g for g in GOALS if g > n), None)
    detail = ""
    if cv and level != "sin_modelo":
        acc, majority, area = cv.get("accuracy"), cv.get("majority_accuracy"), cv.get("auc")
        if acc is not None and majority is not None:
            detail = f"acierta el {round(acc * 100)} % de los votos que no ha visto (decir siempre lo mismo daría {round(majority * 100)} %)"
            if acc <= majority + 0.02 or (area is not None and area < 0.6):
                level, text = "no_aprende", "Todavía no acierta más que adivinar: hacen falta más votos (o más constantes)"
    return {"level": level, "text": text, "votes": n, "next_goal": goal, "missing": None if goal is None else goal - n,
            "max_confidence": max_confidence(n) if n >= MIN_VOTES else 0.5, "detail": detail}


# ----------------------------------------------------------------------------------------------- detalle de los votos
def _write_json(path, payload):
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def extra_of(record) -> dict:
    """Lo que la tabla de votos no guarda y el modelo usa: confianzas de rejilla y tono, duraciones, final y notas de audio."""
    out = {}
    for side in ("a", "b"):
        grid = _grid_conf(record, side)
        conf = _first(record.get(f"{side}_tone_conf"), _info(record, side).get("tone_conf"))
        for key, value in ((f"{side}_grid_conf", grid), (f"{side}_tone_conf", conf),
                           (f"{side}_duration_s", _seconds(record, side, "duration")), (f"{side}_outro_s", _seconds(record, side, "outro"))):
            if value is not None:
                out[key] = round(float(value), 4)
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    clean = {}
    for name in AUDIO_METRICS:
        m = metrics.get(name)
        value = _num(m.get("value") if isinstance(m, dict) else m)
        if value is not None:
            clean[name] = value
    if clean:
        out["metrics"] = clean
    return out


def load_extras(path=None) -> dict:
    try:
        with open(path or EXTRAS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("no se pudo leer el detalle de los votos: %s", e)
        return {}


def save_extra(vote_id, record, path=None) -> bool:
    """Guarda el detalle de un voto (ver `extra_of`) con su id. False si falla (el voto ya está guardado igualmente)."""
    if vote_id is None:
        return False
    try:
        data = load_extras(path)
        data[str(vote_id)] = extra_of(record)
        _write_json(path or EXTRAS_PATH, data)
        return True
    except Exception as e:
        logger.warning("no se pudo guardar el detalle del voto %s: %s", vote_id, e)
        return False


def training_records(info_for=None, rows=None) -> list:
    """Los votos de la base (o `rows`) listos para el modelo: cada fila con su detalle guardado y, si falta y se da
    `info_for(ruta) -> ficha`, con las fichas de ahora de sus canciones."""
    if rows is None:
        from services import transition_votes
        rows = transition_votes.votes()
    extras = load_extras()
    out = []
    for row in rows:
        record = dict(row)
        extra = extras.get(str(row.get("id")))
        if isinstance(extra, dict):
            record.update(extra)
        elif info_for is not None:
            for side in ("a", "b"):
                try:
                    info = info_for(row.get(f"{side}_path"))
                except Exception:
                    info = None
                if isinstance(info, dict):
                    record[f"{side}_info"] = info
        out.append(record)
    return out


def train_from_db(info_for=None, kind: str = "logistic", save: bool = True, rows=None):
    """Entrena con todos los votos guardados. Devuelve (modelo o None, estado, validación cruzada o None). Con pocos votos no
    entrena y lo dice en el estado; nunca lanza por falta de datos."""
    records = training_records(info_for, rows)
    try:
        cv = cross_validate(records, kind=kind)
        model = TasteModel(kind).fit(records)
    except NotEnoughData as e:
        st = status(len(records))
        st["detail"] = str(e)
        return None, st, None
    model.cv = cv
    if save:
        model.save()
    return model, status(len(records), cv), cv


def plan_dict(plan) -> dict:
    """Un `TransitionPlan` (o dict) como dict, para guardarlo o pasarlo a `features`."""
    if is_dataclass(plan) and not isinstance(plan, type):
        return asdict(plan)
    return dict(plan) if isinstance(plan, dict) else {}
