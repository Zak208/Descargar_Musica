"""Diagnóstico (no es una prueba): cuántas transiciones del orden inteligente se pueden mezclar de verdad con TUS canciones.
Analiza las canciones de la carpeta (el análisis se guarda en una carpeta de datos temporal propia, así la segunda vez es
instantáneo y nunca se tocan tus datos), genera órdenes con semillas distintas (`dj_planner.plan`) y para cada par seguido
pide el plan de mezcla (`mix_planner.plan_transition`) y cuenta: cortes por tempo, otros cortes, mezclas sin cuadrar compases,
mezclas por frases, lo que dura la mezcla media, la correlación de la energía con la curva de fiesta, el artista repetido
seguido y el mejor y el peor par (nota de `transition_scorer.score_plan`).
Uso:  python pruebas/medir_orden_real.py [carpeta] [semillas]"""
import importlib.util
import math
import os
import random
import sys
import tempfile
import time
from collections import Counter

# carpeta de datos propia y persistente (no la del usuario ni una que se borre): el análisis queda guardado entre ejecuciones
os.environ.setdefault("DESCARGADOR_DATA_DIR", os.path.join(tempfile.gettempdir(), "descargador_medir_orden"))
os.makedirs(os.environ["DESCARGADOR_DATA_DIR"], exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401,E402  (añade src a la ruta; con la carpeta de datos ya puesta no crea otra)

from services import dj_planner, mix_planner, track_analysis, transition_scorer  # noqa: E402
from services.mix_types import KIND_CUT  # noqa: E402

AUDIO = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac", ".wma")


def load(folder):
    """{ruta: análisis} de las canciones de la carpeta (del guardado si ya se analizaron)."""
    paths = sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(AUDIO))
    found = {}
    for i, path in enumerate(paths, 1):
        result = track_analysis.stored(path, need_audio=True)
        if result is None:
            print(f"  analizando {i}/{len(paths)}: {os.path.basename(path)}", flush=True)
            result = track_analysis.analyze(path)
        if result is not None:
            found[path] = result
    return found


def info_of(analysis):
    """La ficha que recibe el planificador de mezclas (como `_dj_engine_info`, sin BPM a mano)."""
    info = dict(analysis)
    info["beatgrid"] = track_analysis.grid_from(info)
    return info


def track_of(path, analysis):
    """La ficha que recibe el orden inteligente (como `_dj_track`)."""
    energy = analysis.get("energy") if analysis.get("loudness_db") is not None else None
    return dj_planner.Track(path, analysis.get("bpm"), analysis.get("tone") or None, analysis.get("tone_conf") or 0.0, energy,
                            analysis.get("genre") or "", analysis.get("artist") or "")


def correlation(xs, ys):
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


def classify(plan):
    if plan.kind == KIND_CUT:
        return "corte_tempo" if "tempos" in plan.reason else "corte_otro"
    return "frases" if plan.bass_swap_s is not None else "sin_rejilla"


def name(path):
    return os.path.splitext(os.path.basename(path))[0][:40]


