"""Modelo de gusto (fase 26) con votos SINTÉTICOS de verdad conocida: un «gusto» inventado (una función de las características
con ruido) vota transiciones de una biblioteca inventada, y se comprueba que el modelo lo aprende por encima del azar, que no
entrena con pocos votos ni con una sola clase, que no da confianza alta con pocos datos, su calibración, guardar y cargar,
características raras y el tiempo que tarda.

Lo que NO comprueba (no se puede sin votos reales): que aprenda TU gusto, ni la puerta de la fase 26 (acertar más del 75 % de
tus votos en transiciones que no ha visto). Aquí el gusto es una fórmula: aprenderla solo demuestra que el código funciona.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_gusto.py"""
import json
import logging
import math
import os
import random
import sys
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import taste_model as tm
from services import transition_votes, vote_session
from services.mix_types import BeatGrid

logging.disable(logging.CRITICAL)        # silenciosa: los avisos esperados (archivo roto...) no se imprimen


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def info(msg):
    print("     " + msg, flush=True)


# ------------------------------------------------------------------ biblioteca y gusto sintéticos
def library(n, seed):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        family = rng.choice((92, 96, 124, 128, 172))
        bpm = family * rng.uniform(0.97, 1.03)
        dur = rng.uniform(150, 240)
        grid = BeatGrid(0.12, bpm, 4, 0, rng.uniform(0.2, 0.95)) if rng.random() < 0.8 else None
        out.append({"path": f"C:/musica/cancion_{seed}_{i}.mp3", "title": f"Canción {i}", "bpm": bpm, "beatgrid": grid,
                    "tone": f"{rng.randint(1, 12)}{rng.choice('AB')}", "tone_conf": rng.uniform(0.3, 1.0),
                    "energy": rng.uniform(0.1, 0.95), "duration_s": dur, "intro_s": rng.uniform(4, 30), "outro_s": rng.uniform(6, 40)})
    return out


NAMES = tm.PLAN_FEATURES


def true_logit(c):
    f = dict(zip(NAMES, tm.features(c)))
    gap = f["bpm_gap"] if f["bpm_gap"] == f["bpm_gap"] else 4.0
    key = f["key_score"] if f["key_score"] == f["key_score"] else 0.5
    grid = f["grid_conf"] if f["grid_conf"] == f["grid_conf"] else 0.3
    return 2.0 * (1.5 - 0.35 * gap - 2.0 * (key <= 0.0) + 1.0 * f["kind_blend"] - 0.5 * f["kind_cut_bar"] - 1.5 * f["kind_cut"]
            - 2.5 * f["energy_abs"] + 1.5 * (grid - 0.5))


def true_p(c):
    return 1.0 / (1.0 + math.exp(-true_logit(c)))


def votes_for(cands, seed, p_of=true_p):
    rng = random.Random(seed)
    rows = []
    for c in cands:
        r = dict(c)
        r["vote"] = 1 if rng.random() < p_of(c) else -1
        rows.append(r)
    return rows


lib = library(80, 1)
pool = vote_session.build_candidates(lib, 4000, random.Random(2))
rng = random.Random(3)
rng.shuffle(pool)
train_pool, test_pool = pool[:2400], pool[2400:]
check(f"la biblioteca sintética da muchas candidatas ({len(pool)})", len(pool) >= 3000)
p_test = np.array([true_p(c) for c in test_pool])
y_test = np.array([1.0 if v["vote"] > 0 else 0.0 for v in votes_for(test_pool, 99)])
bayes = float(np.mean(np.maximum(p_test, 1 - p_test)))
info(f"gusto sintético: le gusta el {np.mean(p_test) * 100:.0f} % · acierto máximo posible con ese ruido (Bayes): {bayes * 100:.1f} %")

# ------------------------------------------------------------------ características
x = tm.features(pool[0])
check("el vector tiene una característica por nombre", x.shape == (len(tm.PLAN_FEATURES),))
check("con audio, más características", tm.features(pool[0], use_audio=True).shape == (len(tm.PLAN_FEATURES) + len(tm.AUDIO_FEATURES),))
raros = [{}, None, "basura", {"a_bpm": "rápido", "b_bpm": float("inf"), "kind": 12, "length_s": -5, "a_tone": "Zm", "b_tone": None,
                             "a_energy": float("nan"), "tempo_ratio_b": 0},
         {"a_bpm": 0, "b_bpm": -120, "a_info": "no", "b_info": {"beatgrid": "x", "duration_ms": "mucho"}, "plan": 3},
         {"a_bpm": 1e9, "b_bpm": 1e-9, "a_tone": "8A", "b_tone": "8A", "kind": "desconocido", "metrics": {"click": "x"}}]
