"""Página y Cabina de DJ Profesional: Simulación visual interactiva de mesa de mezclas.
Soporta:
- Plato A (Deck A) y Plato B (Deck B) con pantallas digitales de información (Título, Artista, BPM, Camelot Key, Tiempo).
- Vinilos/Jog Wheels animados y giratorios con carátula central.
- Controles de canal por deck: EQ de 3 bandas (Graves, Medios, Agudos), Filtro resonante (HPF/LPF), Fader de volumen y Vúmetros.
- Sección central de mezcla con Crossfader interactivo.
- Doble modo de operación:
  * Modo IA DJ (Automático): La IA planifica y mueve físicamente el crossfader, los filtros y los ecualizadores en pantalla al compás.
  * Modo Manual: El usuario puede mezclar a mano deslizando el crossfader y ajustando los knobs.
- Botón destacado de «🔥 Mezclar Ahora» para disparar la transición al instante sin esperar.
- Selector de perfiles simplificado (Club, Radio, Chill).
- Lista inferior de canciones preparadas para pinchar.
"""
import os
import math
import random
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QListWidget, QAbstractItemView, QMenu, QScrollArea, QSizePolicy
)

from services.transition_votes import TAGS
from ui.dj_votes_mixin import TAG_LABELS
from ui.icons import icon
from ui.widgets import ElidedLabel
from ui.dj_components import DjRotaryKnob, DjJogWheel, DjVuMeter, DjCrossfader, DjFader

UPCOMING_SHOWN = 30
COMPACT_MIN_W = 50


