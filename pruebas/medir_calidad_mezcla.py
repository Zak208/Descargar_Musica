"""Diagnóstico (no es una prueba): calidad de las transiciones del motor del DJ con canciones REALES, antes y después de la
integración (limitador, tipos de transición y puntuador). Analiza las canciones de la carpeta (solo lectura; datos aislados con
_aislar), ordena la sesión con el orden inteligente (`dj_planner.plan`, varias semillas), hace sonar cada transición con la
`EngineSession` real en silencio (`MixEngine.pull`, sin dispositivo) y la puntúa con `transition_scorer.score_audio`.

Configuraciones:
  BASE     EngineSession(typed=False, audio_check=None, entry_gain=False) sobre MixEngine(limit=False): solo mezcla larga o
           corte limpio, sin limitador (los arreglos de la fase 0 y de los silencios ya están y no se pueden quitar).
  ANTES    lo de por defecto sin la ganancia de entrada de B (entry_gain=False).
  DESPUÉS  lo que hay por defecto: tipos de transición, puntuador ligero, limitador y ganancia de entrada (bucles apagados).

Cuenta: veredictos (ok, dudosa, descartar), clics, recorte (muestras > 1,0 en lo que sale), huecos de silencio, saltos de
volumen, pico, muestras que tocó el limitador (> 0,9), tipos elegidos, % de mezclas que empiezan en un comienzo de frase de A
(8 compases), duración media de la mezcla y tiempo de preparación (de que suena A a que la transición está lista).
Criterio de aceptación (DESPUÉS): ninguna transición con clic, recorte > 0,1 % o hueco de silencio, ningún salto de volumen de
8 dB o más salvo que A ya callase justo antes de que entre B, y el mayor salto por debajo de 6 dB.

Uso:  python pruebas/medir_calidad_mezcla.py [carpeta] [semillas]      (por omisión ~/Music/Canciones_YouTube y 3 semillas)"""
import os
import random
import sys
import time
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np  # noqa: E402

from services import dj_planner, mix_planner, pcm_loader, track_analysis, transition_scorer as ts, transition_types  # noqa: E402
from services.audio_engine import MixEngine  # noqa: E402
from services import dj_engine  # noqa: E402
from services.dj_engine import EngineSession, _gated_rms  # noqa: E402
from services.mix_types import KIND_CUT, SAMPLE_RATE, BeatGrid, TransitionPlan  # noqa: E402

SR = SAMPLE_RATE
CONTEXT_S = 4.0                 # segundos antes y después de la mezcla que se sacan
CUT_PIECE = int(0.5 * SR)


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def analyse_folder(folder):
    names = sorted(f for f in os.listdir(folder) if f.lower().endswith((".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus")))
    infos = {}
    t0 = time.monotonic()
    for name in names:
        path = os.path.join(folder, name)
        res = track_analysis.analyze(path)
        if not res:
            print(f"   (sin análisis: {name})", flush=True)
            continue
        info = dict(res)
        info["beatgrid"] = track_analysis.grid_from(res)
        info["structure"] = track_analysis.structure_from(res)
        info["path"] = path
        infos[norm(path)] = info
    print(f"analizadas {len(infos)} de {len(names)} canciones en {time.monotonic() - t0:.0f} s", flush=True)
    return infos


def smart_orders(infos, seeds):
    tracks = [dj_planner.Track(i, i.get("bpm"), i.get("tone") or None, i.get("tone_conf") or 0.0,
                               i.get("energy") if i.get("loudness_db") is not None else None, i.get("genre") or "",
                               i.get("artist") or "") for i in infos.values()]
    pairs = []
    for seed in seeds:
        order = [t.ref["path"] for t in dj_planner.plan(tracks, rng=random.Random(seed))]
        pairs += list(zip(order, order[1:]))
    seen, out = set(), []
    for a, b in pairs:                                      # las parejas repetidas entre semillas se miden una vez
        if (norm(a), norm(b)) not in seen:
            seen.add((norm(a), norm(b)))
            out.append((a, b))
    return out, len(pairs)


