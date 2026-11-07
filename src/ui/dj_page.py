"""Página y Cabina de DJ Profesional: Emulación virtual completa de Pioneer CDJ y DJM-A9.
Incluye:
1. Reproductores CDJ (Izquierdo y Derecho):
   - Display / Screen (Canción, BPM, Waveform, Key Camelot, Pitch %, Tiempo)
   - Browse, Load, Menu, Back
   - Jog Wheel giratorio con modo Vinyl
   - Play/Pause iluminado, Cue iluminado
   - Tempo / Pitch Fader (+/- 10%) con center detent LED 0.0%
   - Master Tempo (Key Lock), Sync, Quantize, Slip, Reverse
   - Hot Cue Pads (4 pads RGB con modos Hot Cue, Loop, Jump)
   - Beat Loop (In/4Beat, Out, Reloop/Exit, 1/2X, 2X) y Beat Jump
   - USB Port ("USB 1" / "USB 2") y botón Eject seguro

2. Mesa de mezclas DJM-A9:
   - Canales 1 y 2: Selector de entrada (USB A/B, LINE, PHONO), Trim/Gain, EQ de 3 bandas (HI, MID, LOW con kill),
     Sound Color FX + Filter, Cue / PFL preescucha, Channel Fader y Channel Meter (VU por canal)
   - Selector y Crossfader Assign (A / THRU / B)
   - Beat FX Rack central: Pantalla OLED, Selector (Echo, Reverb, Delay, Flanger, Roll, Phaser, Filter FX),
     Channel Assign, Beat division (< y >), Level/Depth knob y botón iluminado BEAT FX ON/OFF
   - Sección de Monitorización: Master Level, Master Meter dual estéreo, Booth Monitor, Headphones Level & Mix, Master Cue, HP A/B
   - Crossfader horizontal interactivo con botón gigante MEZCLAR AHORA

3. Conexiones y Entradas: Panel trasero interactivo (Master XLR, RCA, Booth, USBs, LAN Link, MICs, AUX, LINE, PHONO, Power, Tierra)
4. Equipamiento adicional: Barra de entorno de cabina (Auriculares, Monitores, PA, Subwoofer, Micrófono, USBs, Laptop, Tarjeta, Soporte)
5. Tabla de referencia rápida: Modal de aprendizaje de los 12 controles clave en orden de prioridad.
"""
import os
import math
import random
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QUrl
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QListWidget, QMenu, QScrollArea, QSizePolicy, QComboBox, QFileDialog
)

from services.transition_votes import TAGS
from ui.dj_votes_mixin import TAG_LABELS
from ui.icons import icon
from ui.widgets import ElidedLabel
from ui.dj_components import (
    DjRotaryKnob, DjJogWheel, DjVuMeter, DjCrossfader, DjFader,
    DjPitchFader, DjHotCuePads, DjLoopControls, DjBeatFxRack,
    DjMasterMonitorSection, DjRearPanelDialog, DjEnvironmentBar,
    DjQuickReferenceGuide, DjColorFxSelector, DjTrackBrowserDialog,
    DjMasterWaveformDisplay, DjVirtualBrowser, DjOverviewWaveform
)

UPCOMING_SHOWN = 30
COMPACT_MIN_W = 50


class DeckScreen(QFrame):
    """Pantalla digital estilo CDJ / VirtualDJ con información de pista, BPM, Camelot y forma de onda."""
    seekRequested = Signal(int)

    def __init__(self, deck_label="DECK A", accent_color="#00D2FF", parent=None):
        super().__init__(parent)
        self.deck_label = deck_label
        self.accent_color = accent_color
        self.setObjectName("PanelCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            QFrame#PanelCard {
                background-color: #121216;
                border: 1px solid #252530;
                border-radius: 8px;
            }
        """)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(84)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Barra superior de la pantalla: etiqueta de Deck, Badges de modo y tiempo
        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        self.deck_tag = QLabel(deck_label)
        self.deck_tag.setStyleSheet(f"font-size: 11px; font-weight: 900; color: {accent_color}; letter-spacing: 1.5px; background: transparent;")
        top_row.addWidget(self.deck_tag)

        # Badges de modos de hardware CDJ
        self.badge_mt = QLabel("MT")
        self.badge_mt.setStyleSheet("font-size: 8px; font-weight: 900; color: #22EC6A; background: #12301A; border-radius: 2px; padding: 1px 3px;")
        self.badge_mt.setToolTip("Master Tempo / Key Lock activado")
        self.badge_mt.setVisible(True)

        self.badge_quantize = QLabel("QUANT")
        self.badge_quantize.setStyleSheet("font-size: 8px; font-weight: 900; color: #FF4444; background: #331515; border-radius: 2px; padding: 1px 3px;")
        self.badge_quantize.setToolTip("Quantize activado (snap a compases y beats)")
        self.badge_quantize.setVisible(False)

        self.badge_slip = QLabel("SLIP")
        self.badge_slip.setStyleSheet("font-size: 8px; font-weight: 900; color: #FF8822; background: #332010; border-radius: 2px; padding: 1px 3px;")
        self.badge_slip.setToolTip("Slip Mode activado (tiempo continuo de fondo)")
        self.badge_slip.setVisible(False)

        self.badge_vinyl = QLabel("VINYL")
        self.badge_vinyl.setStyleSheet(f"font-size: 8px; font-weight: 900; color: {accent_color}; background: #152238; border-radius: 2px; padding: 1px 3px;")
        self.badge_vinyl.setToolTip("Vinyl Mode activado (scratch y needle drop)")
        self.badge_vinyl.setVisible(True)

        self.badge_loop = QLabel("LOOP")
        self.badge_loop.setStyleSheet("font-size: 8px; font-weight: 900; color: #FFDD44; background: #332A10; border-radius: 2px; padding: 1px 3px;")
        self.badge_loop.setToolTip("Bucle activo")
        self.badge_loop.setVisible(False)

        top_row.addWidget(self.badge_mt)
        top_row.addWidget(self.badge_quantize)
        top_row.addWidget(self.badge_slip)
        top_row.addWidget(self.badge_vinyl)
        top_row.addWidget(self.badge_loop)

        self.on_air_badge = QLabel("• EN EL AIRE")
        self.on_air_badge.setStyleSheet("font-size: 9px; font-weight: 800; color: #FF3344; background: #331015; border-radius: 3px; padding: 1px 4px;")
        self.on_air_badge.setVisible(False)
        top_row.addWidget(self.on_air_badge)
        top_row.addStretch()

        self.time_lbl = QLabel("-00:00")
        self.time_lbl.setStyleSheet("font-size: 12px; font-weight: 800; color: #FFFFFF; font-family: monospace; background: transparent;")
        top_row.addWidget(self.time_lbl)
        layout.addLayout(top_row)

        # Título y artista estilo VirtualDJ
        self.title_lbl = ElidedLabel("Arrastra una canción en este deck para cargarlo")
        self.title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF; background: transparent;")
        layout.addWidget(self.title_lbl)

        self.artist_lbl = ElidedLabel("---")
        self.artist_lbl.setStyleSheet("font-size: 11px; color: #A0A0B0; background: transparent;")
        layout.addWidget(self.artist_lbl)

        # Fila técnica: BPM, Tono Camelot y Pitch
        tech_row = QHBoxLayout()
        tech_row.setSpacing(6)

        self.bpm_box = QLabel("--- BPM")
        self.bpm_box.setStyleSheet(f"font-size: 11px; font-weight: 900; color: {accent_color}; background: #181822; border-radius: 4px; padding: 2px 6px;")
        self.lbl_bpm = self.bpm_box  # Alias de compatibilidad
        tech_row.addWidget(self.bpm_box)

        self.key_box = QLabel("--- KEY")
        self.key_box.setStyleSheet("font-size: 11px; font-weight: 800; color: #E0E0FF; background: #222235; border-radius: 4px; padding: 2px 6px;")
        tech_row.addWidget(self.key_box)

        self.pitch_box = QLabel("±0.00%")
        self.pitch_box.setStyleSheet("font-size: 10px; font-weight: 700; color: #888899; background: transparent;")
        tech_row.addWidget(self.pitch_box)

        tech_row.addStretch()
        layout.addLayout(tech_row)

        # Waveform minimapa del deck estilo VirtualDJ
        self.overview_waveform = DjOverviewWaveform(accent_color=accent_color, height=20)
        self.overview_waveform.seekRequested.connect(self.seekRequested)
        layout.addWidget(self.overview_waveform)

        # Barra de progreso con gradiente
        self.progress_bar = QFrame()
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setStyleSheet("""
            QFrame {
                background-color: #22222A;
                border-radius: 1px;
            }
        """)
        layout.addWidget(self.progress_bar)

    def setTrack(self, title: str, artist: str, bpm: float = None, key: str = None, on_air: bool = False, time_str: str = "-00:00", duration_ms: int = 0):
        self.title_lbl.setText(title or "Arrastra una canción en este deck para cargarlo")
        self.artist_lbl.setText(artist or "---")
        self.on_air_badge.setVisible(bool(on_air))
        self.time_lbl.setText(time_str or "-00:00")
        if bpm and bpm > 0:
            self.bpm_box.setText(f"{bpm:.1f} BPM")
        else:
            self.bpm_box.setText("--- BPM")
        if key:
            self.key_box.setText(f"KEY: {key}")
            self.key_box.setVisible(True)
        else:
            self.key_box.setText("KEY: ---")
        if duration_ms > 0:
            self.overview_waveform.setTrack(title, duration_ms)

    def updatePitchDisplay(self, rate: float, nominal_bpm: float):
        bpm = float(nominal_bpm or 128.0)
        live_bpm = bpm * rate
        pct = (rate - 1.0) * 100.0
        self.bpm_box.setText(f"{live_bpm:.1f} BPM")
        self.pitch_box.setText(f"{pct:+.2f}%")
        color = "#1ED760" if abs(pct) < 0.05 else ("#00E5FF" if pct > 0 else "#FFAA00")
        self.pitch_box.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {color}; background: transparent;")

    def setTrackProgress(self, pos_ms: int, dur_ms: int):
        self.overview_waveform.setPosition(pos_ms)
        if dur_ms > 0:
            frac = max(0.0, min(1.0, pos_ms / float(dur_ms)))
            self.progress_bar.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {self.accent_color}, stop:{frac:.3f} {self.accent_color},
                        stop:{min(1.0, frac + 0.001):.3f} #22222A, stop:1 #22222A);
                    border-radius: 2px;
                }}
            """)
            rem_ms = max(0, dur_ms - pos_ms)
            s_rem = rem_ms // 1000
            m = s_rem // 60
            s = s_rem % 60
            self.time_lbl.setText(f"-{m:02d}:{s:02d}")
        else:
            s_el = pos_ms // 1000
            m = s_el // 60
            s = s_el % 60
            self.time_lbl.setText(f"{m:02d}:{s:02d}")

    def setBadges(self, mt=None, quantize=None, slip=None, vinyl=None, loop=None, master_tempo=None):
        if master_tempo is not None:
            mt = master_tempo
        if mt is not None:
            self.badge_mt.setVisible(bool(mt))
        if quantize is not None:
            self.badge_quantize.setVisible(bool(quantize))
        if slip is not None:
            self.badge_slip.setVisible(bool(slip))
        if vinyl is not None:
            self.badge_vinyl.setVisible(bool(vinyl))
        if loop is not None:
            self.badge_loop.setVisible(bool(loop))


