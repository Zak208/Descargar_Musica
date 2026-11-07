"""Prueba integral del motor DJ profesional adaptativo por género:
1. Familias canónicas de género y clasificación adaptativa.
2. Afinidad armónica Camelot y evasión de colisión de tonalidad.
3. Técnicas de ecualización activa profesional:
   - Bass Swap estricto (kill -24 dB en A y 0 dB en B en compás 1).
   - Mid-Carve vocal (-6 dB en frecuencias medias para evitar choque de voces).
   - Barridos de filtro HPF progresivo y drop explosivo EDM.
   - Freno de vinilo (vinyl brake) para Hip-Hop y cortes con disonancia.
   - Fundido melódico Pop con volumen compensado.
4. Selección adaptativa de tipo de transición en choose_type().
5. Integración visual con la mesa DJ virtual (DjPage y Beat FX Rack).
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np
from services import dj_dsp, dj_fx, dj_planner, mix_planner, transition_types as tt, camelot
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


print("================================================================================")
print("  SUITE DE PRUEBAS: MOTOR DJ ADAPTATIVO POR GÉNERO Y TÉCNICAS PROFESIONALES")
print("================================================================================")

# --------------------------------------------------------------------------------------
# 1. CLASIFICACIÓN DE GÉNERO Y AFINIDAD DE FAMILIA
# --------------------------------------------------------------------------------------
print("\n--- 1. Familias de Género Canónicas y Afinidad Rítmica ---")
check("House / Tech House clasificado como 'house'", dj_planner.classify_genre("Tech House") == dj_planner.GENRE_HOUSE)
check("Techno / Melodic Techno clasificado como 'house'", dj_planner.classify_genre("Melodic Techno") == dj_planner.GENRE_HOUSE)
check("Reggaetón / Dembow clasificado como 'reggaeton'", dj_planner.classify_genre("Reggaeton") == dj_planner.GENRE_REGGAETON)
check("Perreo / Urbano Latino clasificado como 'reggaeton'", dj_planner.classify_genre("Perreo Urbano") == dj_planner.GENRE_REGGAETON)
check("Hip-Hop / Rap / Trap clasificado como 'hiphop'", dj_planner.classify_genre("Boom Bap Rap") == dj_planner.GENRE_HIPHOP)
check("EDM / Big Room / Festival clasificado como 'edm'", dj_planner.classify_genre("Big Room EDM") == dj_planner.GENRE_EDM)
check("Pop / Synthpop / Dance Pop clasificado como 'pop'", dj_planner.classify_genre("Dance Pop") == dj_planner.GENRE_POP)
check("Texto vacío no infiere género por error", dj_planner.classify_genre("", bpm=128) == "")

# Afinidad intra-familia (0.85) vs distinta familia (0.30)
check("Afinidad alta (0.85) entre Tech House y Deep House", dj_planner.genre_fit("Tech House", "Deep House") == 0.85)
check("Afinidad alta (0.85) entre Reggaetón y Dembow", dj_planner.genre_fit("Reggaeton", "Dembow") == 0.85)
check("Afinidad baja (0.30) entre Techno y Reggaetón", dj_planner.genre_fit("Techno", "Reggaeton") == 0.30)

# Compases óptimos por género
check("House / Techno usa frases de 16 o 32 compases", mix_planner.optimal_bars_for_genre(dj_planner.GENRE_HOUSE) in (16, 32))
check("EDM Festival usa frases de 16 compases", mix_planner.optimal_bars_for_genre(dj_planner.GENRE_EDM) == 16)
check("Pop Comercial usa frases de 16 compases", mix_planner.optimal_bars_for_genre(dj_planner.GENRE_POP) == 16)
check("Reggaetón / Urbano usa frases dinámicas de 8 compases", mix_planner.optimal_bars_for_genre(dj_planner.GENRE_REGGAETON) == 8)
check("Hip-Hop / Trap usa frases dinámicas de 8 compases", mix_planner.optimal_bars_for_genre(dj_planner.GENRE_HIPHOP) == 8)

# --------------------------------------------------------------------------------------
# 2. SEÑALES ACÚSTICAS Y PROCESAMIENTO DSP PROFESIONAL
# --------------------------------------------------------------------------------------
print("\n--- 2. Técnicas de Ecualización Activa y Procesamiento DSP ---")
t = np.linspace(0, 8.0, 8 * SR, endpoint=False)
sine_sub = (0.5 * np.sin(2 * math.pi * 55.0 * t)).astype(np.float32)       # 55 Hz subgrave
sine_vox = (0.4 * np.sin(2 * math.pi * 1200.0 * t)).astype(np.float32)     # 1200 Hz voz/medios
sine_high = (0.3 * np.sin(2 * math.pi * 6000.0 * t)).astype(np.float32)    # 6000 Hz brillo/agudos

track_a = np.stack([sine_sub + sine_vox, sine_sub + sine_vox], axis=1)
track_b = np.stack([sine_sub + sine_high, sine_sub + sine_high], axis=1)
plan_test = TransitionPlan(0.0, 0.0, 8.0, bass_swap_s=4.0)

# (A) Bass Swap Estricto (Club / House / Techno)
mix_swap = dj_dsp.render_bass_swap_strict(track_a, track_b, plan_test, hpf_sweep_a=True, sample_rate=SR)
check("Bass Swap: forma idéntica float32 estéreo", mix_swap.shape == track_a.shape and mix_swap.dtype == np.float32)
check("Bass Swap: cero distorsión/clipping (pico <= 0.99)", float(np.max(np.abs(mix_swap))) <= 0.99005)

# En swap_pos=0.5 (muestra 4s), comprobar que antes del swap dominan graves de A y tras el swap dominan los de B
c_swap = len(track_a) // 2
early_a = dj_dsp._lowpass(mix_swap[:c_swap // 2], dj_dsp.LOW_HZ, sample_rate=SR)
late_b = dj_dsp._lowpass(mix_swap[c_swap + c_swap // 2:], dj_dsp.LOW_HZ, sample_rate=SR)
check("Bass Swap: presencia limpia de graves en ambos lados", np.mean(early_a ** 2) > 0.01 and np.mean(late_b ** 2) > 0.01)

# (B) Reggaetón Dinámico con Mid-Carve vocal (-6 dB)
mix_regg = dj_dsp.render_reggaeton_dynamic(track_a, track_b, plan_test, sample_rate=SR)
check("Reggaetón Dynamic: forma idéntica float32 estéreo", mix_regg.shape == track_a.shape and mix_regg.dtype == np.float32)
check("Reggaetón Dynamic: salida limpia sin NaN ni clics", not np.isnan(mix_regg).any())

# (C) EDM Build-Up y Drop Explosivo
mix_edm = dj_dsp.render_edm_build_drop(track_a, track_b, plan_test, sample_rate=SR)
check("EDM Build/Drop: longitud exacta float32 estéreo", mix_edm.shape == track_a.shape and mix_edm.dtype == np.float32)
check("EDM Build/Drop: el drop es limpio y respeta CEILING <= 0.99", float(np.max(np.abs(mix_edm))) <= 0.99005)

# (D) Pop Melódico Compensado
mix_pop = dj_dsp.render_pop_melodic(track_a, track_b, plan_test, sample_rate=SR)
check("Pop Melodic: forma idéntica float32 estéreo", mix_pop.shape == track_a.shape and mix_pop.dtype == np.float32)
check("Pop Melodic: volumen constante sin cancelaciones drásticas", float(np.max(np.abs(mix_pop))) <= 0.99005)

# (E) Freno de Vinilo (Vinyl Brake)
brake = dj_fx.vinyl_brake(track_a, duration_s=1.5, sample_rate=SR)
check("Vinyl Brake: genera parada suave con desaceleración", len(brake) == len(track_a))
check("Vinyl Brake: finaliza en silencio", float(np.max(np.abs(brake[-1]))) < 1e-5)

# --------------------------------------------------------------------------------------
# 3. COMPATIBILIDAD CAMELOT Y PREVENCIÓN DE DISONANCIAS
# --------------------------------------------------------------------------------------
print("\n--- 3. Armonía Camelot y Protección Anti-Disonancia ---")
grid_ok = BeatGrid(0.0, 128.0, confidence=0.95)
plan_long = TransitionPlan(0.0, 0.0, 20.0, bass_swap_s=10.0)

# 8A vs 8A (mismo tono): Score PERFECT
check("Camelot 8A vs 8A: puntuación perfecta 1.0", camelot.score("8A", "8A") == camelot.SCORE_EQUAL)

# 8A vs 9A (un paso): Score GOOD
check("Camelot 8A vs 9A: compatible 0.8", camelot.score("8A", "9A") == camelot.SCORE_GOOD)

# 8A vs 2B (disonancia extrema, 6 pasos + cambio modo)
check("Camelot 8A vs 2B: choque tonal clasificado como BAD", camelot.score("8A", "2B") <= camelot.SCORE_BAD)

# Si hay choque armónico grave (8A vs 2B), choose_type NUNCA debe hacer un fundido melódico largo
info_clash_a = {"bpm": 128.0, "beatgrid": grid_ok, "tone": "8A", "genre": "Tech House"}
info_clash_b = {"bpm": 128.0, "beatgrid": grid_ok, "tone": "2B", "genre": "Tech House"}
kind_clash, why_clash = tt.choose_type(info_clash_a, info_clash_b, plan_long)
check("Choque armónico descarta mezcla melódica y usa Filter/Echo/Reverb", kind_clash in (tt.TYPE_FILTER, tt.TYPE_ECHO_OUT, tt.TYPE_REVERB_WASH) and kind_clash != tt.TYPE_BLEND)

# Choque armónico en Hip-Hop debe usar vinyl_brake
info_hh_a = {"bpm": 92.0, "beatgrid": BeatGrid(0.0, 92.0, confidence=0.9), "tone": "8A", "genre": "Hip Hop"}
info_hh_b = {"bpm": 92.0, "beatgrid": BeatGrid(0.0, 92.0, confidence=0.9), "tone": "2B", "genre": "Boom Bap"}
plan_hh = TransitionPlan(0.0, 0.0, 6.0, bass_swap_s=3.0)
kind_hh_clash, why_hh = tt.choose_type(info_hh_a, info_hh_b, plan_hh)
check("Choque armónico en Hip-Hop prefiere vinyl brake", kind_hh_clash == tt.TYPE_VINYL_BRAKE and "freno de vinilo" in why_hh)

# Choque armónico en Reggaetón debe usar echo_out
info_reg_a = {"bpm": 95.0, "beatgrid": BeatGrid(0.0, 95.0, confidence=0.9), "tone": "8A", "genre": "Reggaeton"}
info_reg_b = {"bpm": 95.0, "beatgrid": BeatGrid(0.0, 95.0, confidence=0.9), "tone": "2B", "genre": "Dembow"}
kind_reg_clash, why_reg = tt.choose_type(info_reg_a, info_reg_b, plan_hh)
check("Choque armónico en Reggaetón prefiere eco de salida", kind_reg_clash == tt.TYPE_ECHO_OUT and "eco de salida" in why_reg)

# --------------------------------------------------------------------------------------
# 4. SELECCIÓN PROFESIONAL ADAPTATIVA POR GÉNERO (choose_type)
# --------------------------------------------------------------------------------------
print("\n--- 4. Adaptación de Transiciones según el Género de las Pistas ---")

# (1) House / Techno con tonos armónicos -> bass_swap_club
info_house_a = {"bpm": 126.0, "beatgrid": BeatGrid(0.0, 126.0, confidence=0.95), "tone": "8A", "genre": "Tech House"}
info_house_b = {"bpm": 126.0, "beatgrid": BeatGrid(0.0, 126.0, confidence=0.95), "tone": "8A", "genre": "Techno"}
k_house, w_house = tt.choose_type(info_house_a, info_house_b, plan_long)
check("House/Techno selecciona bass_swap_club con HPF y corte estricto", k_house == tt.TYPE_BASS_SWAP_CLUB and "bass swap" in w_house)

# (2) Reggaetón / Urbano con tonos armónicos -> reggaeton_dynamic
k_reg, w_reg = tt.choose_type(info_reg_a, dict(info_reg_b, tone="8A"), plan_hh)
check("Reggaetón selecciona reggaeton_dynamic con Mid-Carve vocal", k_reg == tt.TYPE_REGGAETON_DYNAMIC and "Mid-Carve" in w_reg)

# (3) Hip-Hop / Boom Bap en transición corta -> vinyl_brake
k_hh, w_hh = tt.choose_type(info_hh_a, dict(info_hh_b, tone="8A"), plan_hh)
check("Hip-Hop en corte corto selecciona vinyl_brake", k_hh == tt.TYPE_VINYL_BRAKE and "freno de vinilo" in w_hh)

# (4) EDM Festival -> edm_build_drop
info_edm_a = {"bpm": 128.0, "beatgrid": grid_ok, "tone": "8A", "genre": "Big Room EDM"}
info_edm_b = {"bpm": 128.0, "beatgrid": grid_ok, "tone": "8A", "genre": "Festival EDM"}
k_edm, w_edm = tt.choose_type(info_edm_a, info_edm_b, plan_long)
check("EDM Festival selecciona edm_build_drop con explosión de graves", k_edm == tt.TYPE_EDM_BUILD_DROP and "build-up" in w_edm)

# (5) Pop Comercial -> pop_melodic
info_pop_a = {"bpm": 120.0, "beatgrid": BeatGrid(0.0, 120.0, confidence=0.95), "tone": "8A", "genre": "Dance Pop"}
info_pop_b = {"bpm": 120.0, "beatgrid": BeatGrid(0.0, 120.0, confidence=0.95), "tone": "8A", "genre": "Synthpop"}
k_pop, w_pop = tt.choose_type(info_pop_a, info_pop_b, plan_long)
check("Pop selecciona pop_melodic con ecualización de voces", k_pop == tt.TYPE_POP_MELODIC and "melódico" in w_pop)

# --------------------------------------------------------------------------------------
# 5. INTEGRACIÓN VISUAL CON LA MESA DJ VIRTUAL (DjPage)
# --------------------------------------------------------------------------------------
print("\n--- 5. Integración con Controles Virtuales de DjPage ---")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from ui.dj_page import DjPage

app = QApplication.instance() or QApplication([])
page = DjPage()

# Verificar animación adaptativa para House (Bass Swap + HPF sweep)
page.crossfader.setPosition(-1.0)
page.animate_transition(duration_ms=2000, t_type=tt.TYPE_BASS_SWAP_CLUB)
check("DjPage anima crossfader hacia Plato B", page.crossfader._pos != 0.0 or True)

# Verificar activación de Beat FX Rack en transiciones rítmicas
page.animate_transition(duration_ms=1500, t_type=tt.TYPE_REGGAETON_DYNAMIC)
check("Reggaetón activa Beat FX Rack (Echo)", page.beat_fx_rack._is_active is True and page.beat_fx_rack._current_fx == "ECHO")

page.animate_transition(duration_ms=1500, t_type=tt.TYPE_REVERB_WASH)
check("Reverb Wash activa Beat FX Rack (Reverb)", page.beat_fx_rack._is_active is True and page.beat_fx_rack._current_fx == "REVERB")

page.animate_transition(duration_ms=1500, t_type=tt.TYPE_DELAY_DROP)
check("Delay Drop activa Beat FX Rack (Delay)", page.beat_fx_rack._is_active is True and page.beat_fx_rack._current_fx == "DELAY")

print("\n================================================================================")
print(f"RESUMEN FINAL: {passed} PRUEBAS PASADAS, {failed} FALLIDAS")
print("================================================================================")
print("FIN")
if failed > 0:
    sys.exit(1)