def run_pair(a_path, b_path, infos, limit, **session_kw):
    """Hace sonar la transición de A a B con la sesión real y devuelve un dict con lo medido (o None si no hubo plan)."""
    eng = MixEngine(limit=limit)
    sess = EngineSession(eng, lambda p: infos.get(norm(p), {}), lambda p: b_path if norm(p) == norm(a_path) else None,
                         **session_kw)
    try:
        sess.play(a_path)
        t0 = time.monotonic()
        st = None
        while time.monotonic() - t0 < 120:
            st = sess.tick()
            if st["plan"] is not None or (st["state"] == "stopped" and st["error"]):
                break
            time.sleep(0.01)
        if st is None or st["plan"] is None:
            return None
        prep = sess.timings.get("ready", 0.0) - sess.timings.get("sound", 0.0)
        with sess._lock:
            p, a = sess._pair, sess._a
            plan, kind, a_data, b_tr = p.plan, p.kind, a.data, p.b
            a_mix, check = p.a_mix, dict(p.check)
        cut = plan.kind == KIND_CUT
        n = (len(p.x1) if p.x1 is not None else 0) + len(p.entry[0][0]) if cut else round(plan.length_s * SR)
        # trozos de A y B que entraron en la mezcla (B estirada como la estira el motor)
        ratio = float(plan.tempo_ratio_b or 1.0)
        if cut:
            k = len(p.x1) if p.x1 is not None else 0
            a_part = a_data[a_mix:a_mix + k]
            bs = p.b_cut
            b_part = b_tr.data[bs:bs + n - k]
            split = k
        else:
            a_part = a_data[a_mix:a_mix + n]
            bs = round(plan.b_start_s * SR)
            if abs(ratio - 1.0) < 1e-6:
                b_part = b_tr.data[bs:bs + n]
            else:
                b_part = pcm_loader.load(b_path, tempo_ratio=ratio, start_s=plan.b_start_s, duration_s=plan.length_s * ratio)[:n]
                b_part = b_part * np.float32(b_tr.gain)
            split = (transition_types._cut_point(plan, n, SR) if kind in (transition_types.TYPE_CUT_BAR, transition_types.TYPE_ECHO_OUT)
                     else n // 2)
        # con la ganancia de entrada, los trozos tal cual entraron en la mezcla (el puntuador debe medir lo que se le pasó)
        ga, gb = (10 ** (check.get(key, 0.0) / 20.0) for key in ("a_end_gain_db", "entry_gain_db"))
        if ga != 1.0:
            a_part = a_part.copy()
            lo_f = max(0, split - int(dj_engine.TRIM_A_FADE_S * SR)) if not cut else 0
            a_part[lo_f:split] *= dj_engine._fade_to(ga, split - lo_f)[:, None]
            a_part[split:] *= np.float32(ga)
        if gb != 1.0:
            b_part = b_part * dj_engine._trim_curve(gb, split, split + len(b_part) if cut else max(n, len(b_part)))[
                split if cut else 0:(split if cut else 0) + len(b_part), None]
        # sonar desde unos segundos antes de la mezcla hasta unos segundos después
        start = max(0, a_mix - int(CONTEXT_S * SR))
        sess.seek(start / SR)
        sess.tick()
        total = (a_mix - start) + n + int(CONTEXT_S * SR)
        parts, got = [], 0
        while got < total:
            before = eng.position_frames
            chunk = eng.pull(min(4096, total - got))
            k_ = eng.position_frames - before
            if k_ <= 0:
                break
            parts.append(chunk[:k_])
            got += k_
            sess.tick()
        audio = np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)
        m0 = a_mix - start
        w4 = int(0.4 * SR)                                  # niveles de 400 ms de lo que sale, de 2 s antes a 4 s después de que entra B
        levels = [round(20 * np.log10(max(float(np.sqrt(np.mean(np.square(audio[m0 + split + j * w4:m0 + split + (j + 1) * w4],
                                                                          dtype=np.float64)))), 1e-6)), 1)
                  for j in range(-5, 10) if 0 <= m0 + split + j * w4 and m0 + split + (j + 1) * w4 <= len(audio)]
        a_silent = _gated_rms(a_data[max(0, a_mix + split - SR):a_mix + split]) is None   # A (sola) ya callaba antes de que entre B
        mix = audio[m0:m0 + n]
        a_before, b_after = audio[max(0, m0 - 2 * SR):m0], audio[m0 + n:m0 + n + 2 * SR]
        # se mide como lo que es: con corte en el compás o eco, un corte en `split`
        grid_b = infos.get(norm(b_path), {}).get("beatgrid")
        plan_s, ap, bp = plan, a_part, b_part
        if cut or kind in (transition_types.TYPE_CUT_BAR, transition_types.TYPE_ECHO_OUT):
            ap, bp = a_part[:split], b_part[split:] if not cut else b_part
            plan_s = TransitionPlan(plan.a_start_s, plan.b_start_s, 0.0, 1.0, None, KIND_CUT, plan.reason)
        ia, ib = infos.get(norm(a_path), {}), infos.get(norm(b_path), {})
        res = ts.score_audio(mix, ap, bp, plan_s, ia.get("beatgrid"), grid_b if isinstance(grid_b, BeatGrid) else None,
                             tone_a=ia.get("tone"), tone_b=ib.get("tone"), tone_conf_a=ia.get("tone_conf"),
                             tone_conf_b=ib.get("tone_conf"), a_before=a_before, b_after=b_after)
        m = res["metrics"]
        # salto de volumen. En un corte el puntuador cuenta entero el cambio entre las ventanas de 400 ms que pisan el corte, y
        # ahí entra también la dinámica propia de A (un golpe y su caída: hasta 9 dB entre dos ventanas de un mismo compás).
        # Se separan las dos cosas: el salto de A a B (nivel de 1 s antes y después del corte, sin contar el silencio) y lo
        # brusco que no sea ese cambio (el puntuador con el cambio de A a B ya contado como «esperado»). Se da el mayor.
        loud_raw = (m.get("loudness_step_db") or {}).get("value")
        loud = loud_raw
        if cut or kind in (transition_types.TYPE_CUT_BAR, transition_types.TYPE_ECHO_OUT):
            k_ = len(ap)
            gain_a = (np.arange(n) < k_).astype(np.float64)
            dyn = ts._loudness(np, mix, ts._place(np, ap, 0, n), ts._place(np, bp, k_, n), gain_a, 1.0 - gain_a,
                               a_before, b_after, SR, None)[0]
            la, lb = _gated_rms(audio[max(0, m0 + k_ - SR):m0 + k_]), _gated_rms(audio[m0 + k_:m0 + k_ + SR])
            step = abs(20.0 * np.log10(la / lb)) if la and lb else 0.0
            loud = max(dyn or 0.0, step)
        whole = audio[max(0, m0 - SR):m0 + n + 3 * SR]       # lo que sale alrededor de la mezcla (con la cola del eco)
        grid_a = ia.get("beatgrid")
        on_phrase = None
        if not cut and isinstance(grid_a, BeatGrid):
            bar_f = grid_a.bar_at(plan.a_start_s)
            on_phrase = abs(bar_f - round(bar_f)) < 0.05 and round(bar_f) % 8 == 0
        return {"verdict": res["verdict"], "reasons": res["reasons"], "kind": kind if not cut else f"corte/{kind}",
                "plan_kind": plan.kind, "length": 0.0 if cut else plan.length_s, "prep": prep,
                "click": (m.get("click") or {}).get("note") == 0.0, "click_ratio": (m.get("click") or {}).get("value"),
                "clip_frac": float((np.abs(whole) > 1.0).mean()) if len(whole) else 0.0,
                "limited_frac": float((np.abs(whole) > 0.9).mean()) if len(whole) else 0.0,
                "peak": float(np.abs(whole).max()) if len(whole) else 0.0,
                "gap_ms": (m.get("silence_gap_ms") or {}).get("value") or 0.0,
                "loud_db": loud, "loud_raw": loud_raw, "loud_at": (m.get("loudness_step_db") or {}).get("at_s"),
                "split_s": split / SR, "n_s": n / SR, "levels": levels, "on_phrase": on_phrase, "check": check, "a_silent": a_silent,
                "reason": plan.reason, "a": os.path.basename(a_path), "b": os.path.basename(b_path)}
    finally:
        sess.stop(wait=True)


