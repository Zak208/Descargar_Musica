"""Construye la barra de reproducción inferior."""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)

from ui.animations import press_feedback
from ui.controls import CoverLabel, DotButton, PlayPauseButton
from ui.osd import Osd
from ui.sliders import SmoothSlider
from ui.textfx import FixedDigitsLabel, SwapLabel

from ui.styles import THEME_CONFIGS
from ui.icons import icon
from ui.visualizer_widget import AudioVisualizerWidget

from ui.common import resource_path


def central_parent_of(window):
    return window.centralWidget() if window.centralWidget() is not None else window


def build_player_bar(self):
    """Construye la barra de reproducción inferior."""
    # --- REPRODUCTOR INFERIOR ---
    self.player_bar = QFrame()
    self.player_bar.setObjectName("PlayerBar")
    self.player_bar.setFixedHeight(92)
    self.player_bar.setVisible(False)

    player_layout = QHBoxLayout(self.player_bar)
    player_layout.setContentsMargins(20, 8, 20, 8)
    player_layout.setSpacing(16)

    # Info Canción
    self.info_widget = QWidget()
    info_widget_layout = QHBoxLayout(self.info_widget)
    info_widget_layout.setContentsMargins(0, 0, 0, 0)
    info_widget_layout.setSpacing(10)

    self.player_thumb = CoverLabel(radius=6, placeholder="#1E1E1E")
    self.player_thumb.setFixedSize(56, 56)
    self.player_thumb.setStyleSheet("background-color: #1E1E1E; border-radius: 6px;")
    info_widget_layout.addWidget(self.player_thumb)

    info_text_layout = QVBoxLayout()
    info_text_layout.setAlignment(Qt.AlignVCenter)
    info_text_layout.setSpacing(2)

    self.player_title = SwapLabel("Cargando...")
    self.player_title.setObjectName("PlayerTitle")
    self.player_title.setWordWrap(False)
    self.player_title.set_marquee(True)
    self.player_artist = SwapLabel("")
    self.player_artist.set_marquee(True)
    self.player_artist.setObjectName("PlayerArtist")
    info_text_layout.addWidget(self.player_title)
    info_text_layout.addWidget(self.player_artist)
    info_widget_layout.addLayout(info_text_layout)

    # Botón Favorito en barra de reproducción
    self.player_heart_btn = QPushButton("")
    self.player_heart_btn.setIcon(icon("plus_circle.svg", "#B3B3B3"))
    self.player_heart_btn.setIconSize(QSize(20, 20))
    self.player_heart_btn.setFixedSize(30, 30)
    self.player_heart_btn.setToolTip("Guardar en una lista")
    self.player_heart_btn.setCursor(Qt.PointingHandCursor)
    self.player_heart_btn.setStyleSheet("background: transparent; border: none; padding: 0;")
    self.player_heart_btn.clicked.connect(self.toggle_player_heart)
    info_widget_layout.addWidget(self.player_heart_btn)

    # Visualizador de espectro animado en tiempo real
    accent_color = THEME_CONFIGS.get(self.current_theme, {}).get("accent", "#1ED760")
    self.visualizer = AudioVisualizerWidget(accent_color=accent_color)
    info_widget_layout.addWidget(self.visualizer)

    player_layout.addWidget(self.info_widget, stretch=1)
    self.info_widget.setMaximumWidth(360)

    # en pausa la información se ve más apagada (sin efectos gráficos permanentes: un color distinto y la portada atenuada)
    self.player_thumb.set_dim(True)

    # Controles Centrales
    center_layout = QVBoxLayout()
    center_layout.setAlignment(Qt.AlignCenter)
    center_layout.setSpacing(4)

    controls_layout = QHBoxLayout()
    controls_layout.setAlignment(Qt.AlignCenter)
    controls_layout.setSpacing(18)
    tools_layout = QHBoxLayout()     # herramientas de la derecha: letra, cola, panel, ecualizador, mini y volumen
    tools_layout.setSpacing(4)

    # Aleatorio
    self.btn_shuffle = DotButton()
    self.btn_shuffle.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "shuffle.svg"))))
    self.btn_shuffle.setIconSize(QSize(18, 18))
    self.btn_shuffle.setObjectName("ControlBtn")
    self.btn_shuffle.setToolTip("Reproducir en orden aleatorio")
    self.btn_shuffle.setCursor(Qt.PointingHandCursor)
    self.btn_shuffle.clicked.connect(self.toggle_shuffle)
    controls_layout.addWidget(self.btn_shuffle)

    # Anterior
    self.btn_prev = QPushButton("")
    self.btn_prev.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "prev.svg"))))
    self.btn_prev.setIconSize(QSize(18, 18))
    self.btn_prev.setObjectName("ControlBtn")
    self.btn_prev.setToolTip("Anterior")
    self.btn_prev.setCursor(Qt.PointingHandCursor)
    self.btn_prev.clicked.connect(self.play_previous)
    controls_layout.addWidget(self.btn_prev)

    # Play / Pause
    self.btn_play_pause = PlayPauseButton()
    self.btn_play_pause.setToolTip("Reproducir / pausa")
    self.btn_play_pause.setIconSize(QSize(20, 20))
    self.btn_play_pause.setObjectName("PlayPauseBtn")
    self.btn_play_pause.setCursor(Qt.PointingHandCursor)
    self.btn_play_pause.clicked.connect(self.toggle_play_pause)
    controls_layout.addWidget(self.btn_play_pause)

    # Siguiente
    self.btn_next = QPushButton("")
    self.btn_next.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "next.svg"))))
    self.btn_next.setIconSize(QSize(18, 18))
    self.btn_next.setObjectName("ControlBtn")
    self.btn_next.setToolTip("Siguiente")
    self.btn_next.setCursor(Qt.PointingHandCursor)
    self.btn_next.clicked.connect(self.play_next)
    controls_layout.addWidget(self.btn_next)

    # Bucle
    self.btn_loop = DotButton()
    self.btn_loop.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "repeat.svg"))))
    self.btn_loop.setIconSize(QSize(18, 18))
    self.btn_loop.setObjectName("ControlBtn")
    self.btn_loop.setToolTip("Repetir esta canción")
    self.btn_loop.setCursor(Qt.PointingHandCursor)
    self.btn_loop.clicked.connect(self.toggle_loop)
    controls_layout.addWidget(self.btn_loop)

    # Letras / Karaoke
    self.btn_lyrics = QPushButton("")
    self.btn_lyrics.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "mic.svg"))))
    self.btn_lyrics.setIconSize(QSize(18, 18))
    self.btn_lyrics.setObjectName("ControlBtn")
    self.btn_lyrics.setToolTip("Ver la letra")
    self.btn_lyrics.setCursor(Qt.PointingHandCursor)
    self.btn_lyrics.clicked.connect(self.open_lyrics)
    tools_layout.addWidget(self.btn_lyrics)

    # Mini Reproductor (PiP)
    self.btn_pip = QPushButton("")
    self.btn_pip.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "pip.svg"))))
    self.btn_pip.setIconSize(QSize(18, 18))
    self.btn_pip.setObjectName("ControlBtn")
    self.btn_pip.setToolTip("Reproductor pequeño")
    self.btn_pip.setCursor(Qt.PointingHandCursor)
    self.btn_pip.clicked.connect(self.toggle_mini_player)
    tools_layout.addWidget(self.btn_pip)

    # Cola de reproducción
    self.btn_queue = QPushButton("")
    self.btn_queue.setIcon(icon("queue.svg"))
    self.btn_queue.setIconSize(QSize(18, 18))
    self.btn_queue.setObjectName("ControlBtn")
    self.btn_queue.setToolTip("Siguientes canciones")
    self.btn_queue.setCursor(Qt.PointingHandCursor)
    self.btn_queue.clicked.connect(self.open_queue_dialog)
    tools_layout.addWidget(self.btn_queue)

    # Panel lateral «En reproducción»
    self.btn_panel = QPushButton("")
    self.btn_panel.setIcon(icon("panel.svg"))
    self.btn_panel.setIconSize(QSize(18, 18))
    self.btn_panel.setObjectName("ControlBtn")
    self.btn_panel.setToolTip("Vista «En reproducción» (portada, letra e información del artista)")
    self.btn_panel.setCursor(Qt.PointingHandCursor)
    self.btn_panel.clicked.connect(self.toggle_now_playing)
    tools_layout.addWidget(self.btn_panel)

    # Más opciones: temporizador, velocidad, repetir tramo, fundido y volumen igualado
    self.btn_options = QPushButton("")
    self.btn_options.setIcon(icon("timer.svg"))
    self.btn_options.setIconSize(QSize(18, 18))
    self.btn_options.setObjectName("ControlBtn")
    self.btn_options.setToolTip("Temporizador, velocidad y más")
    self.btn_options.setCursor(Qt.PointingHandCursor)
    self.btn_options.clicked.connect(self.open_playback_options)
    tools_layout.addWidget(self.btn_options)

    # Ecualizador de audio
    self.btn_eq = QPushButton("")
    self.btn_eq.setIcon(icon("sliders.svg"))
    self.btn_eq.setIconSize(QSize(18, 18))
    self.btn_eq.setObjectName("ControlBtn")
    self.btn_eq.setToolTip("Ecualizador")
    self.btn_eq.setCursor(Qt.PointingHandCursor)
    self.btn_eq.clicked.connect(self.open_equalizer)
    tools_layout.addWidget(self.btn_eq)

    center_layout.addLayout(controls_layout)

    # Barra de tiempo
    seek_layout = QHBoxLayout()
    seek_layout.setSpacing(8)

    self.time_current_label = FixedDigitsLabel("00:00")
    self.time_current_label.setStyleSheet("color: #B3B3B3; font-size: 11px; min-width: 35px;")
    self.time_current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    self.seek_slider = SmoothSlider(Qt.Horizontal, bubble_text=self.format_time)
    self.seek_slider.setRange(0, 0)
    self.seek_slider.setCursor(Qt.PointingHandCursor)
    self.seek_slider.setFixedHeight(16)
    self.seek_slider.setMaximumWidth(560)
    self.seek_slider.valueChanged.connect(self.on_seek_changed)

    self.time_total_label = FixedDigitsLabel("00:00")
    self.time_total_label.setStyleSheet("color: #B3B3B3; font-size: 11px; min-width: 35px;")
    self.time_total_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    seek_layout.addWidget(self.time_current_label)
    seek_layout.addWidget(self.seek_slider, stretch=1)
    seek_layout.addWidget(self.time_total_label)

    center_layout.addLayout(seek_layout)
    player_layout.addLayout(center_layout, stretch=2)

    # Control de Volumen y Estado
    right_layout = QVBoxLayout()
    right_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    right_layout.setSpacing(4)

    self.player_status = QLabel("")
    self.player_status.setObjectName("PlayerStatus")
    self.player_status.setAlignment(Qt.AlignRight)
    right_layout.addWidget(self.player_status)

    vol_layout = tools_layout
    vol_layout.addSpacing(8)
    vol_icon = self.vol_icon = CoverLabel(radius=0, placeholder="#00000000")
    vol_icon.setFixedSize(16, 16)
    vol_icon.setPixmap(icon("volume.svg", "#B3B3B3").pixmap(16, 16))
    vol_icon.setStyleSheet("background: transparent;")

    self.volume_slider = SmoothSlider(Qt.Horizontal)
    self.volume_slider.setRange(0, 100)
    self.volume_slider.setValue(100)
    self.volume_slider.setFixedWidth(96)
    self.volume_slider.setFixedHeight(16)
    self.volume_slider.setCursor(Qt.PointingHandCursor)
    self.volume_slider.valueChanged.connect(self.change_volume)

    vol_layout.addWidget(vol_icon)
    vol_layout.addWidget(self.volume_slider)

    right_layout.addLayout(tools_layout)
    player_layout.addLayout(right_layout)

    # Cerrar reproductor
    self.btn_close_player = QPushButton("")
    self.btn_close_player.setIcon(QIcon(resource_path(os.path.join("assets", "icons", "x.svg"))))
    self.btn_close_player.setObjectName("ControlBtn")
    self.btn_close_player.setFixedSize(24, 24)
    self.btn_close_player.setCursor(Qt.PointingHandCursor)
    self.btn_close_player.clicked.connect(self.stop_player)
    player_layout.addWidget(self.btn_close_player, alignment=Qt.AlignTop)

    # transporte: pulsación visible en todos los controles
    for btn in (self.btn_shuffle, self.btn_prev, self.btn_play_pause, self.btn_next, self.btn_loop, self.btn_lyrics,
                self.btn_queue, self.btn_panel, self.btn_options, self.btn_eq, self.btn_pip):
        press_feedback(btn)

    # chip del temporizador de dormir (solo se ve si hay uno activo) y aviso flotante del teclado
    self.sleep_chip = QLabel("")
    self.sleep_chip.setObjectName("SleepChip")
    self.sleep_chip.setVisible(False)
    tools_layout.insertWidget(tools_layout.indexOf(self.btn_options), self.sleep_chip)

    self.main_vbox.addWidget(self.player_bar)
    self.osd = Osd(central_parent_of(self))
