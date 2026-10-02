import random
import math
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QBrush
from PySide6.QtWidgets import QWidget

from services import envelope
from ui.anim_clock import clock
from ui.perf import eco, visualizer_enabled


class AudioVisualizerWidget(QWidget):
    """
    Widget visualizador de barras de espectro de audio animado en tiempo real.
    Reacciona dinámicamente cuando la música se está reproduciendo.
    """
    def __init__(self, num_bars=7, accent_color="#1ED760", parent=None):
        super().__init__(parent)
        self.num_bars = num_bars
        self.accent_color = QColor(accent_color)
        self.bar_heights = [4.0] * num_bars
        self.target_heights = [4.0] * num_bars
        self.is_playing = False
        self.phase = 0.0
        self.enabled = visualizer_enabled()
        self.paused_by_window = False       # ventana minimizada: no se anima

        self.setFixedSize(34, 22)
        self.setStyleSheet("background: transparent;")
        if not self.enabled:
            self.hide()

        self._env = None            # envolvente de la canción (graves, medios y agudos cada 0,1 s), si ya está calculada
        self._pos = 0
        self._token = None          # suscripción al reloj compartido: solo existe mientras se anima
        self._fps = 10 if eco() else 22

    def set_envelope(self, data):
        """Con la envolvente de la canción las barras siguen sus graves y agudos de verdad; sin ella, el movimiento de antes."""
        self._env = data or None

    def set_position(self, ms: int):
        self._pos = ms

    def set_accent_color(self, hex_color: str):
        self.accent_color = QColor(hex_color)
        self.update()

    def set_window_active(self, active: bool):
        """Con la ventana minimizada se detiene la animación (y se retoma al volver)."""
        self.paused_by_window = not active
        if not active:
            self._stop()
        elif self.is_playing and self.enabled:
            self._start()

    def set_playing(self, playing: bool):
        self.is_playing = playing
        if playing:
            if self.enabled and not self.paused_by_window:
                self._start()
        else:
            # Desvanecer barras al pausar
            self.target_heights = [3.0] * self.num_bars

    def _start(self):
        if self._token is None:
            self._token = clock().subscribe(self._animate_step, self._fps)

    def _stop(self):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None

    def _animate_step(self, _dt=0):
        self.phase += 0.25
        max_h = self.height() - 4

        levels = envelope.level_at(self._env, self._pos) if (self.is_playing and self._env) else None
        if levels is not None:
            low, mid, high = levels
            last = max(1, self.num_bars - 1)
            for i in range(self.num_bars):
                x = i / last
                value = low * max(0.0, 1 - 2 * x) + mid * (1 - abs(2 * x - 1)) + high * max(0.0, 2 * x - 1)
                value *= 0.9 + 0.1 * math.sin(self.phase * 2 + i)         # un leve movimiento propio de cada barra
                self.target_heights[i] = max(4.0, min(float(max_h), value * max_h))
        elif self.is_playing:
            for i in range(self.num_bars):
                # Generar pulsos rítmicos combinando seno y aleatoriedad suave
                wave = math.sin(self.phase + (i * 0.9)) * 0.5 + 0.5
                r = random.uniform(0.6, 1.0)
                self.target_heights[i] = max(4.0, wave * max_h * r)
        else:
            self.target_heights = [3.0] * self.num_bars
            if all(abs(h - 3.0) < 0.5 for h in self.bar_heights):
                self._stop()

        # Interpolación suave (LERP) hacia los objetivos
        for i in range(self.num_bars):
            self.bar_heights[i] += (self.target_heights[i] - self.bar_heights[i]) * 0.35

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        bar_w = 4
        spacing = 3
        total_w = self.num_bars * bar_w + (self.num_bars - 1) * spacing
        start_x = (w - total_w) // 2

        for i in range(self.num_bars):
            bar_h = int(self.bar_heights[i])
            x = start_x + i * (bar_w + spacing)
            y = h - bar_h - 2

            # Gradiente sutil o color sólido del tema
            color = QColor(self.accent_color)
            if not self.is_playing:
                color.setAlpha(120)

            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(x, y, bar_w, bar_h, 2, 2)
