"""Rampa de vuelta al tempo original de B tras una mezcla con B estirada (dj_engine.EngineSession(tempo_ramp=True)): tres tramos
de 2 s con el tempo cada vez más cerca de 1,0, cargados con el cargador y empalmados con el fundido de 20 ms. Con el cargador
falso (estirado exacto) se compara lo que sale con la canción ideal (B leída con la misma curva de tempo): fase de golpes
continua, sin clic, cuerpo de B en su sitio, posiciones y seek. Con FFmpeg y rubberband, una medida de verdad: dónde caen los
golpes de B tras la mezcla con y sin rampa (error frente a su sitio ideal, en ms).
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_motor_rampa.py"""
import logging
import os
import shutil
import subprocess
import tempfile
import time
import wave

import _banco_dj as bd
from _banco_dj import SR, Rig, check, max_jump

import numpy as np

from services import dj_engine
from services.audio_engine import MixEngine
from services.deck_gain import deck_gain
from services.dj_engine import EngineSession
from services.mix_types import BeatGrid

logging.getLogger("services.dj_engine").setLevel(logging.CRITICAL)
bd.DEFAULTS["entry_gain"] = False     # se compara muestra a muestra; la ganancia de entrada: prueba_motor_ganancia.py


def song(dur, freq, bpm, **kw):
    return dict(dur=dur, freq=freq, bpm=bpm, **kw)


def tempo_curve(plan, out0):
    """(tramos) de la curva de tempo de B tras la mezcla: [(salida desde, salida hasta, tiempo de B al empezar, razón)]."""
    r = float(plan.tempo_ratio_b)
    t = plan.b_start_s + plan.length_s * r
    o = out0
    segs = []
    for i in range(1, dj_engine.RAMP_STEPS + 1):
        ri = r + (1.0 - r) * i / (dj_engine.RAMP_STEPS + 1)
        segs.append((o, o + dj_engine.RAMP_SEG_S, t, ri))
        t += dj_engine.RAMP_SEG_S * ri
        o += dj_engine.RAMP_SEG_S
    segs.append((o, o + 3600.0, t, 1.0))
    return segs


def b_time(segs, out_s):
    for o0, o1, t0, r in segs:
        if o0 <= out_s < o1:
            return t0 + (out_s - o0) * r
    return None


# ---- cargador falso: lo que sale es B leída con la curva de tempo, sin saltos de fase ---------------------------------------
SONGS = {"A": song(70, 220.0, 120.0), "B": song(70, 330.0, 124.0)}
r = Rig(SONGS, {"A": "B", "B": None}, tempo_ramp=True)
st = r.start()
plan = st["plan"]
ratio = float(plan.tempo_ratio_b)
calls = [c for c in r.fake.calls if c[0] == "B" and c[1] != 1.0]
want = [ratio + (1.0 - ratio) * i / 4 for i in range(1, 4)]
check(f"mezcla con B estirada ({ratio:.4f}) y 3 tramos de rampa cargados con razones {', '.join(f'{c[1]:.4f}' for c in calls[1:])}",
      st["transition_type"] == "blend" and len(calls) == 4 and all(abs(c[1] - w) < 1e-9 for c, w in zip(calls[1:], want)))
a_mix, n = round(plan.a_start_s * SR), round(plan.length_s * SR)
segs = tempo_curve(plan, (a_mix + n) / SR)
check("cada tramo empieza en el tiempo de B donde acaba el anterior (se carga desde 0,5 s antes, que se tira)",
      all(abs(c[2] + min(dj_engine.RAMP_PREROLL_S, sg[2]) - sg[2]) < 1e-9 for c, sg in zip(calls[1:], segs)))
with r.sess._lock:
    b_body = r.sess._pair.b_body
end_ramp = a_mix + n + round(dj_engine.RAMP_STEPS * dj_engine.RAMP_SEG_S * SR)
r.pull_to(end_ramp + 3 * SR)
out = r.audio()
gb = deck_gain(bd.LUFS["B"], max(float(r.fake.full("B").max()), -float(r.fake.full("B").min())))
full_b = r.fake.full("B") * np.float32(gb)
idx = np.arange(a_mix + n, end_ramp + 2 * SR)
tau = np.array([b_time(segs, i / SR) for i in idx])
ideal = np.interp(tau * SR, np.arange(len(full_b)), full_b[:, 0])
err = np.abs(out[idx, 0] - ideal)
check(f"lo que suena tras la mezcla es B con la curva de tempo de la rampa, sin saltos de fase (error máximo {err.max():.4f})",
      err.max() < 0.03)
check(f"sin clic en ninguna unión (salto máximo {max_jump(out[a_mix - SR:]):.4f})", max_jump(out[a_mix - SR:]) < bd.CLICK)
body_out = end_ramp + round(dj_engine.JOIN_S * SR)
check("después de la rampa, el cuerpo original de B tal cual", np.array_equal(out[body_out:body_out + SR],
                                                                           full_b[b_body:b_body + SR]))
st2 = next(s_ for s_ in r.states if s_["path"] == "B" and a_mix + n + 2 * SR + 1000 <= s_["_frames"] < a_mix + n + 4 * SR - 3000)
exp = b_time(segs, st2["_frames"] / SR)
check(f"la posición en el 2.º tramo sigue la curva de tempo ({st2['position_s']:.3f} s, esperada {exp:.3f} s)",
      abs(st2["position_s"] - exp) < 0.03)
r.sess.stop()
r = Rig(SONGS, {"A": "B"}, tempo_ramp=True)
st = r.start()
with r.sess._lock:
    b_body = r.sess._pair.b_body