def summary(name, rows):
    n = len(rows)
    if not n:
        print(f"{name}: sin transiciones", flush=True)
        return {}
    v = Counter(r["verdict"] for r in rows)
    kinds = Counter(r["kind"] for r in rows)
    mixes = [r for r in rows if r["plan_kind"] != KIND_CUT]
    phrased = [r["on_phrase"] for r in mixes if r["on_phrase"] is not None]
    louds = [r["loud_db"] for r in rows if r["loud_db"] is not None]
    out = {
        "transiciones": n,
        "ok / dudosa / descartar": f"{v['ok']} / {v['dudosa']} / {v['descartar']}",
        "con clic (puntuador)": sum(r["click"] for r in rows),
        "recorte > 0,1 % de muestras": sum(r["clip_frac"] > 1e-3 for r in rows),
        "recorte medio (% muestras > 1,0)": f"{100 * np.mean([r['clip_frac'] for r in rows]):.3f}",
        "limitador tocó (% muestras > 0,9)": f"{100 * np.mean([r['limited_frac'] for r in rows]):.2f}",
        "pico máximo / medio": f"{max(r['peak'] for r in rows):.3f} / {np.mean([r['peak'] for r in rows]):.3f}",
        "huecos >= 500 ms": sum(r["gap_ms"] >= 500 for r in rows),
        "saltos de volumen >= 8 / >= 6 / >= 5 dB": f"{sum(x >= 8 for x in louds)} / {sum(x >= 6 for x in louds)} / {sum(x >= 5 for x in louds)}",
        "con ganancia de entrada (media dB)": (lambda g: f"{len(g)} ({np.mean(g):+.1f})" if g else "0")(
            [r["check"]["entry_gain_db"] for r in rows if "entry_gain_db" in r["check"]]),
        "salto de volumen máximo (dB)": f"{max(louds):.1f}" if louds else "-",
        "  (puntuador tal cual: >= 8 dB / máximo)": (lambda r_: f"{sum(x >= 8 for x in r_)} / {max(r_):.1f}" if r_ else "-")(
            [r["loud_raw"] for r in rows if r["loud_raw"] is not None]),
        "tipos": ", ".join(f"{k} {c}" for k, c in kinds.most_common()),
        "mezclas (no corte)": len(mixes),
        "% mezclas que empiezan en frase de 8": f"{100 * sum(phrased) / len(phrased):.0f} %" if phrased else "-",
        "duración media de la mezcla (s)": f"{np.mean([r['length'] for r in mixes]):.1f}" if mixes else "-",
        "preparación media / máxima (s)": f"{np.mean([r['prep'] for r in rows]):.2f} / {max(r['prep'] for r in rows):.2f}",
        "cambiadas por el puntuador": sum(bool(r["check"].get("swapped")) for r in rows),
    }
    return out


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Music/Canciones_YouTube")
    seeds = list(range(1, 1 + (int(sys.argv[2]) if len(sys.argv) > 2 else 3)))
    print(f"carpeta: {folder} (solo lectura); semillas: {seeds}", flush=True)
    infos = analyse_folder(folder)
    if len(infos) < 2:
        print("no hay al menos dos canciones analizadas (¿FFmpeg?): no se puede medir", flush=True)
        print("FIN", flush=True)
        return
    pairs, total = smart_orders(infos, seeds)
    tempo_ok = sum(1 for a, b in pairs if (lambda r: r is not None and abs(r - 1) <= mix_planner.MAX_TEMPO_CHANGE)(
        mix_planner.tempo_ratio(infos[norm(a)].get("bpm"), infos[norm(b)].get("bpm"))))
    print(f"{len(pairs)} transiciones distintas ({total} con las repetidas); {tempo_ok} con tempos a menos del 8 %", flush=True)
    configs = (("BASE", dict(limit=False, typed=False, audio_check=None, entry_gain=False)),
               ("ANTES", dict(limit=True, entry_gain=False)), ("DESPUÉS", dict(limit=True)))
    tables = {}
    for name, kw in configs:
        rows, t0 = [], time.monotonic()
        for i, (a, b) in enumerate(pairs, 1):
            try:
                row = run_pair(a, b, infos, **kw)
            except Exception as e:
                print(f"   {name} {i}: error {type(e).__name__}: {e}", flush=True)
                continue
            if row is None:
                print(f"   {name} {i}: sin plan", flush=True)
                continue
            rows.append(row)
            flag = " CLIC" if row["click"] else ""
            print(f"   {name} {i:2}/{len(pairs)} {row['a'][:26]:26} -> {row['b'][:26]:26} {row['kind']:16} {row['verdict']:9} "
                  f"pico {row['peak']:.2f} salto {row['loud_db'] if row['loud_db'] is not None else '-'} dB "
                  f"ganancia {row['check'].get('entry_gain_db', 0):+.1f} dB{flag}", flush=True)
        print(f"{name}: {len(rows)} transiciones en {time.monotonic() - t0:.0f} s", flush=True)
        tables[name] = (summary(name, rows), rows)
    names = [c[0] for c in configs]
    keys = list(tables[names[-1]][0])
    print("\n" + f"{'':42}" + "".join(f" {n:>26}" for n in names), flush=True)
    for k in keys:
        print(f"{k:42}" + "".join(f" {str(tables[n][0].get(k, '-')):>26}" for n in names), flush=True)
    after = tables["DESPUÉS"][1]
    print("\nsaltos de volumen de 5 dB o más DESPUÉS:", flush=True)
    for r in after:
        if (r["loud_db"] or 0) >= 5:
            print(f"   {r['loud_db']:5.1f} dB  {r['a'][:30]} -> {r['b'][:30]} ({r['kind']}; ganancia "
                  f"{r['check'].get('entry_gain_db', 0):+.1f} dB; A callada antes: {'sí' if r['a_silent'] else 'no'})", flush=True)
    print("\nmotivos de «descartar» DESPUÉS:", flush=True)
    for r in after:
        if r["verdict"] == "descartar":
            print(f"   {r['a'][:30]} -> {r['b'][:30]} ({r['kind']}): {'; '.join(r['reasons'])[:150]}", flush=True)
    bad = [r for r in after if r["click"] or r["clip_frac"] > 1e-3 or r["gap_ms"] >= 500
           or ((r["loud_db"] or 0) >= 8 and not r["a_silent"])]
    louds = [r["loud_db"] for r in after if r["loud_db"] is not None and not r["a_silent"]]
    top = max(louds) if louds else 0.0
    verdict = ("NO (no se midió ninguna transición)" if not after else
               "SÍ" if not bad and top < 6 else f"NO ({len(bad)} con clic, recorte, hueco o salto >= 8 dB; mayor salto {top:.1f} dB)")
    print("\nACEPTACIÓN (DESPUÉS: sin clic, recorte > 0,1 %, huecos ni saltos >= 8 dB; mayor salto < 6 dB):", verdict, flush=True)
    for r in bad:
        print(f"   {r['a']} -> {r['b']}: clic={r['click']} recorte={r['clip_frac']:.4f} hueco={r['gap_ms']} ms "
              f"salto={r['loud_db']} dB", flush=True)
    print("FIN", flush=True)


if __name__ == "__main__":
    main()