ok = True
for r in raros:
    try:
        v = tm.features(r, use_audio=True)
        ok = ok and not np.isinf(v).any()
    except Exception as e:
        info(f"lanzó con {r!r}: {e}")
        ok = False
check("características raras: nunca lanza ni da infinitos (lo que no entiende es «no se sabe»)", ok)
fila = {"a_bpm": 128, "b_bpm": 64, "a_tone": "8A", "b_tone": "3B", "a_energy": 0.2, "b_energy": 0.9, "kind": "filter", "length_s": 15.0,
        "tempo_ratio_b": 1.0, "vote": 1}
f = dict(zip(NAMES, tm.features(fila)))
check("una fila de la base: 128 y 64 BPM son el mismo ritmo (doble), con salto de familia",
      abs(f["bpm_gap"]) < 1e-9 and f["tempo_family"] == 1.0 and f["kind_filter"] == 1.0)
check("tonos 8A y 3B: distancia, nota 0 y cambio de modo", f["key_steps"] == 5 and f["key_score"] == 0.0 and f["key_mode_change"] == 1.0)
check("energía de 0,2 a 0,9: sube 0,7", abs(f["energy_delta"] - 0.7) < 1e-9 and f["grid_missing"] == 1.0)

# ------------------------------------------------------------------ no entrena sin datos suficientes
rows300 = votes_for(train_pool[:300], 10)


def raises(fn):
    try:
        fn()
    except tm.NotEnoughData:
        return True
    return False


check("con 29 votos no entrena", raises(lambda: tm.TasteModel().fit(rows300[:29])))
una = [dict(r, vote=1) for r in rows300[:100]]
check("con 100 votos de una sola clase no entrena", raises(lambda: tm.TasteModel().fit(una)))
casi = [dict(r, vote=1) for r in rows300[:37]] + [dict(r, vote=-1) for r in rows300[37:40]]
check("con 40 votos pero solo 3 malos no entrena", raises(lambda: tm.TasteModel().fit(casi)))
check("ni la validación cruzada con pocos votos", raises(lambda: tm.cross_validate(rows300[:20])))
try:
    tm.TasteModel().predict_proba(np.zeros(len(NAMES)))
    sin_entrenar = False
except RuntimeError:
    sin_entrenar = True
check("un modelo sin entrenar no predice", sin_entrenar)

# ------------------------------------------------------------------ aprende el gusto sintético
cv = tm.cross_validate(rows300, k=5)
info(f"300 votos, validación cruzada 5 particiones: acierto {cv['accuracy'] * 100:.1f} % (mayoría {cv['majority_accuracy'] * 100:.1f} %, "
     f"Bayes {bayes * 100:.1f} %), AUC {cv['auc']:.3f}, log-loss {cv['log_loss']:.3f}, ECE {cv['calibration']['ece']:.3f}")
check("con 300 votos acierta por encima del azar en transiciones que no ha visto (más de la mayoría + 5 puntos)",
      cv["accuracy"] > cv["majority_accuracy"] + 0.05)
check("y ordena bien (AUC > 0,7)", cv["auc"] > 0.7)
check("calibración razonable (error medio por tramos < 0,12)", cv["calibration"]["ece"] < 0.12)
for b in cv["calibration"]["bins"]:
    info(f"  predijo {b['from']:.1f} a {b['to']:.1f}: {b['count']} votos, media predicha {b['predicted']:.2f}, le gustó {b['observed']:.2f}")

# curva de aprendizaje en un conjunto aparte (el mismo para todos)
X_test = tm.matrix(test_pool)
curve = {}
for n in (100, 300, 1000, 1500):
    rows = votes_for(train_pool[:n], 20 + n)
    model = tm.TasteModel().fit(rows)
    p = model.predict_proba(X_test)
    acc = float(((p >= 0.5) == (y_test == 1)).mean())
    agree = float(((p >= 0.5) == (p_test >= 0.5)).mean())
    clear = (p_test < 0.2) | (p_test > 0.8)
    auc_clear = tm.auc(p_test[clear] > 0.5, p[clear]) if clear.any() else float("nan")
    curve[n] = (acc, tm.auc(y_test, p), agree, auc_clear, float(p.max()))
    info(f"{n:>5} votos: acierto con votos nuevos {acc * 100:.1f} % (Bayes {bayes * 100:.1f} %), AUC {curve[n][1]:.3f}, coincide con el gusto "
         f"real sin ruido {agree * 100:.1f} %, AUC en lo claramente bueno/malo {auc_clear:.3f}, p máx {curve[n][4]:.2f}")