class DeckScreen(QFrame):
    """Pantalla digital estilo CDJ / DJ controller con información de pista, BPM, Camelot y forma de onda."""
    def __init__(self, deck_label="DECK A", accent_color="#1ED760", parent=None):
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
        self.setMinimumHeight(75)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Barra superior de la pantalla: etiqueta de Deck y estado ON AIR
        top_row = QHBoxLayout()
        self.deck_tag = QLabel(deck_label)
        self.deck_tag.setStyleSheet(f"font-size: 11px; font-weight: 900; color: {accent_color}; letter-spacing: 1.5px; background: transparent;")
        top_row.addWidget(self.deck_tag)

        self.on_air_badge = QLabel("• EN EL AIRE")
        self.on_air_badge.setStyleSheet("font-size: 9px; font-weight: 800; color: #FF3344; background: #331015; border-radius: 3px; padding: 1px 4px;")
        self.on_air_badge.setVisible(False)
        top_row.addWidget(self.on_air_badge)
        top_row.addStretch()

        self.time_lbl = QLabel("-00:00")
        self.time_lbl.setStyleSheet("font-size: 12px; font-weight: 800; color: #FFFFFF; font-family: monospace; background: transparent;")
        top_row.addWidget(self.time_lbl)
        layout.addLayout(top_row)

        # Título y artista
        self.title_lbl = ElidedLabel("Sin pista cargada")
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
        tech_row.addWidget(self.bpm_box)

        self.key_box = QLabel("--- KEY")
        self.key_box.setStyleSheet("font-size: 11px; font-weight: 800; color: #E0E0FF; background: #222235; border-radius: 4px; padding: 2px 6px;")
        tech_row.addWidget(self.key_box)

        self.pitch_box = QLabel("±0.0%")
        self.pitch_box.setStyleSheet("font-size: 10px; font-weight: 700; color: #888899; background: transparent;")
        tech_row.addWidget(self.pitch_box)

        tech_row.addStretch()
        layout.addLayout(tech_row)

        # Mini barra de progreso / forma de onda simulada
        self.progress_bar = QFrame()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setStyleSheet("""
            QFrame {
                background-color: #22222A;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)

    def setTrack(self, title: str, artist: str, bpm: float = None, key: str = None, on_air: bool = False, time_str: str = "-00:00"):
        self.title_lbl.setText(title or "Sin pista cargada")
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
        self.btn_fx_freeze = QPushButton("Echo Freeze: OFF")
        self.btn_fx_reverb = QPushButton("Reverb: OFF")
        self.btn_fx_echo = QPushButton("Eco Tape: OFF")
        self.btn_fx_pingpong = QPushButton("Ping-Pong")

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
        scroll_lay.setSpacing(14)

        # 1. Cabecera y Barra de Control General
        self._build_top_bar(scroll_lay)

        # 2. Chasis de la Mesa de DJ (Dual Decks + Mixer Central)
        self._build_console(scroll_lay)

        # 3. Lista de Canciones Próximas & Opciones Rápidas
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
        self.title_lbl = QLabel("Mesa DJ Inteligente")
        self.title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #FFFFFF;")
        title_box.addWidget(self.title_lbl)

        self.source = QLabel("Carpeta de música...")
        self.source.setStyleSheet("font-size: 11px; color: #A0A0B0;")
        title_box.addWidget(self.source)
        row1.addLayout(title_box, 1)

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

        self.btn_auto_mode = QPushButton(" 🤖 Auto DJ: ON")
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
        self.btn_prof_club = QPushButton("🎧 Club")
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

        row2.addStretch()

        # Botón Cambiar carpeta
        self.btn_folder = QPushButton(" Carpeta")
        self.btn_folder.setIcon(icon("folder.svg", "#CCCCCC"))
        self.btn_folder.setObjectName("TopPillBtn")
        self.btn_folder.setCursor(Qt.PointingHandCursor)
        self.btn_folder.setStyleSheet("""
            QPushButton {
                background-color: #22222A;
                color: #CCCCCC;
                border: 1px solid #333340;
                border-radius: 13px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #2D2D38; color: #FFFFFF; }
        """)
        self.btn_folder.clicked.connect(self.folder_requested.emit)
        row2.addWidget(self.btn_folder)

        top_lay.addLayout(row2)
        layout.addWidget(top_card)

        # Subtítulo de progreso del análisis
        self.progress = QLabel("")
        self.progress.setStyleSheet("font-size: 11px; color: #1ED760; padding-left: 4px;")
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

    def _toggle_auto_mode(self):
        self._auto_mode = not self._auto_mode
        if self._auto_mode:
            self.btn_auto_mode.setText(" 🤖 DJ Automático: ON")
            self.btn_auto_mode.setStyleSheet("""
                QPushButton {
                    background-color: #1A3828;
                    color: #1ED760;
                    font-weight: 800;
                    border: 1px solid #1ED760;
                    border-radius: 16px;
                    padding: 6px 14px;
                }
                QPushButton:hover { background-color: #244C36; }
            """)
            if self.main_window and hasattr(self.main_window, "notify"):
                self.main_window.notify("DJ Automático activado: la IA moverá los platos, filtros y crossfader sola.")
        else:
            self.btn_auto_mode.setText(" 🎛️ Mezclador Manual")
            self.btn_auto_mode.setStyleSheet("""
                QPushButton {
                    background-color: #382A1A;
                    color: #FFAA33;
                    font-weight: 800;
                    border: 1px solid #FFAA33;
                    border-radius: 16px;
                    padding: 6px 14px;
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

        # ===== PLATO A (IZQUIERDA) =====
        self.deck_a_frame = self._build_deck_side("DECK A", "#1ED760", is_deck_a=True)

        # ===== MEZCLADOR CENTRAL (MIXER & CROSSFADER) =====
        self.mixer_frame = self._build_mixer_center()

        # ===== PLATO B (DERECHA) =====
        self.deck_b_frame = self._build_deck_side("DECK B", "#FF7700", is_deck_a=False)

        # Inicializar en modo adaptativo según el ancho actual
        self._apply_responsive_layout(self.width() or 1000)

        layout.addWidget(self.console_box)

    def _build_deck_side(self, name: str, accent: str, is_deck_a: bool) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #14141A;
                border: 1px solid #22222D;
                border-radius: 10px;
            }
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Pantalla digital del deck
        screen = DeckScreen(name, accent)
        if is_deck_a:
            self.screen_a = screen
        else:
            self.screen_b = screen
        lay.addWidget(screen)

        # Sección central del plato: Jog Wheel + Tira de Ecualización / Filtro
        center_row = QHBoxLayout()
        center_row.setSpacing(8)

        # Jog Wheel giratorio
        jog = DjJogWheel(name, accent)
        if is_deck_a:
            self.jog_a = jog
        else:
            self.jog_b = jog
        center_row.addWidget(jog, 1)

        # Columna de potenciómetros (EQ + Filter)
        eq_box = QVBoxLayout()
        eq_box.setSpacing(2)
        knob_high = DjRotaryKnob("HIGH", accent_color=accent)
        knob_mid = DjRotaryKnob("MID", accent_color=accent)
        knob_low = DjRotaryKnob("LOW", accent_color=accent)
        knob_filter = DjRotaryKnob("FILTER", accent_color="#00D2FF" if is_deck_a else "#FF0055", unit="%")

        if is_deck_a:
            self.knob_high_a, self.knob_mid_a, self.knob_low_a, self.knob_filter_a = (
                knob_high, knob_mid, knob_low, knob_filter
            )
        else:
            self.knob_high_b, self.knob_mid_b, self.knob_low_b, self.knob_filter_b = (
                knob_high, knob_mid, knob_low, knob_filter
            )

        for k in (knob_high, knob_mid, knob_low, knob_filter):
            eq_box.addWidget(k)
        center_row.addLayout(eq_box)

        # Columna de fader de volumen + vúmetro del canal
        ch_box = QHBoxLayout()
        ch_box.setSpacing(2)
        fader = DjFader(f"CH {1 if is_deck_a else 2}", accent_color=accent)
        vu = DjVuMeter()
        if is_deck_a:
            self.fader_a, self.vu_a = fader, vu
        else:
            self.fader_b, self.vu_b = fader, vu
        ch_box.addWidget(fader)
        ch_box.addWidget(vu)
        center_row.addLayout(ch_box)

        lay.addLayout(center_row)

        # Botones de transporte y rendimiento en dos filas compactas
        transport_box = QVBoxLayout()
        transport_box.setSpacing(4)

        transport_row1 = QHBoxLayout()
        transport_row1.setSpacing(4)

        btn_play = QPushButton(" ▶ PLAY")
        btn_play.setCursor(Qt.PointingHandCursor)
        btn_play.setStyleSheet(f"""
            QPushButton {{
                min-width: 0px;
                background-color: #1A3828;
                color: #FFFFFF;
                font-weight: bold;
                border: 2px solid {accent};
                border-radius: 5px;
                padding: 4px 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #244C36; }}
        """)
        btn_cue = QPushButton("CUE")
        btn_cue.setCursor(Qt.PointingHandCursor)
        btn_cue.setStyleSheet("""
            QPushButton {{
                min-width: 0px;
                background-color: #382A1A;
                color: #FFAA33;
                font-weight: bold;
                border: 2px solid #FFAA33;
                border-radius: 5px;
                padding: 4px 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #4C3824; }}
        """)
        btn_sync = QPushButton("SYNC")
        btn_sync.setCursor(Qt.PointingHandCursor)
        btn_sync.setStyleSheet("""
            QPushButton {{
                min-width: 0px;
                background-color: #1A2438;
                color: #44AAFF;
                font-weight: bold;
                border: 1px solid #44AAFF;
                border-radius: 5px;
                padding: 4px 6px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #24344C; }}
        """)

        if is_deck_a:
            self.btn_play_a, self.btn_cue_a, self.btn_sync_a = btn_play, btn_cue, btn_sync
            btn_play.clicked.connect(self._on_play_a_clicked)
            btn_cue.clicked.connect(lambda: self._on_cue_clicked("A"))
            btn_sync.clicked.connect(lambda: self._on_sync_clicked("A"))
        else:
            self.btn_play_b, self.btn_cue_b, self.btn_sync_b = btn_play, btn_cue, btn_sync
            btn_play.clicked.connect(self._on_play_b_clicked)
            btn_cue.clicked.connect(lambda: self._on_cue_clicked("B"))
            btn_sync.clicked.connect(lambda: self._on_sync_clicked("B"))

        transport_row1.addWidget(btn_play, 2)
        transport_row1.addWidget(btn_cue, 1)
        transport_row1.addWidget(btn_sync, 1)
        transport_box.addLayout(transport_row1)

        # Fila 2: FX Rápidos por Deck (Delay / Reverb)
        transport_row2 = QHBoxLayout()
        transport_row2.setSpacing(4)

        btn_fx_delay = QPushButton("DELAY")
        btn_fx_delay.setCursor(Qt.PointingHandCursor)
        btn_fx_delay.setStyleSheet("QPushButton { min-width: 0px; background-color: #22222E; color: #BBB; border-radius: 4px; font-size: 10px; padding: 4px 6px; }")
        btn_fx_delay.clicked.connect(lambda: self.fx_changed.emit("delay", {"beats": 0.75, "active": True}))

        btn_fx_reverb = QPushButton("WASH")
        btn_fx_reverb.setCursor(Qt.PointingHandCursor)
        btn_fx_reverb.setStyleSheet("QPushButton { min-width: 0px; background-color: #22222E; color: #BBB; border-radius: 4px; font-size: 10px; padding: 4px 6px; }")
        btn_fx_reverb.clicked.connect(self.washout_requested.emit)

        transport_row2.addWidget(btn_fx_delay)
        transport_row2.addWidget(btn_fx_reverb)
        transport_box.addLayout(transport_row2)

        lay.addLayout(transport_box)
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
        self.mixer_layout.setContentsMargins(10, 10, 10, 10)
        self.mixer_layout.setSpacing(8)

        # Cabecera Mixer
        self.mixer_cap = QLabel("CENTRO DE CONTROL & MEZCLA")
        self.mixer_cap.setStyleSheet("font-size: 10px; font-weight: 900; color: #777788; letter-spacing: 1.5px;")
        self.mixer_cap.setAlignment(Qt.AlignCenter)

        # HUD Estado IA DJ
        self.hud_frame = QFrame()
        self.hud_frame.setStyleSheet("""
            QFrame {
                background-color: #0A0A0E;
                border: 1px solid #00E5FF;
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

        # Vúmetro Máster Central
        self.vu_master = DjVuMeter()

        # Botón gigante MEZCLAR AHORA (IA)
        self.btn_auto_mix = QPushButton("🔥 MEZCLAR AHORA")
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
        self.btn_auto_mix.setToolTip("Dispara la transición inmediatamente al compás usando filtros y efectos calculados.")
        self.btn_auto_mix.clicked.connect(self._on_auto_mix_clicked)

        # CROSSFADER INTERACTIVO
        self.xf_cap = QLabel("CROSSFADER (PLATO A ◄—► B)")
        self.xf_cap.setStyleSheet("font-size: 9px; font-weight: 800; color: #888899; letter-spacing: 1px;")
        self.xf_cap.setAlignment(Qt.AlignCenter)

        self.crossfader = DjCrossfader()
        self.crossfader.positionChanged.connect(self._on_crossfader_moved)

        # Botones rápidos de ayuda a la mezcla
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

    def _rebuild_mixer(self, is_wide: bool):
        """Adapta la disposición interna del mezclador central según la pantalla."""
        while self.mixer_layout.count():
            item = self.mixer_layout.takeAt(0)
            sub = item.layout()
            if sub:
                while sub.count():
                    sub.takeAt(0)

        if is_wide:
            self.mixer_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            self.mixer_layout.addWidget(self.mixer_cap)
            self.mixer_layout.addWidget(self.hud_frame)

            master_vu_row = QHBoxLayout()
            master_vu_row.addStretch()
            master_vu_row.addWidget(self.vu_master)
            master_vu_row.addStretch()
            self.mixer_layout.addLayout(master_vu_row)

            self.mixer_layout.addWidget(self.btn_auto_mix)
            self.mixer_layout.addSpacing(4)
            self.mixer_layout.addWidget(self.xf_cap)
            self.mixer_layout.addWidget(self.crossfader)
            self.mixer_layout.addWidget(self.quick_btns_box)
        else:
            self.mixer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            # En modo compacto: Fila superior horizontal de control y Crossfader ancho abajo
            top_row = QHBoxLayout()
            top_row.setContentsMargins(0, 0, 0, 0)
            top_row.setSpacing(8)

            top_row.addWidget(self.hud_frame, 3)

            # VU Master + Botón Mezclar Ahora en el centro
            mid_col = QVBoxLayout()
            mid_col.setSpacing(3)
            vu_sub = QHBoxLayout()
            vu_sub.addStretch()
            vu_sub.addWidget(self.vu_master)
            vu_sub.addStretch()
            mid_col.addLayout(vu_sub)
            mid_col.addWidget(self.btn_auto_mix)
            top_row.addLayout(mid_col, 2)

            self.mixer_layout.addLayout(top_row)
            self.mixer_layout.addWidget(self.xf_cap)
            self.mixer_layout.addWidget(self.crossfader)
            self.mixer_layout.addWidget(self.quick_btns_box)

            self.mixer_layout.addWidget(self.xf_cap)
            self.mixer_layout.addWidget(self.crossfader)

    def _apply_responsive_layout(self, width: int):
        """Conmuta dinámicamente entre modo apaisado completo (3 columnas) y compacto (2 niveles)."""
        target_mode = "wide" if width >= 920 else "compact"
        if self._current_layout_mode == target_mode:
            return
        self._current_layout_mode = target_mode

        # Vaciar layout principal del chasis
        while self.console_box_layout.count():
            item = self.console_box_layout.takeAt(0)
            sub_lay = item.layout()
            if sub_lay:
                while sub_lay.count():
                    sub_lay.takeAt(0)

        # Reconstruir mixer para el modo
        self._rebuild_mixer(is_wide=(target_mode == "wide"))

        if target_mode == "wide":
            wide_row = QHBoxLayout()
            wide_row.setContentsMargins(0, 0, 0, 0)
            wide_row.setSpacing(12)
            wide_row.addWidget(self.deck_a_frame, 3)
            wide_row.addWidget(self.mixer_frame, 2)
            wide_row.addWidget(self.deck_b_frame, 3)
            self.console_box_layout.addLayout(wide_row)
        else:
            decks_row = QHBoxLayout()
            decks_row.setContentsMargins(0, 0, 0, 0)
            decks_row.setSpacing(10)
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

        # Cabecera y acciones de cola
        head_box = QVBoxLayout()
        head_box.setSpacing(6)

        head_row1 = QHBoxLayout()
        tray_title = QLabel("PRÓXIMAS PISTAS DE LA SESIÓN DJ")
        tray_title.setStyleSheet("font-size: 11px; font-weight: 900; color: #FFFFFF; letter-spacing: 1px;")
        head_row1.addWidget(tray_title)
        head_row1.addStretch()
        head_box.addLayout(head_row1)

        head_row2 = QHBoxLayout()
        head_row2.setSpacing(6)

        self.btn_skip = QPushButton(" Saltar")
        self.btn_skip.setIcon(icon("next.svg", "#CCC"))
        self.btn_skip.setCursor(Qt.PointingHandCursor)
        self.btn_skip.setStyleSheet("QPushButton { background-color: #22222E; color: #DDD; font-size: 11px; border-radius: 5px; padding: 4px 8px; }")
        self.btn_skip.clicked.connect(self.skip_requested.emit)
        head_row2.addWidget(self.btn_skip)

        self.btn_drop = QPushButton(" Quitar")
        self.btn_drop.setIcon(icon("x.svg", "#CCC"))
        self.btn_drop.setCursor(Qt.PointingHandCursor)
        self.btn_drop.setStyleSheet("QPushButton { background-color: #22222E; color: #DDD; font-size: 11px; border-radius: 5px; padding: 4px 8px; }")
        self.btn_drop.clicked.connect(self.drop_next_requested.emit)
        head_row2.addWidget(self.btn_drop)

        self.btn_shuffle = QPushButton(" Barajar")
        self.btn_shuffle.setIcon(icon("shuffle.svg", "#CCC"))
        self.btn_shuffle.setCursor(Qt.PointingHandCursor)
        self.btn_shuffle.setStyleSheet("QPushButton { background-color: #22222E; color: #DDD; font-size: 11px; border-radius: 5px; padding: 4px 8px; }")
        self.btn_shuffle.clicked.connect(self.reshuffle_requested.emit)
        head_row2.addWidget(self.btn_shuffle)

        self.btn_block = QPushButton(" Bloquear")
        self.btn_block.setIcon(icon("offline.svg", "#CCC"))
        self.btn_block.setCursor(Qt.PointingHandCursor)
        self.btn_block.setStyleSheet("QPushButton { background-color: #22222E; color: #DDD; font-size: 11px; border-radius: 5px; padding: 4px 8px; }")
        self.btn_block.clicked.connect(self.block_requested.emit)
        head_row2.addWidget(self.btn_block)
        head_row2.addStretch()

        head_box.addLayout(head_row2)
        tray_lay.addLayout(head_box)

        # Lista de canciones próximas
        self.upcoming_list = QListWidget()
        self.upcoming_list.setObjectName("QueueList")
        self.upcoming_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.upcoming_list.setFocusPolicy(Qt.NoFocus)
        self.upcoming_list.setMaximumHeight(160)
        self.upcoming_list.setStyleSheet("""
            QListWidget {
                background: #0E0E12;
                border: 1px solid #1E1E26;
                border-radius: 6px;
                color: #DDD;
                font-size: 13px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #16161E;
            }
            QListWidget::item:hover {
                background-color: #1A1A24;
            }
        """)
        tray_lay.addWidget(self.upcoming_list)

        # Fila de valoración de la mezcla
        vote_row = QHBoxLayout()
        vote_row.setSpacing(6)
        vote_title = QLabel("Calificar:")
        vote_title.setStyleSheet("font-weight: 700; color: #BBB; font-size: 11px;")
        vote_row.addWidget(vote_title)

        self.btn_up = QPushButton("👍 Buena")
        self.btn_up.setCursor(Qt.PointingHandCursor)
        self.btn_up.setStyleSheet("QPushButton { background-color: #1A3828; color: #1ED760; border-radius: 5px; padding: 4px 10px; font-weight: bold; font-size: 11px; }")
        self.btn_up.clicked.connect(lambda: self.vote_requested.emit(1, []))
        vote_row.addWidget(self.btn_up)

        self.btn_down = QPushButton("👎 Mala")
        self.btn_down.setCursor(Qt.PointingHandCursor)
        self.btn_down.setStyleSheet("QPushButton { background-color: #381A20; color: #FF4455; border-radius: 5px; padding: 4px 10px; font-weight: bold; font-size: 11px; }")
        self.btn_down.clicked.connect(lambda: self.vote_requested.emit(-1, []))
        vote_row.addWidget(self.btn_down)
        vote_row.addStretch()
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
    # Manejadores de interacción y acciones de Deck
    # -------------------------------------------------------------------------------------------------
    def _on_play_a_clicked(self):
        if self.main_window and hasattr(self.main_window, "player"):
            if self.main_window.player.playbackState() == 1:  # Playing
                self.main_window.player.pause()
            else:
                self.main_window.player.play()

    def _on_play_b_clicked(self):
        # En modo DJ, Plato B entra al disparar la mezcla
        self._on_auto_mix_clicked()

    def _on_cue_clicked(self, deck: str):
        if self.main_window and hasattr(self.main_window, "player"):
            self.main_window.player.setPosition(0)
            self.main_window.notify(f"Deck {deck} rebobinado a CUE (00:00)")

    def _on_sync_clicked(self, deck: str):
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify(f"Deck {deck} sincronizado al compás de la mezcla (SYNC Lock ON)")

    def _on_auto_mix_clicked(self):
        """Dispara la mezcla inmediata por IA con animación visual en los controles."""
        self.auto_mix_requested.emit()
        self.skip_requested.emit()
        if self.main_window and hasattr(self.main_window, "notify"):
            self.main_window.notify("¡Mezclando ahora! La IA ejecuta transición armónica al compás.")

        # Si el modo automático está activo, simular la transición física del crossfader y filtros
        if self._auto_mode:
            current_xf = self.crossfader._pos
            target_xf = 1.0 if current_xf < 0.0 else -1.0
            self.crossfader.animateTo(target_xf, duration_ms=2500)
            self.knob_filter_a.animateTo(0.65, duration_ms=1200)
            self.knob_low_a.animateTo(-0.8, duration_ms=1800)
            QTimer.singleShot(2500, lambda: self.knob_filter_a.animateTo(0.0, duration_ms=600))
            QTimer.singleShot(2500, lambda: self.knob_low_a.animateTo(0.0, duration_ms=600))

    def _on_crossfader_moved(self, pos: float):
        """Ajusta las ganancias de canal según la posición del crossfader (-1.0 a +1.0)."""
        # Curva de potencia constante para la mezcla
        norm = (pos + 1.0) / 2.0  # 0.0 (Deck A) a 1.0 (Deck B)
        gain_a = math.cos(norm * (math.pi / 2.0))
        gain_b = math.sin(norm * (math.pi / 2.0))

        self.fader_a.setValue(gain_a)
        self.fader_b.setValue(gain_b)

    # -------------------------------------------------------------------------------------------------
    # Bucle de actualización visual y animación continua
    # -------------------------------------------------------------------------------------------------
    def _on_anim_frame(self):
        """Frame de animación: hace girar los vinilos si hay reproducción y anima los vúmetros."""
        if not self.isVisible() or not self.main_window:
            return

        is_playing = False
        try:
            player = getattr(self.main_window, "player", None)
            if player and hasattr(player, "playbackState"):
                is_playing = (player.playbackState() == 1)  # QMediaPlayer.PlayingState
        except Exception:
            pass

        # Girar vinilos según estado
        self.jog_a.setPlaying(is_playing)
        is_mixing = getattr(self.main_window, "_xf_active", False)
        self.jog_b.setPlaying(is_playing and is_mixing)

        # Animar vúmetros con dinámica natural
        if is_playing:
            base_vol = 0.65 + 0.25 * random.random()
            xf = (self.crossfader._pos + 1.0) / 2.0
            vol_a = base_vol * (1.0 - xf * 0.7)
            vol_b = base_vol * (xf if is_mixing else 0.05)

            self.vu_a.setLevels(vol_a, vol_a * 0.95)
            self.vu_b.setLevels(vol_b, vol_b * 0.92)
            self.vu_master.setLevels(max(vol_a, vol_b), max(vol_a, vol_b) * 0.97)
        else:
            self.vu_a.setLevels(0.0, 0.0)
            self.vu_b.setLevels(0.0, 0.0)
            self.vu_master.setLevels(0.0, 0.0)

    # -------------------------------------------------------------------------------------------------
    # Métodos llamados por dj_mixin.py para actualizar el estado
    # -------------------------------------------------------------------------------------------------
    def set_source(self, text: str, blocked_count: int = 0):
        self.source.setText(text)

    def set_progress(self, text: str):
        if text:
            self.progress.setText(text)
            self.progress.setVisible(True)
        else:
            self.progress.setVisible(False)

    def _cycle_filter(self):
        modes = ["OFF", "HPF", "LPF"]
        cur = self._fx_state.get("filter_mode", "OFF")
        nxt = modes[(modes.index(cur) + 1) % len(modes)]
        self._fx_state["filter_mode"] = nxt
        self.btn_fx_filter.setText(f"Filtro: {nxt}")
        self.btn_fx_filter.setStyleSheet("QPushButton { background: #1ED760; color: #000000; font-weight: bold; }" if nxt != "OFF" else "")
        self.fx_changed.emit("filter", {"mode": nxt.lower(), "q": 1.5})

    def _cycle_delay(self):
        times = ["3/4", "1/2", "1T", "OFF"]
        cur = self._fx_state.get("delay_time", "OFF")
        nxt = times[(times.index(cur) + 1) % len(times)]
        self._fx_state["delay_time"] = nxt
        self.btn_fx_delay.setText(f"Delay: {nxt}")
        self.btn_fx_delay.setStyleSheet("QPushButton { background: #1ED760; color: #000000; font-weight: bold; }" if nxt != "OFF" else "")
        self.fx_changed.emit("delay", {"beats": nxt, "active": nxt != "OFF"})

    def _toggle_pingpong(self):
        cur = self._fx_state.get("ping_pong", True)
        nxt = not cur
        self._fx_state["ping_pong"] = nxt
        self.btn_fx_pingpong.setStyleSheet("QPushButton { background: #1ED760; color: #000000; font-weight: bold; }" if nxt else "")
        self.fx_changed.emit("ping_pong", {"enabled": nxt})

    def _toggle_echo(self):
        cur = self._fx_state.get("echo_active", False)
        nxt = not cur
        self._fx_state["echo_active"] = nxt
        self.btn_fx_echo.setText(f"Eco Tape: {'ON' if nxt else 'OFF'}")
        self.btn_fx_echo.setStyleSheet("QPushButton { background: #1ED760; color: #000000; font-weight: bold; }" if nxt else "")
        self.fx_changed.emit("echo", {"active": nxt})

    def _toggle_freeze(self):
        cur = self._fx_state.get("freeze_active", False)
        nxt = not cur
        self._fx_state["freeze_active"] = nxt
        self.btn_fx_freeze.setStyleSheet("QPushButton { background: #38ef7d; color: #000000; font-weight: bold; }" if nxt else "")
        self.freeze_requested.emit(nxt)

    def _toggle_reverb(self):
        cur = self._fx_state.get("reverb_active", False)
        nxt = not cur
        self._fx_state["reverb_active"] = nxt
        self.btn_fx_reverb.setText(f"Reverb: {'ON' if nxt else 'OFF'}")
        self.btn_fx_reverb.setStyleSheet("QPushButton { background: #1ED760; color: #000000; font-weight: bold; }" if nxt else "")
        self.fx_changed.emit("reverb", {"active": nxt})

    def set_countdown(self, text: str):
        self.countdown.setText(text or "En pausa")
        if "Mezclando" in text or "mezcla" in text.lower():
            self.hud_tag.setText("⚡ TRANSICIÓN IA EN CURSO")
            self.hud_tag.setStyleSheet("font-size: 9px; font-weight: 800; color: #1ED760; letter-spacing: 1px;")
        else:
            self.hud_tag.setText("ESTADO DE MEZCLA (IA)")
            self.hud_tag.setStyleSheet("font-size: 9px; font-weight: 800; color: #00E5FF; letter-spacing: 1px;")

    def set_vote_target(self, text: str):
        self.vote_status.setText(text or "")

    def set_profile(self, profile: str):
        p = (profile or "club").lower()
        for name, btn in self._profile_buttons.items():
            if name == p:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1ED760;
                        color: #000000;
                        border: 1px solid #1ED760;
                        border-radius: 14px;
                        padding: 5px 12px;
                        font-size: 12px;
                        font-weight: 800;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #22222A;
                        color: #CCCCCC;
                        border: 1px solid #333340;
                        border-radius: 14px;
                        padding: 5px 12px;
                        font-size: 12px;
                        font-weight: bold;
                    }
                    QPushButton:hover { background-color: #2D2D38; color: #FFFFFF; }
                """)

    def set_session(self, active: bool, current: dict = None, nxt: dict = None,
                    upcoming: list = None, remaining: int = 0, describe_fn=None):
        """Pone al día la información técnica de Deck A, Deck B y la cola."""
        if not active or not current:
            self.screen_a.setTrack("Sin pista", "Pulsa «Empezar sesión DJ»")
            self.screen_b.setTrack("En espera", "---")
            self.upcoming_list.clear()
            self.btn_start.setText(" Empezar sesión DJ")
            return

        self.btn_start.setText(" Sesión DJ en marcha")

        # 1. Deck A (Pista actual que suena)
        self._now_path = current.get("local_path", "")
        title_a = current.get("title", os.path.basename(self._now_path) or "Pista A")
        artist_a = current.get("uploader", current.get("artist", "Artista"))
        analysis_a = getattr(self.main_window, "_dj_analysis", {}).get(self._now_path, {})
        bpm_a = analysis_a.get("bpm") or current.get("bpm")
        key_a = analysis_a.get("tone") or current.get("key")
        self.screen_a.setTrack(title_a, artist_a, bpm_a, key_a, on_air=True)

        # 2. Deck B (Pista siguiente preparada para la mezcla)
        if nxt:
            self._next_path = nxt.get("local_path", "")
            title_b = nxt.get("title", os.path.basename(self._next_path) or "Pista B")
            artist_b = nxt.get("uploader", nxt.get("artist", "Artista"))
            analysis_b = getattr(self.main_window, "_dj_analysis", {}).get(self._next_path, {})
            bpm_b = analysis_b.get("bpm") or nxt.get("bpm")
            key_b = analysis_b.get("tone") or nxt.get("key")
            self.screen_b.setTrack(title_b, artist_b, bpm_b, key_b, on_air=False)
        else:
            self.screen_b.setTrack("Fin de sesión", "No hay más pistas en la cola")

        # 3. Lista de canciones próximas
        self.upcoming_list.clear()
        if upcoming:
            for idx, track in enumerate(upcoming[:UPCOMING_SHOWN]):
                t_title = track.get("title", "Desconocido")
                t_artist = track.get("uploader", track.get("artist", ""))
                p_path = track.get("local_path", "")
                an = getattr(self.main_window, "_dj_analysis", {}).get(p_path, {})
                t_bpm = an.get("bpm") or track.get("bpm", "")
                t_bpm_str = f" · {t_bpm:.0f} BPM" if t_bpm else ""
                t_key = an.get("tone") or track.get("key", "")
                t_key_str = f" · ⚡ {t_key}" if t_key else ""
                row_str = f"{idx + 1}.  {t_title} — {t_artist}{t_bpm_str}{t_key_str}"
                self.upcoming_list.addItem(row_str)
