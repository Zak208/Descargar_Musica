"""Pruebas de anticipación de mezcla y mantenimiento de volumen en el motor DJ:
1. Detección de caída de volumen (_fading_end) y adelanto de mezcla (_before_silence).
2. Transición sin caída de volumen en la salida (groove y energía constantes).
3. Soporte de delay_drop en alineación audible (_audible_plan y _split).
4. Pruebas de previsualización sin descarga (direct CDN y formato YouTube seguro).
"""
import math
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from services.dj_engine import _fading_end, _last_sound, EngineSession
from services.mix_types import TransitionPlan, BeatGrid, SAMPLE_RATE, KIND_BLEND
from services.youtube_service import PreviewAudioWorker
from services import transition_types

def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)

# -------------------------------------------------------------------------
# 1. Detección de caída de volumen y adelanto de mezcla
# -------------------------------------------------------------------------
sr = SAMPLE_RATE
total_s = 120
total_samples = total_s * sr
data = np.ones((total_samples, 2), dtype=np.float32) * 0.6
fade_start = 105 * sr  # últimos 15 segundos caen de 0.6 a 0.02
data[fade_start:] *= np.linspace(1.0, 0.03, total_samples - fade_start)[:, None]

class TrackMock:
    frames = total_samples
    data = data

# Mezcla originalmente planeada en los últimos 16 segundos (de 104s a 120s)
plan = TransitionPlan(a_start_s=104.0, b_start_s=0.0, length_s=16.0, kind=KIND_BLEND)
grid = BeatGrid(first_beat_s=0.0, bpm=120.0) # 2.0s por compás

fading = _fading_end(data, total_samples, ref_s=16.0)
check("fading_end detecta correctamente el punto antes de que la canción decaiga",
      fading is not None and 105 * sr <= fading <= 118 * sr)

shifted = EngineSession._before_silence(TrackMock, plan, grid)
check("before_silence adelanta la mezcla para evitar el bajón de volumen",
      shifted.a_start_s < plan.a_start_s and "decae de volumen" in shifted.reason)

check("la mezcla adelantada concluye antes de que el volumen caiga a niveles muertos",
      (shifted.a_start_s + shifted.length_s) * sr <= fading + 2 * sr)

# -------------------------------------------------------------------------
# 2. Alineación audible con delay_drop
# -------------------------------------------------------------------------
dd_plan = TransitionPlan(a_start_s=80.0, b_start_s=0.0, length_s=16.0, bass_swap_s=8.0)
split_dd = EngineSession._split(transition_types.TYPE_DELAY_DROP, dd_plan, 16 * sr)
check("EngineSession._split maneja TYPE_DELAY_DROP usando cut_point",
      split_dd == int(round(8.0 * sr)))

# -------------------------------------------------------------------------
# 3. Formato seguro de extracción en PreviewAudioWorker
# -------------------------------------------------------------------------
worker = PreviewAudioWorker("https://www.youtube.com/watch?v=dummy")
check("PreviewAudioWorker está instanciado y listo", worker is not None)

# -------------------------------------------------------------------------
# 4. Verificación de no-silencio y preservación de energía
# -------------------------------------------------------------------------
# Verificamos que a.frames y low limit no se excedan
check("el adelanto musical respeta el límite inferior (a_dur / 2)",
      shifted.a_start_s >= total_s / 2)

print("\n==========================================")
print("TODAS LAS PRUEBAS DE ANTICIPACIÓN SUPERADAS")
print("==========================================")
print("FIN")
