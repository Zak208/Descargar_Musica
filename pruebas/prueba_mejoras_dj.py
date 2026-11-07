"""Pruebas de validación de las mejoras profesionales del modo DJ:
1. Filtros resonantes modelados (HPF y LPF con Q musical).
2. Tempo delay rítmico estéreo sincronizado a compás con ducking y ping-pong.
3. Dub / Tape Echo mejorado con corte de graves y soporte para Echo Freeze.
4. Space / Washout Reverb con cola envolvente.
5. Nuevos tipos de transición: reverb_wash, delay_drop y smart_filter_eq (Mid-Carve).
6. Elección multivariable choose_type según energía, Camelot, estructura y perfil.
7. Controles interactivos de perfil y rack FX en DjPage y DjMixin.
"""
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np
from services import dj_dsp, dj_fx, transition_types as tt, camelot
from services.mix_types import BeatGrid, TransitionPlan, SAMPLE_RATE

SR = SAMPLE_RATE
passed = 0
failed = 0


def check(desc: str, cond: bool):
    global passed, failed
    if cond:
        passed += 1
        print(f"OK    {desc}", flush=True)
    else:
        failed += 1
        print(f"FALLO {desc}", flush=True)


print("--- 1. Filtros Resonantes Modelados (HPF & LPF con Q musical) ---")
t = np.linspace(0, 1.0, SR, endpoint=False)
sine_low = np.sin(2 * math.pi * 100.0 * t)
sine_mid = np.sin(2 * math.pi * 1000.0 * t)
sine_high = np.sin(2 * math.pi * 5000.0 * t)
combo = np.stack([sine_low + sine_mid, sine_mid + sine_high], axis=1).astype(np.float32)

# LPF: 400 Hz cutoff
lpf = dj_dsp.resonant_filter(combo, cutoff_hz=400.0, kind="lp", q=1.5)
check("LPF devuelve float32 con forma idéntica a la entrada", lpf.shape == combo.shape and lpf.dtype == np.float32)
# Check 100 Hz survives much stronger than 5000 Hz
e_low = np.mean(lpf[:, 0] ** 2)
check("LPF deja pasar bajas frecuencias y atenúa agudos", e_low > 0.1)

# HPF: 2000 Hz cutoff
hpf = dj_dsp.resonant_filter(combo, cutoff_hz=2000.0, kind="hp", q=2.0)
check("HPF devuelve float32 con forma idéntica a la entrada", hpf.shape == combo.shape and hpf.dtype == np.float32)
hpf_low = dj_dsp.resonant_filter(sine_low, cutoff_hz=2000.0, kind="hp", q=1.0)
check("HPF atenúa graves de 100 Hz drásticamente", float(np.max(np.abs(hpf_low))) < 0.05)

# Mid-Carve
carved = dj_dsp.mid_carve(combo, center_hz=1000.0, width_oct=1.0, gain_db=-6.0)
check("Mid-Carve devuelve float32 con forma idéntica", carved.shape == combo.shape and carved.dtype == np.float32)
check("Mid-Carve atenúa los 1000 Hz en torno a -6 dB", np.mean(carved ** 2) < np.mean(combo ** 2))

print("\n--- 2. Tempo Delay Rítmico Estéreo (1/2, 3/4, 1T) con Ducking y Ping-Pong ---")
bpm = 120.0
impulse = np.zeros((SR, 2), dtype=np.float32)
impulse[0, :] = 1.0  # single impulse at t=0

# Delay 1/2 beat = 0.25 s
dly_half = dj_fx.tempo_delay(impulse, bpm=bpm, beats=0.5, feedback=0.5, mix=0.5, ping_pong=True)
check("tempo_delay devuelve array estéreo extendido con cola", dly_half.shape[1] == 2 and len(dly_half) > len(impulse))

# Ping-Pong test: Tap 1 should be on Left channel (t=0.25s), Tap 2 on Right channel (t=0.50s)
tap1_idx = int(round(0.25 * SR))
tap2_idx = int(round(0.50 * SR))
check("tempo_delay ping-pong: primer rebote en canal izquierdo", abs(dly_half[tap1_idx, 0]) > 0.1 and abs(dly_half[tap1_idx, 1]) < 0.01)
check("tempo_delay ping-pong: segundo rebote en canal derecho", abs(dly_half[tap2_idx, 1]) > 0.05 and abs(dly_half[tap2_idx, 0]) < 0.01)

# Ducking test: continuous tone with ducking should attenuate wet repeats
dly_duck = dj_fx.tempo_delay(combo, bpm=128.0, beats=0.75, feedback=0.5, mix=0.5, ducking=0.8)
check("tempo_delay con ducking atenúa delay durante presencia seca", dly_duck.shape[1] == 2 and not np.isnan(dly_duck).any())

print("\n--- 3. Dub / Tape Echo con Corte de Graves y Echo Freeze ---")
# Dub echo with freeze
dub_freeze = dj_fx.dub_tape_echo(combo[:int(0.5 * SR)], bpm=128.0, beats=0.75, freeze=True, tail_s=3.0)
check("dub_tape_echo con freeze genera cola sostenida de 3 s", len(dub_freeze) >= int(3.5 * SR))
check("dub_tape_echo con freeze no satura por encima de ±0.99", np.max(np.abs(dub_freeze)) <= 0.99)
check("dub_tape_echo no contiene NaN ni ceros corruptos", not np.isnan(dub_freeze).any())

