"""Componentes visuales para la Mesa de DJ Virtual.
Incluye:
- DjRotaryKnob: Potenciómetro giratorio realista (EQ, Filtro, Ganancia) con indicador LED.
- DjJogWheel: Plato / vinilo giratorio realista con textura de surcos y etiqueta central.
- DjVuMeter: Vúmetro estéreo con barras LED animadas (verde, amarillo, rojo).
- DjCrossfader: Deslizador horizontal de mezcla entre plato A y B con soporte manual y automático.
- DjFader: Fader vertical de volumen de canal con escala en dB.
"""
import math
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient, QConicalGradient,
    QPainterPath, QPixmap
)
from PySide6.QtWidgets import QWidget, QSizePolicy


class DjRotaryKnob(QWidget):
    """Potenciómetro giratorio para EQ (High, Mid, Low), Filtro o FX.
    Rango de -1.0 a +1.0 (o 0.0 a 1.0). Doble clic vuelve a 0.0 (centro)."""
    valueChanged = Signal(float)

    def __init__(self, label="EQ", min_val=-1.0, max_val=1.0, default_val=0.0,
                 accent_color="#1ED760", bipolar=True, unit="dB", parent=None):
        super().__init__(parent)
        self.label = label
        self.min_val = float(min_val)
        self.max_val = float(max_val)
        self._value = float(default_val)
        self.default_val = float(default_val)
        self.accent_color = QColor(accent_color)
        self.bipolar = bipolar
        self.unit = unit
        self._dragging = False
        self._last_y = 0
        self.setMinimumSize(48, 64)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{label}: {self._format_value()}")

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, val: float):
        v = max(self.min_val, min(self.max_val, float(val)))
        if abs(v - self._value) > 1e-4:
            self._value = v
            self.setToolTip(f"{self.label}: {self._format_value()}")
            self.valueChanged.emit(self._value)
            self.update()

    value = Property(float, _get_value, _set_value)

    def setValue(self, val: float):
        self._set_value(val)

    def animateTo(self, target_val: float, duration_ms: int = 400):
        """Animación suave del potenciómetro (utilizada por el DJ de IA)."""
        anim = QPropertyAnimation(self, b"value", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self._value)
        anim.setEndValue(float(target_val))
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _format_value(self) -> str:
        if self.unit == "dB":
            v_db = self._value * 24.0 if self.bipolar else (self._value - 0.5) * 48.0
            return f"{v_db:+.1f} dB" if abs(v_db) > 0.05 else "0.0 dB"
        elif self.unit == "%":
            return f"{int(self._value * 100)}%"
        return f"{self._value:+.2f}"

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_y = event.position().y()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setValue(self.default_val)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            dy = self._last_y - event.position().y()
            self._last_y = event.position().y()
            step = (self.max_val - self.min_val) / 120.0
            self.setValue(self._value + dy * step)
            event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        knob_size = min(w - 6, h - 20)
        center_x = w / 2.0
        center_y = knob_size / 2.0 + 3

        # 1. Fondo de arco / carátula
        radius = knob_size / 2.0 - 2
        arc_rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)

        p.setPen(QPen(QColor(40, 40, 45), 3, Qt.SolidLine, Qt.RoundCap))
        start_angle = 225.0
        total_span = 270.0
        p.drawArc(arc_rect, int(-start_angle * 16), int(-total_span * 16))

        # 2. Arco activo coloreado
        norm_val = (self._value - self.min_val) / (self.max_val - self.min_val)
        if self.bipolar:
            center_norm = (self.default_val - self.min_val) / (self.max_val - self.min_val)
            span = (norm_val - center_norm) * total_span
            angle_from = start_angle + center_norm * total_span
            p.setPen(QPen(self.accent_color, 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(arc_rect, int(-angle_from * 16), int(-span * 16))
        else:
            span = norm_val * total_span
            p.setPen(QPen(self.accent_color, 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(arc_rect, int(-start_angle * 16), int(-span * 16))

        # 3. Cuerpo metálico del potenciómetro
        body_rad = radius - 5
        body_grad = QRadialGradient(center_x - 3, center_y - 3, body_rad * 1.2)
        body_grad.setColorAt(0.0, QColor(65, 65, 75))
        body_grad.setColorAt(0.6, QColor(35, 35, 40))
        body_grad.setColorAt(1.0, QColor(20, 20, 25))

        p.setPen(QPen(QColor(15, 15, 20), 1.5))
        p.setBrush(QBrush(body_grad))
        p.drawEllipse(QPointF(center_x, center_y), body_rad, body_rad)

        # 4. Línea marcadora / aguja indicadora
        angle_deg = start_angle + norm_val * total_span
        angle_rad = math.radians(angle_deg)
        nx = math.cos(angle_rad)
        ny = math.sin(angle_rad)

        line_start = QPointF(center_x + nx * (body_rad * 0.4), center_y + ny * (body_rad * 0.4))
        line_end = QPointF(center_x + nx * (body_rad * 0.88), center_y + ny * (body_rad * 0.88))

        p.setPen(QPen(self.accent_color, 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(line_start, line_end)

        # 5. Etiqueta inferior
        p.setPen(QColor(170, 170, 180))
        f = p.font()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        text_rect = QRectF(0, knob_size + 4, w, 14)
        p.drawText(text_rect, Qt.AlignCenter, self.label)


class DjJogWheel(QWidget):
    """Plato / Jog Wheel realista de DJ con vinilo, estrías, ribete metálico y rotación continua."""
    def __init__(self, deck_name="DECK A", accent_color="#1ED760", parent=None):
        super().__init__(parent)
        self.deck_name = deck_name
        self.accent_color = QColor(accent_color)
        self._angle = 0.0
        self._playing = False
        self._pixmap = None
        self._timer = QTimer(self)
        self._timer.setInterval(25)  # 40 fps
        self._timer.timeout.connect(self._rotate_step)
        self.setMinimumSize(140, 140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setPlaying(self, playing: bool):
        self._playing = bool(playing)
        if self._playing and not self._timer.isActive():
            self._timer.start()
        elif not self._playing and self._timer.isActive():
            self._timer.stop()
            self.update()

    def setCoverPixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self.update()

    def _rotate_step(self):
        self._angle = (self._angle + 2.5) % 360.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        dim = min(w, h) - 8
        cx = w / 2.0
        cy = h / 2.0
        radius = dim / 2.0

        # 1. Borde exterior metálico estriado
        outer_grad = QRadialGradient(cx, cy, radius)
        outer_grad.setColorAt(0.92, QColor(30, 30, 35))
        outer_grad.setColorAt(0.96, QColor(70, 70, 80))
        outer_grad.setColorAt(1.0, QColor(15, 15, 20))
        p.setPen(QPen(QColor(10, 10, 12), 2))
        p.setBrush(QBrush(outer_grad))
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        # 2. Anillo de LED activo
        p.setPen(QPen(self.accent_color if self._playing else QColor(50, 50, 55), 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), radius - 4, radius - 4)

        # 3. Superficie del vinilo negro con estrías concéntricas
        vinyl_rad = radius - 8
        v_grad = QRadialGradient(cx, cy, vinyl_rad)
        v_grad.setColorAt(0.0, QColor(22, 22, 26))
        v_grad.setColorAt(0.85, QColor(12, 12, 15))
        v_grad.setColorAt(1.0, QColor(20, 20, 24))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(v_grad))
        p.drawEllipse(QPointF(cx, cy), vinyl_rad, vinyl_rad)

        # Dibujar surcos microscópicos
        p.setPen(QPen(QColor(32, 32, 38), 1))
        for r_step in range(int(vinyl_rad * 0.45), int(vinyl_rad * 0.95), 8):
            p.drawEllipse(QPointF(cx, cy), r_step, r_step)

        # Reflejo especular cónico del vinilo
        p.save()
        p.translate(cx, cy)
        p.rotate(self._angle)

        conic = QConicalGradient(0, 0, 0)
        conic.setColorAt(0.0, QColor(255, 255, 255, 0))
        conic.setColorAt(0.12, QColor(255, 255, 255, 18))
        conic.setColorAt(0.25, QColor(255, 255, 255, 0))
        conic.setColorAt(0.5, QColor(255, 255, 255, 0))
        conic.setColorAt(0.62, QColor(255, 255, 255, 18))
        conic.setColorAt(0.75, QColor(255, 255, 255, 0))
        conic.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(conic))
        p.drawEllipse(QPointF(0, 0), vinyl_rad, vinyl_rad)

        # 4. Etiqueta central (Center Label)
        label_rad = vinyl_rad * 0.40
        p.setPen(QPen(self.accent_color, 1.5))
        p.setBrush(QColor(28, 28, 35))
        p.drawEllipse(QPointF(0, 0), label_rad, label_rad)

        if self._pixmap and not self._pixmap.isNull():
            path = QPainterPath()
            path.addEllipse(QPointF(0, 0), label_rad - 2, label_rad - 2)
            p.save()
            p.setClipPath(path)
            scaled = self._pixmap.scaled(int((label_rad - 2) * 2), int((label_rad - 2) * 2),
                                         Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(int(-label_rad + 2), int(-label_rad + 2), scaled)
            p.restore()
        else:
            p.setPen(QColor(220, 220, 225))
            f = p.font()
            f.setPointSize(8)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(-label_rad, -label_rad, label_rad * 2, label_rad * 2),
                       Qt.AlignCenter, self.deck_name)

        # 5. Marcador de aguja / aguja blanca de rotación
        p.setPen(QPen(QColor(255, 255, 255, 240), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(label_rad * 0.9, 0), QPointF(vinyl_rad * 0.96, 0))

        # Eje central (Spindle)
        p.setPen(QPen(QColor(15, 15, 18), 1))
        p.setBrush(QColor(180, 180, 190))
        p.drawEllipse(QPointF(0, 0), 6, 6)

        p.restore()


class DjVuMeter(QWidget):
    """Vúmetro estéreo vertical con barras LED de 14 segmentos (Verde -> Amarillo -> Rojo)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._left = 0.0
        self._right = 0.0
        self._peak_left = 0.0
        self._peak_right = 0.0
        self._decay_timer = QTimer(self)
        self._decay_timer.setInterval(40)
        self._decay_timer.timeout.connect(self._decay)
        self.setMinimumSize(22, 100)
        self.setMaximumWidth(32)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def setLevels(self, left: float, right: float):
        self._left = max(0.0, min(1.0, float(left)))
        self._right = max(0.0, min(1.0, float(right)))
        if self._left > self._peak_left:
            self._peak_left = self._left
        if self._right > self._peak_right:
            self._peak_right = self._right
        if not self._decay_timer.isActive():
            self._decay_timer.start()
        self.update()

    def _decay(self):
        self._left = max(0.0, self._left - 0.05)
        self._right = max(0.0, self._right - 0.05)
        self._peak_left = max(0.0, self._peak_left - 0.02)
        self._peak_right = max(0.0, self._peak_right - 0.02)
        if self._peak_left <= 0.01 and self._peak_right <= 0.01:
            self._decay_timer.stop()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        bar_w = (w - 7) / 2.0
        num_leds = 14
        led_gap = 2.0
        led_h = (h - 8 - (num_leds - 1) * led_gap) / num_leds

        # Fondo chasis de los LEDs
        p.fillRect(0, 0, w, h, QColor(16, 16, 20))

        # Colores por altura
        def led_color(idx: int, active: bool) -> QColor:
            frac = idx / float(num_leds)
            if frac >= 0.85:
                base = QColor(255, 50, 50)   # Rojo pico
            elif frac >= 0.65:
                base = QColor(255, 180, 20)  # Amarillo advertencia
            else:
                base = QColor(30, 215, 96)   # Verde nominal
            if not active:
                base.setAlpha(35)            # Apagado tenue
            return base

        for channel, val in enumerate((self._left, self._right)):
            bx = 3 + channel * (bar_w + 2)
            active_leds = int(val * num_leds)
            for i in range(num_leds):
                ly = h - 4 - (i + 1) * led_h - i * led_gap
                color = led_color(i, i < active_leds)
                p.fillRect(QRectF(bx, ly, bar_w, led_h), color)


class DjCrossfader(QWidget):
    """Crossfader horizontal suave con selector de curva y soporte manual/IA."""
    positionChanged = Signal(float)  # -1.0 (Plato A) a +1.0 (Plato B)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pos = 0.0  # Centro (0.0), A (-1.0), B (+1.0)
        self._dragging = False
        self.setMinimumSize(180, 50)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, val: float):
        v = max(-1.0, min(1.0, float(val)))
        if abs(v - self._pos) > 1e-4:
            self._pos = v
            self.positionChanged.emit(self._pos)
            self.update()

    crossfaderPos = Property(float, _get_pos, _set_pos)

    def setPosition(self, pos: float):
        self._set_pos(pos)

    def animateTo(self, target_pos: float, duration_ms: int = 2000):
        """Animación automática del fader realizada por la IA de mezcla."""
        anim = QPropertyAnimation(self, b"crossfaderPos", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self._pos)
        anim.setEndValue(float(target_pos))
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._update_from_mouse(event.position().x())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_mouse(event.position().x())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setPosition(0.0)  # Centro
            event.accept()

    def _update_from_mouse(self, x: float):
        track_w = self.width() - 40
        if track_w <= 0:
            return
        frac = (x - 20) / track_w
        self.setPosition((frac * 2.0) - 1.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cy = h / 2.0

        # Carril horizontal metálico
        track_h = 10
        track_rect = QRectF(20, cy - track_h / 2.0, w - 40, track_h)
        p.setPen(QPen(QColor(10, 10, 12), 1.5))
        p.setBrush(QColor(18, 18, 22))
        p.drawRoundedRect(track_rect, 4, 4)

        # Marcas de escala (A, Centro, B)
        p.setPen(QPen(QColor(80, 80, 90), 1))
        # Centro
        p.drawLine(QPointF(w / 2.0, cy - 14), QPointF(w / 2.0, cy + 14))
        # Cuartos
        p.drawLine(QPointF(20 + (w - 40) * 0.25, cy - 8), QPointF(20 + (w - 40) * 0.25, cy + 8))
        p.drawLine(QPointF(20 + (w - 40) * 0.75, cy - 8), QPointF(20 + (w - 40) * 0.75, cy + 8))

        # Texto de ayuda
        p.setPen(QColor(130, 130, 145))
        f = p.font()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, h - 14, 40, 14), Qt.AlignLeft, "PLATO A")
        p.drawText(QRectF(w / 2.0 - 20, h - 14, 40, 14), Qt.AlignCenter, "MIX")
        p.drawText(QRectF(w - 50, h - 14, 40, 14), Qt.AlignRight, "PLATO B")

        # Botón / Maneta deslizante (Knob del crossfader)
        track_w = w - 40
        hx = 20 + ((self._pos + 1.0) / 2.0) * track_w
        handle_w = 28
        handle_h = 32
        handle_rect = QRectF(hx - handle_w / 2.0, cy - handle_h / 2.0 - 3, handle_w, handle_h)

        h_grad = QLinearGradient(hx - handle_w / 2.0, 0, hx + handle_w / 2.0, 0)
        h_grad.setColorAt(0.0, QColor(70, 70, 80))
        h_grad.setColorAt(0.5, QColor(40, 40, 48))
        h_grad.setColorAt(1.0, QColor(25, 25, 30))

        p.setPen(QPen(QColor(10, 10, 12), 2))
        p.setBrush(QBrush(h_grad))
        p.drawRoundedRect(handle_rect, 4, 4)

        # Línea central blanca en la maneta
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(QPointF(hx, cy - handle_h / 2.0 + 1), QPointF(hx, cy + handle_h / 2.0 - 7))


class DjFader(QWidget):
    """Fader vertical de volumen de canal con escala en decibelios."""
    valueChanged = Signal(float)  # 0.0 a 1.0

    def __init__(self, label="CH 1", accent_color="#1ED760", parent=None):
        super().__init__(parent)
        self.label = label
        self.accent_color = QColor(accent_color)
        self._value = 1.0
        self._dragging = False
        self.setMinimumSize(38, 120)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, val: float):
        v = max(0.0, min(1.0, float(val)))
        if abs(v - self._value) > 1e-4:
            self._value = v
            self.valueChanged.emit(self._value)
            self.update()

    faderValue = Property(float, _get_value, _set_value)

    def setValue(self, val: float):
        self._set_value(val)

    def animateTo(self, target_val: float, duration_ms: int = 500):
        anim = QPropertyAnimation(self, b"faderValue", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self._value)
        anim.setEndValue(float(target_val))
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._update_from_mouse(event.position().y())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_mouse(event.position().y())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def _update_from_mouse(self, y: float):
        h = self.height() - 36
        if h <= 0:
            return
        frac = 1.0 - ((y - 18) / h)
        self.setValue(frac)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx = w / 2.0

        # Carril vertical
        track_w = 6
        track_h = h - 36
        track_rect = QRectF(cx - track_w / 2.0, 18, track_w, track_h)
        p.setPen(QPen(QColor(10, 10, 12), 1.5))
        p.setBrush(QColor(18, 18, 22))
        p.drawRoundedRect(track_rect, 3, 3)

        # Marcas de escala
        p.setPen(QPen(QColor(70, 70, 80), 1))
        steps = (0.0, 0.25, 0.5, 0.75, 1.0)
        for s in steps:
            sy = 18 + (1.0 - s) * track_h
            p.drawLine(QPointF(cx - 10, sy), QPointF(cx - 5, sy))
            p.drawLine(QPointF(cx + 5, sy), QPointF(cx + 10, sy))

        # Maneta deslizante
        hy = 18 + (1.0 - self._value) * track_h
        handle_w = 26
        handle_h = 18
        handle_rect = QRectF(cx - handle_w / 2.0, hy - handle_h / 2.0, handle_w, handle_h)

        h_grad = QLinearGradient(0, hy - handle_h / 2.0, 0, hy + handle_h / 2.0)
        h_grad.setColorAt(0.0, QColor(75, 75, 85))
        h_grad.setColorAt(0.5, QColor(42, 42, 50))
        h_grad.setColorAt(1.0, QColor(25, 25, 30))

        p.setPen(QPen(QColor(12, 12, 15), 1.5))
        p.setBrush(QBrush(h_grad))
        p.drawRoundedRect(handle_rect, 3, 3)

        # Línea central de la maneta
        p.setPen(QPen(self.accent_color, 2))
        p.drawLine(QPointF(cx - handle_w / 2.0 + 3, hy), QPointF(cx + handle_w / 2.0 - 3, hy))