check("más votos, mejor o igual (1.500 frente a 100, con 1 punto de margen)", curve[1500][0] >= curve[100][0] - 0.01)
check("con 100 votos ya separa lo claramente malo de lo claramente bueno (AUC > 0,8 en esos casos)", curve[100][3] > 0.8)

# ------------------------------------------------------------------ nunca confianza alta con pocos datos
facil = [dict(c, vote=1 if true_logit(c) > 0 else -1) for c in train_pool[:40]]
if sum(r["vote"] > 0 for r in facil) >= 5 and sum(r["vote"] < 0 for r in facil) >= 5:
    m40 = tm.TasteModel().fit(facil)
    p40 = m40.predict_proba(X_test)
    check(f"con 40 votos perfectamente separables, nunca pasa de 0,75 ni baja de 0,25 (da {p40.min():.2f} a {p40.max():.2f})",
          p40.max() <= 0.75 + 1e-9 and p40.min() >= 0.25 - 1e-9)
else:
    check("(no hay 5 de cada clase en los 40 primeros: se salta)", True)
check("el tope sube con los votos (0,75 / 0,85 / 0,93 / 0,98)",
      [tm.max_confidence(n) for n in (40, 100, 300, 1000)] == [0.75, 0.85, 0.93, 0.98])

# ------------------------------------------------------------------ votos al azar: no aprende y lo dice
ruido = [dict(c, vote=random.Random(i).choice((1, -1))) for i, c in enumerate(train_pool[:300])]
cv_ruido = tm.cross_validate(ruido)
st = tm.status(300, cv_ruido)
info(f"votos al azar: acierto {cv_ruido['accuracy'] * 100:.1f} % (mayoría {cv_ruido['majority_accuracy'] * 100:.1f} %), AUC {cv_ruido['auc']:.3f} "
     f"; estado «{st['level']}»")
check("con votos al azar no acierta más que adivinar (AUC < 0,62)", cv_ruido["auc"] < 0.62)
check("y el estado lo dice («no_aprende») aunque haya 300 votos", st["level"] == "no_aprende")

# ------------------------------------------------------------------ estados honestos
levels = {n: tm.status(n)["level"] for n in (0, 29, 30, 99, 100, 299, 300, 999, 1000, 5000)}
check("estados según los votos: sin modelo (<30), aprendiendo, solo lo malo (100), usable (300), bueno (1.000)",
      levels == {0: "sin_modelo", 29: "sin_modelo", 30: "aprendiendo", 99: "aprendiendo", 100: "solo_malo", 299: "solo_malo",
                 300: "usable", 999: "usable", 1000: "bueno", 5000: "bueno"})
check("«sin modelo» dice cuántos faltan", "faltan 18" in tm.status(12)["text"])
check("con validación cruzada buena, el estado da el acierto", "acierta el" in tm.status(300, cv)["detail"] and tm.status(300, cv)["level"] == "usable")

# ------------------------------------------------------------------ explicar y ordenar
model = tm.TasteModel().fit(votes_for(train_pool[:1000], 5))
choque = next(c for c in test_pool if dict(zip(NAMES, tm.features(c)))["key_score"] == 0.0)
why = model.explain(choque)
info("por qué (tonos que chocan): " + "; ".join(f"{w['label']} {w['effect']:+.2f}" for w in why))
check("explain da las 3 que más pesan, con su etiqueta en español", len(why) == 3 and all(w["label"] and w["text"] for w in why))
check("y con tonos que chocan, el tono sale entre ellas y en contra",
      any(w["feature"] in ("key_score", "key_steps") and w["effect"] < 0 for w in why))
ranked = model.rank_candidates(test_pool[:200])
ps = [p for _c, p in ranked]
check("rank_candidates ordena de más a menos probable", ps == sorted(ps, reverse=True) and len(ranked) == 200)
top = np.mean([true_p(c) for c, _p in ranked[:20]])
bottom = np.mean([true_p(c) for c, _p in ranked[-20:]])
check(f"las 20 primeras le gustan más de verdad que las 20 últimas ({top:.2f} frente a {bottom:.2f})", top > bottom + 0.2)
check("predict_proba con un solo registro da un número", isinstance(model.predict_proba(test_pool[0]), float))
check("uncertainty: 1 en 0,5 y 0 en los extremos", tm.uncertainty(0.5) == 1.0 and tm.uncertainty(1.0) == 0.0 and abs(tm.uncertainty(0.75) - 0.5) < 1e-9)

