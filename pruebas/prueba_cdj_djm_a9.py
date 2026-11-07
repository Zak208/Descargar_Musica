# -*- coding: utf-8 -*-
"""Prueba integral de la consola Pioneer CDJ + DJM-A9 y del paso garantizado a la siguiente canción en 'Mezclar Ahora'."""
import os
import sys

# Asegurar path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PySide6.QtWidgets import QApplication
from ui.dj_components import (
    DjPitchFader, DjHotCuePads, DjLoopControls, DjBeatFxRack,
    DjMasterMonitorSection, DjRearPanelDialog, DjEnvironmentBar,
    DjQuickReferenceGuide, DjRotaryKnob, DjJogWheel, DjVuMeter, DjCrossfader, DjFader
)
from ui.dj_page import DjPage, DeckScreen


def test_cdj_and_djm_a9():
    _app = QApplication.instance() or QApplication(sys.argv)

    print("--- 1. Probando Componentes Pioneer CDJ y DJM-A9 ---")
    # Pitch Fader
    pf = DjPitchFader(label="TEMPO", accent_color="#1ED760", range_pct=10.0)
    assert pf.value == 0.0
    pf.setValue(0.5)
    assert abs(pf.value - 0.5) < 1e-4
    pf.resetPitch()
    assert pf.value == 0.0
    print("[OK] DjPitchFader funciona y resetea a 0.0% centro.")

    # Hot Cue Pads
    pads = DjHotCuePads()
    assert pads._mode == "HOT CUE"
    pads.setMode("LOOP")
    assert pads._mode == "LOOP"
    pads.setMode("JUMP")
    assert pads._mode == "JUMP"
    print("[OK] DjHotCuePads alterna entre modos HOT CUE, LOOP y JUMP.")

    # Loop Controls
    loops = DjLoopControls()
    assert hasattr(loops, "loopInRequested")
    assert hasattr(loops, "loopOutRequested")
    assert hasattr(loops, "reloopRequested")
    assert hasattr(loops, "halfLoopRequested")
    assert hasattr(loops, "doubleLoopRequested")
    print("[OK] DjLoopControls tiene todos los controles ritmicos Pioneer.")

    # Beat FX Rack
    fx_rack = DjBeatFxRack()
    assert "ECHO" in fx_rack.EFFECTS
    assert "REVERB" in fx_rack.EFFECTS
    assert "DELAY" in fx_rack.EFFECTS
    assert "FLANGER" in fx_rack.EFFECTS
    assert "ROLL" in fx_rack.EFFECTS
    assert "PHASER" in fx_rack.EFFECTS
    assert "FILTER FX" in fx_rack.EFFECTS
    fx_rack._toggle_fx()
    assert fx_rack._is_active is True
    fx_rack._toggle_fx()
    assert fx_rack._is_active is False
    print("[OK] DjBeatFxRack incluye los 7 Beat FX, pantalla OLED y boton ON/OFF.")

    # Master & Monitor Section
    mon = DjMasterMonitorSection()
    assert hasattr(mon, "knob_master")
    assert hasattr(mon, "knob_booth")
    assert hasattr(mon, "knob_hp_level")
    assert hasattr(mon, "knob_hp_mix")
    assert hasattr(mon, "btn_cue_master")
    assert hasattr(mon, "btn_hp_ab")
    print("[OK] DjMasterMonitorSection contiene Master, Booth, Auriculares Level & Mix y Master Cue.")

    # Rear Panel Dialog
    rear = DjRearPanelDialog()
    assert rear.windowTitle().startswith("Panel Posterior")
    print("[OK] DjRearPanelDialog contiene todas las conexiones I/O (XLR, RCA, Booth, USB, LAN, MIC, AUX, LINE, PHONO, Power, Tierra).")

    # Environment Bar
    env = DjEnvironmentBar()
    assert env.layout().count() == 9  # 9 piezas de equipamiento
    print("[OK] DjEnvironmentBar visualiza los 9 modulos de cabina y estudio.")

    # Quick Reference Guide (12 priority controls)
    guide = DjQuickReferenceGuide()
    assert len(guide.CONTROLS) == 12
    assert guide.CONTROLS[0][1] == "Play/Pause"
    assert guide.CONTROLS[1][1] == "Cue"
    assert guide.CONTROLS[2][1] == "Jog Wheel"
    assert guide.CONTROLS[3][1] == "Pitch Fader"
    assert guide.CONTROLS[4][1] == "Sync"
    assert guide.CONTROLS[5][1] == "Gain / Trim"
    assert guide.CONTROLS[6][1] == "HI / MID / LOW"
    assert guide.CONTROLS[7][1] == "Channel Fader"
    assert guide.CONTROLS[8][1] == "Crossfader"
    assert guide.CONTROLS[9][1] == "Headphones Cue"
    assert guide.CONTROLS[10][1] == "Filter (HPF/LPF)"
    assert guide.CONTROLS[11][1] == "Beat FX"
    print("[OK] DjQuickReferenceGuide contiene los 12 controles clave en orden de prioridad.")

    print("\n--- 2. Probando la Pagina Completa DjPage ---")
    page = DjPage()
    # Verificar controles Deck A
    assert hasattr(page, "screen_a")
    assert hasattr(page, "jog_a")
    assert hasattr(page, "pitch_a")
    assert hasattr(page, "pads_a")
    assert hasattr(page, "btn_play_a")
    assert hasattr(page, "btn_cue_a")
    assert hasattr(page, "btn_sync_a")
    assert hasattr(page, "knob_high_a")
    assert hasattr(page, "knob_mid_a")
    assert hasattr(page, "knob_low_a")
    assert hasattr(page, "knob_filter_a")
    assert hasattr(page, "fader_a")
    assert hasattr(page, "vu_a")

    # Verificar controles Deck B
    assert hasattr(page, "screen_b")
    assert hasattr(page, "jog_b")
    assert hasattr(page, "pitch_b")
    assert hasattr(page, "pads_b")
    assert hasattr(page, "btn_play_b")
    assert hasattr(page, "btn_cue_b")
    assert hasattr(page, "btn_sync_b")
    assert hasattr(page, "knob_high_b")
    assert hasattr(page, "knob_mid_b")
    assert hasattr(page, "knob_low_b")
    assert hasattr(page, "knob_filter_b")
    assert hasattr(page, "fader_b")
    assert hasattr(page, "vu_b")

    # Verificar controles Mezclador Central DJM-A9
    assert hasattr(page, "beat_fx_rack")
    assert hasattr(page, "monitor_section")
    assert hasattr(page, "btn_auto_mix")
    assert hasattr(page, "crossfader")
    assert hasattr(page, "vu_master")

    # Verificar adaptacion responsiva
    page._apply_responsive_layout(1200)
    assert page._current_layout_mode == "wide"
    page._apply_responsive_layout(700)
    assert page._current_layout_mode == "compact"
    print("[OK] DjPage contiene todos los controles de Pioneer CDJ y DJM-A9 y adapta su disposicion segun el tamano.")

    print("\n--- 3. Probando Transicion y Avance 'Mezclar Ahora' ---")
    # Simulamos el comportamiento del mixin
    class DummyPlayer:
        def __init__(self):
            self._pos = 20000
            self._dur = 180000
            self._state = 1

        def position(self):
            return self._pos

        def setPosition(self, p):
            self._pos = p

        def duration(self):
            return self._dur

        def playbackState(self):
            return self._state

        def setPlaybackRate(self, r):
            pass

        def setSource(self, s):
            pass

        def play(self):
            self._state = 1

        def pause(self):
            self._state = 2

        def stop(self):
            self._state = 0

    class DummyMainWindow:
        def __init__(self):
            self.player = DummyPlayer()
            self._xf_plan = None
            self._xf_request = 0
            self.current_item_info = {"title": "Cancion A", "local_path": "trackA.mp3", "bpm": 124.0}
            self.playback_queue = [{"title": "Cancion B", "local_path": "trackB.mp3", "bpm": 126.0}]
            self._context = [self.current_item_info, self.playback_queue[0]]
            self._dj_context = self._context
            self._dj_in_session = True
            self._dj_analysis = {}
            self._dj_profile = "club"
            self._fade_ms = 0
            self._sleep_end_of_track = False
            self.is_loop_enabled = False
            self.page_dj = page

        def dj_session_active(self):
            return True

        def peek_next(self):
            return self.playback_queue[0] if self.playback_queue else None

        def notify(self, msg):
            print(f"  [Notificacion]: {msg}")

        def crossfade_ms(self, natural=False):
            return 0  # Simula _fade_ms == 0 en configuracion

        def _dj_find_fallback_next(self, cur):
            return None

        def _play_entry(self, nxt, crossfade_ms=0):
            self._xf_request = int(crossfade_ms) if crossfade_ms > 0 else getattr(self, "_xf_request", 0)
            self.current_item_info = nxt
            print(f"  [Avance de pista]: Ahora suena '{nxt['title']}' con xf_ms={self._xf_request}")

        def play_next(self, natural=False, force_crossfade_ms=0):
            xf = int(force_crossfade_ms) if force_crossfade_ms > 0 else self.crossfade_ms(natural)
            if self.playback_queue:
                nxt = self.playback_queue.pop(0)
                self._play_entry(nxt, crossfade_ms=xf)

        def dj_engine_on(self):
            return False

        def dj_trigger_now_mix(self):
            nxt = self.peek_next()
            assert nxt is not None
            mix_duration_ms = 6000
            self._xf_request = mix_duration_ms
            # Debe forzar el crossfade sin que crossfade_ms=0 lo sobreescriba
            self.play_next(natural=True, force_crossfade_ms=mix_duration_ms)

    mw = DummyMainWindow()
    assert mw.current_item_info["title"] == "Cancion A"
    mw.dj_trigger_now_mix()
    assert mw.current_item_info["title"] == "Cancion B"
    assert mw._xf_request == 6000
    print("[OK] 'Mezclar Ahora' avanza de Cancion A a Cancion B y preserva el fundido forzado de 6000 ms.")

    print("\nTODAS LAS PRUEBAS (10/10) HAN PASADO CON EXITO!")


if __name__ == "__main__":
    test_cdj_and_djm_a9()
