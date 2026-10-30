"""Grabar el mix del modo DJ (services/mix_recorder, fase 17): render fuera de línea con la EngineSession real, sin sonido.
Canciones sintéticas (golpes graves a un tempo sobre un tono, escritas a wav) con un análisis dado a mano: render de 3 canciones a
wav (duración, lista de canciones y tiempos coherentes con los planes, sin NaN, pico, sin saltos bruscos), listados txt y cue,
clip de una transición suelta (longitud y velocidad), cancelación (sin archivo), errores. Sin FFmpeg se omiten con un aviso.
Con la variable MIX_REAL=1 hace además una ejecución INFORMATIVA con 4 canciones reales de la carpeta de música (solo lectura) y
cuenta cuánto tarda en relación al tiempo real (no es un test: tarda varios minutos por el análisis).
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_grabar_mix.py"""
import glob
import logging
import os
import shutil
import sys
import tempfile
import time
import wave

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np

from services import mix_recorder
from services.ffmpeg_service import FFmpegService
from services.mix_types import KIND_BLEND, KIND_CUT, SAMPLE_RATE, BeatGrid

SR = SAMPLE_RATE
logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def info(msg):
    print("INFO", msg, flush=True)


def make_wav(path, freq, bpm, seconds):
    """Golpes graves (bombo de 60 Hz con ataque suave) a `bpm` sobre un tono: algo con ritmo y sin clics propios."""
    t = np.arange(int(seconds * SR)) / SR
    ph = t % (60.0 / bpm)
    env = np.where(ph < 0.15, np.sin(np.pi * ph / 0.15) ** 2, 0.0)
    v = 0.25 * np.sin(2 * np.pi * freq * t) + 0.3 * env * np.sin(2 * np.pi * 60.0 * t)
    pcm = (np.stack([v, v], axis=1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm.tobytes())


def read_wav(path):
    with wave.open(path, "rb") as f:
        raw = f.readframes(f.getnframes())
        assert f.getnchannels() == 2 and f.getframerate() == SR
    return np.frombuffer(raw, dtype="<i2").reshape(-1, 2).astype(np.float32) / 32768.0


def max_jump(x):
    return float(np.abs(np.diff(x[:, 0])).max()) if len(x) > 1 else 0.0


def jump_outside(x, centers, half=100):
    """Salto maximo entre muestras seguidas ignorando una ventana de +-`half` muestras alrededor de cada centro (en muestras)."""
    d = np.abs(np.diff(x[:, 0]))
    keep = np.ones(len(d), bool)
    for c in centers:
        keep[max(0, int(c) - half):int(c) + half] = False
    return float(d[keep].max())


class Songs:
    def __init__(self, root):
        self.root, self.meta, self.paths = root, {}, []

    def add(self, name, freq, bpm, seconds):
        p = os.path.join(self.root, name)
        make_wav(p, freq, bpm, seconds)
        self.meta[p] = {"duration_ms": seconds * 1000.0, "intro_ms": 4000, "outro_ms": 16000, "bpm": bpm,
                        "beatgrid": BeatGrid(0.0, bpm)}
        self.paths.append(p)
        return p

    def info_for(self, p):
        return self.meta.get(p, {})


def expected_duration(plans, total_s):
    """Duración de la salida con los planes dados: A hasta a_start, la mezcla, B desde el final de la mezcla (en su tiempo)... """
    out, b_pos = 0.0, 0.0
    for k, p in enumerate(plans):
        out += (p["a_start_s"] - b_pos) + p["length_s"]
        b_pos = p["b_start_s"] + p["length_s"] * p["tempo_ratio_b"]
        if k == len(plans) - 1:
            out += total_s[k + 1] - b_pos
    return out


# ---- 0. sin FFmpeg: error claro (no hace falta FFmpeg de verdad: se simula que no está) --------------------------------------
real_get = FFmpegService.get_ffmpeg_path
FFmpegService.get_ffmpeg_path = staticmethod(lambda: None)
try:
    mix_recorder.render_session(["a.wav"], lambda p: {}, os.path.join(tempfile.gettempdir(), "no_debe_existir.mp3"))
    check("sin FFmpeg: error claro y no se crea nada", False)
except RuntimeError as e:
    check("sin FFmpeg: error claro y no se crea nada", "FFmpeg" in str(e))
FFmpegService.get_ffmpeg_path = real_get
try:
    mix_recorder.render_session([], lambda p: {}, "x.wav")
    check("lista vacía: error", False)
except ValueError:
    check("lista vacía: error", True)

if not FFmpegService.get_ffmpeg_path():
    print("AVISO no hay FFmpeg: se omiten las pruebas con archivos", flush=True)
    print("FIN", flush=True)
    sys.exit(0)

tmp = tempfile.mkdtemp(prefix="grabar_mix_")
try:
    S = Songs(tmp)
    a = S.add("a.wav", 220, 120.0, 60)
    b = S.add("b.wav", 330, 124.0, 56)
    c = S.add("c.wav", 440, 128.0, 52)
    d = S.add("d.wav", 262, 150.0, 50)             # tempo lejano de los demás: obliga a un corte limpio
    dur = {a: 60, b: 56, c: 52, d: 50}

    # ---- 1. render de 3 canciones a wav ---------------------------------------------------------------------------------
    out = os.path.join(tmp, "mix.wav")
    seen = []
    t0 = time.monotonic()
    res = mix_recorder.render_session([a, b, c], S.info_for, out, bars=8, progress=lambda i, n, s: seen.append((i, n, s)))
    wall = time.monotonic() - t0
    audio = read_wav(out)
    info(f"3 canciones de ~1 min: {res['duration_s']:.1f} s de mix en {wall:.1f} s ({res['duration_s'] / wall:.1f}x tiempo real); "
         f"pico {res['peak']:.3f}")
    check("el archivo existe y no queda el .part", os.path.isfile(out) and not os.path.exists(out + ".part")
          and res["out_path"] == out and not res["cancelled"])
    trans = res["transitions"]
    plans = [t["plan"] for t in trans]
    check(f"hay 2 transiciones con su plan ({[p['kind'] if p else None for p in plans]})", len(trans) == 2 and all(plans)
          and all(t["from"] and t["to"] for t in trans))
    exp = expected_duration(plans, [60, 56, 52]) if all(plans) else -1
    check(f"duración total ~ la esperada con los planes ({res['duration_s']:.2f} s contra {exp:.2f} s)",
          abs(res["duration_s"] - exp) < 0.1 and abs(len(audio) / SR - res["duration_s"]) < 0.05)
    tl = res["tracklist"]
    check("el listado tiene las 3 canciones en orden, con título del nombre del archivo",
          [t["path"] for t in tl] == [a, b, c] and [t["title"] for t in tl] == ["a", "b", "c"])
    starts = [t["start_s"] for t in tl]
    check(f"tiempos crecientes ({[round(s, 2) for s in starts]})", starts[0] == 0.0 and starts[0] < starts[1] < starts[2])
    if all(plans):
        s1 = plans[0]["a_start_s"] + plans[0]["length_s"] / 2
        mix2 = plans[0]["a_start_s"] + plans[0]["length_s"] + (plans[1]["a_start_s"]
                                                              - (plans[0]["b_start_s"] + plans[0]["length_s"] * plans[0]["tempo_ratio_b"]))
        s2 = mix2 + plans[1]["length_s"] / 2
        check(f"cada entrada cae a la mitad de su mezcla (esperado {s1:.2f} y {s2:.2f} s)",
              abs(starts[1] - s1) < 0.05 and abs(starts[2] - s2) < 0.05)
        check("at_s es el comienzo de la mezcla", abs(trans[0]["at_s"] - plans[0]["a_start_s"]) < 0.05
              and abs(trans[1]["at_s"] - mix2) < 0.05)
    check("el progreso se informó (índice de canción y total)", seen and seen[-1][1] == 3 and seen[-1][0] >= 1)
    check(f"sin NaN y pico <= 1,5 ({res['peak']:.3f})", res["nonfinite"] == 0 and np.isfinite(audio).all() and res["peak"] <= 1.5)
    jump = max_jump(audio)
    near = max(max_jump(audio[max(0, int((t["start_s"] - 20) * SR)):int((t["start_s"] + 20) * SR)]) for t in tl[1:])
    info(f"salto maximo entre muestras con tempos distintos (B estirada): {jump:.4f} en todo el mix, {near:.4f} en las uniones")
    # con B estirada, el empalme del final de la mezcla (tramo estirado -> cuerpo original) deja un salto de 1 a 5 ms de desfase del
    # estirado (limite conocido del motor, ver pcm_loader): aqui solo se informa. El resto del mix tiene que estar limpio.
    mix_ends = [(t["at_s"] + p["length_s"]) for t, p in zip(trans, plans)]
    check(f"sin saltos bruscos fuera del empalme del final de cada mezcla ({jump_outside(audio, [e * SR for e in mix_ends]):.4f})",
          jump_outside(audio, [e * SR for e in mix_ends]) < 0.1)
    # con el mismo tempo (sin estirar) las uniones, todas, tienen que estar limpias
    e1 = S.add("e1.wav", 247, 120.0, 60)
    e2 = S.add("e2.wav", 311, 120.0, 56)
    e3 = S.add("e3.wav", 392, 120.0, 52)
    out_e = os.path.join(tmp, "mix_e.wav")
    res_e = mix_recorder.render_session([e1, e2, e3], S.info_for, out_e, bars=8)
    audio_e = read_wav(out_e)
    check(f"mismo tempo: mezclas con tempo 1,0 y todas las uniones limpias (salto maximo {max_jump(audio_e):.4f})",
          all(t["plan"] and t["plan"]["tempo_ratio_b"] == 1.0 for t in res_e["transitions"]) and max_jump(audio_e) < 0.08
          and res_e["peak"] <= 1.5)

    # ---- 2. corte limpio entre tempos lejanos + listados ---------------------------------------------------------------
    out2 = os.path.join(tmp, "mix2.wav")
    res2 = mix_recorder.render_session([c, d], S.info_for, out2, bars=8)
    p = res2["transitions"][0]["plan"]
    audio2 = read_wav(out2)
    exp2 = expected_duration([p], [52, 50]) if p else -1
    check(f"tempos lejanos: corte limpio ({p['kind'] if p else None}), duración {res2['duration_s']:.2f} s ~ {exp2:.2f} s",
          p is not None and p["kind"] == KIND_CUT and abs(res2["duration_s"] - exp2) < 0.1)
    check(f"y sin clic en el corte (salto máximo {max_jump(audio2):.4f})", max_jump(audio2) < 0.08)
    check("el corte entra en el instante del plan", p is not None and abs(res2["tracklist"][1]["start_s"] - p["a_start_s"]) < 0.05)
    txt, cue = os.path.join(tmp, "mix.txt"), os.path.join(tmp, "mix.cue")
    mix_recorder.write_tracklist(res, txt)
    mix_recorder.write_cue(res, cue)
    lines = open(txt, encoding="utf-8").read().splitlines()
    m, s = divmod(int(starts[1]), 60)
    check(f"listado de texto: {lines}", len(lines) == 3 and lines[0] == "01. 00:00  a" and lines[1] == f"02. {m:02d}:{s:02d}  b")
    cue_lines = open(cue, encoding="utf-8").read().splitlines()
    ff = int((starts[1] % 1) * 75 + 1e-6)
    check("cue estándar: FILE, TRACK 01 AUDIO, TITLE e INDEX 01 mm:ss:ff",
          cue_lines[0] == 'FILE "mix.wav" WAVE' and cue_lines[1] == "  TRACK 01 AUDIO" and cue_lines[2] == '    TITLE "a"'
          and cue_lines[3] == "    INDEX 01 00:00:00" and cue_lines[4] == "  TRACK 02 AUDIO"
          and cue_lines[6] == f"    INDEX 01 {m:02d}:{s:02d}:{ff:02d}" and len(cue_lines) == 10)
    check("título con metadatos si la ficha los trae",
          mix_recorder._title(a, {"title": "Tema", "artist": "Yo"}) == "Yo - Tema" and mix_recorder._title(a, {"artist": "Yo"}) == "a")

    # ---- 3. mp3 por la tubería y max_tracks -----------------------------------------------------------------------------
    out3 = os.path.join(tmp, "mix3.mp3")
    res3 = mix_recorder.render_session([a, b, c], S.info_for, out3, bars=8, max_tracks=2, bitrate="128k")
    size = os.path.getsize(out3)
    check(f"mp3 de 2 canciones ({size // 1024} KiB, {res3['duration_s']:.1f} s a 128k)", len(res3["tracklist"]) == 2
          and abs(size - res3["duration_s"] * 16000) < 0.1 * size)

    # ---- 4. clip de una transición suelta -------------------------------------------------------------------------------
    t0 = time.monotonic()
    clip = mix_recorder.render_transition_clip(a, b, S.meta[a], S.meta[b], context_s=12.0, bars=8)
    took = time.monotonic() - t0
    pl = clip.plan
    want = (12.0 + pl.length_s + 12.0) * SR
    info(f"clip de transición: {len(clip.audio) / SR:.1f} s en {took:.1f} s; mezcla de {clip.mix_start_s:.2f} a {clip.mix_end_s:.2f} s")
    check(f"el clip dura contexto + mezcla + contexto ({len(clip.audio)} muestras, esperadas {int(want)})",
          clip.audio.shape[1] == 2 and abs(len(clip.audio) - want) <= 2 and pl.kind == KIND_BLEND)
    check("el inicio y el fin de la mezcla caen donde dice el plan", abs(clip.mix_start_s - 12.0) < 1e-6
          and abs(clip.mix_end_s - (12.0 + pl.length_s)) < 1e-6 and abs(clip.a_from_s - (pl.a_start_s - 12.0)) < 1e-6)
    ce = int(clip.mix_end_s * SR)
    rest = jump_outside(clip.audio[int(0.05 * SR):], [ce - int(0.05 * SR)])
    info(f"salto en el empalme del final de la mezcla del clip: {max_jump(clip.audio[ce - 100:ce + 100]):.4f}")
    check(f"rapido ({took:.1f} s < 10 s), finito y sin saltos bruscos fuera del empalme ({rest:.4f})",
          took < 10 and np.isfinite(clip.audio).all() and rest < 0.08)
    # el clip es lo mismo que lo grabado en el mix: la misma mezcla en el mismo sitio (cuerpo de A del mix = cuerpo de A del clip)
    k0 = int(res["transitions"][0]["at_s"] * SR)
    mix_part = audio[k0:k0 + int(pl.length_s * SR)]
    clip_part = clip.audio[int(clip.mix_start_s * SR):int(clip.mix_end_s * SR)]
    n = min(len(mix_part), len(clip_part))
    check(f"y es la misma mezcla que se oye en el mix grabado (diferencia máxima {float(np.abs(mix_part[:n] - clip_part[:n]).max()):.4f})",
          n > 0 and float(np.abs(mix_part[:n] - clip_part[:n]).max()) < 0.01)
    early = mix_recorder.render_transition_clip(b, c, S.meta[b], S.meta[c], context_s=500.0, bars=8)
    check("con más contexto del que hay: empieza en el principio de A y acaba donde acaba B",
          early.a_from_s == 0.0 and abs(early.mix_start_s - early.plan.a_start_s) < 1e-6 and len(early.audio) / SR < dur[b] + dur[c])
    cut = mix_recorder.render_transition_clip(c, d, S.meta[c], S.meta[d], context_s=5.0, bars=8)
    check("clip de un corte: la mezcla no dura nada", cut.plan.kind == KIND_CUT and cut.mix_start_s == cut.mix_end_s
          and abs(len(cut.audio) / SR - 10.0) < 0.01)
    try:
        mix_recorder.render_transition_clip(os.path.join(tmp, "no_existe.wav"), b, {}, S.meta[b])
        check("clip con una canción que no existe: error", False)
    except RuntimeError as e:
        check("clip con una canción que no existe: error claro", "no_existe" in str(e))

    # ---- 5. cancelación a mitad: sin archivo -----------------------------------------------------------------------------
    out5 = os.path.join(tmp, "cancelado.mp3")
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) > 400                          # ya hay audio escrito (a 4096 muestras por vuelta, ~35 s)

    res5 = mix_recorder.render_session([a, b, c], S.info_for, out5, bars=8, cancel=cancel)
    check(f"cancelar a mitad: devuelve cancelled, no deja archivo ni .part ({res5['duration_s']:.0f} s grabados)",
          res5["cancelled"] and res5["out_path"] is None and not os.path.exists(out5) and not os.path.exists(out5 + ".part")
          and 10 < res5["duration_s"] < res["duration_s"] - 10)
    open(out5, "wb").write(b"anterior")
    calls.clear()
    mix_recorder.render_session([a, b], S.info_for, out5, bars=8, cancel=cancel)
    check("y si ya había un archivo con ese nombre, se queda como estaba", open(out5, "rb").read() == b"anterior")

    # ---- 6. errores -------------------------------------------------------------------------------------------------------
    try:
        mix_recorder.render_session([os.path.join(tmp, "no_existe.wav")], S.info_for, os.path.join(tmp, "x.mp3"))
        check("primera canción que no existe: error", False)
    except RuntimeError:
        check("primera canción que no existe: error, sin dejar archivos", not [f for f in os.listdir(tmp) if f.startswith("x.mp3")])
    try:
        mix_recorder.render_session([a], S.info_for, os.path.join(tmp, "x.xyz"))
        check("formato no admitido: error", False)
    except ValueError:
        check("formato no admitido: error", True)
    res7 = mix_recorder.render_session([a, os.path.join(tmp, "no_existe.wav"), c], S.info_for, os.path.join(tmp, "salta.wav"), bars=8)
    check(f"una canción rota en medio se salta y se avisa ({[t['title'] for t in res7['tracklist']]})",
          [t["path"] for t in res7["tracklist"]] == [a, c] and res7["errors"])

    # ---- 7. ejecución informativa con canciones reales ------------------------------------------------------------------------
    folder = r"C:\Users\juego\Music\Canciones_YouTube"
    if os.environ.get("MIX_REAL") and os.path.isdir(folder):
        from services import track_analysis
        files = sorted(glob.glob(os.path.join(folder, "Quevedo - *.mp3")))[:4]
        t0 = time.monotonic()
        analysis = {}
        for f in files:
            analysis[f] = track_analysis.analyze(f) or {}

        def real_info(p):
            r = dict(analysis.get(p) or {})
            r["beatgrid"] = track_analysis.grid_from(r)
            return r

        info(f"análisis de {len(files)} canciones: {time.monotonic() - t0:.0f} s")
        outr = os.path.join(tmp, "real.mp3")
        t0 = time.monotonic()
        rr = mix_recorder.render_session(files, real_info, outr)
        wall = time.monotonic() - t0
        rate = rr["duration_s"] / wall
        info(f"{len(files)} canciones reales: {rr['duration_s'] / 60:.1f} min de mix en {wall:.1f} s = {rate:.1f}x el tiempo real "
             f"(una hora tardaría unos {3600 / rate:.0f} s); pico {rr['peak']:.2f}; avisos: {rr['errors']}")
        for t in rr["transitions"]:
            pl = t["plan"] or {}
            info(f"  en {t['at_s']:.1f} s: {pl.get('kind')} de {pl.get('length_s', 0):.1f} s, tempo B x{pl.get('tempo_ratio_b', 1):.3f}")
        t0 = time.monotonic()
        cl = mix_recorder.render_transition_clip(files[0], files[1], real_info(files[0]), real_info(files[1]))
        info(f"clip de transición real: {len(cl.audio) / SR:.0f} s de audio en {time.monotonic() - t0:.1f} s ({cl.plan.kind})")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("FIN", flush=True)