class DjPage(QWidget):
    start_requested = Signal()
    folder_requested = Signal()
    skip_requested = Signal()
    drop_next_requested = Signal()
    block_requested = Signal()
    reshuffle_requested = Signal()
    unblock_all_requested = Signal()
    bpm_requested = Signal(str, str)
    vote_requested = Signal(int, list)
    profile_requested = Signal(str)
    fx_changed = Signal(str, dict)
    freeze_requested = Signal(bool)
    washout_requested = Signal()
    auto_mix_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._auto_mode = True  # True: IA maneja fader/knobs; False: usuario manual
        self._current_layout_mode = None
        self._now_path = ""
        self._next_path = ""
        self._upcoming_paths = []
        self._transition_active = False
        self._meter_val_a = 0.0
        self._meter_val_b = 0.0

        # Estado físico de reproducción DJ, Cues, Loops y EQ
        self._deck_a_bpm = 128.0
        self._deck_b_bpm = 128.0
        self._cue_a_ms = 0
        self._cue_b_ms = 0
        self._hot_cues_a = [None, None, None, None]
        self._hot_cues_b = [None, None, None, None]
        self._loop_start_a = None
        self._loop_end_a = None
        self._loop_active_a = False
        self._loop_start_b = None
        self._loop_end_b = None
        self._loop_active_b = False
        self._eq_debounce_timer = None

        # Modos de transporte y hardware Pioneer CDJ
        self._quantize_a = True
        self._quantize_b = True
        self._slip_a = False
        self._slip_b = False
        self._slip_virtual_pos_a = 0
        self._slip_virtual_pos_b = 0
        self._master_tempo_a = True
        self._master_tempo_b = True
        self._rev_active_a = False
        self._rev_active_b = False
        self._rev_timer_a = None
        self._rev_timer_b = None
        self._usb_mounted_a = True
        self._usb_mounted_b = True
        self._cue_audition_a = False
        self._cue_audition_b = False
        self._blink_counter = 0

        # Mixer DJM-A9 & Monitorización
        self._xf_assign_a = "A"       # "A" | "THRU" | "B"
        self._xf_assign_b = "B"       # "A" | "THRU" | "B"
        self._cue_pfl_a = False
        self._cue_pfl_b = False
        self._master_cue = False
        self._hp_ab_mode = "A"
        self._booth_vol = 0.7
        self._hp_vol = 0.75
        self._hp_mix = 0.0
        self._subwoofer_boost = False
        self._talkover_active = False
        self._pa_muted = False
        self._booth_muted = False
        self._current_color_fx = "FILTER"
        self._channel_in_a = "USB A"
        self._channel_in_b = "USB B"
        self._upcoming_tracks_cache = []

        # Atributos de compatibilidad con versiones y pruebas anteriores
        self.empty = QWidget(self)
        self.empty.setVisible(True)
        self.session = QWidget(self)
        self.session.setVisible(False)
        self.now_title = QLabel()
        self.now_detail = QLabel()
        self.next_title = QLabel()
        self.progress = QLabel()
        self.btn_shuffle = QPushButton("Barajar")
        self.btn_shuffle.setToolTip("Cambiar el orden de las canciones")
        self.unblock_all = QPushButton("Desbloquear")
        self.btn_skip = QPushButton("Saltar")
        self.btn_skip.clicked.connect(self.skip_requested.emit)
        self.btn_drop = QPushButton("Esta no")
        self.btn_drop.clicked.connect(self.drop_next_requested.emit)
        self.btn_block = QPushButton("Bloquear")
        self.btn_block.clicked.connect(self.block_requested.emit)
        self.btn_unblock = QPushButton("Desbloquear (0)")
        self.btn_unblock.clicked.connect(self.unblock_all_requested.emit)
        self.btn_unblock.setVisible(False)
        self.bpm_buttons = [
            QPushButton("/2"), QPushButton("x2"),
            QPushButton("Escribir BPM"), QPushButton("Automático")
        ]
        self.bpm_buttons[0].clicked.connect(lambda: self.bpm_requested.emit(self._now_path, "half"))
        self.bpm_buttons[1].clicked.connect(lambda: self.bpm_requested.emit(self._now_path, "double"))
        self.bpm_buttons[2].clicked.connect(lambda: self.bpm_requested.emit(self._now_path, "set"))
        self.bpm_buttons[3].clicked.connect(lambda: self.bpm_requested.emit(self._now_path, "auto"))

        self._fx_state = {
            "filter_mode": "OFF",
            "delay_time": "OFF",
            "ping_pong": True,
            "echo_active": False,
            "freeze_active": False,
            "reverb_active": False,
        }

        self.btn_fx_filter = QPushButton("Filtro: OFF")
        self.btn_fx_delay = QPushButton("Delay: OFF")
        self.btn_fx_freeze = QPushButton("Echo Freeze")
        self.btn_fx_filter.clicked.connect(self._cycle_filter)
        self.btn_fx_delay.clicked.connect(self._cycle_delay)
        self.btn_fx_freeze.clicked.connect(self._toggle_freeze)

        # Layout principal con scroll para pantallas estrechas o resoluciones bajas
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        scroll_content = QWidget()
        scroll_lay = QVBoxLayout(scroll_content)
        scroll_lay.setContentsMargins(12, 10, 12, 14)
        scroll_lay.setSpacing(12)

        # 1. Cabecera y Barra de Control General
        self._build_top_bar(scroll_lay)

        # 2. Barra de Entorno de Cabina (Auriculares, Monitores, PA, Subwoofer, Micrófono, etc.)
        self.env_bar = DjEnvironmentBar(self)
        self.env_bar.itemTriggered.connect(self._on_env_bar_item_triggered)
        scroll_lay.addWidget(self.env_bar)

        # 2b. VISUALIZADOR SUPERIOR DE FORMAS DE ONDA DUALES Y BEAT MATCHING (ESTILO VIRTUALDJ)
        self.waveform_display = DjMasterWaveformDisplay(self)
        self.waveform_display.juntarBeatsRequested.connect(self._on_juntar_beats)
        self.waveform_display.nudgeRequested.connect(self._on_waveform_nudge)
        self.waveform_display.seekRequested.connect(self._on_waveform_seek)
        scroll_lay.addWidget(self.waveform_display)

        # 3. Chasis de la Mesa de DJ (Dual Decks + Mixer Central Pioneer DJM-A9)
        self._build_console(scroll_lay)

        # 4. Lista de Canciones Próximas & Opciones Rápidas
        self._build_bottom_tray(scroll_lay)

        scroll.setWidget(scroll_content)
        root.addWidget(scroll)

        # Timer de animación visual periódica (40 ms = 25 FPS) para platos, vúmetros y mezcla de IA
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(40)
        self._anim_timer.timeout.connect(self._on_anim_frame)
        self._anim_timer.start()

    # -------------------------------------------------------------------------------------------------
    # 1. Cabecera superior
    # -------------------------------------------------------------------------------------------------
    def _build_top_bar(self, layout):
        top_card = QFrame()
        top_card.setObjectName("PanelCard")
        top_card.setAttribute(Qt.WA_StyledBackground, True)
        top_card.setStyleSheet("""
            QFrame#PanelCard {
                background-color: #16161C;
                border: 1px solid #262632;
                border-radius: 10px;
            }
        """)
        top_lay = QVBoxLayout(top_card)
        top_lay.setContentsMargins(14, 10, 14, 10)
        top_lay.setSpacing(8)

        # Fila 1: Título e inicio de sesión
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icon("sliders.svg", "#1ED760", 28).pixmap(22, 22))
        row1.addWidget(icon_lbl)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self.title_lbl = QLabel("Mesa DJ Profesional (Pioneer CDJ-3000 & DJM-A9)")
        self.title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
        title_box.addWidget(self.title_lbl)

        self.source = QLabel("Carpeta de música...")
        self.source.setStyleSheet("font-size: 11px; color: #A0A0B0;")
        title_box.addWidget(self.source)
        row1.addLayout(title_box, 1)

        # Botones de navegación adicionales: Panel Trasero I/O y Guía de 12 Controles
        btn_rear = QPushButton("🔌 Panel Trasero (I/O)")
        btn_rear.setCursor(Qt.PointingHandCursor)
        btn_rear.setStyleSheet("""
            QPushButton {
                background-color: #1C1C28;
                color: #00E5FF;
                font-size: 11px;
                font-weight: 800;
                border: 1px solid #00E5FF;
                border-radius: 14px;
                padding: 5px 12px;
            }
            QPushButton:hover { background-color: #242436; }
        """)
        btn_rear.clicked.connect(self._open_rear_panel)
        row1.addWidget(btn_rear)

        btn_guide = QPushButton("📖 Guía Rápida (12 Controles)")
        btn_guide.setCursor(Qt.PointingHandCursor)
        btn_guide.setStyleSheet("""
            QPushButton {
                background-color: #1C1C28;
                color: #FFDD44;
                font-size: 11px;
                font-weight: 800;
                border: 1px solid #FFDD44;
                border-radius: 14px;
                padding: 5px 12px;
            }
            QPushButton:hover { background-color: #242436; }
        """)
        btn_guide.clicked.connect(self._open_quick_guide)
        row1.addWidget(btn_guide)

        # Botón grande empezar a pinchar
        self.btn_start = QPushButton(" Empezar sesión DJ")
        self.btn_start.setObjectName("GiantActionBtn")
        self.btn_start.setIcon(icon("play_black.svg", "#000000"))
        self.btn_start.setIconSize(QSize(15, 15))
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #1ED760;
                color: #000000;
                font-size: 12px;
                font-weight: 800;
                border-radius: 15px;
                padding: 6px 16px;
            }
            QPushButton:hover { background-color: #22EC6A; }
        """)
        self.btn_start.clicked.connect(self.start_requested.emit)
        row1.addWidget(self.btn_start)
        top_lay.addLayout(row1)

        # Fila 2: Selector de Modo, Perfiles y Carpeta
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self.btn_auto_mode = QPushButton(" ⚡ Auto DJ: ON")
        self.btn_auto_mode.setObjectName("TopPillBtn")
        self.btn_auto_mode.setCursor(Qt.PointingHandCursor)
        self.btn_auto_mode.setToolTip("La IA calcula y mueve el crossfader, filtros y ecualizadores sola. Pulsa para mezclar manual.")
        self.btn_auto_mode.setStyleSheet("""
            QPushButton {
                background-color: #1A3828;
                color: #1ED760;
                font-weight: 800;
                border: 1px solid #1ED760;
                border-radius: 13px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #244C36; }
        """)
        self.btn_auto_mode.clicked.connect(self._toggle_auto_mode)
        row2.addWidget(self.btn_auto_mode)

        # Selector rápido de perfiles (Club / Radio / Chill)
        self.btn_prof_club = QPushButton("⚡ Club")
        self.btn_prof_club.setCursor(Qt.PointingHandCursor)
        self.btn_prof_club.setToolTip("Mezclas largas con Mid-Carve y swap de graves")
        self.btn_prof_club.clicked.connect(lambda: self.profile_requested.emit("club"))

        self.btn_prof_radio = QPushButton("📻 Radio")
        self.btn_prof_radio.setCursor(Qt.PointingHandCursor)
        self.btn_prof_radio.setToolTip("Cortes rápidos a compás y delay drop dinámico")
        self.btn_prof_radio.clicked.connect(lambda: self.profile_requested.emit("radio"))

        self.btn_prof_chill = QPushButton("☕ Chill")
        self.btn_prof_chill.setCursor(Qt.PointingHandCursor)
        self.btn_prof_chill.setToolTip("Transiciones etéreas y washout reverb envolvente")
        self.btn_prof_chill.clicked.connect(lambda: self.profile_requested.emit("chill"))

        self._profile_buttons = {
            "club": self.btn_prof_club,
            "radio": self.btn_prof_radio,
            "chill": self.btn_prof_chill,
        }
        for b in (self.btn_prof_club, self.btn_prof_radio, self.btn_prof_chill):
            b.setObjectName("TopPillBtn")
            b.setStyleSheet("""
                QPushButton {
                    background-color: #22222A;
                    color: #CCCCCC;
                    border: 1px solid #333340;
                    border-radius: 13px;
                    padding: 4px 8px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #2D2D38; color: #FFFFFF; }
            """)
            row2.addWidget(b)

        btn_folder = QPushButton("📁 Cambiar carpeta...")
        btn_folder.setCursor(Qt.PointingHandCursor)
        btn_folder.setStyleSheet("""
            QPushButton {
                background-color: #22222A;
                color: #CCCCCC;
                border: 1px solid #333340;
                border-radius: 13px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #2D2D38; color: #FFFFFF; }
        """)
        btn_folder.clicked.connect(self.folder_requested.emit)
        row2.addWidget(btn_folder)

        row2.addStretch()
        top_lay.addLayout(row2)
        layout.addWidget(top_card)

    def _open_rear_panel(self):
        dlg = DjRearPanelDialog(self)
        dlg.exec()

    def _open_quick_guide(self):
        dlg = DjQuickReferenceGuide(self)
        dlg.exec()

    def _on_env_bar_item_triggered(self, item_id: str, title: str):
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Cabina DJ: {title} activado")

    def _toggle_auto_mode(self):
        self._auto_mode = not self._auto_mode
        if self._auto_mode:
            self.btn_auto_mode.setText(" ⚡ Auto DJ: ON")
            self.btn_auto_mode.setStyleSheet("""
                QPushButton {
                    background-color: #1A3828;
                    color: #1ED760;
                    font-weight: 800;
                    border: 1px solid #1ED760;
                    border-radius: 13px;
                    padding: 4px 10px;
                    font-size: 11px;
                }
                QPushButton:hover { background-color: #244C36; }
            """)
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify("Modo Auto DJ activado: la IA maneja las mezclas y controles físicos.")
        else:
            self.btn_auto_mode.setText(" 🖐️ Manual DJ")
            self.btn_auto_mode.setStyleSheet("""
                QPushButton {
                    background-color: #382A1A;
                    color: #FFAA33;
                    font-weight: 800;
                    border: 1px solid #FFAA33;
                    border-radius: 13px;
                    padding: 4px 10px;
                    font-size: 11px;
                }
                QPushButton:hover { background-color: #4C3824; }
            """)
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify("Modo Manual: usa el crossfader y los knobs para mezclar a tu gusto.")

    # -------------------------------------------------------------------------------------------------
    # 2. Chasis de la Mesa de DJ (Dual Decks + Mixer Central Adaptativo)
    # -------------------------------------------------------------------------------------------------
    def _build_console(self, layout):
        self.console_box = QFrame()
        self.console_box.setObjectName("DjConsoleChassis")
        self.console_box.setStyleSheet("""
            QFrame#DjConsoleChassis {
                background-color: #101014;
                border: 2px solid #202028;
                border-radius: 14px;
            }
        """)
        self.console_box_layout = QVBoxLayout(self.console_box)
        self.console_box_layout.setContentsMargins(10, 10, 10, 10)
        self.console_box_layout.setSpacing(8)

        # ===== PLATO A (IZQUIERDA - ESTILO VIRTUALDJ CYAN) =====
        self.deck_a_frame = self._build_deck_side("DECK A", "#00D2FF", is_deck_a=True)

        # ===== MEZCLADOR CENTRAL (MIXER DJM-A9 & CROSSFADER) =====
        self.mixer_frame = self._build_mixer_center()

        # ===== PLATO B (DERECHA - ESTILO VIRTUALDJ ROJO NEON) =====
        self.deck_b_frame = self._build_deck_side("DECK B", "#FF3344", is_deck_a=False)

        # Inicializar en modo adaptativo según el ancho actual
        self._apply_responsive_layout(self.width() or 1000)

        layout.addWidget(self.console_box)

    def _build_deck_side(self, name: str, accent: str, is_deck_a: bool) -> QWidget:
        deck_code = "A" if is_deck_a else "B"
        frame = QFrame()
        frame.setAcceptDrops(True)
        frame.dragEnterEvent = lambda e: e.acceptProposedAction() if (e.mimeData().hasUrls() or e.mimeData().hasText()) else None
        frame.dragMoveEvent = lambda e: e.acceptProposedAction() if (e.mimeData().hasUrls() or e.mimeData().hasText()) else None
        frame.dropEvent = lambda e, d=deck_code: self._on_deck_drop(d, e)
        frame.setStyleSheet("""
            QFrame {
                background-color: #14141A;
                border: 1px solid #22222D;
                border-radius: 10px;
            }
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # 1. Barra superior del CDJ: USB Port, Eject, Load, Browse, Menu, Back
        top_nav = QHBoxLayout()
        top_nav.setSpacing(3)

        usb_btn = QPushButton(f"● USB {1 if is_deck_a else 2}")
        usb_btn.setCursor(Qt.PointingHandCursor)
        usb_btn.setStyleSheet("QPushButton { min-width: 0px; font-size: 8px; font-weight: 900; color: #00FF66; background: #0E2214; border: 1px solid #00FF66; border-radius: 3px; padding: 2px 4px; }")
        usb_btn.clicked.connect(lambda _=False, d=deck_code: self._on_usb_clicked(d))
        top_nav.addWidget(usb_btn)

        btn_eject = QPushButton("EJECT")
        btn_eject.setCursor(Qt.PointingHandCursor)
        btn_eject.setStyleSheet("QPushButton { min-width: 0px; background-color: #1F1F2A; color: #999; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 2px 4px; }")
        btn_eject.clicked.connect(lambda _=False, d=deck_code: self._on_eject_clicked(d))
        top_nav.addWidget(btn_eject)

        btn_load = QPushButton("LOAD")
        btn_load.setCursor(Qt.PointingHandCursor)
        btn_load.setStyleSheet(f"QPushButton {{ min-width: 0px; background-color: #262638; color: {accent}; font-size: 8px; font-weight: 900; border: 1px solid {accent}; border-radius: 3px; padding: 2px 5px; }}")
        btn_load.clicked.connect(lambda _=False, a=is_deck_a: self._on_load_clicked(a))
        top_nav.addWidget(btn_load)

        btn_browse = QPushButton("BROWSE")
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.setStyleSheet("QPushButton { min-width: 0px; background-color: #1F1F2A; color: #BBB; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 2px 4px; }")
        btn_browse.clicked.connect(lambda _=False, d=deck_code: self._on_browse_clicked(d))
        top_nav.addWidget(btn_browse)

        btn_menu = QPushButton("MENU")
        btn_menu.setCursor(Qt.PointingHandCursor)
        btn_menu.setStyleSheet("QPushButton { min-width: 0px; background-color: #1F1F2A; color: #888; font-size: 8px; border-radius: 3px; padding: 2px 4px; }")
        btn_menu.clicked.connect(lambda _=False, d=deck_code: self._on_menu_clicked(d))
        top_nav.addWidget(btn_menu)

        btn_back = QPushButton("BACK")
        btn_back.setCursor(Qt.PointingHandCursor)
        btn_back.setStyleSheet("QPushButton { min-width: 0px; background-color: #1F1F2A; color: #888; font-size: 8px; border-radius: 3px; padding: 2px 4px; }")
        btn_back.clicked.connect(lambda _=False, d=deck_code: self._on_back_clicked(d))
        top_nav.addWidget(btn_back)

        lay.addLayout(top_nav)

        # 2. Pantalla digital del deck (DeckScreen) con waveform overview y búsqueda de compás
        screen = DeckScreen(name, accent)
        screen.seekRequested.connect(lambda pos, a=is_deck_a: self._on_waveform_seek(a, pos))
        if is_deck_a:
            self.screen_a = screen
        else:
            self.screen_b = screen
        lay.addWidget(screen)

        # 3. Fila de modos y controles de pista (Quantize, Slip, Rev, Vinyl, Sync, Master Tempo)
        modes_row = QHBoxLayout()
        modes_row.setSpacing(3)

        btn_quantize = QPushButton("QUANTIZE")
        btn_quantize.setCursor(Qt.PointingHandCursor)
        btn_quantize.setStyleSheet("QPushButton { min-width: 0px; background-color: #FF3344; color: #000000; font-size: 8px; font-weight: 900; border: 1.5px solid #FFFFFF; border-radius: 3px; padding: 2px 4px; }")
        btn_quantize.clicked.connect(lambda _=False, d=deck_code: self._toggle_quantize(d))

        btn_slip = QPushButton("SLIP")
        btn_slip.setCursor(Qt.PointingHandCursor)
        btn_slip.setStyleSheet("QPushButton { min-width: 0px; background-color: #332010; color: #FF8822; font-size: 8px; font-weight: 900; border: 1px solid #FF8822; border-radius: 3px; padding: 2px 4px; }")
        btn_slip.clicked.connect(lambda _=False, d=deck_code: self._toggle_slip(d))

        btn_rev = QPushButton("REV")
        btn_rev.setCursor(Qt.PointingHandCursor)
        btn_rev.setStyleSheet("QPushButton { min-width: 0px; background-color: #20202E; color: #AAA; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 2px 4px; }")
        btn_rev.clicked.connect(lambda _=False, d=deck_code: self._toggle_reverse(d))

        btn_vinyl = QPushButton("VINYL")
        btn_vinyl.setCursor(Qt.PointingHandCursor)
        btn_vinyl.setStyleSheet("QPushButton { min-width: 0px; background-color: #152238; color: #00D2FF; font-size: 8px; font-weight: 900; border: 1px solid #00D2FF; border-radius: 3px; padding: 2px 4px; }")
        btn_vinyl.clicked.connect(lambda _=False, a=is_deck_a, b=btn_vinyl: self._toggle_vinyl_mode(a, b))

        btn_mt = QPushButton("MASTER TEMPO")
        btn_mt.setCursor(Qt.PointingHandCursor)
        btn_mt.setStyleSheet("QPushButton { min-width: 0px; background-color: #15331F; color: #22EC6A; font-size: 8px; font-weight: 900; border: 1px solid #22EC6A; border-radius: 3px; padding: 2px 4px; }")
        btn_mt.clicked.connect(lambda _=False, d=deck_code: self._toggle_master_tempo(d))

        modes_row.addWidget(btn_quantize)
        modes_row.addWidget(btn_slip)
        modes_row.addWidget(btn_rev)
        modes_row.addWidget(btn_vinyl)
        modes_row.addWidget(btn_mt)
        lay.addLayout(modes_row)

        # 4. Sección central del plato: Jog Wheel giratorio + Pitch Fader de Tempo
        center_row = QHBoxLayout()
        center_row.setSpacing(6)

        jog = DjJogWheel(name, accent)
        if is_deck_a:
            self.jog_a = jog
            jog.scratched.connect(self._on_jog_a_scratched)
            jog.nudged.connect(self._on_jog_a_nudged)
        else:
            self.jog_b = jog
            jog.scratched.connect(self._on_jog_b_scratched)
            jog.nudged.connect(self._on_jog_b_nudged)
        center_row.addWidget(jog, 1)

        # Columna lateral derecha: Pitch / Tempo Fader con Nudge Bend (+ / -)
        pitch_box = QVBoxLayout()
        pitch_box.setSpacing(2)
        pitch_lbl = QLabel("PITCH")
        pitch_lbl.setStyleSheet("font-size: 8px; font-weight: 900; color: #888899; letter-spacing: 0.5px;")
        pitch_lbl.setAlignment(Qt.AlignCenter)
        pitch_box.addWidget(pitch_lbl)

        btn_bend_up = QPushButton("+")
        btn_bend_up.setToolTip("Pitch Bend + (acelerar compás)")
        btn_bend_up.setCursor(Qt.PointingHandCursor)
        btn_bend_up.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A22; color: #AAA; font-size: 9px; font-weight: bold; border-radius: 3px; padding: 2px 4px; }")

        pitch_fader = DjPitchFader(label="TEMPO", accent_color=accent)
        if is_deck_a:
            self.pitch_a = pitch_fader
            pitch_fader.rateChanged.connect(self._on_pitch_a_rate_changed)
        else:
            self.pitch_b = pitch_fader
            pitch_fader.rateChanged.connect(self._on_pitch_b_rate_changed)

        btn_pitch_reset = QPushButton("0.0%")
        btn_pitch_reset.setCursor(Qt.PointingHandCursor)
        btn_pitch_reset.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A22; color: #AAA; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 2px 4px; }")
        btn_pitch_reset.clicked.connect(pitch_fader.resetPitch)

        btn_bend_down = QPushButton("-")
        btn_bend_down.setToolTip("Pitch Bend - (frenar compás)")
        btn_bend_down.setCursor(Qt.PointingHandCursor)
        btn_bend_down.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A22; color: #AAA; font-size: 9px; font-weight: bold; border-radius: 3px; padding: 2px 4px; }")

        btn_bend_up.pressed.connect(lambda f=pitch_fader: f.setValue(f.value + 0.15))
        btn_bend_up.released.connect(lambda f=pitch_fader: f.setValue(f.value - 0.15))
        btn_bend_down.pressed.connect(lambda f=pitch_fader: f.setValue(f.value - 0.15))
        btn_bend_down.released.connect(lambda f=pitch_fader: f.setValue(f.value + 0.15))

        pitch_box.addWidget(btn_bend_up)
        pitch_box.addWidget(pitch_fader)
        pitch_box.addWidget(btn_pitch_reset)
        pitch_box.addWidget(btn_bend_down)

        center_row.addLayout(pitch_box)
        lay.addLayout(center_row)

        # 5. Sección de rendimiento: Loops, Beat Jump, Hot Cues y Transporte
        perf_box = QVBoxLayout()
        perf_box.setSpacing(4)

        # 5a. Beat Loop Controls (In/4Beat, Out, Reloop, 1/2X, 2X) + Beat Jump
        loop_jump_row = QHBoxLayout()
        loop_jump_row.setSpacing(4)
        loop_ctrl = DjLoopControls()
        if is_deck_a:
            self.loop_a = loop_ctrl
        else:
            self.loop_b = loop_ctrl
        loop_ctrl.loopInRequested.connect(lambda: self._on_loop_in("A" if is_deck_a else "B"))
        loop_ctrl.loopOutRequested.connect(lambda: self._on_loop_out("A" if is_deck_a else "B"))
        loop_ctrl.reloopRequested.connect(lambda: self._on_reloop("A" if is_deck_a else "B"))
        loop_ctrl.halfLoopRequested.connect(lambda: self._on_half_loop("A" if is_deck_a else "B"))
        loop_ctrl.doubleLoopRequested.connect(lambda: self._on_double_loop("A" if is_deck_a else "B"))
        loop_jump_row.addWidget(loop_ctrl, 1)

        btn_jump_back = QPushButton("<< 1")
        btn_jump_back.setCursor(Qt.PointingHandCursor)
        btn_jump_back.setStyleSheet("QPushButton { min-width: 0px; background-color: #20202E; color: #00E5FF; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 3px 4px; }")
        btn_jump_back.clicked.connect(lambda _=False, a=is_deck_a: self._on_beat_jump(a, -1))

        btn_jump_fwd = QPushButton("1 >>")
        btn_jump_fwd.setCursor(Qt.PointingHandCursor)
        btn_jump_fwd.setStyleSheet("QPushButton { min-width: 0px; background-color: #20202E; color: #00E5FF; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 3px 4px; }")
        btn_jump_fwd.clicked.connect(lambda _=False, a=is_deck_a: self._on_beat_jump(a, 1))

        loop_jump_row.addWidget(btn_jump_back)
        loop_jump_row.addWidget(btn_jump_fwd)
        perf_box.addLayout(loop_jump_row)

        # 5b. Hot Cue Pads (6 pads RGB estilo VirtualDJ)
        hot_pads = DjHotCuePads(accent_color=accent)
        if is_deck_a:
            self.pads_a = hot_pads
        else:
            self.pads_b = hot_pads
        hot_pads.padTriggered.connect(lambda idx, mode, a=is_deck_a: self._on_pad_action(a, idx, mode))
        hot_pads.padCleared.connect(lambda idx, a=is_deck_a: self._on_pad_cleared(a, idx))
        perf_box.addWidget(hot_pads)

        # 5c. Botones de transporte principales VirtualDJ: CUE, PAUSE, PLAY, SYNC
        transport_row = QHBoxLayout()
        transport_row.setSpacing(4)

        btn_cue = QPushButton("CUE")
        btn_cue.setCursor(Qt.PointingHandCursor)
        btn_cue.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #382A1A;
                color: #FFAA33;
                font-weight: 900;
                border: 2px solid #FFAA33;
                border-radius: 6px;
                padding: 6px 6px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #4C3824; }
        """)

        btn_pause = QPushButton("❚❚")
        btn_pause.setToolTip("Pausar reproducción")
        btn_pause.setCursor(Qt.PointingHandCursor)
        btn_pause.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #22222E;
                color: #FFFFFF;
                font-weight: 900;
                border: 2px solid #555566;
                border-radius: 6px;
                padding: 6px 6px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #333345; }
        """)

        btn_play = QPushButton("▶")
        btn_play.setToolTip("Iniciar reproducción")
        btn_play.setCursor(Qt.PointingHandCursor)
        btn_play.setStyleSheet(f"""
            QPushButton {{
                min-width: 0px;
                background-color: #0E2214;
                color: {accent};
                font-weight: 900;
                border: 2px solid {accent};
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #163620; }}
        """)

        btn_sync = QPushButton("SYNC")
        btn_sync.setToolTip("Sincronizar BPM y compás con el otro deck")
        btn_sync.setCursor(Qt.PointingHandCursor)
        btn_sync.setStyleSheet(f"""
            QPushButton {{
                min-width: 0px;
                background-color: #122030;
                color: {accent};
                font-weight: 900;
                border: 2px solid {accent};
                border-radius: 6px;
                padding: 6px 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #1C3048; }}
        """)

        if is_deck_a:
            self.btn_usb_a = usb_btn
            self.btn_eject_a = btn_eject
            self.btn_load_a = btn_load
            self.btn_browse_a = btn_browse
            self.btn_menu_a = btn_menu
            self.btn_back_a = btn_back
            self.btn_quantize_a = btn_quantize
            self.btn_slip_a = btn_slip
            self.btn_rev_a = btn_rev
            self.btn_vinyl_a = btn_vinyl
            self.btn_mt_a = btn_mt
            self.btn_pitch_reset_a = btn_pitch_reset
            self.btn_bend_up_a = btn_bend_up
            self.btn_bend_down_a = btn_bend_down
            self.btn_jump_back_a = btn_jump_back
            self.btn_jump_fwd_a = btn_jump_fwd
            self.btn_play_a, self.btn_pause_a, self.btn_cue_a, self.btn_sync_a = btn_play, btn_pause, btn_cue, btn_sync

            btn_play.clicked.connect(self._on_play_a_clicked)
            btn_pause.clicked.connect(self._on_pause_a_clicked)
            btn_cue.pressed.connect(lambda: self._on_cue_pressed("A"))
            btn_cue.released.connect(lambda: self._on_cue_released("A"))
            btn_cue.clicked.connect(lambda: self._on_cue_clicked("A"))
            btn_sync.clicked.connect(lambda: self._on_sync_clicked("A"))
        else:
            self.btn_usb_b = usb_btn
            self.btn_eject_b = btn_eject
            self.btn_load_b = btn_load
            self.btn_browse_b = btn_browse
            self.btn_menu_b = btn_menu
            self.btn_back_b = btn_back
            self.btn_quantize_b = btn_quantize
            self.btn_slip_b = btn_slip
            self.btn_rev_b = btn_rev
            self.btn_vinyl_b = btn_vinyl
            self.btn_mt_b = btn_mt
            self.btn_pitch_reset_b = btn_pitch_reset
            self.btn_bend_up_b = btn_bend_up
            self.btn_bend_down_b = btn_bend_down
            self.btn_jump_back_b = btn_jump_back
            self.btn_jump_fwd_b = btn_jump_fwd
            self.btn_play_b, self.btn_pause_b, self.btn_cue_b, self.btn_sync_b = btn_play, btn_pause, btn_cue, btn_sync

            btn_play.clicked.connect(self._on_play_b_clicked)
            btn_pause.clicked.connect(self._on_pause_b_clicked)
            btn_cue.pressed.connect(lambda: self._on_cue_pressed("B"))
            btn_cue.released.connect(lambda: self._on_cue_released("B"))
            btn_cue.clicked.connect(lambda: self._on_cue_clicked("B"))
            btn_sync.clicked.connect(lambda: self._on_sync_clicked("B"))

        transport_row.addWidget(btn_cue, 1)
        transport_row.addWidget(btn_pause, 1)
        transport_row.addWidget(btn_play, 2)
        transport_row.addWidget(btn_sync, 1)
        perf_box.addLayout(transport_row)

        lay.addLayout(perf_box)
        return frame

    def _build_mixer_center(self) -> QWidget:
        self.mixer_frame = QFrame()
        self.mixer_frame.setStyleSheet("""
            QFrame {
                background-color: #121217;
                border: 1px solid #1E1E26;
                border-radius: 10px;
            }
        """)
        self.mixer_layout = QVBoxLayout(self.mixer_frame)
        self.mixer_layout.setContentsMargins(8, 8, 8, 8)
        self.mixer_layout.setSpacing(6)

        # Cabecera del Mixer
        self.mixer_cap = QLabel("PIONEER DJM-A9 4CH MIXER")
        self.mixer_cap.setStyleSheet("font-size: 10px; font-weight: 900; color: #FFFFFF; letter-spacing: 1.5px;")
        self.mixer_cap.setAlignment(Qt.AlignCenter)

        # HUD de estado de mezcla (IA)
        self.hud_frame = QFrame()
        self.hud_frame.setStyleSheet("""
            QFrame {
                background-color: #0E0E14;
                border: 1px solid #1A1A24;
                border-radius: 6px;
            }
        """)
        self.hud_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        hud_lay = QVBoxLayout(self.hud_frame)
        hud_lay.setContentsMargins(8, 6, 8, 6)
        hud_lay.setSpacing(2)

        self.hud_tag = QLabel("ESTADO DE MEZCLA (IA)")
        self.hud_tag.setStyleSheet("font-size: 9px; font-weight: 800; color: #00E5FF; letter-spacing: 1px;")
        hud_lay.addWidget(self.hud_tag)

        self.countdown = QLabel("Esperando inicio de sesión...")
        self.countdown.setStyleSheet("font-size: 12px; font-weight: 700; color: #FFFFFF;")
        self.countdown.setWordWrap(True)
        hud_lay.addWidget(self.countdown)

        self.hud_detail = QLabel("Sincronizado al compás")
        self.hud_detail.setStyleSheet("font-size: 10px; color: #888899;")
        self.hud_detail.setWordWrap(True)
        hud_lay.addWidget(self.hud_detail)

        # Canales de ecualización Ch 1 (Deck A Cyan) y Ch 2 (Deck B Red)
        self.ch1_strip = self._build_channel_strip(is_deck_a=True, accent="#00D2FF")
        self.ch2_strip = self._build_channel_strip(is_deck_a=False, accent="#FF3344")

        # Vúmetro Máster Central
        self.vu_master = DjVuMeter()

        # Sound Color FX Selector Panel
        self.color_fx_selector = DjColorFxSelector()
        self.color_fx_selector.colorFxChanged.connect(self._on_color_fx_selected)

        # Beat FX Rack
        self.beat_fx_rack = DjBeatFxRack()
        self.beat_fx_rack.fxChanged.connect(self._on_beat_fx_changed)
        self.beat_fx_rack.fxToggled.connect(self._on_beat_fx_toggled)

        # Master & Headphone Monitor Section
        self.monitor_section = DjMasterMonitorSection()
        self.monitor_section.masterVolumeChanged.connect(self._on_master_vol_changed)
        self.monitor_section.boothVolumeChanged.connect(self._on_booth_vol_changed)
        self.monitor_section.hpLevelChanged.connect(self._on_hp_level_changed)
        self.monitor_section.hpMixChanged.connect(self._on_hp_mix_changed)
        self.monitor_section.cueToggled.connect(self._on_monitor_cue_toggled)
        self.monitor_section.hpAbToggled.connect(self._on_hp_ab_toggled)

        # Botón gigante MEZCLAR AHORA (IA)
        self.btn_auto_mix = QPushButton("⚡ MEZCLAR AHORA")
        self.btn_auto_mix.setCursor(Qt.PointingHandCursor)
        self.btn_auto_mix.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #E60045;
                color: #FFFFFF;
                font-size: 12px;
                font-weight: 900;
                letter-spacing: 0.5px;
                border-radius: 8px;
                padding: 8px 10px;
                border: none;
            }
            QPushButton:hover { background-color: #FF1A5E; }
            QPushButton:pressed { background-color: #CC003D; }
        """)
        self.btn_auto_mix.setToolTip("Dispara la transición inmediatamente al compás con punto de cue, filtros y ecualización profesional.")
        self.btn_auto_mix.clicked.connect(self._on_auto_mix_clicked)

        # CROSSFADER INTERACTIVO
        self.xf_cap = QLabel("CROSSFADER (PLATO A ◀━━━▶ PLATO B)")
        self.xf_cap.setStyleSheet("font-size: 9px; font-weight: 800; color: #888899; letter-spacing: 1px;")
        self.xf_cap.setAlignment(Qt.AlignCenter)

        self.crossfader = DjCrossfader()
        self.crossfader.positionChanged.connect(self._on_crossfader_moved)

        # Botones rápidos de ayuda
        self.quick_btns_box = QWidget()
        quick_btns = QHBoxLayout(self.quick_btns_box)
        quick_btns.setContentsMargins(0, 0, 0, 0)
        quick_btns.setSpacing(6)
        btn_drop = QPushButton("Salto Beat")
        btn_drop.setCursor(Qt.PointingHandCursor)
        btn_drop.setStyleSheet("QPushButton { min-width: 0px; background-color: #22222A; color: #CCC; font-size: 11px; border-radius: 5px; padding: 5px 8px; }")
        btn_drop.clicked.connect(self.skip_requested.emit)

        btn_freeze = QPushButton("Echo Freeze")
        btn_freeze.setCursor(Qt.PointingHandCursor)
        btn_freeze.setStyleSheet("QPushButton { min-width: 0px; background-color: #22222A; color: #CCC; font-size: 11px; border-radius: 5px; padding: 5px 8px; }")
        btn_freeze.clicked.connect(lambda: self.freeze_requested.emit(True))

        quick_btns.addWidget(btn_drop)
        quick_btns.addWidget(btn_freeze)

        return self.mixer_frame

    def _build_channel_strip(self, is_deck_a: bool, accent: str) -> QWidget:
        """Construye una tira de canal completa DJM-A9: Input Selector, Trim, 3-Band EQ, Color FX, Filter, Cue, Fader, VU, XF Assign."""
        strip = QFrame()
        strip.setStyleSheet("background-color: #101016; border: 1px solid #1E1E28; border-radius: 6px;")
        lay = QVBoxLayout(strip)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)

        # Input selector (USB A/B, LINE, PHONO)
        combo_in = QComboBox()
        combo_in.addItems(["USB A", "USB B", "LINE", "PHONO"])
        combo_in.setCurrentText("USB A" if is_deck_a else "USB B")
        combo_in.setStyleSheet("QComboBox { background-color: #181822; color: #AAA; font-size: 8px; border: 1px solid #282835; border-radius: 3px; padding: 1px 2px; }")
        combo_in.currentTextChanged.connect(lambda txt, a=is_deck_a: self._on_channel_input_changed(a, txt))
        lay.addWidget(combo_in)

        # Trim / Gain Knob
        trim = DjRotaryKnob("TRIM", -1.0, 1.0, 0.0, accent_color=accent, bipolar=True, unit="dB")
        lay.addWidget(trim)

        # 3-Band EQ (HI, MID, LOW con kill)
        hi = DjRotaryKnob("HI", -1.0, 1.0, 0.0, accent_color=accent, bipolar=True, unit="dB")
        mid = DjRotaryKnob("MID", -1.0, 1.0, 0.0, accent_color=accent, bipolar=True, unit="dB")
        low = DjRotaryKnob("LOW", -1.0, 1.0, 0.0, accent_color=accent, bipolar=True, unit="dB")
        lay.addWidget(hi)
        lay.addWidget(mid)
        lay.addWidget(low)

        # Sound Color FX / Filter
        color_fx = DjRotaryKnob("COLOR", -1.0, 1.0, 0.0, accent_color="#00D2FF" if is_deck_a else "#FF0055", bipolar=True, unit="%")
        lay.addWidget(color_fx)

        # Cue / PFL botón
        btn_cue = QPushButton(f"CUE CH{1 if is_deck_a else 2}")
        btn_cue.setCursor(Qt.PointingHandCursor)
        btn_cue.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #2D2010;
                color: #FFAA33;
                font-size: 8px;
                font-weight: 800;
                border: 1px solid #FFAA33;
                border-radius: 3px;
                padding: 2px 4px;
            }
            QPushButton:hover { background-color: #443018; }
        """)
        btn_cue.clicked.connect(lambda _=False, a=is_deck_a: self._on_ch_cue_clicked(a))
        lay.addWidget(btn_cue)

        # Fader de canal + Vúmetro estéreo
        fader_row = QHBoxLayout()
        fader_row.setSpacing(2)
        fader = DjFader(f"CH {1 if is_deck_a else 2}", accent_color=accent)
        vu = DjVuMeter()
        fader_row.addWidget(fader)
        fader_row.addWidget(vu)
        lay.addLayout(fader_row)

        # Conectar controles a la cadena de audio real
        trim.valueChanged.connect(lambda _: self._apply_audio_gains())
        hi.valueChanged.connect(self._on_eq_control_changed)
        mid.valueChanged.connect(self._on_eq_control_changed)
        low.valueChanged.connect(self._on_eq_control_changed)
        color_fx.valueChanged.connect(self._on_eq_control_changed)
        fader.valueChanged.connect(lambda _: self._apply_audio_gains())

        # Crossfader Assign (A / THRU / B)
        default_xf = 'A' if is_deck_a else 'B'
        xf_assign = QPushButton(f"XF: {default_xf}")
        xf_assign.setCursor(Qt.PointingHandCursor)
        xf_assign.setStyleSheet("QPushButton { min-width: 0px; background-color: #181822; color: #888; font-size: 8px; border-radius: 2px; padding: 1px 3px; }")
        xf_assign.clicked.connect(lambda _, a=is_deck_a: self._on_xf_assign_clicked(a))
        lay.addWidget(xf_assign)

        if is_deck_a:
            self.combo_in_a = combo_in
            self.btn_cue_ch1 = btn_cue
            self.btn_xf_assign_a = xf_assign
            self.knob_trim_a = trim
            self.knob_high_a, self.knob_mid_a, self.knob_low_a = hi, mid, low
            self.knob_filter_a = color_fx
            self.fader_a, self.vu_a = fader, vu
        else:
            self.combo_in_b = combo_in
            self.btn_cue_ch2 = btn_cue
            self.btn_xf_assign_b = xf_assign
            self.knob_trim_b = trim
            self.knob_high_b, self.knob_mid_b, self.knob_low_b = hi, mid, low
            self.knob_filter_b = color_fx
            self.fader_b, self.vu_b = fader, vu

        return strip

    def _rebuild_mixer(self, is_wide: bool):
        """Adapta la disposición interna del mezclador central según la pantalla."""
        while self.mixer_layout.count():
            item = self.mixer_layout.takeAt(0)
            sub = item.layout()
            if sub:
                while sub.count():
                    sub.takeAt(0)

        self.mixer_layout.addWidget(self.mixer_cap)
        self.mixer_layout.addWidget(self.hud_frame)

        if is_wide:
            self.mixer_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

            # En modo ancho: disposición en columnas paralelas [ Ch 1 Strip | Center FX & VU | Ch 2 Strip ]
            ch_row = QHBoxLayout()
            ch_row.setSpacing(6)
            ch_row.addWidget(self.ch1_strip, 1)

            center_col = QVBoxLayout()
            center_col.setSpacing(4)
            vu_sub = QHBoxLayout()
            vu_sub.addStretch()
            vu_sub.addWidget(self.vu_master)
            vu_sub.addStretch()
            center_col.addLayout(vu_sub)
            center_col.addWidget(self.color_fx_selector)
            center_col.addWidget(self.beat_fx_rack)
            center_col.addWidget(self.monitor_section)
            center_col.addWidget(self.btn_auto_mix)
            ch_row.addLayout(center_col, 2)

            ch_row.addWidget(self.ch2_strip, 1)
            self.mixer_layout.addLayout(ch_row)

            self.mixer_layout.addWidget(self.xf_cap)
            self.mixer_layout.addWidget(self.crossfader)
            self.mixer_layout.addWidget(self.quick_btns_box)
        else:
            self.mixer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            # En modo compacto: disposición optimizada en 2 niveles
            ch_row = QHBoxLayout()
            ch_row.setSpacing(6)
            ch_row.addWidget(self.ch1_strip, 1)

            compact_center = QVBoxLayout()
            compact_center.setSpacing(3)
            compact_center.addWidget(self.color_fx_selector)
            compact_center.addWidget(self.beat_fx_rack)
            compact_center.addWidget(self.monitor_section)
            ch_row.addLayout(compact_center, 2)

            ch_row.addWidget(self.ch2_strip, 1)
            self.mixer_layout.addLayout(ch_row)

            self.mixer_layout.addWidget(self.btn_auto_mix)
            self.mixer_layout.addWidget(self.xf_cap)
            self.mixer_layout.addWidget(self.crossfader)
            self.mixer_layout.addWidget(self.quick_btns_box)

    def _apply_responsive_layout(self, width: int):
        """Conmuta dinámicamente entre modo apaisado completo (3 columnas) y compacto (2 niveles)."""
        target_mode = "wide" if width >= 940 else "compact"
        if self._current_layout_mode == target_mode:
            return
        self._current_layout_mode = target_mode

        while self.console_box_layout.count():
            item = self.console_box_layout.takeAt(0)
            sub_lay = item.layout()
            if sub_lay:
                while sub_lay.count():
                    sub_lay.takeAt(0)

        self._rebuild_mixer(is_wide=(target_mode == "wide"))

        if target_mode == "wide":
            wide_row = QHBoxLayout()
            wide_row.setContentsMargins(0, 0, 0, 0)
            wide_row.setSpacing(10)
            wide_row.addWidget(self.deck_a_frame, 3)
            wide_row.addWidget(self.mixer_frame, 3)
            wide_row.addWidget(self.deck_b_frame, 3)
            self.console_box_layout.addLayout(wide_row)
        else:
            decks_row = QHBoxLayout()
            decks_row.setContentsMargins(0, 0, 0, 0)
            decks_row.setSpacing(8)
            decks_row.addWidget(self.deck_a_frame, 1)
            decks_row.addWidget(self.deck_b_frame, 1)
            self.console_box_layout.addLayout(decks_row)

            self.console_box_layout.addWidget(self.mixer_frame)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = self.width()
        if w > 50:
            self._apply_responsive_layout(w)

    def showEvent(self, event):
        super().showEvent(event)
        w = self.width()
        if w > 50:
            self._apply_responsive_layout(w)

    # -------------------------------------------------------------------------------------------------
    # 3. Lista inferior de canciones y cola de sesión
    # -------------------------------------------------------------------------------------------------
    def _build_bottom_tray(self, layout):
        tray_card = QFrame()
        tray_card.setObjectName("PanelCard")
        tray_card.setAttribute(Qt.WA_StyledBackground, True)
        tray_card.setStyleSheet("""
            QFrame#PanelCard {
                background-color: #14141A;
                border: 1px solid #22222D;
                border-radius: 10px;
            }
        """)
        tray_lay = QVBoxLayout(tray_card)
        tray_lay.setContentsMargins(14, 10, 14, 10)
        tray_lay.setSpacing(8)

        head_row = QHBoxLayout()
        tray_title = QLabel("PRÓXIMAS PISTAS DE LA SESIÓN DJ")
        tray_title.setStyleSheet("font-size: 11px; font-weight: 900; color: #FFFFFF; letter-spacing: 1px;")
        head_row.addWidget(tray_title)
        head_row.addStretch()

        btn_drop = QPushButton("Quitar siguiente")
        btn_drop.setCursor(Qt.PointingHandCursor)
        btn_drop.setStyleSheet("QPushButton { min-width: 0px; background-color: #22222E; color: #CCC; font-size: 10px; border-radius: 4px; padding: 3px 6px; }")
        btn_drop.clicked.connect(self.drop_next_requested.emit)

        btn_block = QPushButton("Bloquear actual")
        btn_block.setCursor(Qt.PointingHandCursor)
        btn_block.setStyleSheet("QPushButton { min-width: 0px; background-color: #381A1A; color: #FF6666; font-size: 10px; border-radius: 4px; padding: 3px 6px; }")
        btn_block.clicked.connect(self.block_requested.emit)

        btn_reshuffle = QPushButton("Reordenar cola")
        btn_reshuffle.setCursor(Qt.PointingHandCursor)
        btn_reshuffle.setStyleSheet("QPushButton { min-width: 0px; background-color: #22222E; color: #CCC; font-size: 10px; border-radius: 4px; padding: 3px 6px; }")
        btn_reshuffle.clicked.connect(self.reshuffle_requested.emit)

        head_row.addWidget(btn_drop)
        head_row.addWidget(btn_block)
        head_row.addWidget(btn_reshuffle)
        tray_lay.addLayout(head_row)

        self.upcoming_list = QListWidget()
        self.upcoming = self.upcoming_list
        self.upcoming_list.setStyleSheet("""
            QListWidget {
                background-color: #0E0E14;
                border: 1px solid #1C1C24;
                border-radius: 6px;
                color: #CCCCCC;
                font-size: 11px;
                padding: 4px;
            }
            QListWidget::item { padding: 4px; border-radius: 4px; }
            QListWidget::item:hover { background-color: #1A1A26; color: #FFFFFF; }
        """)
        self.upcoming_list.setFixedHeight(75)
        self.upcoming = self.upcoming_list
        tray_lay.addWidget(self.upcoming_list)

        # EXPLORADOR / BIBLIOTECA INTEGRADA (ESTILO VIRTUALDJ)
        self.virtual_browser = DjVirtualBrowser(parent_window=self.main_window, parent=self)
        self.virtual_browser.loadDeckRequested.connect(self._on_browser_load_deck)
        tray_lay.addWidget(self.virtual_browser)

        vote_row = QHBoxLayout()
        vote_row.setSpacing(8)
        lbl_vote = QLabel("Votar última mezcla:")
        lbl_vote.setStyleSheet("font-size: 11px; font-weight: bold; color: #FFFFFF;")
        vote_row.addWidget(lbl_vote)

        self.btn_up = QPushButton("👍 Me ha gustado")
        self.btn_up.setCursor(Qt.PointingHandCursor)
        self.btn_up.setStyleSheet("QPushButton { background-color: #1A3828; color: #1ED760; font-weight: bold; border-radius: 5px; padding: 4px 8px; font-size: 11px; }")
        self.btn_up.clicked.connect(lambda: self.vote_requested.emit(1, []))
        vote_row.addWidget(self.btn_up)

        self.btn_down = QPushButton("👎 No me ha gustado...")
        self.btn_down.setCursor(Qt.PointingHandCursor)
        self.btn_down.setStyleSheet("QPushButton { background-color: #381A1A; color: #FF6666; font-weight: bold; border-radius: 5px; padding: 4px 8px; font-size: 11px; }")
        down_menu = QMenu(self.btn_down)
        down_menu.addAction("Sin motivo").triggered.connect(lambda: self.vote_requested.emit(-1, []))
        down_menu.addSeparator()
        for tag in TAGS:
            down_menu.addAction(TAG_LABELS.get(tag, tag)).triggered.connect(lambda _=False, t=tag: self.vote_requested.emit(-1, [t]))
        self.btn_down.setMenu(down_menu)
        vote_row.addWidget(self.btn_down)

        self.vote_status = QLabel("")
        self.vote_status.setStyleSheet("color: #888899; font-size: 11px;")
        vote_row.addWidget(self.vote_status, 1)

        tray_lay.addLayout(vote_row)
        layout.addWidget(tray_card)

    # -------------------------------------------------------------------------------------------------
    # Manejadores de interacción y acciones de Deck (Control Real de Audio y DSP)
    # -------------------------------------------------------------------------------------------------
    def _on_load_clicked(self, is_deck_a: bool):
        if is_deck_a:
            if self.main_window and hasattr(self.main_window, "player"):
                self.main_window.player.setPosition(0)
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify("Deck A recargado al inicio.")
        else:
            nxt = getattr(self.main_window, "peek_next", lambda: None)()
            if nxt and self.main_window and hasattr(self.main_window, "notify"):
                title = nxt.get('title', 'Pista siguiente')
                self.main_window.notify(f"Deck B preparado: «{title}»")
            else:
                self._on_browse_clicked("B")

    def _on_usb_clicked(self, deck: str):
        """Monta o abre una unidad USB virtual con archivos de música para el reproductor."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        attr_name = f"_usb_mounted_{deck.lower()}"
        mounted = getattr(self, attr_name, True)
        btn = getattr(self, f"btn_usb_{deck.lower()}", None)
        if not mounted:
            setattr(self, attr_name, True)
            if btn:
                btn.setText(f"USB {1 if deck == 'A' else 2} ●")
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A3828; color: #1ED760; font-size: 8px; font-weight: 800; border: 1px solid #1ED760; border-radius: 3px; padding: 2px 4px; }")
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck {deck}: Unidad USB conectada correctamente (Biblioteca lista).")
        else:
            folder = QFileDialog.getExistingDirectory(self, f"Seleccionar carpeta de música para USB {deck}")
            if folder:
                setattr(self, f"_usb_folder_{deck.lower()}", folder)
                if self.main_window and hasattr(self.main_window, "notify"):
                    self.main_window.notify(f"Deck {deck}: USB montado con carpeta «{os.path.basename(folder)}»")
            else:
                if self.main_window and hasattr(self.main_window, "notify"):
                    self.main_window.notify(f"Deck {deck}: Unidad USB activa y lista para reproducir.")

    def _on_eject_clicked(self, deck: str):
        """Expulsa de forma segura el medio USB del deck con retroalimentación visual."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        setattr(self, f"_usb_mounted_{deck.lower()}", False)
        btn = getattr(self, f"btn_usb_{deck.lower()}", None)
        if btn:
            btn.setText(f"USB {1 if deck == 'A' else 2} ○")
            btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #2D2010; color: #FFAA33; font-size: 8px; font-weight: 800; border: 1px solid #FFAA33; border-radius: 3px; padding: 2px 4px; }")
        scr = self.screen_a if deck == "A" else self.screen_b
        if scr:
            scr.setTrack("NO MEDIA", "USB expulsado con seguridad")
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Deck {deck}: USB extraído con seguridad. Puedes desconectar el medio.")

    def _on_browse_clicked(self, deck: str):
        """Abre la pantalla de navegación de pistas CDJ-3000 con selector rápido."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        tracks = list(self._upcoming_tracks_cache)
        if not tracks and hasattr(self, "_now_path") and self._now_path:
            tracks.append({
                "title": getattr(self.now_title, "text", lambda: "Pista A")() or "Pista A",
                "artist": getattr(self.now_detail, "text", lambda: "")() or "Artista",
                "local_path": self._now_path,
                "bpm": getattr(self, "_deck_a_bpm", 128.0),
                "key": "8A"
            })
        dlg = DjTrackBrowserDialog(tracks, target_deck=deck, parent=self)
        dlg.trackSelected.connect(lambda d, trk: self._load_track_into_deck(d, trk))
        dlg.exec()

    def _load_track_into_deck(self, deck: str, track: dict):
        """Carga una pista seleccionada en el deck correspondiente y actualiza la pantalla."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        title = track.get("title", "Pista")
        artist = track.get("artist", track.get("uploader", "Artista"))
        bpm = track.get("bpm") or 128.0
        key = track.get("key") or track.get("tone") or "8A"
        path = track.get("local_path", "")

        if deck == "A":
            self._now_path = path
            self._deck_a_bpm = float(bpm)
            self._cue_a_ms = 0
            self._hot_cues_a = [None, None, None, None]
            if hasattr(self, "pads_a"):
                self.pads_a.clearAllCues()
            self.screen_a.setTrack(title, artist, bpm, key, on_air=True)
            self.now_title.setText(title)
            self.now_detail.setText(artist)
            if self.main_window and hasattr(self.main_window, "player") and path and os.path.exists(path):
                self.main_window.player.setSource(QUrl.fromLocalFile(path))
                self.main_window.player.setPosition(0)
        else:
            self._next_path = path
            self._deck_b_bpm = float(bpm)
            self._cue_b_ms = 0
            self._hot_cues_b = [None, None, None, None]
            if hasattr(self, "pads_b"):
                self.pads_b.clearAllCues()
            self.screen_b.setTrack(title, artist, bpm, key, on_air=False)
            self.next_title.setText(title)
            spare = getattr(self.main_window, "_spare_deck", None)
            if spare and len(spare) > 0 and spare[0] and path and os.path.exists(path):
                spare[0].setSource(QUrl.fromLocalFile(path))
                spare[0].setPosition(0)

        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Deck {deck}: «{title}» cargada con éxito.")

    def _on_menu_clicked(self, deck: str):
        """Menú de configuración y utilidades CDJ-3000."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #1A1A24; color: #FFF; border: 1px solid #333345; } QMenu::item:selected { background-color: #00E5FF; color: #000; }")
        menu.addAction("⚙ Configuración de Cuadrícula (Beat Grid)").triggered.connect(
            lambda: self.main_window.notify(f"Deck {deck}: Calibración de Beat Grid iniciada.") if hasattr(self.main_window, "notify") else None
        )
        menu.addAction("🎚 Sensibilidad del Jog Wheel (Light / Heavy)").triggered.connect(
            lambda: self.main_window.notify(f"Deck {deck}: Sensibilidad Jog ajustada.") if hasattr(self.main_window, "notify") else None
        )
        menu.addAction("🎯 Nivel de Auto Cue: -60 dB").triggered.connect(
            lambda: self.main_window.notify(f"Deck {deck}: Auto Cue fijado a -60 dB.") if hasattr(self.main_window, "notify") else None
        )
        menu.addAction("💿 Ajuste de parada de vinilo (Vinyl Speed Adjust)").triggered.connect(
            lambda: self.main_window.notify(f"Deck {deck}: Vinyl Speed ajustado a tiempo real.") if hasattr(self.main_window, "notify") else None
        )
        btn = self.btn_menu_a if deck == "A" else self.btn_menu_b
        if btn:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _on_back_clicked(self, deck: str):
        """Botón BACK de Pioneer CDJ: retrocede al nivel anterior de carpetas o pantalla principal."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        scr = self.screen_a if deck == "A" else self.screen_b
        if scr and hasattr(scr, "title_lbl"):
            scr.title_lbl.setText(getattr(scr, "_last_title", None) or scr.title_lbl.text())
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Deck {deck}: Regresando a la vista principal de reproducción.")

    def _toggle_quantize(self, deck: str):
        """Activa o desactiva la cuantización de compases (Quantize) Pioneer."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        if deck == "A":
            self._quantize_a = not self._quantize_a
            state = self._quantize_a
            btn = self.btn_quantize_a
        else:
            self._quantize_b = not self._quantize_b
            state = self._quantize_b
            btn = self.btn_quantize_b

        if state:
            btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #2D2010; color: #FFAA33; font-size: 8px; font-weight: 800; border: 1px solid #FFAA33; border-radius: 3px; padding: 2px 4px; }")
        else:
            btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A22; color: #666; font-size: 8px; border-radius: 3px; padding: 2px 4px; }")

        self._update_screen_badges(deck)
        if self.main_window and hasattr(self.main_window, "notify"):
            txt = "activado (Ajuste automático a beat grid)" if state else "desactivado (Modo libre)"
            self.main_window.notify(f"Deck {deck}: Quantize {txt}")

    def _toggle_slip(self, deck: str):
        """Activa o desactiva el modo SLIP Pioneer."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        if deck == "A":
            self._slip_a = not self._slip_a
            state = self._slip_a
            btn = self.btn_slip_a
            if state and self.main_window and hasattr(self.main_window, "player"):
                self._slip_virtual_pos_a = self.main_window.player.position()
        else:
            self._slip_b = not self._slip_b
            state = self._slip_b
            btn = self.btn_slip_b

        if state:
            btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #381A1A; color: #FF4444; font-size: 8px; font-weight: 800; border: 1px solid #FF4444; border-radius: 3px; padding: 2px 4px; }")
        else:
            btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A22; color: #666; font-size: 8px; border-radius: 3px; padding: 2px 4px; }")

        self._update_screen_badges(deck)
        if self.main_window and hasattr(self.main_window, "notify"):
            txt = "activado (El tiempo sigue corriendo en segundo plano)" if state else "desactivado"
            self.main_window.notify(f"Deck {deck}: Slip Mode {txt}")

    def _toggle_reverse(self, deck: str):
        """Activa o desactiva la reproducción invertida (Reverse / Backspin)."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        if deck == "A":
            self._rev_active_a = not self._rev_active_a
            state = self._rev_active_a
            btn = self.btn_rev_a
            if state:
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #2D2010; color: #FFAA33; font-size: 8px; font-weight: 800; border: 1px solid #FFAA33; border-radius: 3px; padding: 2px 4px; }")
                if not self._rev_timer_a:
                    self._rev_timer_a = QTimer(self)
                    self._rev_timer_a.setInterval(60)
                    self._rev_timer_a.timeout.connect(lambda: self._do_reverse_step("A"))
                self._rev_timer_a.start()
            else:
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A22; color: #666; font-size: 8px; border-radius: 3px; padding: 2px 4px; }")
                if self._rev_timer_a:
                    self._rev_timer_a.stop()
        else:
            self._rev_active_b = not self._rev_active_b
            state = self._rev_active_b
            btn = self.btn_rev_b
            if state:
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #2D2010; color: #FFAA33; font-size: 8px; font-weight: 800; border: 1px solid #FFAA33; border-radius: 3px; padding: 2px 4px; }")
            else:
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A22; color: #666; font-size: 8px; border-radius: 3px; padding: 2px 4px; }")

        if self.main_window and hasattr(self.main_window, "notify"):
            txt = "activada (Reproduciendo hacia atrás)" if state else "desactivada"
            self.main_window.notify(f"Deck {deck}: Reproducción Invertida {txt}")

    def _do_reverse_step(self, deck: str):
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        if deck == "A" and self.main_window and hasattr(self.main_window, "player"):
            p = self.main_window.player
            if p.playbackState() == 1:
                cur = p.position()
                p.setPosition(max(0, cur - 120))

    def _toggle_master_tempo(self, deck: str):
        """Conmuta Master Tempo (Key Lock) conservando el tono musical al cambiar BPM."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        if deck == "A":
            self._master_tempo_a = not self._master_tempo_a
            state = self._master_tempo_a
            btn = self.btn_mt_a
        else:
            self._master_tempo_b = not self._master_tempo_b
            state = self._master_tempo_b
            btn = self.btn_mt_b

        if state:
            btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A2438; color: #44AAFF; font-size: 8px; font-weight: 800; border: 1px solid #44AAFF; border-radius: 3px; padding: 2px 4px; }")
        else:
            btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A22; color: #666; font-size: 8px; border-radius: 3px; padding: 2px 4px; }")

        self._update_screen_badges(deck)
        if self.main_window and hasattr(self.main_window, "notify"):
            txt = "activado (Tono musical fijado)" if state else "desactivado (Pitch libre)"
            self.main_window.notify(f"Deck {deck}: Master Tempo {txt}")

    def _update_screen_badges(self, deck: str):
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        scr = self.screen_a if deck == "A" else self.screen_b
        if not scr:
            return
        mt = self._master_tempo_a if deck == "A" else self._master_tempo_b
        quant = self._quantize_a if deck == "A" else self._quantize_b
        slip = self._slip_a if deck == "A" else self._slip_b
        jog = self.jog_a if deck == "A" else self.jog_b
        vinyl = jog.isVinylMode() if jog else False
        loop = self._loop_active_a if deck == "A" else self._loop_active_b
        scr.setBadges(master_tempo=mt, quantize=quant, slip=slip, vinyl=vinyl, loop=loop)

    def _on_cue_pressed(self, deck: str):
        """Comportamiento profesional Pioneer CUE: si el plato está detenido, mantener CUE reproduce temporalmente."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        if deck == "A" and self.main_window and hasattr(self.main_window, "player"):
            p = self.main_window.player
            if p.playbackState() != 1:
                self._cue_audition_a = True
                target_cue = self._cue_a_ms or 0
                p.setPosition(target_cue)
                p.play()

    def _on_cue_released(self, deck: str):
        """Al soltar CUE tras preescucha momentánea, vuelve al punto de CUE y se pausa."""
        if isinstance(deck, bool):
            deck = "A" if deck else "B"
        if deck == "A" and getattr(self, "_cue_audition_a", False):
            self._cue_audition_a = False
            if self.main_window and hasattr(self.main_window, "player"):
                p = self.main_window.player
                p.pause()
                p.setPosition(self._cue_a_ms or 0)

    def _on_beat_jump(self, is_deck_a: bool, bars: int):
        if self.main_window and hasattr(self.main_window, "player"):
            bpm = getattr(self, "_deck_a_bpm" if is_deck_a else "_deck_b_bpm", None) or 128.0
            cur_ms = self.main_window.player.position()
            jump_ms = int(bars * (60.0 / bpm * 4.0) * 1000)
            new_pos = max(0, cur_ms + jump_ms)
            self.main_window.player.setPosition(new_pos)
            direction = "adelante" if bars > 0 else "atrás"
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Beat Jump {direction} ({abs(bars)} compás)")

    def _on_pad_action(self, is_deck_a: bool, pad_idx: int, mode: str):
        if not self.main_window or not hasattr(self.main_window, "player"):
            return
        p = self.main_window.player
        cues = self._hot_cues_a if is_deck_a else self._hot_cues_b
        pads = self.pads_a if is_deck_a else self.pads_b

        if mode == "HOT CUE":
            cur_ms = p.position()
            target_cue = cues[pad_idx]
            if target_cue is None:
                cues[pad_idx] = cur_ms
                m = cur_ms // 60000
                s = (cur_ms % 60000) // 1000
                pads.setCueActive(pad_idx, True, f"CUE {pad_idx + 1}")
                if hasattr(self.main_window, "notify"):
                    self.main_window.notify(f"Hot Cue {pad_idx + 1} fijado en {m:02d}:{s:02d}")
            else:
                p.setPosition(target_cue)
                if p.playbackState() != 1:
                    p.play()
                m = target_cue // 60000
                s = (target_cue % 60000) // 1000
                if hasattr(self.main_window, "notify"):
                    self.main_window.notify(f"Saltando a Hot Cue {pad_idx + 1} ({m:02d}:{s:02d})")

        elif mode == "LOOP":
            bpm = getattr(self, "_deck_a_bpm" if is_deck_a else "_deck_b_bpm", None) or 128.0
            beat_ms = int(60.0 / bpm * 1000)
            beats_map = [1, 2, 4, 8]
            loop_len = beats_map[pad_idx] * beat_ms
            cur = p.position()
            if is_deck_a:
                self._loop_start_a = cur
                self._loop_end_a = cur + loop_len
                self._loop_active_a = True
                if hasattr(self, "loop_a"):
                    self.loop_a.setLoopActive(True)
                self._update_screen_badges("A")
            else:
                self._loop_start_b = cur
                self._loop_end_b = cur + loop_len
                self._loop_active_b = True
                if hasattr(self, "loop_b"):
                    self.loop_b.setLoopActive(True)
                self._update_screen_badges("B")
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Beat Loop activado: {beats_map[pad_idx]} beats")

        elif mode == "JUMP":
            bpm = getattr(self, "_deck_a_bpm" if is_deck_a else "_deck_b_bpm", None) or 128.0
            beat_ms = int(60.0 / bpm * 1000)
            jumps = [-4, -1, 1, 4]
            jump_ms = jumps[pad_idx] * beat_ms
            p.setPosition(max(0, p.position() + jump_ms))
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Beat Jump {jumps[pad_idx]:+d} beats")

    def _on_pad_cleared(self, is_deck_a: bool, pad_idx: int):
        cues = self._hot_cues_a if is_deck_a else self._hot_cues_b
        cues[pad_idx] = None
        pads = self.pads_a if is_deck_a else self.pads_b
        pads.setCueActive(pad_idx, False)
        deck_str = "A" if is_deck_a else "B"
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Deck {deck_str}: Hot Cue {pad_idx + 1} eliminado.")

    def _on_loop_in(self, deck: str):
        if not self.main_window or not hasattr(self.main_window, "player"):
            return
        pos = self.main_window.player.position()
        if deck == "A":
            self._loop_start_a = pos
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck A: Loop IN marcado en {pos // 1000}s")
        else:
            self._loop_start_b = pos
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck B: Loop IN marcado en {pos // 1000}s")

    def _on_loop_out(self, deck: str):
        if not self.main_window or not hasattr(self.main_window, "player"):
            return
        pos = self.main_window.player.position()
        if deck == "A":
            if self._loop_start_a is None or pos <= self._loop_start_a:
                self._loop_start_a = max(0, pos - 4000)
            self._loop_end_a = pos
            self._loop_active_a = True
            dur_s = (self._loop_end_a - self._loop_start_a) / 1000.0
            if hasattr(self, "loop_a"):
                self.loop_a.setLoopActive(True)
            self._update_screen_badges("A")
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck A: Loop activo ({dur_s:.1f}s)")
        else:
            if self._loop_start_b is None or pos <= self._loop_start_b:
                self._loop_start_b = max(0, pos - 4000)
            self._loop_end_b = pos
            self._loop_active_b = True
            dur_s = (self._loop_end_b - self._loop_start_b) / 1000.0
            if hasattr(self, "loop_b"):
                self.loop_b.setLoopActive(True)
            self._update_screen_badges("B")
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck B: Loop activo ({dur_s:.1f}s)")

    def _on_reloop(self, deck: str):
        if deck == "A":
            self._loop_active_a = not self._loop_active_a
            if hasattr(self, "loop_a"):
                self.loop_a.setLoopActive(self._loop_active_a)
            self._update_screen_badges("A")
            state_str = "activado" if self._loop_active_a else "desactivado"
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck A: Reloop {state_str}")
        else:
            self._loop_active_b = not self._loop_active_b
            if hasattr(self, "loop_b"):
                self.loop_b.setLoopActive(self._loop_active_b)
            self._update_screen_badges("B")
            state_str = "activado" if self._loop_active_b else "desactivado"
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck B: Reloop {state_str}")

    def _on_half_loop(self, deck: str):
        if deck == "A" and self._loop_start_a is not None and self._loop_end_a is not None:
            length = self._loop_end_a - self._loop_start_a
            self._loop_end_a = self._loop_start_a + max(250, length // 2)
            dur_s = (self._loop_end_a - self._loop_start_a) / 1000.0
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck A: Loop 1/2X ({dur_s:.1f}s)")
        elif deck == "B" and self._loop_start_b is not None and self._loop_end_b is not None:
            length = self._loop_end_b - self._loop_start_b
            self._loop_end_b = self._loop_start_b + max(250, length // 2)
            dur_s = (self._loop_end_b - self._loop_start_b) / 1000.0
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck B: Loop 1/2X ({dur_s:.1f}s)")

    def _on_double_loop(self, deck: str):
        if deck == "A" and self._loop_start_a is not None and self._loop_end_a is not None:
            length = self._loop_end_a - self._loop_start_a
            self._loop_end_a = self._loop_start_a + length * 2
            dur_s = (self._loop_end_a - self._loop_start_a) / 1000.0
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck A: Loop 2X ({dur_s:.1f}s)")
        elif deck == "B" and self._loop_start_b is not None and self._loop_end_b is not None:
            length = self._loop_end_b - self._loop_start_b
            self._loop_end_b = self._loop_start_b + length * 2
            dur_s = (self._loop_end_b - self._loop_start_b) / 1000.0
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck B: Loop 2X ({dur_s:.1f}s)")

    def _on_pitch_a_rate_changed(self, rate: float):
        if self.main_window and hasattr(self.main_window, "player"):
            try:
                self.main_window.player.setPlaybackRate(float(rate))
            except Exception:
                pass
        bpm_nominal = getattr(self, "_deck_a_bpm", None) or 128.0
        live_bpm = bpm_nominal * rate
        if hasattr(self, "screen_a"):
            self.screen_a.updatePitchDisplay(rate, live_bpm)

    def _on_pitch_b_rate_changed(self, rate: float):
        bpm_nominal = getattr(self, "_deck_b_bpm", None) or 128.0
        live_bpm = bpm_nominal * rate
        if hasattr(self, "screen_b"):
            self.screen_b.updatePitchDisplay(rate, live_bpm)

    def _on_jog_a_scratched(self, delta_ms: int):
        if self.main_window and hasattr(self.main_window, "player"):
            try:
                p = self.main_window.player
                cur = p.position()
                dur = p.duration()
                new_pos = max(0, min(dur, cur + delta_ms)) if dur > 0 else max(0, cur + delta_ms)
                p.setPosition(new_pos)
            except Exception:
                pass

    def _on_jog_b_scratched(self, delta_ms: int):
        spare = getattr(self.main_window, "_spare_deck", None)
        if spare and len(spare) > 0 and spare[0]:
            try:
                p = spare[0]
                cur = p.position()
                p.setPosition(max(0, cur + delta_ms))
            except Exception:
                pass

    def _on_jog_a_nudged(self, nudge: float):
        if self.main_window and hasattr(self.main_window, "player"):
            try:
                base_rate = 1.0 + (self.pitch_a.value * 0.10) if hasattr(self, "pitch_a") else 1.0
                effective_rate = max(0.5, min(2.0, base_rate + nudge))
                self.main_window.player.setPlaybackRate(effective_rate)
            except Exception:
                pass

    def _on_jog_b_nudged(self, nudge: float):
        pass

    def _toggle_vinyl_mode(self, is_deck_a: bool, btn_widget: QPushButton):
        jog = self.jog_a if is_deck_a else self.jog_b
        new_mode = not jog.isVinylMode()
        jog.setVinylMode(new_mode)
        deck_str = "A" if is_deck_a else "B"
        if new_mode:
            btn_widget.setStyleSheet("QPushButton { min-width: 0px; background-color: #152238; color: #00D2FF; font-size: 8px; font-weight: 900; border: 1px solid #00D2FF; border-radius: 3px; padding: 2px 4px; }")
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck {deck_str}: Modo Vinilo activado (Scratch & Needle Scrub)")
        else:
            btn_widget.setStyleSheet("QPushButton { min-width: 0px; background-color: #20202A; color: #777788; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 2px 4px; }")
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck {deck_str}: Modo CDJ activado (Pitch Bend)")
        self._update_screen_badges(deck_str)

    def _on_play_a_clicked(self):
        if self.main_window and hasattr(self.main_window, "player"):
            if self.main_window.player.playbackState() == 1:
                self.main_window.player.pause()
            else:
                self.main_window.player.play()

    def _on_pause_a_clicked(self):
        if self.main_window and hasattr(self.main_window, "player"):
            self.main_window.player.pause()

    def _on_play_b_clicked(self):
        spare = getattr(self.main_window, "_spare_deck", None)
        if spare and len(spare) > 0 and spare[0]:
            if spare[0].playbackState() == 1:
                spare[0].pause()
            else:
                spare[0].play()
        else:
            self._on_auto_mix_clicked()

    def _on_pause_b_clicked(self):
        spare = getattr(self.main_window, "_spare_deck", None)
        if spare and len(spare) > 0 and spare[0]:
            spare[0].pause()

    def _on_cue_clicked(self, deck: str):
        if not self.main_window:
            return
        if deck == "A":
            p = getattr(self.main_window, "player", None)
            if not p:
                return
            if p.playbackState() == 1:
                p.pause()
                target_cue = self._cue_a_ms or 0
                p.setPosition(target_cue)
                if hasattr(self.main_window, "notify"):
                    self.main_window.notify(f"Deck A: Rebobinado a punto CUE ({target_cue // 1000}s)")
            else:
                self._cue_a_ms = p.position()
                if hasattr(self.main_window, "notify"):
                    self.main_window.notify(f"Deck A: Punto CUE marcado en {self._cue_a_ms // 1000}s")
        else:
            spare = getattr(self.main_window, "_spare_deck", None)
            if spare and len(spare) > 0 and spare[0]:
                sp = spare[0]
                if sp.playbackState() == 1:
                    sp.pause()
                    target_cue = self._cue_b_ms or 0
                    sp.setPosition(target_cue)
                    if hasattr(self.main_window, "notify"):
                        self.main_window.notify(f"Deck B: Rebobinado a punto CUE ({target_cue // 1000}s)")
                else:
                    self._cue_b_ms = sp.position()
                    if hasattr(self.main_window, "notify"):
                        self.main_window.notify(f"Deck B: Punto CUE marcado en {self._cue_b_ms // 1000}s")
            else:
                if hasattr(self.main_window, "notify"):
                    self.main_window.notify("Deck B: Punto CUE preparado en el Drop")

    def _on_deck_drop(self, deck: str, event):
        mime = event.mimeData()
        if mime.hasUrls():
            urls = mime.urls()
            if urls:
                path = urls[0].toLocalFile()
                if path and os.path.isfile(path):
                    base = os.path.splitext(os.path.basename(path))[0]
                    track_dict = {"title": base, "artist": "Archivo local", "local_path": path, "bpm": 128.0}
                    self._on_browser_load_deck(deck, track_dict)
                    event.acceptProposedAction()
                    return
        if mime.hasText():
            txt = mime.text()
            if txt:
                try:
                    import json
                    d = json.loads(txt)
                    if isinstance(d, dict):
                        self._on_browser_load_deck(deck, d)
                        event.acceptProposedAction()
                        return
                except Exception:
                    pass
        event.acceptProposedAction()

    def _on_sync_clicked(self, deck: str):
        bpm_a = getattr(self, "_deck_a_bpm", None) or 128.0
        bpm_b = getattr(self, "_deck_b_bpm", None) or 128.0
        if deck == "A" and bpm_b > 20 and hasattr(self, "pitch_a"):
            ratio = bpm_b / bpm_a
            pitch_val = (ratio - 1.0) / 0.10
            self.pitch_a.setValue(pitch_val)
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck A SYNC Lock: Tempo ajustado a {bpm_b:.1f} BPM")
        elif deck == "B" and bpm_a > 20 and hasattr(self, "pitch_b"):
            ratio = bpm_a / bpm_b
            pitch_val = (ratio - 1.0) / 0.10
            self.pitch_b.setValue(pitch_val)
            if hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck B SYNC Lock: Tempo ajustado a {bpm_a:.1f} BPM")

    def _on_ch_cue_clicked(self, is_deck_a: bool):
        if is_deck_a:
            self._cue_pfl_a = not self._cue_pfl_a
            state = self._cue_pfl_a
            btn = getattr(self, "btn_cue_ch1", None)
            deck_str = "CH 1"
        else:
            self._cue_pfl_b = not self._cue_pfl_b
            state = self._cue_pfl_b
            btn = getattr(self, "btn_cue_ch2", None)
            deck_str = "CH 2"

        if btn:
            if state:
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #FFAA33; color: #000; font-size: 8px; font-weight: 900; border: 1px solid #FFAA33; border-radius: 3px; padding: 2px 4px; }")
            else:
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #2D2010; color: #FFAA33; font-size: 8px; font-weight: 800; border: 1px solid #FFAA33; border-radius: 3px; padding: 2px 4px; }")

        if self.main_window and hasattr(self.main_window, "notify"):
            txt = "activada" if state else "desactivada"
            self.main_window.notify(f"Preescucha por Auriculares {deck_str} (PFL CUE {txt})")

    def _on_xf_assign_clicked(self, is_deck_a: bool):
        """Cicla la asignación de crossfader entre A -> THRU -> B."""
        cur = self._xf_assign_a if is_deck_a else self._xf_assign_b
        cycle = {"A": "THRU", "THRU": "B", "B": "A"}
        new_val = cycle.get(cur, "THRU")
        if is_deck_a:
            self._xf_assign_a = new_val
            btn = getattr(self, "btn_xf_assign_a", None)
        else:
            self._xf_assign_b = new_val
            btn = getattr(self, "btn_xf_assign_b", None)

        if btn:
            btn.setText(f"XF: {new_val}")
            if new_val == "THRU":
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #252535; color: #FFF; font-size: 8px; font-weight: bold; border-radius: 2px; padding: 1px 3px; }")
            elif new_val == "A":
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #153020; color: #1ED760; font-size: 8px; font-weight: bold; border-radius: 2px; padding: 1px 3px; }")
            else:
                btn.setStyleSheet("QPushButton { min-width: 0px; background-color: #352015; color: #FF7700; font-size: 8px; font-weight: bold; border-radius: 2px; padding: 1px 3px; }")

        self._apply_audio_gains()
        deck_str = "CH 1" if is_deck_a else "CH 2"
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Mixer {deck_str}: Crossfader asignado a {new_val}")

    def _on_channel_input_changed(self, is_deck_a: bool, source: str):
        if is_deck_a:
            self._channel_in_a = source
        else:
            self._channel_in_b = source
        deck_str = "CH 1" if is_deck_a else "CH 2"
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Mixer {deck_str}: Fuente conmutada a {source}")

    def _on_color_fx_selected(self, fx_name: str):
        self._current_color_fx = fx_name
        self._on_eq_control_changed()
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Sound Color FX seleccionado: {fx_name}")

    def _on_master_vol_changed(self, val: float):
        self._master_volume_val = val
        self._apply_audio_gains()

    def _on_booth_vol_changed(self, val: float):
        self._booth_vol = val
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Booth Monitor Level: {int(val * 100)}%")

    def _on_hp_level_changed(self, val: float):
        self._hp_vol = val
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Headphones Level: {int(val * 100)}%")

    def _on_hp_mix_changed(self, val: float):
        self._hp_mix = val
        pct_master = int(val * 100)
        pct_cue = 100 - pct_master
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Headphones Mixing: CUE {pct_cue}% / MASTER {pct_master}%")

    def _on_monitor_cue_toggled(self, ch_or_active, active=None):
        if active is None:
            is_act = bool(ch_or_active)
        else:
            is_act = bool(active)
        self._master_cue = is_act
        state = "activada (Master PFL)" if is_act else "desactivada"
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Preescucha Master en auriculares {state}")

    def _on_hp_ab_toggled(self, mode: str):
        self._hp_ab_mode = mode
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Circuito de Auriculares cambiado a Salida {mode}")

    def _on_env_bar_item_triggered(self, item_id: str, title: str):
        if item_id == "rear_panel":
            self._open_rear_panel()
        elif item_id == "subwoofer":
            self._subwoofer_boost = not self._subwoofer_boost
            st = "activado (+4dB punch sub-grave)" if self._subwoofer_boost else "plano (estándar)"
            self._on_eq_control_changed()
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Subwoofer Club: {st}")
        elif item_id == "talkover":
            self._talkover_active = not self._talkover_active
            st = "activado (-12dB ducking automático)" if self._talkover_active else "desactivado"
            self._apply_audio_gains()
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Micrófono Talkover: {st}")
        elif item_id == "pa_system":
            self._pa_muted = not self._pa_muted
            st = "MUTEADO" if self._pa_muted else "ACTIVO (Sonando en sala)"
            self._apply_audio_gains()
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Sistema PA Master: {st}")
        elif item_id == "monitors":
            self._booth_muted = not self._booth_muted
            st = "MUTEADOS" if self._booth_muted else "ACTIVOS"
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Monitores de Cabina (Booth): {st}")
        elif item_id == "headphones":
            self._master_cue = not self._master_cue
            if hasattr(self, "monitor_section") and hasattr(self.monitor_section, "btn_master_cue"):
                self.monitor_section.btn_master_cue.setChecked(self._master_cue)
            st = "Cue Master activado" if self._master_cue else "Cue Master desactivado"
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Auriculares DJ: {st}")
        elif item_id == "usbs":
            self._on_browse_clicked("A")
        elif item_id == "lighting":
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify("Iluminación DMX sincronizada con el BPM de la sesión.")
        elif item_id == "laptop":
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify("Software DJ Link: Modo Pro DJ LINK activo a 1 Gbps.")

    def _on_beat_fx_changed(self, fx_type: str, params: dict):
        self.fx_changed.emit(fx_type, params)

    def _on_beat_fx_toggled(self, active: bool):
        if self.main_window and hasattr(self.main_window, "notify"):
            fx_name = getattr(self.beat_fx_rack, "_current_fx", "BEAT FX")
            state_str = "activado" if active else "apagado"
            self.main_window.notify(f"Beat FX {fx_name} {state_str}")

    def _on_auto_mix_clicked(self):
        """Dispara la mezcla inmediata por IA con animación visual en los controles."""
        self.auto_mix_requested.emit()

    def _cycle_filter(self):
        modes = ["OFF", "HPF", "LPF"]
        cur = self._fx_state.get("filter_mode", "OFF")
        nxt_idx = (modes.index(cur) + 1) % len(modes) if cur in modes else 0
        nxt = modes[nxt_idx]
        self._fx_state["filter_mode"] = nxt
        self.btn_fx_filter.setText(f"Filtro: {nxt}")
        if hasattr(self, "color_fx_selector"):
            self.color_fx_selector.selectFx("FILTER" if nxt != "OFF" else "SPACE")
        return nxt

    def _cycle_delay(self):
        times = ["OFF", "1/2", "3/4", "1T"]
        cur = self._fx_state.get("delay_time", "OFF")
        nxt_idx = (times.index(cur) + 1) % len(times) if cur in times else 0
        nxt = times[nxt_idx]
        self._fx_state["delay_time"] = nxt
        self.btn_fx_delay.setText(f"Delay: {nxt}")
        if hasattr(self, "beat_fx_rack"):
            self.beat_fx_rack.setFx("DELAY")
            if nxt != "OFF":
                self.beat_fx_rack.setBeat("1/2" if nxt == "1/2" else ("3/4" if nxt == "3/4" else "1"))
                self.beat_fx_rack.setActive(True)
            else:
                self.beat_fx_rack.setActive(False)
        return nxt

    def _toggle_freeze(self):
        cur = not self._fx_state.get("freeze_active", False)
        self._fx_state["freeze_active"] = cur
        if hasattr(self, "beat_fx_rack"):
            self.beat_fx_rack.setActive(cur)
            if cur:
                self.beat_fx_rack.setFx("ECHO")
        return cur

    def animate_transition(self, duration_ms: int = 5000, t_type: str = "smart_filter_eq"):
        """Anima físicamente el crossfader, ecualizadores y filtros de la mesa DJ durante la transición adaptada al género."""
        current_xf = self.crossfader._pos if hasattr(self, "crossfader") else 0.0
        target_xf = 1.0 if current_xf < 0.0 else -1.0
        from_deck_a = current_xf <= 0.0

        out_filter = getattr(self, "knob_filter_a" if from_deck_a else "knob_filter_b", None)
        out_low = getattr(self, "knob_low_a" if from_deck_a else "knob_low_b", None)
        out_mid = getattr(self, "knob_mid_a" if from_deck_a else "knob_mid_b", None)

        in_filter = getattr(self, "knob_filter_b" if from_deck_a else "knob_filter_a", None)
        in_low = getattr(self, "knob_low_b" if from_deck_a else "knob_low_a", None)

        kind = str(t_type or "").lower()
        half_dur = max(300, duration_ms // 2)

        # Adaptación según género y técnica de mezcla DJ profesional
        if "bass_swap" in kind or "house" in kind or "techno" in kind:
            # House / Tech House / Techno: Mezcla progresiva larga con HPF sweep y corte estricto de bajos a -24 dB
            if hasattr(self, "crossfader"):
                self.crossfader.animateTo(target_xf, duration_ms=duration_ms)
            if out_filter:
                out_filter.animateTo(0.75, duration_ms=int(duration_ms * 0.55))
            if out_low:
                out_low.animateTo(-1.0, duration_ms=half_dur)
            if in_low:
                in_low.animateTo(0.0, duration_ms=half_dur)
            if in_filter:
                in_filter.animateTo(0.0, duration_ms=int(duration_ms * 0.70))

        elif "reggaeton" in kind or "dynamic" in kind:
            # Reggaetón / Urbano / Dembow: Tallado de medios vocal (-6 dB Mid-Carve), corte dinámico y Echo-Out rítmico
            if hasattr(self, "crossfader"):
                self.crossfader.animateTo(target_xf, duration_ms=max(600, int(duration_ms * 0.6)))
            if out_mid:
                out_mid.animateTo(-0.5, duration_ms=int(duration_ms * 0.35))
            if out_low:
                out_low.animateTo(-1.0, duration_ms=int(duration_ms * 0.40))
            if in_low:
                in_low.animateTo(0.0, duration_ms=int(duration_ms * 0.45))
            if hasattr(self, "beat_fx_rack"):
                self.beat_fx_rack.setFx("ECHO")
                self.beat_fx_rack.setBeat("1/2")
                self.beat_fx_rack.setActive(True)

        elif "vinyl_brake" in kind or "hiphop" in kind:
            # Hip-Hop / Trap / Boom Bap: Freno de vinilo (motor off) y corte al primer beat de frase
            if hasattr(self, "crossfader"):
                self.crossfader.animateTo(target_xf, duration_ms=max(400, int(duration_ms * 0.35)))
            if out_low:
                out_low.animateTo(-1.0, duration_ms=300)
            if in_low:
                in_low.animateTo(0.0, duration_ms=300)
            jog = self.jog_a if from_deck_a else self.jog_b
            if jog and hasattr(jog, "setPlaying"):
                jog.setPlaying(False)

        elif "edm" in kind or "build_drop" in kind:
            # EDM Festival: Build-up sincronizado subiendo filtro HPF en ambas pistas y drop explosivo de graves
            if hasattr(self, "crossfader"):
                self.crossfader.animateTo(target_xf, duration_ms=duration_ms)
            if out_filter:
                out_filter.animateTo(0.85, duration_ms=int(duration_ms * 0.85))
            if in_filter:
                in_filter.animateTo(0.70, duration_ms=int(duration_ms * 0.50))
                QTimer.singleShot(int(duration_ms * 0.85), lambda: in_filter.animateTo(0.0, duration_ms=150))
            if out_low:
                out_low.animateTo(-1.0, duration_ms=int(duration_ms * 0.85))
            if in_low:
                in_low.animateTo(0.0, duration_ms=int(duration_ms * 0.85))

        elif "pop" in kind or "melodic" in kind:
            # Pop / Comercial: Fundido melódico con volumen compensado y atenuación de medios vocales
            if hasattr(self, "crossfader"):
                self.crossfader.animateTo(target_xf, duration_ms=duration_ms)
            if out_mid:
                out_mid.animateTo(-0.3, duration_ms=half_dur)
            if out_low:
                out_low.animateTo(-0.8, duration_ms=half_dur)
            if in_low:
                in_low.animateTo(0.0, duration_ms=duration_ms)

        elif "echo" in kind or "delay" in kind:
            # Beat FX: Echo / Delay Drop
            if hasattr(self, "crossfader"):
                self.crossfader.animateTo(target_xf, duration_ms=duration_ms)
            if out_low:
                out_low.animateTo(-1.0, duration_ms=half_dur)
            if hasattr(self, "beat_fx_rack"):
                self.beat_fx_rack.setFx("DELAY" if "delay" in kind else "ECHO")
                self.beat_fx_rack.setBeat("3/4" if "delay" in kind else "1/2")
                self.beat_fx_rack.setActive(True)

        elif "reverb" in kind:
            # Beat FX: Reverb Wash
            if hasattr(self, "crossfader"):
                self.crossfader.animateTo(target_xf, duration_ms=duration_ms)
            if out_filter:
                out_filter.animateTo(0.60, duration_ms=half_dur)
            if hasattr(self, "beat_fx_rack"):
                self.beat_fx_rack.setFx("REVERB")
                self.beat_fx_rack.setActive(True)

        else:
            # Smart Filter EQ / Blend estándar
            if hasattr(self, "crossfader"):
                self.crossfader.animateTo(target_xf, duration_ms=duration_ms)
            if out_low:
                out_low.animateTo(-0.9, duration_ms=int(duration_ms * 0.45))
            if out_mid:
                out_mid.animateTo(-0.4, duration_ms=int(duration_ms * 0.40))
            if out_filter:
                out_filter.animateTo(0.70, duration_ms=int(duration_ms * 0.60))
            if in_filter:
                in_filter.animateTo(0.0, duration_ms=int(duration_ms * 0.70))
            if in_low:
                in_low.animateTo(0.0, duration_ms=half_dur)

        def _reset_controls():
            if out_filter:
                out_filter.animateTo(0.0, duration_ms=400)
            if out_low:
                out_low.animateTo(0.0, duration_ms=400)
            if out_mid:
                out_mid.animateTo(0.0, duration_ms=400)
            if in_filter:
                in_filter.animateTo(0.0, duration_ms=400)
            if in_low:
                in_low.animateTo(0.0, duration_ms=400)
            if hasattr(self, "beat_fx_rack") and getattr(self.beat_fx_rack, "_is_active", False):
                self.beat_fx_rack.setActive(False)

        QTimer.singleShot(duration_ms + 150, _reset_controls)

    def _on_crossfader_moved(self, pos: float):
        self._apply_audio_gains()

    def _apply_audio_gains(self):
        if not self.main_window or not hasattr(self.main_window, "audio_output"):
            return
        pos = self.crossfader._pos if hasattr(self, "crossfader") else 0.0
        norm = (pos + 1.0) / 2.0
        curve_a = math.cos(norm * (math.pi / 2.0))
        curve_b = math.sin(norm * (math.pi / 2.0))

        # Asignación de crossfader por canal (A / THRU / B)
        if getattr(self, "_xf_assign_a", "A") == "THRU":
            xf_gain_a = 1.0
        elif getattr(self, "_xf_assign_a", "A") == "A":
            xf_gain_a = curve_a
        else:
            xf_gain_a = curve_b

        if getattr(self, "_xf_assign_b", "B") == "THRU":
            xf_gain_b = 1.0
        elif getattr(self, "_xf_assign_b", "B") == "B":
            xf_gain_b = curve_b
        else:
            xf_gain_b = curve_a

        f_a = self.fader_a._value if hasattr(self, "fader_a") else 1.0
        f_b = self.fader_b._value if hasattr(self, "fader_b") else 1.0

        trim_a = 1.0 + (self.knob_trim_a._value if hasattr(self, "knob_trim_a") else 0.0)
        trim_b = 1.0 + (self.knob_trim_b._value if hasattr(self, "knob_trim_b") else 0.0)

        master_vol = getattr(self, "_master_volume_val", 1.0) * getattr(self.main_window, "_volume_master", 1.0)
        if getattr(self, "_talkover_active", False):
            master_vol *= 0.35  # Ducking de -12 dB
        if getattr(self, "_pa_muted", False):
            master_vol = 0.0

        effective_a = max(0.0, min(1.0, f_a * trim_a * xf_gain_a * master_vol))
        effective_b = max(0.0, min(1.0, f_b * trim_b * xf_gain_b * master_vol))

        try:
            self.main_window.audio_output.setVolume(effective_a)
        except Exception:
            pass

        spare = getattr(self.main_window, "_spare_deck", None)
        if spare and len(spare) > 1 and spare[1]:
            try:
                spare[1].setVolume(effective_b)
            except Exception:
                pass
        out_deck = getattr(self.main_window, "_out_deck", None)
        if out_deck and len(out_deck) > 1 and out_deck[1]:
            try:
                out_deck[1].setVolume(effective_b)
            except Exception:
                pass

    def _on_eq_control_changed(self, _val: float = 0.0):
        if not self.main_window:
            return
        if not hasattr(self, "_eq_debounce_timer") or self._eq_debounce_timer is None:
            self._eq_debounce_timer = QTimer(self)
            self._eq_debounce_timer.setSingleShot(True)
            self._eq_debounce_timer.setInterval(75)
            self._eq_debounce_timer.timeout.connect(self._do_apply_eq)
        self._eq_debounce_timer.start()

    def _do_apply_eq(self):
        if not self.main_window:
            return
        bass_db = (self.knob_low_a._value if hasattr(self, "knob_low_a") else 0.0) * 12.0
        mid_db = (self.knob_mid_a._value if hasattr(self, "knob_mid_a") else 0.0) * 12.0
        treble_db = (self.knob_high_a._value if hasattr(self, "knob_high_a") else 0.0) * 12.0

        if getattr(self, "_subwoofer_boost", False):
            bass_db += 4.0

        filter_val = self.knob_filter_a._value if hasattr(self, "knob_filter_a") else 0.0
        cfx = getattr(self, "_current_color_fx", "FILTER")

        if cfx == "FILTER":
            if filter_val < 0.0:
                treble_db += filter_val * 24.0
                mid_db += filter_val * 8.0
            elif filter_val > 0.0:
                bass_db -= filter_val * 24.0
        elif cfx == "CRUSH":
            if filter_val != 0.0:
                mid_db += abs(filter_val) * 10.0
                treble_db -= abs(filter_val) * 14.0
        elif cfx == "SPACE":
            if filter_val != 0.0:
                treble_db += abs(filter_val) * 8.0
                mid_db += abs(filter_val) * 4.0
        elif cfx == "SWEEP":
            if filter_val < 0.0:
                bass_db += filter_val * 16.0
            elif filter_val > 0.0:
                mid_db += filter_val * 14.0
        elif cfx == "NOISE":
            if filter_val != 0.0:
                treble_db += abs(filter_val) * 12.0
        elif cfx == "DUB ECHO":
            if filter_val != 0.0:
                treble_db += abs(filter_val) * 6.0

        eq_data = {
            "enabled": True,
            "bass": round(max(-24.0, min(12.0, bass_db)), 1),
            "mid": round(max(-24.0, min(12.0, mid_db)), 1),
            "treble": round(max(-24.0, min(12.0, treble_db)), 1),
        }
        if hasattr(self.main_window, "on_eq_changed"):
            try:
                self.main_window.on_eq_changed(eq_data)
            except Exception:
                pass

    # -------------------------------------------------------------------------------------------------
    # Bucle de actualización visual y animación continua
    # -------------------------------------------------------------------------------------------------
    def _on_anim_frame(self):
        if not self.isVisible() or not self.main_window:
            return

        is_playing = False
        pos_ms = 0
        dur_ms = 0
        try:
            player = getattr(self.main_window, "player", None)
            if player and hasattr(player, "playbackState"):
                is_playing = (player.playbackState() == 1)
                pos_ms = player.position()
                dur_ms = player.duration()
        except Exception:
            pass

        # Actualizar visualizador superior de formas de onda duales (VirtualDJ Style)
        if hasattr(self, "waveform_display"):
            t_a = getattr(self, "_now_title_str", "") or (self.screen_a.title_lbl.text() if hasattr(self, "screen_a") else "Deck A")
            t_b = getattr(self, "_next_title_str", "") or (self.screen_b.title_lbl.text() if hasattr(self, "screen_b") else "Deck B")
            bpm_a = getattr(self, "_deck_a_bpm", 128.0)
            bpm_b = getattr(self, "_deck_b_bpm", 128.0)
            s_pos = 0
            s_dur = dur_ms
            spare = getattr(self.main_window, "_spare_deck", None)
            if spare and len(spare) > 0 and spare[0]:
                try:
                    s_pos = spare[0].position()
                    s_dur = spare[0].duration() or dur_ms
                except Exception:
                    pass
            elif hasattr(self, "_deck_b_sim_pos"):
                s_pos = self._deck_b_sim_pos
            self.waveform_display.updateDecks(
                title_a=t_a, bpm_a=bpm_a, pos_a=pos_ms, dur_a=dur_ms, playing_a=is_playing,
                title_b=t_b, bpm_b=bpm_b, pos_b=s_pos, dur_b=s_dur, playing_b=is_playing and getattr(self.main_window, "_xf_active", False)
            )

        # Actualizar display digital CDJ de Deck A
        if hasattr(self, "screen_a") and dur_ms > 0:
            self.screen_a.setTrackProgress(pos_ms, dur_ms)

        # Actualizar display digital CDJ de Deck B
        if hasattr(self, "screen_b"):
            spare = getattr(self.main_window, "_spare_deck", None)
            if spare and len(spare) > 0 and spare[0]:
                try:
                    s_pos = spare[0].position()
                    s_dur = spare[0].duration()
                    if s_dur > 0:
                        self.screen_b.setTrackProgress(s_pos, s_dur)
                except Exception:
                    pass

        # Monitor de Beat Loop en Deck A
        if getattr(self, "_loop_active_a", False) and self._loop_start_a is not None and self._loop_end_a is not None:
            try:
                p = self.main_window.player
                if p and p.playbackState() == 1:
                    if p.position() >= self._loop_end_a:
                        p.setPosition(self._loop_start_a)
            except Exception:
                pass

        # Slip Mode: si está activo y en reproducción, avanzamos la posición virtual
        if getattr(self, "_slip_a", False) and is_playing:
            self._slip_virtual_pos_a += 40

        # Jog wheels
        self.jog_a.setPlaying(is_playing)
        is_mixing = getattr(self.main_window, "_xf_active", False)
        self.jog_b.setPlaying(is_playing and is_mixing)

        # LED Play/Pause feedback
        self._blink_counter = (getattr(self, "_blink_counter", 0) + 1) % 20
        if hasattr(self, "btn_play_a"):
            if is_playing:
                self.btn_play_a.setStyleSheet("QPushButton { min-width: 0px; background-color: #1ED760; color: #000; font-weight: 900; border: 2px solid #1ED760; border-radius: 6px; padding: 6px 10px; font-size: 11px; }")
            else:
                bg = "#1A3828" if self._blink_counter < 10 else "#0F2016"
                self.btn_play_a.setStyleSheet(f"QPushButton {{ min-width: 0px; background-color: {bg}; color: #1ED760; font-weight: 900; border: 2px solid #1ED760; border-radius: 6px; padding: 6px 10px; font-size: 11px; }}")

        # Vúmetros
        if is_playing:
            base_vol = 0.65 + 0.25 * random.random()
            xf = (self.crossfader._pos + 1.0) / 2.0
            f_a = getattr(self.fader_a, "_value", 1.0)
            f_b = getattr(self.fader_b, "_value", 1.0)
            vol_a = base_vol * (1.0 - xf * 0.7) * f_a
            vol_b = base_vol * (xf if is_mixing else 0.05) * f_b

            self.vu_a.setLevels(vol_a, vol_a * 0.95)
            self.vu_b.setLevels(vol_b, vol_b * 0.95)
            self.vu_master.setLevels(max(vol_a, vol_b), max(vol_a, vol_b) * 0.96)
        else:
            self.vu_a.setLevels(0.0, 0.0)
            self.vu_b.setLevels(0.0, 0.0)
            self.vu_master.setLevels(0.0, 0.0)

    # -------------------------------------------------------------------------------------------------
    # Estado externo actualizado por DjMixin
    # -------------------------------------------------------------------------------------------------
    def set_source(self, text: str, blocked_count: int = 0):
        self.source.setText(text)
        if hasattr(self, "btn_unblock"):
            self.btn_unblock.setText(f"Desbloquear ({blocked_count})")
            self.btn_unblock.setVisible(blocked_count > 0)

    def set_progress(self, text: str):
        self.progress.setText(text)
        self.progress.setVisible(bool(text))

    def set_countdown(self, text: str):
        self.countdown.setText(text)

    def set_vote_target(self, text: str):
        self.vote_status.setText(text)

    def set_profile(self, profile: str):
        for k, b in self._profile_buttons.items():
            if k == profile:
                b.setStyleSheet("""
                    QPushButton {
                        background-color: #2E2E3E;
                        color: #1ED760;
                        border: 1px solid #1ED760;
                        border-radius: 13px;
                        padding: 4px 8px;
                        font-size: 11px;
                        font-weight: 900;
                    }
                """)
            else:
                b.setStyleSheet("""
                    QPushButton {
                        background-color: #22222A;
                        color: #CCCCCC;
                        border: 1px solid #333340;
                        border-radius: 13px;
                        padding: 4px 8px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover { background-color: #2D2D38; color: #FFFFFF; }
                """)

    def set_session(self, active: bool, current: dict = None, nxt: dict = None,
                    upcoming: list = None, remaining: int = 0, describe_fn=None):
        self.empty.setVisible(not active)
        self.session.setVisible(active)
        self.btn_start.setToolTip("Empezar de nuevo" if active else "Empezar sesión DJ")
        if not active or not current:
            self.screen_a.setTrack("Sin pista", "Pulsa 'Empezar sesión DJ'")
            self.screen_b.setTrack("En espera", "---")
            self.upcoming_list.clear()
            self._upcoming_paths = []
            self._upcoming_tracks_cache = []
            self.btn_start.setText(" Empezar sesión DJ")
            self.now_title.setText("")
            self.now_detail.setText("")
            self.next_title.setText("")
            return

        self.btn_start.setText(" Empezar de nuevo")

        # 1. Deck A (Pista actual que suena)
        self._now_path = current.get("local_path", "")
        title_a = current.get("title", os.path.basename(self._now_path) or "Pista A")
        self._now_title_str = title_a
        artist_a = current.get("uploader", current.get("artist", "Artista"))
        analysis_a = getattr(self.main_window, "_dj_analysis", {}).get(self._now_path, {})
        bpm_a = analysis_a.get("bpm") or current.get("bpm")
        key_a = analysis_a.get("tone") or current.get("key")
        self._deck_a_bpm = float(bpm_a) if bpm_a else 128.0
        self.screen_a.setTrack(title_a, artist_a, bpm_a, key_a, on_air=True)
        desc_a = describe_fn(current) if describe_fn else ""
        self.now_title.setText(title_a)
        self.now_detail.setText(desc_a)

        # 2. Deck B (Pista siguiente preparada para la mezcla)
        if nxt:
            self._next_path = nxt.get("local_path", "")
            title_b = nxt.get("title", os.path.basename(self._next_path) or "Pista B")
            self._next_title_str = title_b
            artist_b = nxt.get("uploader", nxt.get("artist", "Artista"))
            analysis_b = getattr(self.main_window, "_dj_analysis", {}).get(self._next_path, {})
            bpm_b = analysis_b.get("bpm") or nxt.get("bpm")
            key_b = analysis_b.get("tone") or nxt.get("key")
            self._deck_b_bpm = float(bpm_b) if bpm_b else 128.0
            self.screen_b.setTrack(title_b, artist_b, bpm_b, key_b, on_air=False)
            desc_b = describe_fn(nxt) if describe_fn else ""
            self.next_title.setText(f"{title_b} — {desc_b}" if desc_b else title_b)
        else:
            self.screen_b.setTrack("Fin de sesión", "No hay más pistas en la cola")

        # 3. Lista de canciones próximas
        self.upcoming_list.clear()
        self._upcoming_paths = [t.get("local_path", "") for t in (upcoming or [])]
        self._upcoming_tracks_cache = list(upcoming or [])
        if hasattr(self, "virtual_browser") and upcoming:
            self.virtual_browser.setTracks(list(upcoming))
        if upcoming:
            for idx, track in enumerate(upcoming[:UPCOMING_SHOWN]):
                t_title = track.get("title", "Desconocido")
                t_artist = track.get("uploader", track.get("artist", ""))
                p_path = track.get("local_path", "")
                an = getattr(self.main_window, "_dj_analysis", {}).get(p_path, {})
                t_bpm = an.get("bpm") or track.get("bpm", "")
                t_bpm_str = f" • {t_bpm:.0f} BPM" if t_bpm else ""
                t_key = an.get("tone") or track.get("key", "")
                t_key_str = f" • ♫ {t_key}" if t_key else ""
                desc = describe_fn(track) if describe_fn else ""
                desc_str = f" — {desc}" if desc else ""
                row_str = f"{idx + 1}.  {t_title} — {t_artist}{t_bpm_str}{t_key_str}{desc_str}"
                self.upcoming_list.addItem(row_str)

    # -------------------------------------------------------------------------------------------------
    # Métodos del Visualizador Superior de Formas de Onda y Beat Matching (VirtualDJ Style)
    # -------------------------------------------------------------------------------------------------
    def _on_juntar_beats(self):
        """Sincroniza y junta al compás exacto ambas canciones (Beatmatching y alineación de fase instantánea)."""
        bpm_a = max(30.0, getattr(self, "_deck_a_bpm", 128.0))
        bpm_b = max(30.0, getattr(self, "_deck_b_bpm", 128.0))

        # 1. Emparejar BPM con Pitch Fader de Deck B
        ratio = bpm_a / bpm_b
        target_pitch = (ratio - 1.0) * 100.0
        if hasattr(self, "pitch_b"):
            self.pitch_b.setPitch(target_pitch)
        self._deck_b_bpm = bpm_a

        # 2. Alinear la fase rítmica (desplazar pos_b para que su golpe caiga exactamente con el golpe de A)
        beat_ms = 60000.0 / bpm_a
        pos_a = self._get_deck_a_pos()
        pos_b = self._get_deck_b_pos()

        phase_a = pos_a % beat_ms
        current_beat_b = pos_b // beat_ms
        aligned_pos_b = int(current_beat_b * beat_ms + phase_a)
        if aligned_pos_b < 0:
            aligned_pos_b = int(phase_a)

        self._set_deck_b_pos(aligned_pos_b)

        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"🔗 Beats sincronizados: Deck B emparejado al golpe exacto a {bpm_a:.1f} BPM.")

    def _on_waveform_nudge(self, deck: str, delta_ms: int):
        if deck == "A":
            pos = self._get_deck_a_pos()
            self._set_deck_a_pos(max(0, pos + delta_ms))
        else:
            pos = self._get_deck_b_pos()
            self._set_deck_b_pos(max(0, pos + delta_ms))

    def _on_waveform_seek(self, deck: str, target_ms: int):
        if deck == "A":
            self._set_deck_a_pos(max(0, target_ms))
        else:
            self._set_deck_b_pos(max(0, target_ms))

    def _get_deck_a_pos(self) -> int:
        try:
            if self.main_window and hasattr(self.main_window, "player"):
                return self.main_window.player.position()
        except Exception:
            pass
        return getattr(self, "_deck_a_sim_pos", 0)

    def _set_deck_a_pos(self, pos_ms: int):
        try:
            if self.main_window and hasattr(self.main_window, "player"):
                self.main_window.player.setPosition(pos_ms)
                return
        except Exception:
            pass
        self._deck_a_sim_pos = pos_ms

    def _get_deck_b_pos(self) -> int:
        try:
            spare = getattr(self.main_window, "_spare_deck", None)
            if spare and len(spare) > 0 and spare[0]:
                return spare[0].position()
        except Exception:
            pass
        return getattr(self, "_deck_b_sim_pos", 0)

    def _set_deck_b_pos(self, pos_ms: int):
        try:
            spare = getattr(self.main_window, "_spare_deck", None)
            if spare and len(spare) > 0 and spare[0]:
                spare[0].setPosition(pos_ms)
                return
        except Exception:
            pass
        self._deck_b_sim_pos = pos_ms

    def _on_browser_load_deck(self, deck: str, item_dict: dict):
        if not item_dict:
            return
        title = item_dict.get("title", "Desconocido")
        artist = item_dict.get("uploader", item_dict.get("artist", ""))
        bpm = item_dict.get("bpm") or 128.0
        path = item_dict.get("local_path", "")

        if deck == "A":
            self._now_path = path
            self._now_title_str = title
            self._deck_a_bpm = float(bpm)
            if hasattr(self, "screen_a"):
                self.screen_a.setTrack(title, artist, bpm, None, on_air=True)
            if self.main_window and hasattr(self.main_window, "play_preview"):
                self.main_window.play_preview(item_dict)
        else:
            self._next_path = path
            self._next_title_str = title
            self._deck_b_bpm = float(bpm)
            if hasattr(self, "screen_b"):
                self.screen_b.setTrack(title, artist, bpm, None, on_air=False)
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify(f"Deck B: Cargada «{title}» ({bpm:.1f} BPM)")
