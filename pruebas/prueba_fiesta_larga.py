"""DIAGNÓSTICO DE RESISTENCIA del modo fiesta (fase 30). No es parte de la suite rápida: tarda varios minutos, escribe unos 2 GB
temporales y necesita TUS canciones. Se llama «prueba_…» solo para poder lanzarlo a mano igual que las demás.

Qué hace: renderiza FUERA DE LÍNEA, con `services/mix_recorder.render_session` (la `EngineSession` real sobre un `MixEngine` sin
tarjeta de sonido, muestra a muestra lo que sonaría), una sesión de 3 horas con las canciones de la carpeta (solo se leen;
se repiten en órdenes distintos hasta llenar el tiempo, sin la misma dos veces seguidas). El análisis se hace con
`services/track_analysis.analyze(path)` en una carpeta de datos temporal (`_aislar`: no toca la biblioteca del usuario).
Comprueba:
  * sin excepciones: `render_session` termina, sin errores de la sesión y sin muestras NaN;
  * sin clics en las mezclas: en cada UNIÓN que hace el motor (comienzo de la mezcla, relevo y final, donde se pega el cuerpo
    de B) se mide el mayor salto entre muestras frente a lo normal de su alrededor (`transition_scorer._click_ratio`, la misma
    medida del puntuador) y se compara con el audio de antes y de después de la mezcla; los saltos fuertes del resto del tramo
    se enseñan aparte, sin contar como fallo (casi siempre son golpes de la propia música: con --conservar se pueden escuchar);
  * memoria estable: la memoria privada del proceso se apunta durante todo el render y la del final no puede haber crecido
    más de `MAX_GROWTH_MB` respecto a la del principio;
  * cuánto tardó (y cuántas veces más rápido que el tiempo real).
Lo que NO comprueba (y por eso no sustituye a la puerta del plan, «3 horas seguidas sin fallos en tu equipo» en altavoces): la
tarjeta de sonido y PortAudio (subdesbordamientos, un dispositivo que se desconecta), el hilo de la interfaz bajo carga, el
vigilante (aquí no hay ventana), el calor o el ahorro de energía del portátil en 3 horas reales, ni lo que se oye.
Uso:  python pruebas/prueba_fiesta_larga.py [--minutos 180] [--carpeta RUTA] [--conservar]"""
import argparse
import ctypes
import os
import random
import sys
import tempfile
import time
import wave

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np  # noqa: E402

from services import mix_recorder, track_analysis, transition_scorer  # noqa: E402
from services.dj_service import DJ_EXTS  # noqa: E402
from services.mix_types import SAMPLE_RATE  # noqa: E402

MAX_GROWTH_MB = 80.0            # crecimiento de memoria privada tolerado entre el principio y el final del render
WINDOW_PAD_S = 1.0              # margen alrededor de cada mezcla al buscar clics
REFERENCE_S = 4.0               # audio de antes y de después de la mezcla con el que se compara
JOIN_WINDOW_S = 0.06            # alrededor de cada unión del motor (comienzo, relevo y final de la mezcla)
CUT_PIECE_S = 0.5               # lo que dura la pieza de B de un corte limpio (`dj_engine.CUT_PIECE_S`)


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)
    return cond


def private_mb():
    """Memoria privada del proceso en MB (Windows), o None si no se puede leer."""
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    ok = kernel.K32GetProcessMemoryInfo(ctypes.c_void_p(kernel.GetCurrentProcess()), ctypes.byref(counters), counters.cb)
    return counters.PrivateUsage / 2 ** 20 if ok else None