# ------------------------------------------------------------------ guardar y cargar
path = os.path.join(os.environ["DESCARGADOR_DATA_DIR"], "modelo_prueba.json")
check("se guarda en JSON", model.save(path) and os.path.isfile(path))
again = tm.load_model(path)
check("y se carga con las mismas predicciones", again is not None and np.allclose(again.predict_proba(X_test), model.predict_proba(X_test)))
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
data["features"] = data["features"][:-1] + ["otra_cosa"]
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh)
check("un modelo con otras características no se carga (hay que volver a entrenar)", tm.load_model(path) is None)
with open(path, "w", encoding="utf-8") as fh:
    fh.write("{roto")
check("un archivo roto tampoco (sin lanzar)", tm.load_model(path) is None)
check("sin archivo: None", tm.load_model(path + ".no") is None)

# ------------------------------------------------------------------ MLP (opcional) con un gusto no lineal
def u_logit(c):
    f = dict(zip(NAMES, tm.features(c)))
    length = f["length_s"] if f["length_s"] == f["length_s"] else 0.0
    return 1.2 - ((length - 16.0) / 6.0) ** 2 - 2.0 * f["kind_cut"]


u_rows = votes_for(train_pool[:800], 7, p_of=lambda c: 1 / (1 + math.exp(-u_logit(c))))
cv_lin = tm.cross_validate(u_rows, kind="logistic")
t0 = time.perf_counter()
cv_mlp = tm.cross_validate(u_rows, kind="mlp")
info(f"gusto no lineal (le gustan las mezclas de unos 16 s): logística AUC {cv_lin['auc']:.3f} (acierto {cv_lin['accuracy'] * 100:.1f} %), "
     f"MLP AUC {cv_mlp['auc']:.3f} (acierto {cv_mlp['accuracy'] * 100:.1f} %) en {time.perf_counter() - t0:.1f} s")
check("el MLP aprende un gusto no lineal por encima del azar (AUC > 0,65)", cv_mlp["auc"] > 0.65)
mlp = tm.TasteModel("mlp").fit(u_rows)
mlp.save(path)
check("el MLP también se guarda y se carga", np.allclose(tm.load_model(path).predict_proba(X_test[:50]), mlp.predict_proba(X_test[:50])))

# ------------------------------------------------------------------ la base de datos de verdad
check("con la base vacía: sin modelo y sin lanzar", tm.train_from_db()[0] is None and tm.train_from_db()[1]["level"] == "sin_modelo")
for r in votes_for(train_pool[:120], 11):
    vid = vote_session.record_vote(r, r["vote"], session="prueba")
    if vid is None:
        break
check("120 votos sintéticos guardados con origen «clip»", transition_votes.count()["total"] == 120
      and transition_votes.summary()["by_source"].get("clip", {}).get("total") == 120)
check("con su detalle aparte (rejillas, duraciones)", len(tm.load_extras()) == 120)
m_db, st_db, cv_db = tm.train_from_db()
check("entrena con los votos de la base y guarda el modelo", m_db is not None and os.path.isfile(tm.MODEL_PATH) and tm.load_model() is not None)
info(f"con la base (120 votos): estado «{st_db['level']}» · {st_db['detail']}")
check("el modelo de la base distingue el gusto (AUC con votos nuevos > 0,65)", tm.auc(y_test, m_db.predict_proba(X_test)) > 0.65)

# ------------------------------------------------------------------ rendimiento
recs = test_pool[:1600] * 3
t0 = time.perf_counter()
Xb = tm.matrix(recs)
t_feat = time.perf_counter() - t0
t0 = time.perf_counter()
big = tm.TasteModel().fit(votes_for(train_pool[:1500], 30))
t_fit = time.perf_counter() - t0
t0 = time.perf_counter()
big.predict_proba(Xb)
t_pred = time.perf_counter() - t0
t0 = time.perf_counter()
tm.cross_validate(votes_for(train_pool[:1000], 31))
t_cv = time.perf_counter() - t0
info(f"tiempos: características de {len(recs)} transiciones {t_feat:.2f} s · entrenar con 1.500 votos {t_fit:.2f} s · "
     f"predecir {len(recs)} {t_pred * 1000:.0f} ms · validación cruzada con 1.000 votos {t_cv:.2f} s")
check(f"características de {len(recs)} transiciones en menos de 3 s", t_feat < 3.0)
check("entrenar con 1.500 votos en menos de 3 s", t_fit < 3.0)
check(f"predecir {len(recs)} en menos de 0,2 s", t_pred < 0.2)
check("validación cruzada con 1.000 votos en menos de 15 s", t_cv < 15.0)
print("FIN")