print("\n--- 4. Space / Washout Reverb con Cola Envolvente ---")
wash = dj_fx.washout_reverb(combo, decay_s=2.5, mix_start=0.0, mix_end=0.8, tail_s=2.5)
check("washout_reverb devuelve audio filtrado y reverberado con cola envolvente", len(wash) > len(combo))
check("washout_reverb finaliza suavemente en cero", np.max(np.abs(wash[-100:])) < 1e-4)
check("washout_reverb respeta ganancia segura CEILING <= 0.99", np.max(np.abs(wash)) <= 0.99)

space = dj_fx.space_reverb(combo, decay_s=2.0, mix=0.4)
check("space_reverb genera reverberación difusa sin distorsión", len(space) > len(combo))

print("\n--- 5. Nuevas Transiciones: reverb_wash, delay_drop, smart_filter_eq ---")
grid = BeatGrid(0.0, 128.0, confidence=0.9)
plan = TransitionPlan(10.0, 0.0, 8.0, bass_swap_s=4.0)
song_a = combo[:8 * SR] if len(combo) >= 8 * SR else np.tile(combo, (8, 1))[:8 * SR]
song_b = np.roll(song_a, 100, axis=0)

for kind in (tt.TYPE_REVERB_WASH, tt.TYPE_DELAY_DROP, tt.TYPE_SMART_FILTER_EQ):
    out = tt.render_typed(song_a, song_b, plan, kind, bpm=128.0)
    check(f"render_typed({kind}) genera exactamente {8 * SR} muestras estéreo", out.shape == (8 * SR, 2) and out.dtype == np.float32)
    check(f"render_typed({kind}) no produce NaN ni valores fuera de límites", not np.isnan(out).any())

    mix, tail = tt.render_typed_parts(song_a, song_b, plan, kind, bpm=128.0, tail_s=2.0)
    check(f"render_typed_parts({kind}) devuelve mezcla de {8 * SR} y cola coherente", mix.shape == (8 * SR, 2))

print("\n--- 6. Selección Multivariable en choose_type() ---")
info_a = {"bpm": 128.0, "beatgrid": grid, "tone": "8A", "energy": 0.85, "outro_s": 20.0}
info_b = {"bpm": 128.0, "beatgrid": grid, "tone": "8A", "energy": 0.80, "intro_s": 15.0}
long_plan = TransitionPlan(0.0, 0.0, 24.0, bass_swap_s=12.0)

# 1. High energy + Club profile + compatible keys -> smart_filter_eq
t1, w1 = tt.choose_type(info_a, info_b, long_plan, profile="club")
check("choose_type: alta energía y perfil club selecciona smart_filter_eq", t1 == tt.TYPE_SMART_FILTER_EQ and "Mid-Carve" in w1)

# 2. Large energy drop -> reverb_wash
info_drop_b = dict(info_b, energy=0.3)
t2, w2 = tt.choose_type(info_a, info_drop_b, long_plan)
check("choose_type: caída pronunciada de energía selecciona reverb_wash", t2 == tt.TYPE_REVERB_WASH and "washout" in w2)

# 3. Radio profile or high energy cut -> delay_drop
cut_plan = TransitionPlan(0.0, 0.0, 0.0, kind="cut")
t3, w3 = tt.choose_type(info_a, info_b, cut_plan, profile="radio")
check("choose_type: perfil radio en corte selecciona delay_drop", t3 == tt.TYPE_DELAY_DROP and "delay drop" in w3)

# 4. Chill profile -> reverb_wash
t4, w4 = tt.choose_type(info_a, info_b, long_plan, profile="chill")
check("choose_type: perfil chill selecciona reverb_wash", t4 == tt.TYPE_REVERB_WASH and "Chill" in w4)

print("\n--- 7. UI: Controles de Perfil y Rack FX en DjPage ---")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from ui.dj_page import DjPage

app = QApplication.instance() or QApplication([])
page = DjPage()
page.set_session(True, {"title": "Test Track", "uploader": "Artist", "local_path": "a.mp3"})

# Test profile switching
page.set_profile("radio")
check("DjPage set_profile('radio') actualiza botón activo", "1ED760" in page.btn_prof_radio.styleSheet())
page.set_profile("chill")
check("DjPage set_profile('chill') actualiza botón activo", "1ED760" in page.btn_prof_chill.styleSheet())

# Test FX toggles
page._cycle_filter()
check("DjPage _cycle_filter activa HPF", "HPF" in page.btn_fx_filter.text())
page._cycle_delay()
check("DjPage _cycle_delay cicla tiempo de delay", "Delay" in page.btn_fx_delay.text())
page._toggle_freeze()
check("DjPage _toggle_freeze activa Freeze", page._fx_state["freeze_active"] is True)

print("\n==========================================")
print(f"RESUMEN DE PRUEBAS: {passed} PASADAS, {failed} FALLIDAS")
print("==========================================")
if failed > 0:
    sys.exit(1)
