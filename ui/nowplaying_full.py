"""Pantalla completa «Ahora suena»: portada grande con una luz de su color, título, controles, barra de tiempo y la letra
siguiendo la canción. El fondo es la portada desenfocada y, tras unos segundos sin mover el ratón, los controles y el
cursor se ocultan solos. Se abre con F11 (o con el botón del panel «En reproducción») y se cierra con Esc."""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QWidget

from ui.ambient import AmbientBackdrop, IdleHider
from ui.controls import GlowCover, PlayPauseButton
from ui.icons import icon
from ui.imageloader import ImageLoaderThread, LocalCoverLoader
from ui.now_playing import LyricsBox, cover_color
from ui.sliders import SmoothSlider
from ui.textfx import FixedDigitsLabel, SwapLabel

DEFAULT_COLOR = QColor("#3D5A4A")


class NowPlayingFull(QDialog, AmbientBackdrop):
    def __init__(self, window):
        super().__init__(window)
        self.window_ref = window
        self.setObjectName("NowPlayingFull")
        self.setWindowFlag(Qt.Window, True)
        self.init_backdrop(DEFAULT_COLOR)
        self._loader = None
        self._cover_size = 380

        root = QHBoxLayout(self)
        root.setContentsMargins(70, 50, 70, 40)
        root.setSpacing(60)

        # ---- columna izquierda: portada, título, controles
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addStretch(1)
        self.cover_box = GlowCover(self._cover_size, 18)
        left.addWidget(self.cover_box, alignment=Qt.AlignHCenter)
        self.title = SwapLabel("")
        self.title.setStyleSheet("font-size: 34px; font-weight: 800; color: #FFFFFF; background: transparent;")
        self.title.setFixedHeight(52)
        self.title.set_marquee(True)
        left.addWidget(self.title)
        self.artist = SwapLabel("")
        self.artist.setStyleSheet("font-size: 18px; font-weight: 600; color: rgba(255,255,255,0.75); background: transparent;")
        self.artist.setFixedHeight(30)
        left.addWidget(self.artist)

        self.chrome = QWidget()                       # lo que se oculta solo (controles y barra de tiempo)
        self.chrome.setStyleSheet("background: transparent;")
        chrome = QVBoxLayout(self.chrome)
        chrome.setContentsMargins(0, 8, 0, 0)
        chrome.setSpacing(12)
        seek_row = QHBoxLayout()
        self.time_now = FixedDigitsLabel("00:00")
        self.time_now.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 12px; background: transparent;")
        self.time_now.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_now.setFixedWidth(46)
        self.seek = SmoothSlider(Qt.Horizontal, bubble_text=window.format_time)
        self.seek.setFixedHeight(18)
        self.seek.valueChanged.connect(self._on_seek)
        self.time_total = FixedDigitsLabel("00:00")
        self.time_total.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 12px; background: transparent;")
        self.time_total.setFixedWidth(46)
        seek_row.addWidget(self.time_now)
        seek_row.addWidget(self.seek, stretch=1)
        seek_row.addWidget(self.time_total)
        chrome.addLayout(seek_row)
        controls = QHBoxLayout()
        controls.setSpacing(22)
        controls.addStretch()
        self.btn_prev = self._round_button("prev.svg", window.play_previous, 30)
        controls.addWidget(self.btn_prev)
        self.btn_play = PlayPauseButton()
        self.btn_play.setIconSize(QSize(26, 26))
        self.btn_play.setStyleSheet("QPushButton { background-color: #FFFFFF; border-radius: 32px; border: none; "
                                    "min-width: 64px; min-height: 64px; max-width: 64px; max-height: 64px; }"
                                    "QPushButton:hover { background-color: #E5E5E5; }")
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.clicked.connect(window.toggle_play_pause)
        controls.addWidget(self.btn_play)
        self.btn_next = self._round_button("next.svg", window.play_next, 30)
        controls.addWidget(self.btn_next)
        controls.addStretch()
        chrome.addLayout(controls)
        left.addWidget(self.chrome)
        left.addStretch(1)
        root.addLayout(left, stretch=5)

        # ---- columna derecha: la letra
        right = QVBoxLayout()
        right.addStretch(1)
        self.lyrics = LyricsBox(window)
        self.lyrics.btn_full.setVisible(False)
        right.addWidget(self.lyrics)
        right.addStretch(1)
        root.addLayout(right, stretch=6)

        self.btn_close = QPushButton("")
        self.btn_close.setParent(self)
        self.btn_close.setObjectName("IconBtn")
        self.btn_close.setIcon(icon("fullscreen_exit.svg", "#FFFFFF"))
        self.btn_close.setIconSize(QSize(20, 20))
        self.btn_close.setFixedSize(40, 40)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setToolTip("Salir de pantalla completa (Esc)")
        self.btn_close.clicked.connect(self.close)
        self._idle = IdleHider(self, [self.chrome, self.btn_close])

    def _round_button(self, icon_name: str, slot, size: int) -> QPushButton:
        b = QPushButton("")
        b.setObjectName("ControlBtn")
        b.setIcon(icon(icon_name, "#FFFFFF"))
        b.setIconSize(QSize(size - 6, size - 6))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    # ------------------------------------------------------------------ contenido
    def set_track(self, info: dict, color=None, pix=None):
        if not info:
            return
        self.title.setText(info.get("title", ""))
        self.artist.setText(info.get("uploader", ""))
        self._load_cover(info)
        from ui.playback_mixin import track_key
        self.lyrics.load(info.get("title", ""), info.get("uploader", ""), track_key(info))
        if color is not None:
            self.lyrics.set_color(color)
            self.set_backdrop(color, pix)

    def _load_cover(self, info: dict):
        size = self._cover_size
        url, local = info.get("thumbnail"), info.get("local_path")
        if url:
            loader = ImageLoaderThread(url, False, (size, size), 18)
        elif local and os.path.isfile(local):
            loader = LocalCoverLoader(local, False, (size, size), 18)
        else:
            self.cover_box.cover.clear()
            return
        loader.image_loaded.connect(self._cover_ready)
        self._loader = loader
        loader.start()

    def _cover_ready(self, pix):
        try:
            self.cover_box.cover.setPixmap(pix)
            self.cover_box.set_glow(pix)
            color = cover_color(pix)
            if color is not None:
                self.lyrics.set_color(color)
                self.set_backdrop(color, pix)
        except RuntimeError:
            pass

    def set_position(self, ms: int):
        if not self.seek.isSliderDown():
            self.seek.blockSignals(True)
            self.seek.setValue(ms)
            self.seek.blockSignals(False)
        self.time_now.setText(self.window_ref.format_time(ms))
        self.lyrics.update_position(ms)

    def set_duration(self, ms: int):
        self.seek.setRange(0, ms)
        self.time_total.setText(self.window_ref.format_time(ms))

    def set_playing(self, playing: bool):
        self.btn_play.set_state(playing)

    def _on_seek(self, value: int):
        self.window_ref.player.setPosition(value)

    # ------------------------------------------------------------------ ventana
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.btn_close.move(self.width() - self.btn_close.width() - 24, 20)
        self.lyrics.scroll.setFixedHeight(max(260, int(self.height() * 0.62)))

    def paintEvent(self, _event):
        self.paint_backdrop(QPainter(self), self.rect())

    def showEvent(self, event):
        self.start_backdrop()
        self._idle.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.stop_backdrop()
        self._idle.stop()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F11):
            self.close()
        else:
            self.window_ref.keyPressEvent(event)         # Espacio, flechas, M…: los mismos atajos de la aplicación