def read_wav(path, start_s, end_s):
    """Trozo [start_s, end_s) de un WAV de 16 bits estéreo como float (n, 2)."""
    with wave.open(path, "rb") as f:
        rate, total = f.getframerate(), f.getnframes()
        a = max(0, min(total, int(start_s * rate)))
        b = max(a, min(total, int(end_s * rate)))
        f.setpos(a)
        data = np.frombuffer(f.readframes(b - a), dtype="<i2").astype(np.float32) / 32768.0
    return data.reshape(-1, f.getnchannels())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutos", type=float, default=180.0)
    parser.add_argument("--carpeta", default=os.path.expanduser("~/Music/Canciones_YouTube"))
    parser.add_argument("--conservar", action="store_true", help="no borrar el WAV al terminar (ocupa unos 10 MB por minuto)")
    args = parser.parse_args()

    songs = sorted(os.path.join(args.carpeta, n) for n in os.listdir(args.carpeta) if n.lower().endswith(DJ_EXTS))
    if len(songs) < 3:
        print(f"Hacen falta al menos 3 canciones en {args.carpeta} (hay {len(songs)}).")
        print("FIN")
        return
    print(f"      {len(songs)} canciones en {args.carpeta} (solo lectura)", flush=True)
    t0 = time.monotonic()
    analysis = {}
    for path in songs:
        try:
            result = track_analysis.analyze(path)
        except Exception as e:
            print(f"      no se pudo analizar {os.path.basename(path)}: {e}")
            continue
        if result and (result.get("duration_ms") or 0) > 30000:
            analysis[path] = result
    analysed_s = time.monotonic() - t0
    check(f"análisis de {len(analysis)} de {len(songs)} canciones en {analysed_s:.0f} s (datos aislados)", len(analysis) >= 3)

    rng = random.Random(30)
    target_s = args.minutos * 60.0
    playlist, total = [], 0.0
    pool = list(analysis)
    while total < target_s + 20.0 * len(playlist):    # las mezclas solapan unos 20 s cada canción con la siguiente
        rng.shuffle(pool)
        for path in pool:
            if total >= target_s + 20.0 * len(playlist):
                break
            if playlist and path in playlist[-3:]:
                continue
            playlist.append(path)
            total += analysis[path]["duration_ms"] / 1000.0
    print(f"      lista de {len(playlist)} canciones ({total / 60:.0f} min sin solapar), cada una {len(playlist) / len(pool):.1f} veces",
          flush=True)

    def info_for(path):
        info = dict(analysis.get(path) or {})
        info["beatgrid"] = track_analysis.grid_from(info)
        return info

    out_dir = tempfile.mkdtemp(prefix="descargador_fiesta_larga_")
    out = os.path.join(out_dir, "sesion.wav")
    memory = []                                        # (segundos de salida, MB)
    last = [0.0]

    def progress(index, count, seconds):
        now = time.monotonic()
        if now - last[0] >= 0.5:                       # el render va unas 200 veces más rápido que el tiempo real
            last[0] = now
            mb = private_mb()
            if mb is not None:
                memory.append((seconds, mb))
            if len(memory) % 20 == 1:
                print(f"      … canción {index + 1} de {count}, {seconds / 60:5.1f} min renderizados, memoria {mb or 0:.0f} MB",
                      flush=True)

    t1 = time.monotonic()
    result, error = None, None
    try:
        result = mix_recorder.render_session(playlist, info_for, out, bars=16, progress=progress)
    except Exception as e:                             # lo que se quiere ver: que no pase
        error = e
    wall = time.monotonic() - t1
    check(f"el render termina sin excepciones ({error!r})" if error else "el render termina sin excepciones", error is None)
    if result is None:
        print("FIN")
        return
    rendered = result["duration_s"]
    print(f"      {rendered / 60:.1f} min de sesión en {wall / 60:.1f} min ({rendered / max(wall, 1e-6):.0f} veces el tiempo real), "
          f"{len(result['transitions'])} transiciones", flush=True)
    check("sin errores de la sesión (canciones que no cargan, preparaciones fallidas)", not result["errors"])
    if result["errors"]:
        print("      errores:", result["errors"][:5])
    check(f"sin muestras NaN o infinitas ({result['nonfinite']})", result["nonfinite"] == 0)
    check(f"pico de salida {result['peak']:.2f} (FFmpeg recorta por encima de 1,0)", result["peak"] < 1.5)

    # Clics. Dos medidas: (1) en las UNIONES que hace el motor (comienzo de la mezcla, relevo y final de la mezcla, donde se pega
    # el cuerpo de B), que es donde un fallo del motor sonaría como un clic: tiene que ser 0; (2) el mayor salto de todo el tramo
    # de la mezcla, que también recoge golpes de la propia música (un bombo tras un silencio): solo informa.
    joint_clicks, loud, worst = [], [], (0.0, None)
    path = result.get("out_path")
    if path and os.path.isfile(path):
        for tr in result["transitions"]:
            plan = tr.get("plan") or {}
            cut = plan.get("kind") == "cut" or not plan.get("length_s")
            joins = (tr["at_s"], tr["start_s"], tr["start_s"] + CUT_PIECE_S if cut else tr["at_s"] + plan["length_s"])
            start = tr["at_s"] - WINDOW_PAD_S
            end = joins[2] + WINDOW_PAD_S
            before = read_wav(path, start - REFERENCE_S, start)
            after = read_wav(path, end, end + REFERENCE_S)
            ref = max(transition_scorer._click_ratio(np, before, SAMPLE_RATE)[0], transition_scorer._click_ratio(np, after, SAMPLE_RATE)[0])
            names = f"«{os.path.basename(tr['from'] or '')[:28]}» → «{os.path.basename(tr['to'] or '')[:28]}»"
            for label, t in zip(("comienzo", "relevo", "final"), joins):
                ratio, _at = transition_scorer._click_ratio(np, read_wav(path, t - JOIN_WINDOW_S, t + JOIN_WINDOW_S), SAMPLE_RATE)
                if ratio >= transition_scorer.CLICK_RATIO and ratio >= transition_scorer.CLICK_VS_PARTS * ref:
                    joint_clicks.append(f"{label} de la mezcla a los {t:.2f} s: {ratio:.1f} veces lo normal (alrededor {ref:.1f}), "
                                        f"{plan.get('kind')}, {names}")
            ratio, at = transition_scorer._click_ratio(np, read_wav(path, start, end), SAMPLE_RATE)
            if ratio > worst[0]:
                worst = (ratio, tr)
            if ratio >= transition_scorer.CLICK_RATIO and ratio >= transition_scorer.CLICK_VS_PARTS * ref:
                where = start + (at or 0.0)
                loud.append(f"a los {where:.2f} s ({where - tr['at_s']:+.2f} s del comienzo de la mezcla, ninguna unión a menos de "
                            f"{min(abs(where - j) for j in joins):.2f} s): {ratio:.1f} veces lo normal (alrededor {ref:.1f}), {names}")
        check(f"sin clics en las uniones del motor ({3 * len(result['transitions'])} uniones de {len(result['transitions'])} mezclas)",
              not joint_clicks)
        for text in joint_clicks[:10]:
            print("      clic en el", text)
        print(f"      mayor salto dentro de las mezclas: {worst[0]:.1f} veces lo normal; saltos fuertes fuera de las uniones "
              f"(probablemente golpes de la propia música; escúchalos con --conservar): {len(loud)}")
        for text in loud[:10]:
            print("        ·", text)
    else:
        check("hay archivo para buscar clics", False)

    # Memoria
    if len(memory) >= 6:
        k = max(2, len(memory) // 5)
        first = sorted(mb for _s, mb in memory[:k])[k // 2]
        final = sorted(mb for _s, mb in memory[-k:])[k // 2]
        peak = max(mb for _s, mb in memory)
        check(f"memoria estable: {first:.0f} MB al principio, {final:.0f} MB al final (pico {peak:.0f} MB, tolera +{MAX_GROWTH_MB:.0f})",
              final - first <= MAX_GROWTH_MB)
    else:
        check("memoria: muy pocas medidas (render demasiado corto o no es Windows)", True)

    check(f"duró {wall / 60:.1f} min para {rendered / 60:.0f} min de sesión", rendered >= min(target_s, total) * 0.9)
    print("      AVISO: esto no sustituye a las 3 horas reales en altavoces (puerta del plan): no prueba la tarjeta de sonido, "
          "PortAudio, la interfaz ni el vigilante.")
    if args.conservar and path:
        print(f"      el WAV se queda en {path}")
    else:
        for name in os.listdir(out_dir):
            try:
                os.remove(os.path.join(out_dir, name))
            except OSError:
                pass
        try:
            os.rmdir(out_dir)
        except OSError:
            pass
    print("FIN")


if __name__ == "__main__":
    main()