def planner_from(path):
    """Otra versión de `dj_planner` (un archivo .py), para comparar: por ejemplo la de antes, sacada con
    git show HEAD~1:src/services/dj_planner.py > viejo.py"""
    spec = importlib.util.spec_from_file_location("dj_planner_comparado", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure(planner, tracks, infos, seeds=40) -> dict:
    """Las medidas de `seeds` órdenes de `tracks` con `planner` (un módulo con `plan`). Ver la explicación del módulo."""
    n = len(tracks)
    rank = dj_planner.energy_ranker([t.energy for t in tracks])
    curve = [dj_planner.target_energy(dj_planner.curve_progress(i, n)) for i in range(n)]
    kinds, lengths, corrs, repeats, scores, ramps, seen = Counter(), [], [], [], {}, [], Counter()
    plan_time = 0.0
    orders, firsts = set(), set()
    for seed in range(seeds):
        t1 = time.perf_counter()
        order = planner.plan(tracks, rng=random.Random(seed))
        plan_time += time.perf_counter() - t1
        orders.add(tuple(t.ref for t in order))
        firsts.add(order[0].ref)
        energies = [rank(t.energy) for t in order]
        if all(e is not None for e in energies):
            corrs.append(correlation(energies, curve))
        repeats.append(sum(1 for a, b in zip(order, order[1:]) if a.artist and a.artist.strip().lower() == b.artist.strip().lower()))
        for a, b in zip(order, order[1:]):
            key = (a.ref, b.ref)
            seen[key] += 1
            if key not in scores:
                plan = mix_planner.plan_transition(infos[a.ref], infos[b.ref])
                scores[key] = (transition_scorer.score_plan(infos[a.ref], infos[b.ref], plan)["score"], classify(plan), plan.reason,
                               plan.length_s)
            kind = scores[key][1]
            kinds[kind] += 1
            if kind in ("frases", "sin_rejilla"):
                lengths.append(scores[key][3])
            ratio = mix_planner.tempo_ratio(a.bpm, b.bpm)
            if ratio is not None:
                ramps.append(abs(ratio - 1.0))
    total = max(1, sum(kinds.values()))
    most = Counter(t.artist.strip().lower() for t in tracks if t.artist).most_common(1)
    return {"seeds": seeds, "total": total, "pct": {k: 100.0 * kinds[k] / total for k in ("corte_tempo", "corte_otro", "sin_rejilla", "frases")},
            "mix_s": sum(lengths) / len(lengths) if lengths else 0.0,
            "tempo_change": 100.0 * sum(ramps) / len(ramps) if ramps else 0.0,
            "within5": 100.0 * sum(r <= 0.05 for r in ramps) / max(1, len(ramps)),
            "corr": sum(corrs) / len(corrs) if corrs else 0.0, "corr_min": min(corrs) if corrs else 0.0,
            "repeats": sum(repeats) / len(repeats), "repeats_max": max(repeats),
            "least_repeats": max(0, 2 * most[0][1] - n - 1) if most else 0,
            "orders": len(orders), "pairs": len(seen), "firsts": len(firsts), "ms": 1000 * plan_time / seeds,
            "scores": scores, "seen": seen}


def report(m) -> None:
    pct = m["pct"]
    print(f"\n{m['seeds']} órdenes, {m['total']} transiciones (planificar cada orden: {m['ms']:.1f} ms de media)")
    print(f"  corte por tempo        {pct['corte_tempo']:5.1f} %")
    print(f"  otro corte             {pct['corte_otro']:5.1f} %")
    print(f"  mezcla sin rejilla     {pct['sin_rejilla']:5.1f} %")
    print(f"  mezcla por frases      {pct['frases']:5.1f} %")
    print(f"  mezcla media           {m['mix_s']:5.1f} s")
    print(f"  cambio de tempo medio  {m['tempo_change']:5.1f} %  (dentro de ±5 %: {m['within5']:.0f} %)")
    print(f"  correlación energía    {m['corr']:5.2f}  (mín. {m['corr_min']:.2f})")
    print(f"  artista repetido       {m['repeats']:5.2f} por orden  (máx. {m['repeats_max']}; "
          f"el mínimo posible con estos artistas es {m['least_repeats']})")
    print(f"  variedad               {m['orders']} órdenes distintos, {m['pairs']} parejas distintas, {m['firsts']} primeras distintas")
    scores, seen = m["scores"], m["seen"]
    blends = sorted(((v[0], k) for k, v in scores.items() if v[1] in ("frases", "sin_rejilla")), key=lambda x: x[0])
    cuts = sorted(((seen[k], k) for k, v in scores.items() if v[1] == "corte_tempo"), key=lambda x: x[0])
    picks = []
    if blends:
        picks += [("mejor mezcla", blends[-1][1], f"nota {blends[-1][0]:.2f}"), ("peor mezcla", blends[0][1], f"nota {blends[0][0]:.2f}")]
    if cuts:
        picks.append(("corte más repetido", cuts[-1][1], f"en {cuts[-1][0]} de {m['seeds']} órdenes"))
    for label, key, note in picks:
        print(f"  {label:18} ({note}): {name(key[0])} -> {name(key[1])}\n                     {scores[key][2]}")


def songs(folder):
    """(fichas para el orden, {ruta: ficha para la mezcla}) de las canciones de la carpeta."""
    analyses = load(folder)
    return [track_of(p, a) for p, a in analyses.items()], {p: info_of(a) for p, a in analyses.items()}


def main():
    args = sys.argv[1:]
    planner = dj_planner
    if "--planificador" in args:
        at = args.index("--planificador")
        planner = planner_from(args[at + 1])
        print(f"planificador: {args[at + 1]}")
        del args[at:at + 2]
    folder = args[0] if args else os.path.expanduser("~/Music/Canciones_YouTube")
    seeds = int(args[1]) if len(args) > 1 else 40
    t0 = time.time()
    tracks, infos = songs(folder)
    print(f"{len(tracks)} canciones con análisis ({time.time() - t0:.1f} s)\n", flush=True)
    for t in sorted(tracks, key=lambda t: (t.bpm or 0)):
        grid = infos[t.ref]["beatgrid"]
        print(f"  {t.bpm or 0:6.1f} BPM  energía {t.energy if t.energy is not None else -1:5.2f}  tono {t.tone or '-':4}"
              f"  rejilla {'sí' if grid else 'no'}  {t.artist[:18]:18}  {name(t.ref)}")
    report(measure(planner, tracks, infos, seeds))


if __name__ == "__main__":
    main()