r.sess.seek(st["plan"].a_start_s + 1.0)
st = r.tick()
check("seek dentro de la mezcla: al cuerpo de B después de la rampa", st["path"] == "B" and abs(st["position_s"] - b_body / SR) < 1e-6)
r.sess.stop()
r = Rig(SONGS, {"A": "B"})
st = r.start()
check("sin tempo_ramp (lo normal) no se carga ningún tramo de más", len([c for c in r.fake.calls if c[0] == "B" and c[1] != 1.0]) == 1)
r.sess.stop()

# ---- con FFmpeg y rubberband: dónde caen los golpes de B tras la mezcla -----------------------------------------------------
from services import pcm_loader  # noqa: E402
from services.ffmpeg_service import FFmpegService  # noqa: E402

ffmpeg = FFmpegService.get_ffmpeg_path()


def onsets(x, thr):
    """Instantes (s) en que la envolvente pasa del umbral hacia arriba."""
    env = np.abs(x).max(axis=1)
    k = 44
    env = np.maximum.reduceat(env, np.arange(0, len(env), k))
    up = np.where((env[1:] >= thr) & (env[:-1] < thr))[0] + 1
    out = []
    for i in up:
        j = i * k
        seg = np.abs(x[j - k:j + k]).max(axis=1)
        out.append((j - k + int(np.argmax(seg >= thr))) / SR)
    return np.array(out)


if not ffmpeg or not pcm_loader.rubberband_available():
    print("AVISO sin FFmpeg con rubberband: se salta la medida con el cargador real", flush=True)
else:
    tmp = tempfile.mkdtemp(prefix="motor_rampa_")
    try:
        paths = {}
        for name, freq, bpm in (("a", 220, 120.0), ("b", 330, 124.8)):
            pth = os.path.join(tmp, f"{name}.wav")
            beat = 60.0 / bpm
            t_ = np.arange(150 * SR) / SR                      # golpes exactos a la muestra (el «volume» de lavfi va por bloques)
            v = np.sin(2 * np.pi * freq * t_) * np.where(np.mod(t_, beat) < 0.05, 0.7, 0.1)
            pcm = (np.stack([v, v], axis=1) * 32767).astype("<i2")
            with wave.open(pth, "wb") as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(SR)
                wf.writeframes(pcm.tobytes())
            paths[pth] = {"duration_ms": 150000, "intro_ms": 8000, "outro_ms": 30000, "bpm": bpm,
                          "beatgrid": BeatGrid(0.0, bpm, confidence=0.9), "tone": "8A"}
        pa, pb = list(paths)
        results = {}
        for ramp in (False, True):
            eng = MixEngine()
            sess = EngineSession(eng, lambda p_: paths.get(p_, {}), lambda p_: pb if p_ == pa else None, tempo_ramp=ramp,
                                 lufs_stored=lambda p_: None, lufs_measure=lambda p_: None)
            sess.play(pa)
            t0 = time.monotonic()
            while time.monotonic() - t0 < 60:
                st = sess.tick()
                if st["plan"] is not None or st["error"]:
                    break
                time.sleep(0.02)
            plan = st["plan"]
            sess.seek(plan.a_start_s - 1.0)                        # desde 1 s antes de la mezcla (un seek dentro saltaría a B)
            sess.tick()
            eng.play(fade=False)
            out = eng.pull(int((1.0 + plan.length_s + 12.0) * SR))
            sess.stop()
            mix_end = 1.0 + plan.length_s
            segs = tempo_curve(plan, mix_end) if ramp else [(mix_end, 3600.0, plan.b_start_s + plan.length_s * plan.tempo_ratio_b, 1.0)]
            beat_b = 60.0 / 124.8
            found = onsets(out, 0.35 * float(np.abs(out[int((mix_end + 0.5) * SR):]).max()))
            found = found[found > mix_end + 0.1]
            errs = []
            for f_ in found:
                tb = b_time(segs, f_)
                if tb is None:
                    continue
                errs.append((tb - round(tb / beat_b) * beat_b) / (segs[0][3] if ramp else 1.0) * 1000.0)
            errs = np.array(errs)
            jumps = np.abs(np.diff(errs)) if len(errs) > 1 else np.zeros(1)
            results[ramp] = (errs, jumps)
            print(f"INFO cargador real, {'con' if ramp else 'sin'} rampa: {len(errs)} golpes de B tras la mezcla; desfase frente a su "
                  f"sitio ideal de {errs.min():+.1f} a {errs.max():+.1f} ms; mayor cambio entre golpes seguidos {jumps.max():.1f} ms",
                  flush=True)
        errs, _ = results[True]
        good, extra = errs[np.abs(errs) < 5.0], int(np.sum(np.abs(errs) >= 5.0))
        check(f"con rubberband y rampa, los golpes de B caen en su sitio ({len(good)} golpes, desfase máximo {np.abs(good).max():.1f} ms)",
              len(good) >= 20 and np.abs(good).max() < 2.0)
        print(f"INFO con rampa hay {extra} ataques de más (a unos 30 ms de un golpe, justo tras un empalme de tramos): el fundido de "
              "20 ms entre dos estirados distintos de la misma música puede restar (fases distintas) y la envolvente cae y vuelve a "
              "subir. Es la razón de que la rampa esté apagada por defecto.", flush=True)
    except subprocess.SubprocessError as e:
        print(f"AVISO no se pudieron generar los audios de prueba ({e}): se salta la medida real", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

print("FIN", flush=True)
