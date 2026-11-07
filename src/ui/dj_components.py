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
    QPainterPath, QPixmap, QFont
)
from PySide6.QtWidgets import (
    QWidget, QSizePolicy, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView, QGridLayout,
    QLineEdit
)


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
        self.setMinimumSize(30, 42)
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

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        step = (self.max_val - self.min_val) / 40.0
        if delta > 0:
            self.setValue(self._value + step)
        elif delta < 0:
            self.setValue(self._value - step)
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        knob_size = min(w - 4, h - 16)
        center_x = w / 2.0
        center_y = knob_size / 2.0 + 2

        # 1. Fondo de arco / carátula
        radius = max(6.0, knob_size / 2.0 - 2)
        arc_rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)

        pen_w = max(2.0, min(3.0, radius * 0.25))
        p.setPen(QPen(QColor(40, 40, 45), pen_w, Qt.SolidLine, Qt.RoundCap))
        start_angle = 225.0
        total_span = 270.0
        p.drawArc(arc_rect, int(-start_angle * 16), int(-total_span * 16))

        # 2. Arco activo coloreado
        norm_val = (self._value - self.min_val) / (self.max_val - self.min_val)
        p.setPen(QPen(self.accent_color, pen_w, Qt.SolidLine, Qt.RoundCap))
        if self.bipolar:
            center_norm = (self.default_val - self.min_val) / (self.max_val - self.min_val)
            span = (norm_val - center_norm) * total_span
            angle_from = start_angle + center_norm * total_span
            p.drawArc(arc_rect, int(-angle_from * 16), int(-span * 16))
        else:
            span = norm_val * total_span
            p.drawArc(arc_rect, int(-start_angle * 16), int(-span * 16))

        # 3. Cuerpo metálico del potenciómetro
        body_rad = max(4.0, radius * 0.72)
        body_grad = QRadialGradient(center_x - 2, center_y - 2, body_rad * 1.2)
        body_grad.setColorAt(0.0, QColor(65, 65, 75))
        body_grad.setColorAt(0.6, QColor(35, 35, 40))
        body_grad.setColorAt(1.0, QColor(20, 20, 25))

        p.setPen(QPen(QColor(15, 15, 20), 1.0))
        p.setBrush(QBrush(body_grad))
        p.drawEllipse(QPointF(center_x, center_y), body_rad, body_rad)

        # 4. Línea marcadora / aguja indicadora
        angle_deg = start_angle + norm_val * total_span
        angle_rad = math.radians(angle_deg)
        nx = math.cos(angle_rad)
        ny = math.sin(angle_rad)

        line_start = QPointF(center_x + nx * (body_rad * 0.35), center_y + ny * (body_rad * 0.35))
        line_end = QPointF(center_x + nx * (body_rad * 0.88), center_y + ny * (body_rad * 0.88))

        p.setPen(QPen(self.accent_color, max(1.5, pen_w * 0.8), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(line_start, line_end)

        # 5. Etiqueta inferior
        p.setPen(QColor(170, 170, 180))
        f = p.font()
        f.setPointSize(max(6, min(8, int(knob_size * 0.28))))
        f.setBold(True)
        p.setFont(f)
        text_rect = QRectF(0, knob_size + 3, w, 12)
        p.drawText(text_rect, Qt.AlignCenter, self.label)


class DjJogWheel(QWidget):
    """Plato / Jog Wheel realista de DJ con vinilo, estrías, ribete metálico, rotación y scratch interactivo con ratón."""
    scratched = Signal(int)     # delta en milisegundos para scrub/scratch
    nudged = Signal(float)      # factor para pitch bend temporal en modo CDJ (-0.08 a +0.08)
    vinylModeChanged = Signal(bool)

    def __init__(self, deck_name="DECK A", accent_color="#1ED760", parent=None):
        super().__init__(parent)
        self.deck_name = deck_name
        self.accent_color = QColor(accent_color)
        self._angle = 0.0
        self._playing = False
        self._pixmap = None
        self._vinyl_mode = True
        self._dragging = False
        self._last_mouse_angle = 0.0
        self.setCursor(Qt.OpenHandCursor)
        self._timer = QTimer(self)
        self._timer.setInterval(25)  # 40 fps
        self._timer.timeout.connect(self._rotate_step)
        self.setMinimumSize(60, 60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setToolTip(f"{deck_name}: Arrastra para scratch o needle scrub (Modo Vinilo)")

    def setVinylMode(self, enabled: bool):
        self._vinyl_mode = bool(enabled)
        self.vinylModeChanged.emit(self._vinyl_mode)
        mode_str = "Vinilo (Scratch)" if self._vinyl_mode else "CDJ (Pitch Bend)"
        self.setToolTip(f"{self.deck_name}: Modo {mode_str}. Arrastra para manipular el audio.")

    def isVinylMode(self) -> bool:
        return self._vinyl_mode

    @property
    def angle(self) -> float:
        return self._angle

    def currentAngle(self) -> float:
        return self._angle

    def setPlaying(self, playing: bool):
        self._playing = bool(playing)
        if self._playing and not self._timer.isActive() and not self._dragging:
            self._timer.start()
        elif not self._playing and self._timer.isActive():
            self._timer.stop()
            self.update()

    def setCoverPixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self.update()

    def _rotate_step(self):
        if not self._dragging:
            self._angle = (self._angle + 2.5) % 360.0
            self.update()

    def _calc_angle(self, pos: QPointF) -> float:
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        return math.degrees(math.atan2(pos.y() - cy, pos.x() - cx))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self._last_mouse_angle = self._calc_angle(event.position())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            cur_angle = self._calc_angle(event.position())
            delta = cur_angle - self._last_mouse_angle
            if delta > 180.0:
                delta -= 360.0
            elif delta < -180.0:
                delta += 360.0
            self._last_mouse_angle = cur_angle
            self._angle = (self._angle + delta) % 360.0
            self.update()

            if self._vinyl_mode:
                delta_ms = int(delta * 5.0)
                if delta_ms != 0:
                    self.scratched.emit(delta_ms)
            else:
                nudge = max(-0.08, min(0.08, delta * 0.005))
                self.nudged.emit(nudge)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            if not self._vinyl_mode:
                self.nudged.emit(0.0)
            if self._playing and not self._timer.isActive():
                self._timer.start()
            event.accept()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if self._vinyl_mode:
            self.scratched.emit(int(delta * 2.0))
        else:
            nudge = 0.05 if delta > 0 else -0.05
            self.nudged.emit(nudge)
        self._angle = (self._angle + (delta * 0.1)) % 360.0
        self.update()
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        dim = min(w, h) - 6
        if dim <= 10:
            return
        cx = w / 2.0
        cy = h / 2.0
        radius = dim / 2.0

        # 1. Borde exterior metálico estriado
        outer_grad = QRadialGradient(cx, cy, radius)
        outer_grad.setColorAt(0.92, QColor(30, 30, 35))
        outer_grad.setColorAt(0.96, QColor(70, 70, 80))
        outer_grad.setColorAt(1.0, QColor(15, 15, 20))
        p.setPen(QPen(QColor(10, 10, 12), max(1.0, radius * 0.03)))
        p.setBrush(QBrush(outer_grad))
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        # 2. Anillo de LED activo
        ring_gap = max(2.0, radius * 0.05)
        p.setPen(QPen(self.accent_color if self._playing else QColor(50, 50, 55), max(1.5, radius * 0.035)))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), radius - ring_gap, radius - ring_gap)

        # 3. Superficie del vinilo negro con estrías concéntricas
        vinyl_rad = max(8.0, radius - max(4.0, radius * 0.11))
        v_grad = QRadialGradient(cx, cy, vinyl_rad)
        v_grad.setColorAt(0.0, QColor(22, 22, 26))
        v_grad.setColorAt(0.85, QColor(12, 12, 15))
        v_grad.setColorAt(1.0, QColor(20, 20, 24))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(v_grad))
        p.drawEllipse(QPointF(cx, cy), vinyl_rad, vinyl_rad)

        # Dibujar surcos microscópicos
        p.setPen(QPen(QColor(32, 32, 38), 1))
        step_sz = max(4, int(vinyl_rad * 0.12))
        for r_step in range(int(vinyl_rad * 0.45), int(vinyl_rad * 0.95), step_sz):
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
        label_rad = max(4.0, vinyl_rad * 0.38)
        p.setPen(QPen(self.accent_color, max(1.0, label_rad * 0.08)))
        p.setBrush(QColor(28, 28, 35))
        p.drawEllipse(QPointF(0, 0), label_rad, label_rad)

        if self._pixmap and not self._pixmap.isNull():
            path = QPainterPath()
            path.addEllipse(QPointF(0, 0), label_rad - 1, label_rad - 1)
            p.save()
            p.setClipPath(path)
            scaled = self._pixmap.scaled(int((label_rad - 1) * 2), int((label_rad - 1) * 2),
                                         Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(int(-label_rad + 1), int(-label_rad + 1), scaled)
            p.restore()
        else:
            p.setPen(QColor(220, 220, 225))
            f = p.font()
            f.setPointSize(max(5, min(8, int(label_rad * 0.4))))
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(-label_rad, -label_rad, label_rad * 2, label_rad * 2),
                       Qt.AlignCenter, self.deck_name)

        # 5. Marcador de aguja / aguja blanca de rotación
        p.setPen(QPen(QColor(255, 255, 255, 240), max(1.5, radius * 0.04), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(label_rad * 0.9, 0), QPointF(vinyl_rad * 0.96, 0))

        # Eje central (Spindle)
        spindle_rad = max(2.0, min(5.0, label_rad * 0.22))
        p.setPen(QPen(QColor(15, 15, 18), 1))
        p.setBrush(QColor(180, 180, 190))
        p.drawEllipse(QPointF(0, 0), spindle_rad, spindle_rad)

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
        self.setMinimumSize(12, 45)
        self.setMaximumWidth(28)
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

    @property
    def _level_l(self) -> float:
        return self._left

    @property
    def _level_r(self) -> float:
        return self._right

    @property
    def left_level(self) -> float:
        return self._left

    @property
    def right_level(self) -> float:
        return self._right

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
        bar_w = max(2.0, (w - 5) / 2.0)
        num_leds = max(8, min(14, int(h / 7)))
        led_gap = 1.5
        led_h = max(2.0, (h - 6 - (num_leds - 1) * led_gap) / num_leds)

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
            bx = 2 + channel * (bar_w + 1.5)
            active_leds = int(val * num_leds)
            for i in range(num_leds):
                ly = h - 3 - (i + 1) * led_h - i * led_gap
                color = led_color(i, i < active_leds)
                p.fillRect(QRectF(bx, ly, bar_w, led_h), color)


class DjCrossfader(QWidget):
    """Crossfader horizontal suave con selector de curva y soporte manual/IA."""
    positionChanged = Signal(float)  # -1.0 (Plato A) a +1.0 (Plato B)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pos = 0.0  # Centro (0.0), A (-1.0), B (+1.0)
        self._dragging = False
        self.setMinimumSize(100, 36)
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

    @property
    def value(self) -> float:
        return self._pos

    def setPosition(self, pos: float):
        self._set_pos(pos)

    def setValue(self, pos: float):
        self._set_pos(pos)

    def animateTo(self, target_pos: float, duration_ms: int = 2000):
        """Animación automática del fader realizada por la IA de mezcla."""
        anim = QPropertyAnimation(self, b"crossfaderPos", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self._pos)
        anim.setEndValue(float(target_pos))
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim = anim
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

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.setPosition(self._pos + (0.05 if delta > 0 else -0.05))
        event.accept()

    def _update_from_mouse(self, x: float):
        margin = max(14, int(self.width() * 0.08))
        track_w = self.width() - margin * 2
        if track_w <= 0:
            return
        frac = (x - margin) / track_w
        self.setPosition((frac * 2.0) - 1.0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cy = h / 2.0
        margin = max(14, int(w * 0.08))

        # Carril horizontal metálico
        track_h = max(6.0, min(10.0, h * 0.22))
        track_rect = QRectF(margin, cy - track_h / 2.0, w - margin * 2, track_h)
        p.setPen(QPen(QColor(10, 10, 12), 1.5))
        p.setBrush(QColor(18, 18, 22))
        p.drawRoundedRect(track_rect, 3, 3)

        # Marcas de escala (A, Centro, B)
        p.setPen(QPen(QColor(80, 80, 90), 1))
        # Centro
        p.drawLine(QPointF(w / 2.0, cy - track_h - 2), QPointF(w / 2.0, cy + track_h + 2))

        # Texto de ayuda si cabe
        if h >= 38:
            p.setPen(QColor(130, 130, 145))
            f = p.font()
            f.setPointSize(max(6, min(8, int(h * 0.18))))
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(margin - 4, h - 14, 50, 14), Qt.AlignLeft, "PLATO A")
            p.drawText(QRectF(w / 2.0 - 20, h - 14, 40, 14), Qt.AlignCenter, "MIX")
            p.drawText(QRectF(w - margin - 46, h - 14, 50, 14), Qt.AlignRight, "PLATO B")

        # Botón / Maneta deslizante (Knob del crossfader)
        track_w = w - margin * 2
        hx = margin + ((self._pos + 1.0) / 2.0) * track_w
        handle_w = max(18.0, min(28.0, w * 0.10))
        handle_h = max(18.0, min(30.0, h * 0.65))
        handle_rect = QRectF(hx - handle_w / 2.0, cy - handle_h / 2.0, handle_w, handle_h)

        h_grad = QLinearGradient(hx - handle_w / 2.0, 0, hx + handle_w / 2.0, 0)
        h_grad.setColorAt(0.0, QColor(70, 70, 80))
        h_grad.setColorAt(0.5, QColor(40, 40, 48))
        h_grad.setColorAt(1.0, QColor(25, 25, 30))

        p.setPen(QPen(QColor(10, 10, 12), 1.5))
        p.setBrush(QBrush(h_grad))
        p.drawRoundedRect(handle_rect, 3, 3)

        # Línea central blanca en la maneta
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(QPointF(hx, cy - handle_h / 2.0 + 2), QPointF(hx, cy + handle_h / 2.0 - 2))


class DjFader(QWidget):
    """Fader vertical de volumen de canal con escala en decibelios."""
    valueChanged = Signal(float)  # 0.0 a 1.0

    def __init__(self, label="CH 1", accent_color="#1ED760", parent=None):
        super().__init__(parent)
        self.label = label
        self.accent_color = QColor(accent_color)
        self._value = 1.0
        self._dragging = False
        self.setMinimumSize(20, 50)
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

    @property
    def value(self) -> float:
        return self._value

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

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.setValue(self._value + (0.05 if delta > 0 else -0.05))
        event.accept()

    def _update_from_mouse(self, y: float):
        margin = max(8, int(self.height() * 0.10))
        h = self.height() - margin * 2
        if h <= 0:
            return
        frac = 1.0 - ((y - margin) / h)
        self.setValue(frac)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx = w / 2.0
        margin = max(8, int(h * 0.10))

        # Carril vertical
        track_w = max(4.0, min(6.0, w * 0.20))
        track_h = h - margin * 2
        track_rect = QRectF(cx - track_w / 2.0, margin, track_w, track_h)
        p.setPen(QPen(QColor(10, 10, 12), 1.0))
        p.setBrush(QColor(18, 18, 22))
        p.drawRoundedRect(track_rect, 2, 2)

        # Marcas de escala
        p.setPen(QPen(QColor(70, 70, 80), 1))
        steps = (0.0, 0.25, 0.5, 0.75, 1.0)
        for s in steps:
            sy = margin + (1.0 - s) * track_h
            p.drawLine(QPointF(cx - 8, sy), QPointF(cx - 4, sy))
            p.drawLine(QPointF(cx + 4, sy), QPointF(cx + 8, sy))

        # Maneta deslizante
        hy = margin + (1.0 - self._value) * track_h
        handle_w = max(14.0, min(24.0, w * 0.85))
        handle_h = max(10.0, min(18.0, h * 0.18))
        handle_rect = QRectF(cx - handle_w / 2.0, hy - handle_h / 2.0, handle_w, handle_h)

        h_grad = QLinearGradient(0, hy - handle_h / 2.0, 0, hy + handle_h / 2.0)
        h_grad.setColorAt(0.0, QColor(75, 75, 85))
        h_grad.setColorAt(0.5, QColor(42, 42, 50))
        h_grad.setColorAt(1.0, QColor(25, 25, 30))

        p.setPen(QPen(QColor(12, 12, 15), 1.0))
        p.setBrush(QBrush(h_grad))
        p.drawRoundedRect(handle_rect, 2, 2)

        # Línea central de la maneta
        p.setPen(QPen(self.accent_color, 1.5))
        p.drawLine(QPointF(cx - handle_w / 2.0 + 2, hy), QPointF(cx + handle_w / 2.0 - 2, hy))


# =====================================================================================================
# 1. PITCH / TEMPO FADER (PIONEER CDJ STYLE)
# =====================================================================================================
class DjPitchFader(QWidget):
    """Fader vertical de Tempo / Pitch para CDJ estilo Pioneer.
    Rango de -1.0 a +1.0 (mapeado a +/- 10% o +/- 16%). Con LED de centro 0.0% y botón de reseteo."""
    valueChanged = Signal(float)  # -1.0 a +1.0
    rateChanged = Signal(float)   # factor 0.90 a 1.10

    def __init__(self, label="TEMPO", accent_color="#1ED760", range_pct=10.0, parent=None):
        super().__init__(parent)
        self.label = label
        self.accent_color = QColor(accent_color)
        self.range_pct = float(range_pct)
        self._value = 0.0  # 0.0 es centro (0% pitch)
        self._dragging = False
        self.setMinimumSize(28, 70)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{label}: +0.00%")

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, val: float):
        v = max(-1.0, min(1.0, float(val)))
        if abs(v) < 0.025:
            v = 0.0
        if abs(v - self._value) > 1e-4:
            self._value = v
            pct = self._value * self.range_pct
            self.setToolTip(f"{self.label}: {pct:+.2f}%")
            self.valueChanged.emit(self._value)
            rate = 1.0 + (pct / 100.0)
            self.rateChanged.emit(rate)
            self.update()

    pitchValue = Property(float, _get_value, _set_value)
    value = Property(float, _get_value, _set_value)

    def setValue(self, val: float):
        self._set_value(val)

    def setPitch(self, pct: float):
        norm = max(-1.0, min(1.0, float(pct) / max(0.1, self.range_pct)))
        self._set_value(norm)

    def resetPitch(self):
        self.setValue(0.0)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._update_from_mouse(event.position().y())
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.resetPitch()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_mouse(event.position().y())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.setValue(self._value + (0.05 if delta < 0 else -0.05))
        event.accept()

    def _update_from_mouse(self, y: float):
        margin = max(10, int(self.height() * 0.08))
        h = self.height() - margin * 2
        if h <= 0:
            return
        frac = (y - margin) / h
        val = (frac - 0.5) * 2.0
        self.setValue(val)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx = w / 2.0
        margin = max(10, int(h * 0.08))

        track_w = max(4.0, min(6.0, w * 0.22))
        track_h = h - margin * 2
        track_rect = QRectF(cx - track_w / 2.0, margin, track_w, track_h)
        p.setPen(QPen(QColor(10, 10, 12), 1.0))
        p.setBrush(QColor(16, 16, 20))
        p.drawRoundedRect(track_rect, 2, 2)

        p.setPen(QPen(QColor(70, 70, 80), 1))
        steps = (-1.0, -0.6, -0.3, 0.0, 0.3, 0.6, 1.0)
        for s in steps:
            sy = margin + (s * 0.5 + 0.5) * track_h
            mark_len = 5 if s == 0.0 else 3
            p.drawLine(QPointF(cx - 3 - mark_len, sy), QPointF(cx - 3, sy))
            p.drawLine(QPointF(cx + 3, sy), QPointF(cx + 3 + mark_len, sy))

        center_y = margin + 0.5 * track_h
        is_zero = abs(self._value) < 0.001
        led_color = QColor(0, 255, 100) if is_zero else QColor(25, 50, 30)
        p.setPen(Qt.NoPen)
        p.setBrush(led_color)
        p.drawEllipse(QPointF(cx - track_w / 2.0 - 5, center_y), 2.0, 2.0)

        hy = margin + (self._value * 0.5 + 0.5) * track_h
        handle_w = max(18.0, min(26.0, w * 0.90))
        handle_h = max(12.0, min(18.0, h * 0.16))
        handle_rect = QRectF(cx - handle_w / 2.0, hy - handle_h / 2.0, handle_w, handle_h)

        h_grad = QLinearGradient(0, hy - handle_h / 2.0, 0, hy + handle_h / 2.0)
        h_grad.setColorAt(0.0, QColor(70, 70, 80))
        h_grad.setColorAt(0.5, QColor(35, 35, 42))
        h_grad.setColorAt(1.0, QColor(20, 20, 25))

        p.setPen(QPen(QColor(12, 12, 15), 1.0))
        p.setBrush(QBrush(h_grad))
        p.drawRoundedRect(handle_rect, 2, 2)

        p.setPen(QPen(self.accent_color, 1.5))
        p.drawLine(QPointF(cx - handle_w / 2.0 + 2, hy), QPointF(cx + handle_w / 2.0 - 2, hy))


# =====================================================================================================
# 2. HOT CUE & PERFORMANCE PADS (PIONEER CDJ STYLE)
# =====================================================================================================
class DjHotCuePads(QWidget):
    """Pads de rendimiento multifunción (Hot Cue, Beat Loop, Beat Jump) con 6 pads estilo VirtualDJ."""
    padTriggered = Signal(int, str)  # pad_index (0..5), mode ("HOT CUE" | "LOOP" | "JUMP")
    padCleared = Signal(int)        # pad_index (0..5) para borrar Hot Cue con clic secundario

    def __init__(self, accent_color="#1ED760", parent=None):
        super().__init__(parent)
        self.accent_color = accent_color
        self._mode = "HOT CUE"
        self._pad_colors = ["#00FF66", "#FF8800", "#00DDFF", "#FF0088", "#FFDD00", "#AA44FF"]
        self._active_cues = [False] * 6

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # Barra de selección de modo
        mode_lay = QHBoxLayout()
        mode_lay.setSpacing(2)
        self.btn_mode_cue = QPushButton("HOT CUE")
        self.btn_mode_loop = QPushButton("LOOP")
        self.btn_mode_jump = QPushButton("JUMP")

        for b, m in ((self.btn_mode_cue, "HOT CUE"), (self.btn_mode_loop, "LOOP"), (self.btn_mode_jump, "JUMP")):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("""
                QPushButton {
                    min-width: 0px;
                    background-color: #1A1A22;
                    color: #888899;
                    font-size: 8px;
                    font-weight: 800;
                    border: 1px solid #282835;
                    border-radius: 3px;
                    padding: 2px 4px;
                }
                QPushButton:hover { background-color: #262635; color: #FFFFFF; }
            """)
            b.clicked.connect(lambda _=False, mode_name=m: self.setMode(mode_name))
            mode_lay.addWidget(b)
        lay.addLayout(mode_lay)

        # Rejilla de 6 pads estilo VirtualDJ (2 filas x 3 columnas: 1 2 3 / 4 5 6)
        pads_grid = QGridLayout()
        pads_grid.setSpacing(3)
        self._pad_buttons = []
        labels = ("1", "2", "3", "4", "5", "6")
        for i in range(6):
            btn = QPushButton(labels[i])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            btn.setMinimumHeight(22)
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda _pos, idx=i: self._on_pad_right_clicked(idx))
            c = self._pad_colors[i]
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #161620;
                    color: {c};
                    font-size: 10px;
                    font-weight: 900;
                    border: 1.5px solid {c};
                    border-radius: 4px;
                }}
                QPushButton:hover {{ background-color: {c}33; }}
                QPushButton:pressed {{ background-color: {c}; color: #000000; }}
            """)
            btn.clicked.connect(lambda _=False, idx=i: self._on_pad_clicked(idx))
            self._pad_buttons.append(btn)
            pads_grid.addWidget(btn, i // 3, i % 3)
        lay.addLayout(pads_grid)
        self._update_mode_ui()

    @property
    def pads(self):
        return self._pad_buttons

    @property
    def _pads(self):
        return self._pad_buttons

    def setMode(self, mode: str):
        self._mode = mode
        self._update_mode_ui()

    def _update_mode_ui(self):
        active_style = "background-color: #2E2E42; color: #FFFFFF; font-size: 8px; font-weight: 900; border: 1px solid #00E5FF; border-radius: 3px; padding: 2px 4px;"
        idle_style = "background-color: #1A1A22; color: #888899; font-size: 8px; font-weight: 800; border: 1px solid #282835; border-radius: 3px; padding: 2px 4px;"
        self.btn_mode_cue.setStyleSheet(active_style if self._mode == "HOT CUE" else idle_style)
        self.btn_mode_loop.setStyleSheet(active_style if self._mode == "LOOP" else idle_style)
        self.btn_mode_jump.setStyleSheet(active_style if self._mode == "JUMP" else idle_style)

    def _on_pad_clicked(self, idx: int):
        self.padTriggered.emit(idx, self._mode)

    def _on_pad_right_clicked(self, idx: int):
        self.setCueActive(idx, False)
        self.padCleared.emit(idx)

    def setCueActive(self, idx: int, active: bool, label_text: str = ""):
        if 0 <= idx < len(self._pad_buttons):
            self._active_cues[idx] = bool(active)
            btn = self._pad_buttons[idx]
            c = self._pad_colors[idx]
            if active and self._mode == "HOT CUE":
                text = label_text if label_text else f"● {idx + 1}"
                btn.setText(text)
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c};
                        color: #000000;
                        font-size: 10px;
                        font-weight: 900;
                        border: 2px solid #FFFFFF;
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{ background-color: {c}CC; }}
                """)
            else:
                btn.setText(str(idx + 1))
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #161620;
                        color: {c};
                        font-size: 11px;
                        font-weight: 900;
                        border: 1.5px solid {c};
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{ background-color: {c}33; }}
                    QPushButton:pressed {{ background-color: {c}; color: #000000; }}
                """)

    def clearAllCues(self):
        for i in range(4):
            self.setCueActive(i, False)


# =====================================================================================================
# 3. BEAT LOOP & AUTO BEAT LOOP (PIONEER CDJ STYLE)
# =====================================================================================================
class DjLoopControls(QWidget):
    """Sección de Beat Loop: Loop In / 4 Beat, Loop Out, Reloop / Exit y divisores 1/2X, 2X."""
    loopInRequested = Signal()
    loopOutRequested = Signal()
    reloopRequested = Signal()
    halfLoopRequested = Signal()
    doubleLoopRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loop_active = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        self.btn_in = QPushButton("IN / 4BEAT")
        self.btn_in.setCursor(Qt.PointingHandCursor)
        self.btn_in.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #383015;
                color: #FFDD44;
                font-size: 8px;
                font-weight: 900;
                border: 1px solid #FFDD44;
                border-radius: 3px;
                padding: 3px 4px;
            }
            QPushButton:hover { background-color: #4C401D; }
        """)
        self.btn_in.clicked.connect(self.loopInRequested.emit)

        self.btn_out = QPushButton("OUT")
        self.btn_out.setCursor(Qt.PointingHandCursor)
        self.btn_out.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #383015;
                color: #FFDD44;
                font-size: 8px;
                font-weight: 900;
                border: 1px solid #FFDD44;
                border-radius: 3px;
                padding: 3px 4px;
            }
            QPushButton:hover { background-color: #4C401D; }
        """)
        self.btn_out.clicked.connect(self.loopOutRequested.emit)

        self.btn_reloop = QPushButton("RELOOP")
        self.btn_reloop.setCursor(Qt.PointingHandCursor)
        self.btn_reloop.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #382415;
                color: #FF8822;
                font-size: 8px;
                font-weight: 900;
                border: 1px solid #FF8822;
                border-radius: 3px;
                padding: 3px 4px;
            }
            QPushButton:hover { background-color: #4C301D; }
        """)
        self.btn_reloop.clicked.connect(self.reloopRequested.emit)

        self.btn_half = QPushButton("1/2X")
        self.btn_half.setCursor(Qt.PointingHandCursor)
        self.btn_half.setStyleSheet("QPushButton { min-width: 0px; background-color: #1E1E26; color: #AAA; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 3px 4px; }")
        self.btn_half.clicked.connect(self.halfLoopRequested.emit)

        self.btn_double = QPushButton("2X")
        self.btn_double.setCursor(Qt.PointingHandCursor)
        self.btn_double.setStyleSheet("QPushButton { min-width: 0px; background-color: #1E1E26; color: #AAA; font-size: 8px; font-weight: bold; border-radius: 3px; padding: 3px 4px; }")
        self.btn_double.clicked.connect(self.doubleLoopRequested.emit)

        lay.addWidget(self.btn_in)
        lay.addWidget(self.btn_out)
        lay.addWidget(self.btn_reloop)
        lay.addWidget(self.btn_half)
        lay.addWidget(self.btn_double)

    def setLoopActive(self, active: bool):
        self._loop_active = bool(active)
        if self._loop_active:
            self.btn_reloop.setStyleSheet("""
                QPushButton {
                    min-width: 0px;
                    background-color: #FF8822;
                    color: #000000;
                    font-size: 8px;
                    font-weight: 900;
                    border: 1.5px solid #FFFFFF;
                    border-radius: 3px;
                    padding: 3px 4px;
                }
            """)
        else:
            self.btn_reloop.setStyleSheet("""
                QPushButton {
                    min-width: 0px;
                    background-color: #382415;
                    color: #FF8822;
                    font-size: 8px;
                    font-weight: 900;
                    border: 1px solid #FF8822;
                    border-radius: 3px;
                    padding: 3px 4px;
                }
                QPushButton:hover { background-color: #4C301D; }
            """)


# =====================================================================================================
# 4. BEAT FX UNIT (PIONEER DJM-A9 STYLE)
# =====================================================================================================
class DjBeatFxRack(QWidget):
    """Módulo de Beat FX estilo Pioneer DJM-A9:
    Pantalla OLED de efectos, selector de efectos, asignación de canal, división de beat, knob Depth y botón luminoso ON/OFF."""
    fxChanged = Signal(str, dict)
    fxToggled = Signal(bool)

    EFFECTS = ["ECHO", "REVERB", "DELAY", "FLANGER", "ROLL", "PHASER", "FILTER FX"]
    CHANNELS = ["CH 1", "CH 2", "MASTER", "XF A", "XF B"]
    BEATS = ["1/4", "1/2", "3/4", "1", "2", "4"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_fx = "ECHO"
        self._current_ch = "MASTER"
        self._beat_idx = 2  # 3/4 por defecto
        self._is_active = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.setStyleSheet("""
            DjBeatFxRack {
                background-color: #14141C;
                border: 1px solid #282838;
                border-radius: 8px;
            }
        """)

        lbl_head = QLabel("BEAT FX (DJM-A9)")
        lbl_head.setStyleSheet("font-size: 9px; font-weight: 900; color: #00D2FF; letter-spacing: 1px;")
        lbl_head.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl_head)

        self.screen = QFrame()
        self.screen.setStyleSheet("background-color: #08080C; border: 1px solid #1A1A28; border-radius: 5px;")
        scr_lay = QVBoxLayout(self.screen)
        scr_lay.setContentsMargins(6, 4, 6, 4)
        scr_lay.setSpacing(2)

        scr_top = QHBoxLayout()
        self.lbl_fx_name = QLabel(self._current_fx)
        self.lbl_fx_name.setStyleSheet("font-size: 11px; font-weight: 900; color: #00E5FF;")
        self.lbl_ch = QLabel(self._current_ch)
        self.lbl_ch.setStyleSheet("font-size: 9px; font-weight: bold; color: #FF9900;")
        scr_top.addWidget(self.lbl_fx_name)
        scr_top.addStretch()
        scr_top.addWidget(self.lbl_ch)
        scr_lay.addLayout(scr_top)

        scr_bot = QHBoxLayout()
        self.lbl_beat = QLabel(f"BEAT: {self.BEATS[self._beat_idx]}")
        self.lbl_beat.setStyleSheet("font-size: 10px; font-weight: 800; color: #FFFFFF; font-family: monospace;")
        self.lbl_bpm = QLabel("128.0 BPM")
        self.lbl_bpm.setStyleSheet("font-size: 9px; color: #888899;")
        scr_bot.addWidget(self.lbl_beat)
        scr_bot.addStretch()
        scr_bot.addWidget(self.lbl_bpm)
        scr_lay.addLayout(scr_bot)

        lay.addWidget(self.screen)

        sel_row = QHBoxLayout()
        sel_row.setSpacing(4)
        self.combo_fx = QComboBox()
        self.combo_fx.addItems(self.EFFECTS)
        self.combo_fx.setStyleSheet("QComboBox { background-color: #1A1A24; color: #CCC; font-size: 9px; font-weight: bold; border: 1px solid #333345; border-radius: 4px; padding: 2px 4px; }")
        self.combo_fx.currentTextChanged.connect(self._on_fx_selected)

        self.combo_ch = QComboBox()
        self.combo_ch.addItems(self.CHANNELS)
        self.combo_ch.setStyleSheet("QComboBox { background-color: #1A1A24; color: #CCC; font-size: 9px; font-weight: bold; border: 1px solid #333345; border-radius: 4px; padding: 2px 4px; }")
        self.combo_ch.currentTextChanged.connect(self._on_ch_selected)

        sel_row.addWidget(self.combo_fx, 2)
        sel_row.addWidget(self.combo_ch, 1)
        lay.addLayout(sel_row)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)

        self.btn_prev_beat = QPushButton("<")
        self.btn_prev_beat.setCursor(Qt.PointingHandCursor)
        self.btn_prev_beat.setStyleSheet("QPushButton { min-width: 0px; background-color: #22222E; color: #FFF; font-size: 11px; font-weight: 900; border-radius: 4px; padding: 4px 6px; }")
        self.btn_prev_beat.clicked.connect(self._prev_beat)

        self.btn_next_beat = QPushButton(">")
        self.btn_next_beat.setCursor(Qt.PointingHandCursor)
        self.btn_next_beat.setStyleSheet("QPushButton { min-width: 0px; background-color: #22222E; color: #FFF; font-size: 11px; font-weight: 900; border-radius: 4px; padding: 4px 6px; }")
        self.btn_next_beat.clicked.connect(self._next_beat)

        self.knob_depth = DjRotaryKnob("DEPTH", min_val=0.0, max_val=1.0, default_val=0.5, accent_color="#00D2FF", bipolar=False, unit="%")
        self.knob_depth.valueChanged.connect(self._on_depth_changed)

        ctrl_row.addWidget(self.btn_prev_beat)
        ctrl_row.addWidget(self.knob_depth)
        ctrl_row.addWidget(self.btn_next_beat)
        lay.addLayout(ctrl_row)

        self.btn_on_off = QPushButton("BEAT FX ON/OFF")
        self.btn_on_off.setCursor(Qt.PointingHandCursor)
        self.btn_on_off.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #182235;
                color: #00D2FF;
                font-size: 10px;
                font-weight: 900;
                border: 2px solid #00D2FF;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QPushButton:hover { background-color: #20304C; }
        """)
        self.btn_on_off.clicked.connect(self._toggle_fx)
        lay.addWidget(self.btn_on_off)

    def _on_fx_selected(self, text: str):
        self._current_fx = text
        self.lbl_fx_name.setText(text)
        self._emit_change()

    def _on_ch_selected(self, text: str):
        self._current_ch = text
        self.lbl_ch.setText(text)
        self._emit_change()

    def _prev_beat(self):
        if self._beat_idx > 0:
            self._beat_idx -= 1
            self.lbl_beat.setText(f"BEAT: {self.BEATS[self._beat_idx]}")
            self._emit_change()

    def _next_beat(self):
        if self._beat_idx < len(self.BEATS) - 1:
            self._beat_idx += 1
            self.lbl_beat.setText(f"BEAT: {self.BEATS[self._beat_idx]}")
            self._emit_change()

    def _on_depth_changed(self, val: float):
        self._emit_change()

    def _toggle_fx(self):
        self._is_active = not self._is_active
        if self._is_active:
            self.btn_on_off.setStyleSheet("""
                QPushButton {
                    min-width: 0px;
                    background-color: #00D2FF;
                    color: #000000;
                    font-size: 10px;
                    font-weight: 900;
                    border: 2px solid #FFFFFF;
                    border-radius: 6px;
                    padding: 6px 8px;
                }
            """)
        else:
            self.btn_on_off.setStyleSheet("""
                QPushButton {
                    min-width: 0px;
                    background-color: #182235;
                    color: #00D2FF;
                    font-size: 10px;
                    font-weight: 900;
                    border: 2px solid #00D2FF;
                    border-radius: 6px;
                    padding: 6px 8px;
                }
                QPushButton:hover { background-color: #20304C; }
            """)
        self.fxToggled.emit(self._is_active)
        self._emit_change()

    def setActive(self, active: bool):
        if self._is_active != bool(active):
            self._toggle_fx()

    def setFx(self, fx_name: str):
        fx_upper = str(fx_name).strip().upper()
        for i in range(self.combo_fx.count()):
            if self.combo_fx.itemText(i).upper() == fx_upper or fx_upper in self.combo_fx.itemText(i).upper():
                self.combo_fx.setCurrentIndex(i)
                return
        self._current_fx = fx_upper
        self.lbl_fx_name.setText(fx_upper)
        self._emit_change()

    def setBeat(self, beat_str: str):
        b_str = str(beat_str).strip()
        if b_str in self.BEATS:
            self._beat_idx = self.BEATS.index(b_str)
            self.lbl_beat.setText(f"BEAT: {self.BEATS[self._beat_idx]}")
            self._emit_change()

    @property
    def _current_beat(self) -> str:
        return self.BEATS[self._beat_idx]

    @property
    def current_beat(self) -> str:
        return self.BEATS[self._beat_idx]

    def _emit_change(self):
        beat_val = [0.25, 0.5, 0.75, 1.0, 2.0, 4.0][self._beat_idx]
        self.fxChanged.emit(self._current_fx.lower(), {
            "channel": self._current_ch,
            "beats": beat_val,
            "depth": self.knob_depth.value,
            "active": self._is_active
        })


# =====================================================================================================
# 5. MASTER & HEADPHONE MONITOR SECTION (PIONEER DJM-A9 STYLE)
# =====================================================================================================
class DjMasterMonitorSection(QWidget):
    """Sección de Master, Booth y Monitorización de Auriculares (Headphones Level, Mix, Cue A/B)."""
    cueToggled = Signal(str, bool)
    masterVolumeChanged = Signal(float)
    boothVolumeChanged = Signal(float)
    hpLevelChanged = Signal(float)
    hpMixChanged = Signal(float)
    hpAbToggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._m_cue_active = False
        self._hp_ab_mode = "A"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        lbl = QLabel("MONITOR / MASTER")
        lbl.setStyleSheet("font-size: 8px; font-weight: 800; color: #888899; letter-spacing: 0.5px;")
        lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl)

        knobs_row1 = QHBoxLayout()
        knobs_row1.setSpacing(4)
        self.knob_master = DjRotaryKnob("MASTER", 0.0, 1.0, 1.0, accent_color="#FFFFFF", bipolar=False, unit="%")
        self.knob_booth = DjRotaryKnob("BOOTH", 0.0, 1.0, 0.7, accent_color="#FFAA00", bipolar=False, unit="%")
        self.knob_master.valueChanged.connect(self.masterVolumeChanged.emit)
        self.knob_booth.valueChanged.connect(self.boothVolumeChanged.emit)
        knobs_row1.addWidget(self.knob_master)
        knobs_row1.addWidget(self.knob_booth)
        lay.addLayout(knobs_row1)

        knobs_row2 = QHBoxLayout()
        knobs_row2.setSpacing(4)
        self.knob_hp_level = DjRotaryKnob("HP VOL", 0.0, 1.0, 0.75, accent_color="#00E5FF", bipolar=False, unit="%")
        self.knob_hp_vol = self.knob_hp_level
        self.knob_hp_mix = DjRotaryKnob("HP MIX", -1.0, 1.0, 0.0, accent_color="#00E5FF", bipolar=True, unit="%")
        self.knob_hp_level.valueChanged.connect(self.hpLevelChanged.emit)
        self.knob_hp_mix.valueChanged.connect(self.hpMixChanged.emit)
        knobs_row2.addWidget(self.knob_hp_level)
        knobs_row2.addWidget(self.knob_hp_mix)
        lay.addLayout(knobs_row2)

        cue_row = QHBoxLayout()
        cue_row.setSpacing(4)
        self.btn_cue_master = QPushButton("M-CUE")
        self.btn_master_cue = self.btn_cue_master
        self.btn_cue_master.setCursor(Qt.PointingHandCursor)
        self.btn_cue_master.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #2D2010;
                color: #FFAA33;
                font-size: 9px;
                font-weight: 800;
                border: 1px solid #FFAA33;
                border-radius: 4px;
                padding: 3px 6px;
            }
            QPushButton:hover { background-color: #443018; }
        """)
        self.btn_cue_master.clicked.connect(self._toggle_master_cue)

        self.btn_hp_ab = QPushButton("HP A")
        self.btn_hp_a_b = self.btn_hp_ab
        self.btn_hp_ab.setCursor(Qt.PointingHandCursor)
        self.btn_hp_ab.setStyleSheet("QPushButton { min-width: 0px; background-color: #1E1E26; color: #00E5FF; font-size: 9px; font-weight: bold; border-radius: 4px; padding: 3px 6px; border: 1px solid #00E5FF; }")
        self.btn_hp_ab.clicked.connect(self._toggle_hp_ab)

        cue_row.addWidget(self.btn_cue_master)
        cue_row.addWidget(self.btn_hp_ab)
        lay.addLayout(cue_row)

    def _toggle_master_cue(self):
        self._m_cue_active = not self._m_cue_active
        if self._m_cue_active:
            self.btn_cue_master.setStyleSheet("""
                QPushButton {
                    min-width: 0px;
                    background-color: #FFAA33;
                    color: #000000;
                    font-size: 9px;
                    font-weight: 900;
                    border: 1.5px solid #FFFFFF;
                    border-radius: 4px;
                    padding: 3px 6px;
                }
            """)
        else:
            self.btn_cue_master.setStyleSheet("""
                QPushButton {
                    min-width: 0px;
                    background-color: #2D2010;
                    color: #FFAA33;
                    font-size: 9px;
                    font-weight: 800;
                    border: 1px solid #FFAA33;
                    border-radius: 4px;
                    padding: 3px 6px;
                }
                QPushButton:hover { background-color: #443018; }
            """)
        self.cueToggled.emit("MASTER", self._m_cue_active)

    def _toggle_hp_ab(self):
        self._hp_ab_mode = "B" if self._hp_ab_mode == "A" else "A"
        color = "#00E5FF" if self._hp_ab_mode == "A" else "#FF7700"
        self.btn_hp_ab.setText(f"HP {self._hp_ab_mode}")
        self.btn_hp_ab.setStyleSheet(f"QPushButton {{ min-width: 0px; background-color: #1E1E26; color: {color}; font-size: 9px; font-weight: bold; border-radius: 4px; padding: 3px 6px; border: 1px solid {color}; }}")
        self.hpAbToggled.emit(self._hp_ab_mode)


# =====================================================================================================
# 6. PANEL TRASERO DE CONEXIONES I/O (PIONEER DJM-A9 & CDJ)
# =====================================================================================================
class DjRearPanelDialog(QDialog):
    """Panel posterior gráfico con todas las entradas y salidas reales del DJM-A9 y CDJs:
    Master XLR, Master RCA, Booth Out, USBs, LAN Pro DJ Link, MIC Inputs, AUX, LINE, PHONO, Power y Tierra.
    Totalmente interactivo: cada conector responde a clics conmutando conexión y mostrando especificaciones técnicas."""
    connectionToggled = Signal(str, bool)

    CONNECTORS = [
        ("Master XLR", "Salida principal balanceada (L/R) a sistema de sonido PA profesional", "XLR L/R", "#00FF66", "+24 dBu max, balanceado 600 Ω, Neutrik NC3MD"),
        ("Master RCA", "Salida principal no balanceada (L/R) mediante conectores RCA dorados", "RCA L/R", "#FFCC00", "+18 dBV max, chapado en oro, 10 kΩ"),
        ("Booth Out", "Salida estéreo balanceada (Jack 1/4\" TRS) para monitores de cabina", "JACK TRS", "#00CCFF", "+24 dBu max, balanceado 600 Ω, TRS 6.35mm"),
        ("USB Host/Link", "Conexión USB Type-B y Type-C con ordenador (Antigravity DJ / Rekordbox)", "USB DUAL", "#FF0055", "32-bit / 96 kHz, USB Audio Class 2.0 asíncrono"),
        ("LAN Pro DJ Link", "Puertos Ethernet RJ45 para sincronización de tempo y metadatos", "RJ45 LINK", "#00E5FF", "Gigabit 1000BASE-T, TCPIP Sync & Rekordbox DB"),
        ("MIC Input & Level", "Entrada de micrófono Combo XLR/Jack con control de ganancia y Talkover", "MIC COMBO", "#FFAA00", "-52 dBu sensibilidad, previo analógico Clase A"),
        ("AUX Input", "Entrada auxiliar de línea estéreo RCA para teléfonos o reproductores externos", "AUX STEREO", "#E0E0E0", "-12 dBV / +4 dBu conmutables, 47 kΩ"),
        ("LINE Inputs", "Entradas de nivel de línea RCA para canales 1 y 2", "CH 1/2 LINE", "#CCCCCC", "Nivel de línea estándar +4 dBu, 47 kΩ"),
        ("PHONO Inputs", "Entradas preamplificadas RIAA para tocadiscos de vinilo (Ch 1 y Ch 2)", "PHONO RIAA", "#FF5533", "Curva RIAA de alta precisión, relación S/N 88 dB"),
        ("Ground Terminal", "Borne de toma de tierra metálico (GND) para eliminar zumbidos de masa", "GND SCREW", "#FFDD00", "Borne macizo moleteado de cobre para conexión equipotencial"),
        ("Power (Alimentación)", "Conector eléctrico IEC con interruptor basculante e indicador LED", "POWER AC", "#00FF66", "Entrada IEC C14 100-240V 50/60Hz, 54W"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Panel Posterior de Conexiones I/O - Mesa Pioneer DJM-A9 & CDJs")
        self.resize(800, 440)
        self.setStyleSheet("""
            QDialog {
                background-color: #121218;
                color: #FFFFFF;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("PANEL TRASERO DE ENTRADAS Y SALIDAS (I/O BACKPLANE)")
        title.setStyleSheet("font-size: 15px; font-weight: 900; color: #00E5FF; letter-spacing: 1px;")
        layout.addWidget(title)

        desc = QLabel("Emulación física interactiva de las conexiones profesionales. Haz clic en cualquier puerto para conectar/desconectar o consultar especificaciones:")
        desc.setStyleSheet("font-size: 11px; color: #888899;")
        layout.addWidget(desc)

        chassis = QFrame()
        chassis.setStyleSheet("background-color: #0B0B0F; border: 2px solid #20202C; border-radius: 8px;")
        ch_lay = QGridLayout(chassis)
        ch_lay.setContentsMargins(12, 12, 12, 12)
        ch_lay.setSpacing(8)

        self._conn_states = {}
        self._connector_buttons = {}
        row = 0
        col = 0
        for name, desc_text, badge, color, specs in self.CONNECTORS:
            card = QPushButton()
            card.setText(f"{name} [CONECTADO]")
            card.setCursor(Qt.PointingHandCursor)
            card.setStyleSheet("""
                QPushButton {
                    background-color: #151520;
                    border: 1px solid #262638;
                    border-radius: 6px;
                    padding: 6px;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: #1C1C2C;
                    border-color: #383850;
                }
            """)
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(4, 4, 4, 4)
            c_lay.setSpacing(2)

            top = QHBoxLayout()
            lbl_name = QLabel(name)
            lbl_name.setStyleSheet("font-size: 11px; font-weight: 800; color: #FFFFFF;")
            lbl_badge = QLabel(badge)
            lbl_badge.setStyleSheet(f"font-size: 9px; font-weight: 800; color: {color}; background-color: {color}22; border-radius: 3px; padding: 1px 4px;")
            top.addWidget(lbl_name)
            top.addStretch()
            top.addWidget(lbl_badge)
            c_lay.addLayout(top)

            lbl_d = QLabel(desc_text)
            lbl_d.setStyleSheet("font-size: 9px; color: #9999A8;")
            lbl_d.setWordWrap(True)
            c_lay.addWidget(lbl_d)

            status_lbl = QLabel("● CONECTADO")
            status_lbl.setStyleSheet(f"font-size: 8.5px; font-weight: 800; color: {color};")
            c_lay.addWidget(status_lbl)

            self._conn_states[name] = {"connected": True, "status_lbl": status_lbl, "color": color, "specs": specs}
            self._connector_buttons[name] = card
            card.clicked.connect(lambda _=False, n=name: self._toggle_connector(n))

            ch_lay.addWidget(card, row, col)
            col += 1
            if col >= 3:
                col = 0
                row += 1

        layout.addWidget(chassis)

        btn_row = QHBoxLayout()
        self.lbl_info = QLabel("Haz clic en cualquier puerto para ver sus especificaciones técnicas.")
        self.lbl_info.setStyleSheet("font-size: 10px; color: #00E5FF; font-style: italic;")
        btn_row.addWidget(self.lbl_info, 1)

        btn_close = QPushButton("Cerrar Panel Posterior")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #22222E;
                color: #FFFFFF;
                font-size: 11px;
                font-weight: bold;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover { background-color: #2D2D3D; }
        """)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _toggle_connector(self, name: str):
        info = self._conn_states.get(name)
        if not info:
            return
        info["connected"] = not info["connected"]
        is_conn = info["connected"]
        btn = self._connector_buttons.get(name)
        if btn:
            btn.setText(f"{name} [{'CONECTADO' if is_conn else 'DESCONECTADO'}]")
        lbl = info["status_lbl"]
        color = info["color"]
        if is_conn:
            lbl.setText("● CONECTADO")
            lbl.setStyleSheet(f"font-size: 8.5px; font-weight: 800; color: {color};")
            self.lbl_info.setText(f"{name}: CONECTADO | {info['specs']}")
        else:
            lbl.setText("○ DESCONECTADO")
            lbl.setStyleSheet("font-size: 8.5px; font-weight: 800; color: #666677;")
            self.lbl_info.setText(f"{name}: DESCONECTADO (Señal interrumpida)")
        self.connectionToggled.emit(name, is_conn)


# =====================================================================================================
# 7. ENTORNO Y EQUIPAMIENTO ADICIONAL DE CABINA DJ
# =====================================================================================================
class DjEnvironmentBar(QFrame):
    """Barra interactiva del equipamiento del DJ:
    DJ Headphones, Studio Monitors, PA Speakers, Subwoofer, Microphone, USB Flash Drive, Laptop, Audio Interface, DJ Stand."""
    itemTriggered = Signal(str, str)  # item_id, title

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            DjEnvironmentBar {
                background-color: #121217;
                border: 1px solid #1E1E26;
                border-radius: 8px;
            }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        self._items = [
            ("headphones", "🎧 Headphones", "Preescucha en privado de temas sin salir a público (PFL Cue)", "#00E5FF"),
            ("monitors", "🔊 Monitors", "Monitores activos de cabina para mezcla de precisión (Booth Mute)", "#00FF66"),
            ("pa", "📢 PA Speakers", "Sistema de sonido frontal para la pista de baile (Master Mute)", "#FFDD00"),
            ("subwoofer", "💥 Subwoofer", "Pegada en frecuencias subgraves con pegada dinámica (Bass Boost)", "#FF5533"),
            ("mic", "🎙️ Mic", "Micrófono de cabina con atenuación Talkover automática", "#FFAA00"),
            ("usb", "💾 USB Drive", "Memorias USB montadas y listas para carga de canciones (Explorar)", "#00E5FF"),
            ("laptop", "💻 Laptop", "Núcleo de reproducción y análisis de audio Antigravity DJ (Stats)", "#BB88FF"),
            ("audio_if", "🎛️ Audio I/F", "Tarjeta de sonido profesional 24-bit / 96 kHz (Config)", "#00FF66"),
            ("stand", "🏗️ DJ Stand", "Cabina y soporte ergonómico con aislamiento acústico (Luces)", "#888899"),
        ]

        self.buttons = {}
        for item_id, title, tooltip, color in self._items:
            btn = QPushButton(title)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(f"""
                QPushButton {{
                    min-width: 0px;
                    font-size: 10px;
                    font-weight: 800;
                    color: #CCCCCC;
                    background-color: #1A1A24;
                    border: 1px solid #282836;
                    border-radius: 4px;
                    padding: 3px 6px;
                }}
                QPushButton:hover {{ color: {color}; border-color: {color}; background-color: #242434; }}
                QPushButton:pressed {{ background-color: {color}33; }}
            """)
            btn.clicked.connect(lambda _=False, i=item_id, t=title: self._on_item_clicked(i, t))
            self.buttons[item_id] = btn
            lay.addWidget(btn)

    def _on_item_clicked(self, item_id: str, title: str):
        self.itemTriggered.emit(item_id, title)


# =====================================================================================================
# 7b. SELECTOR DE SOUND COLOR FX (PIONEER DJM-A9)
# =====================================================================================================
class DjColorFxSelector(QWidget):
    """Selector de Sound Color FX estilo Pioneer DJM-A9:
    Botones iluminados para SPACE, DUB ECHO, SWEEP, NOISE, CRUSH, FILTER."""
    colorFxChanged = Signal(str)

    EFFECTS = [
        ("SPACE", "#00E5FF"),
        ("DUB ECHO", "#FFAA00"),
        ("SWEEP", "#FF0088"),
        ("NOISE", "#FFFFFF"),
        ("CRUSH", "#FF3344"),
        ("FILTER", "#00FF66"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_fx = "FILTER"
        self._buttons = {}

        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        for idx, (name, col) in enumerate(self.EFFECTS):
            btn = QPushButton(name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setFixedHeight(18)
            btn.clicked.connect(lambda _=False, n=name: self.selectFx(n))
            self._buttons[name] = (btn, col)
            row = idx // 2
            col_pos = idx % 2
            lay.addWidget(btn, row, col_pos)

        self._update_styles()

    def selectFx(self, name: str):
        if name in self._buttons and name != self._current_fx:
            self._current_fx = name
            self._update_styles()
            self.colorFxChanged.emit(name)

    def currentFx(self) -> str:
        return self._current_fx

    def _update_styles(self):
        for name, (btn, col) in self._buttons.items():
            if name == self._current_fx:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        min-width: 0px;
                        background-color: {col};
                        color: #000000;
                        font-size: 7.5px;
                        font-weight: 900;
                        border: 1px solid #FFFFFF;
                        border-radius: 3px;
                        padding: 1px 3px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        min-width: 0px;
                        background-color: #181822;
                        color: {col}AA;
                        font-size: 7.5px;
                        font-weight: 800;
                        border: 1px solid #282836;
                        border-radius: 3px;
                        padding: 1px 3px;
                    }}
                    QPushButton:hover {{ background-color: #242434; color: #FFFFFF; }}
                """)


# =====================================================================================================
# 7c. NAVEGADOR DE BIBLIOTECA PIONEER CDJ-3000 (BROWSE)
# =====================================================================================================
class DjTrackBrowserDialog(QDialog):
    """Navegador de canciones y biblioteca estilo pantalla Pioneer CDJ-3000.
    Permite buscar, filtrar por BPM/Tono, previsualizar y cargar en Deck A o Deck B."""
    trackSelected = Signal(str, dict)  # "A" o "B", track_dict

    def __init__(self, tracks: list, target_deck="A", parent=None):
        super().__init__(parent)
        self.tracks = tracks or []
        self.target_deck = target_deck
        self.setWindowTitle("Navegador de Biblioteca Pioneer CDJ-3000 (BROWSE)")
        self.resize(720, 440)
        self.setStyleSheet("""
            QDialog {
                background-color: #121218;
                color: #FFFFFF;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QLineEdit {
                background-color: #181824;
                color: #FFFFFF;
                border: 1px solid #2D2D40;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QTableWidget {
                background-color: #14141E;
                alternate-background-color: #181826;
                color: #FFFFFF;
                border: 1px solid #242436;
                border-radius: 6px;
                gridline-color: #1E1E2C;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #1E1E2C;
                color: #00E5FF;
                font-weight: 900;
                padding: 6px;
                border: none;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        # Header
        top = QHBoxLayout()
        lbl_icon = QLabel("💿")
        lbl_icon.setStyleSheet("font-size: 18px;")
        top.addWidget(lbl_icon)

        lbl_t = QLabel(f"PIONEER CDJ BROWSE — CARGAR EN DECK {target_deck}")
        lbl_t.setStyleSheet("font-size: 14px; font-weight: 900; color: #00E5FF; letter-spacing: 1px;")
        top.addWidget(lbl_t)
        top.addStretch()

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Buscar por título, artista, BPM o tono...")
        self.search_box.textChanged.connect(self._filter_tracks)
        top.addWidget(self.search_box, 1)
        lay.addLayout(top)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Título", "Artista", "BPM", "Key"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._on_double_click)
        lay.addWidget(self.table)

        # Buttons bottom
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_local = QPushButton("📁 Abrir archivo de audio en disco...")
        btn_local.setCursor(Qt.PointingHandCursor)
        btn_local.setStyleSheet("QPushButton { background-color: #242436; color: #CCC; font-size: 11px; font-weight: bold; border-radius: 6px; padding: 6px 12px; } QPushButton:hover { background-color: #303046; color: #FFF; }")
        btn_local.clicked.connect(self._on_choose_local_file)
        btn_row.addWidget(btn_local)

        btn_row.addStretch()

        btn_load_a = QPushButton("LOAD A")
        btn_load_a.setCursor(Qt.PointingHandCursor)
        btn_load_a.setStyleSheet("QPushButton { background-color: #1A3828; color: #1ED760; font-size: 11px; font-weight: 900; border: 1.5px solid #1ED760; border-radius: 6px; padding: 6px 14px; } QPushButton:hover { background-color: #244C36; }")
        btn_load_a.clicked.connect(lambda: self._load_selected("A"))
        btn_row.addWidget(btn_load_a)

        btn_load_b = QPushButton("LOAD B")
        btn_load_b.setCursor(Qt.PointingHandCursor)
        btn_load_b.setStyleSheet("QPushButton { background-color: #382415; color: #FF7700; font-size: 11px; font-weight: 900; border: 1.5px solid #FF7700; border-radius: 6px; padding: 6px 14px; } QPushButton:hover { background-color: #4C301D; }")
        btn_load_b.clicked.connect(lambda: self._load_selected("B"))
        btn_row.addWidget(btn_load_b)

        btn_close = QPushButton("Cerrar")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("QPushButton { background-color: #22222E; color: #AAA; font-size: 11px; font-weight: bold; border-radius: 6px; padding: 6px 12px; }")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)

        lay.addLayout(btn_row)

        self._populate_table(self.tracks)

    def _populate_table(self, track_list):
        self.table.setRowCount(0)
        self._current_items = track_list
        for i, t in enumerate(track_list):
            self.table.insertRow(i)
            idx_item = QTableWidgetItem(f"{i + 1}")
            idx_item.setTextAlignment(Qt.AlignCenter)
            title_item = QTableWidgetItem(t.get("title", "Desconocido"))
            artist_item = QTableWidgetItem(t.get("uploader", t.get("artist", "")))
            bpm = t.get("bpm")
            bpm_str = f"{float(bpm):.1f}" if bpm else "---"
            bpm_item = QTableWidgetItem(bpm_str)
            bpm_item.setTextAlignment(Qt.AlignCenter)
            key_item = QTableWidgetItem(str(t.get("key", t.get("tone", "---"))))
            key_item.setTextAlignment(Qt.AlignCenter)

            self.table.setItem(i, 0, idx_item)
            self.table.setItem(i, 1, title_item)
            self.table.setItem(i, 2, artist_item)
            self.table.setItem(i, 3, bpm_item)
            self.table.setItem(i, 4, key_item)

    def _filter_tracks(self, text: str):
        query = text.strip().lower()
        if not query:
            self._populate_table(self.tracks)
            return
        filtered = []
        for t in self.tracks:
            title = str(t.get("title", "")).lower()
            artist = str(t.get("uploader", t.get("artist", ""))).lower()
            bpm = str(t.get("bpm", "")).lower()
            key = str(t.get("key", t.get("tone", ""))).lower()
            if query in title or query in artist or query in bpm or query in key:
                filtered.append(t)
        self._populate_table(filtered)

    def _on_double_click(self, _index):
        self._load_selected(self.target_deck)

    def _load_selected(self, deck: str):
        row = self.table.currentRow()
        if 0 <= row < len(self._current_items):
            item = self._current_items[row]
            self.trackSelected.emit(deck, item)
            self.accept()

    def _on_choose_local_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, f"Seleccionar pista de audio para Deck {self.target_deck}", "",
            "Archivos de Audio (*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.aiff);;Todos los archivos (*.*)"
        )
        if path:
            import os
            title = os.path.splitext(os.path.basename(path))[0]
            item = {"title": title, "artist": "Archivo Local", "local_path": path, "bpm": 128.0, "key": "8A"}
            self.trackSelected.emit(self.target_deck, item)
            self.accept()


# =====================================================================================================
# 8. TABLA DE REFERENCIA RÁPIDA INTERACTIVA (12 CONTROLES CLAVE)
# =====================================================================================================
class DjQuickReferenceGuide(QDialog):
    """Guía rápida de aprendizaje con los 12 controles más importantes de la cabina según prioridad."""
    controlHighlightRequested = Signal(str)

    CONTROLS = [
        ("1", "Play/Pause", "Reproducir y pausar la canción inmediatamente.", "Transporte", "#00FF66"),
        ("2", "Cue", "Marcar puntos de inicio rítmicos y volver a ellos al instante.", "Transporte", "#FFAA33"),
        ("3", "Jog Wheel", "Manipular la reproducción, empujar el tempo o hacer scratch vinilo.", "Plato", "#00E5FF"),
        ("4", "Pitch Fader", "Ajustar la velocidad (BPM) de la pista para sincronizar con precisión.", "Tempo", "#00FF66"),
        ("5", "Sync", "Sincronizar automáticamente el BPM y compás con el otro reproductor.", "Tempo", "#00D2FF"),
        ("6", "Gain / Trim", "Ajustar niveles de entrada de audio para igualar volumen sin saturar.", "Canal", "#FFAA00"),
        ("7", "HI / MID / LOW", "Ecualizar y aislar frecuencias (cortar graves, medios o agudos).", "EQ", "#FF5533"),
        ("8", "Channel Fader", "Controlar el volumen individual de salida de cada plato.", "Canal", "#00FF66"),
        ("9", "Crossfader", "Realizar transiciones suaves o cortes rápidos entre Plato A y B.", "Mezcla", "#FF0055"),
        ("10", "Headphones Cue", "Preparar canciones por auriculares sin que el público las escuche.", "Monitor", "#00E5FF"),
        ("11", "Filter (HPF/LPF)", "Modificar el color y resonancia del sonido barriendo frecuencias.", "Efectos", "#FF0088"),
        ("12", "Beat FX", "Aplicar efectos al ritmo de la música (Echo, Reverb, Delay, Flanger).", "Efectos", "#00D2FF"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Guía Rápida de Aprendizaje - 12 Controles Clave del DJ")
        self.resize(750, 480)
        self.setStyleSheet("""
            QDialog {
                background-color: #121218;
                color: #FFFFFF;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        t = QLabel("TABLA DE REFERENCIA RÁPIDA - CONTROLES DE LA CABINA")
        t.setStyleSheet("font-size: 15px; font-weight: 900; color: #00E5FF; letter-spacing: 1px;")
        lay.addWidget(t)

        sub = QLabel("Aprende a usar la mesa de mezclas en orden de prioridad profesional:")
        sub.setStyleSheet("font-size: 11px; color: #888899;")
        lay.addWidget(sub)

        table = QTableWidget(len(self.CONTROLS), 4)
        table.setHorizontalHeaderLabels(["Prioridad", "Control", "Función y Qué debes aprender", "Sección"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("""
            QTableWidget {
                background-color: #161622;
                alternate-background-color: #1A1A28;
                border: 1px solid #282838;
                border-radius: 6px;
                color: #FFFFFF;
                gridline-color: #222230;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #20202E;
                color: #00E5FF;
                font-weight: 900;
                border: none;
                padding: 6px;
                font-size: 10px;
            }
        """)

        for row_idx, (prio, name, desc_text, cat, _col) in enumerate(self.CONTROLS):
            prio_item = QTableWidgetItem(f" #{prio} ")
            prio_item.setTextAlignment(Qt.AlignCenter)

            name_item = QTableWidgetItem(name)
            name_item.setFont(QFont("Segoe UI", 10, QFont.Bold))

            desc_item = QTableWidgetItem(desc_text)
            cat_item = QTableWidgetItem(cat)
            cat_item.setTextAlignment(Qt.AlignCenter)

            table.setItem(row_idx, 0, prio_item)
            table.setItem(row_idx, 1, name_item)
            table.setItem(row_idx, 2, desc_item)
            table.setItem(row_idx, 3, cat_item)

        lay.addWidget(table)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Entendido")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #1ED760;
                color: #000000;
                font-size: 12px;
                font-weight: 900;
                border-radius: 6px;
                padding: 6px 18px;
            }
            QPushButton:hover { background-color: #22EC6A; }
        """)
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        lay.addLayout(btn_box)


# =====================================================================================================
# 9. VISUALIZADOR SUPERIOR DE FORMAS DE ONDA DUALES Y BEAT MATCHING (ESTILO VIRTUALDJ)
# =====================================================================================================
class DjOverviewWaveform(QWidget):
    """Minimapa de recorrido completo de la pista (Overview Waveform) con cursor y salto por clic."""
    seekRequested = Signal(int)  # target_ms

    def __init__(self, color="#00D2FF", accent_color=None, height=14, parent=None):
        super().__init__(parent)
        chosen = accent_color if accent_color is not None else color
        self.color = QColor(chosen)
        self._pos_ms = 0
        self._dur_ms = 1
        self._cue_ms = 0
        self.setFixedHeight(int(height))
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setPosition(self, pos_ms: int):
        self._pos_ms = max(0, int(pos_ms))
        self.update()

    def setDuration(self, dur_ms: int):
        self._dur_ms = max(1, int(dur_ms))
        self.update()

    def setTrack(self, title: str, dur_ms: int):
        self._dur_ms = max(1, int(dur_ms))
        self.update()

    def setProgress(self, pos_ms: int, dur_ms: int, cue_ms: int = 0):
        self._pos_ms = max(0, int(pos_ms))
        self._dur_ms = max(1, int(dur_ms))
        self._cue_ms = max(0, int(cue_ms))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.width() > 0:
            ratio = max(0.0, min(1.0, event.position().x() / float(self.width())))
            target_ms = int(ratio * self._dur_ms)
            self.seekRequested.emit(target_ms)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Fondo del minimapa
        painter.fillRect(0, 0, w, h, QColor("#0D0D14"))
        painter.setPen(QPen(QColor("#20202E"), 1))
        painter.drawRect(0, 0, w - 1, h - 1)

        # Forma de onda sintética estilizada a lo largo de la canción
        painter.setPen(Qt.NoPen)
        bar_w = 3
        num_bars = max(10, w // (bar_w + 1))
        for i in range(num_bars):
            bx = i * (bar_w + 1)
            # Altura pseudo-aleatoria pero determinista según el tiempo de la canción
            phase = (i / float(num_bars)) * 18.0
            height_ratio = 0.3 + 0.45 * abs(math.sin(phase) * math.cos(phase * 0.4))
            bh = max(3, int(height_ratio * (h - 4)))
            by = (h - bh) // 2

            # Barra pasada vs barra futura
            bar_pos_ratio = bx / float(w)
            curr_pos_ratio = self._pos_ms / float(self._dur_ms)
            if bar_pos_ratio <= curr_pos_ratio:
                painter.setBrush(self.color)
            else:
                c = QColor(self.color)
                c.setAlpha(80)
                painter.setBrush(c)
            painter.drawRect(bx, by, bar_w, bh)

        # Punto CUE (marcador naranja)
        if self._cue_ms > 0 and self._dur_ms > 0:
            cue_x = int((self._cue_ms / float(self._dur_ms)) * w)
            painter.setPen(QPen(QColor("#FFAA00"), 2))
            painter.drawLine(cue_x, 0, cue_x, h)

        # Playhead (cursor blanco de reproducción)
        play_x = int((self._pos_ms / float(self._dur_ms)) * w)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.drawLine(play_x, 0, play_x, h)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPolygon([QPointF(play_x - 3, 0), QPointF(play_x + 3, 0), QPointF(play_x, 4)])


class DjPhaseMeter(QWidget):
    """Medidor de fase y compás entre Deck A y Deck B (Phase Match Indicator).
    Muestra si la pista B está adelantada o atrasada respecto a A y cuándo están perfectamente juntadas."""
    alignRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset_ms = 0.0
        self._beat_interval_ms = 500.0
        self._is_aligned = False
        self.setFixedHeight(22)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Haz clic para sincronizar y juntar la fase al golpe exacto")

    def setPhaseOffset(self, offset_ms: float, beat_interval_ms: float = 500.0):
        self._offset_ms = float(offset_ms)
        self._beat_interval_ms = max(50.0, float(beat_interval_ms))
        # Se considera alineado si está a menos de 20 ms de diferencia
        self._is_aligned = abs(self._offset_ms) <= 20.0
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.alignRequested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mid_x = w / 2.0

        # Fondo
        painter.fillRect(0, 0, w, h, QColor("#101018"))
        painter.setPen(QPen(QColor("#252535"), 1))
        painter.drawRect(0, 0, w - 1, h - 1)

        # Escala de marcas de fase (-1/2 beat a +1/2 beat)
        painter.setPen(QPen(QColor("#353545"), 1))
        for step in (-0.5, -0.25, 0.0, 0.25, 0.5):
            sx = mid_x + step * (w * 0.75)
            painter.drawLine(int(sx), 3, int(sx), h - 3)

        # Línea central de referencia (Blanca)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.drawLine(int(mid_x), 0, int(mid_x), h)

        # Puntero de fase de Deck B relativo a Deck A
        half_beat = self._beat_interval_ms * 0.5
        norm_offset = max(-1.0, min(1.0, self._offset_ms / half_beat))
        pointer_x = mid_x + norm_offset * (w * 0.375)

        if self._is_aligned:
            # Color verde neón de beats alineados
            painter.setBrush(QColor("#00FF66"))
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            painter.drawPolygon([
                QPointF(mid_x - 6, h - 2), QPointF(mid_x + 6, h - 2),
                QPointF(mid_x, 3)
            ])
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.setPen(QColor("#00FF66"))
            painter.drawText(QRectF(0, 2, w, h - 4), Qt.AlignCenter, "● BEATS ALINEADOS (0 ms)")
        else:
            # Puntero activo indicando desfase
            p_color = QColor("#FF3344" if norm_offset > 0 else "#00D2FF")
            painter.setBrush(p_color)
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            painter.drawPolygon([
                QPointF(pointer_x - 5, h - 2), QPointF(pointer_x + 5, h - 2),
                QPointF(pointer_x, 4)
            ])
            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            painter.setPen(QColor("#CCCCCC"))
            sign = "+" if self._offset_ms > 0 else ""
            txt = f"{sign}{int(self._offset_ms)} ms"
            painter.drawText(QRectF(w - 70, 2, 65, h - 4), Qt.AlignRight | Qt.AlignVCenter, txt)


class DjRunningWaveformView(QWidget):
    """Visualizador central de ondas en movimiento (Dual Running Waveforms) estilo VirtualDJ.
    Permite ver por dónde van ambas canciones a la vez con cuadrícula de compases (beatgrid 1, 2, 3, 4)
    y manipularlas con el ratón (arrastrar para juntar beats bajo la aguja blanca central)."""
    nudgeRequested = Signal(str, int)  # deck ("A"|"B"), delta_ms
    seekRequested = Signal(str, int)   # deck ("A"|"B"), target_ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(110)
        self.setCursor(Qt.OpenHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Estado dinámico de Pista A (Cyan) y Pista B (Rojo)
        self._pos_a = 0
        self._dur_a = 180000
        self._bpm_a = 128.0
        self._playing_a = False

        self._pos_b = 0
        self._dur_b = 180000
        self._bpm_b = 128.0
        self._playing_b = False

        # Zoom de compases mostrados (4, 8, 16 compases)
        self._zoom_bars = 4
        self._drag_active = False
        self._drag_deck = "B"
        self._last_mouse_x = 0

    def setPlaybackState(self, pos_a: int, dur_a: int, bpm_a: float, playing_a: bool,
                         pos_b: int, dur_b: int, bpm_b: float, playing_b: bool):
        self._pos_a = int(pos_a)
        self._dur_a = max(1, int(dur_a))
        self._bpm_a = max(30.0, float(bpm_a or 128.0))
        self._playing_a = bool(playing_a)

        self._pos_b = int(pos_b)
        self._dur_b = max(1, int(dur_b))
        self._bpm_b = max(30.0, float(bpm_b or 128.0))
        self._playing_b = bool(playing_b)
        self.update()

    def setZoomBars(self, bars: int):
        self._zoom_bars = max(2, min(16, int(bars)))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = True
            self.setCursor(Qt.ClosedHandCursor)
            self._last_mouse_x = event.position().x()
            # Si el clic es en la mitad superior, manipula Pista A; si es inferior, manipula Pista B
            self._drag_deck = "A" if event.position().y() < (self.height() / 2.0) else "B"
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active and self.width() > 0:
            dx = event.position().x() - self._last_mouse_x
            self._last_mouse_x = event.position().x()
            # Convertir píxeles de arrastre a milisegundos según el tempo y zoom
            bpm = self._bpm_a if self._drag_deck == "A" else self._bpm_b
            beat_ms = 60000.0 / bpm
            window_ms = self._zoom_bars * 4.0 * beat_ms
            ms_per_pixel = window_ms / float(self.width())
            delta_ms = -int(dx * ms_per_pixel)
            if abs(delta_ms) > 0:
                self.nudgeRequested.emit(self._drag_deck, delta_ms)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = False
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        # Zoom con la rueda del ratón
        delta = event.angleDelta().y()
        if delta > 0:
            self.setZoomBars(self._zoom_bars // 2)
        elif delta < 0:
            self.setZoomBars(self._zoom_bars * 2)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mid_y = h / 2.0
        center_x = w / 2.0

        # Fondo general oscuro de cabina DJ
        painter.fillRect(0, 0, w, h, QColor("#0A0A10"))
        painter.setPen(QPen(QColor("#1A1A24"), 1))
        painter.drawRect(0, 0, w - 1, h - 1)

        # 1. Dibujar Pista A (Superior - Cyan #00D2FF)
        self._draw_deck_lane(painter, deck_name="A", color=QColor("#00D2FF"),
                             pos_ms=self._pos_a, bpm=self._bpm_a,
                             top_y=0, lane_h=mid_y, center_x=center_x, width=w)

        # Línea divisoria horizontal entre Deck A y Deck B
        painter.setPen(QPen(QColor("#242436"), 1))
        painter.drawLine(0, int(mid_y), w, int(mid_y))

        # 2. Dibujar Pista B (Inferior - Rojo #FF3344)
        self._draw_deck_lane(painter, deck_name="B", color=QColor("#FF3344"),
                             pos_ms=self._pos_b, bpm=self._bpm_b,
                             top_y=mid_y, lane_h=mid_y, center_x=center_x, width=w)

        # 3. Línea central Playhead vertical (Aguja blanca luminosa)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.drawLine(int(center_x), 0, int(center_x), h)
        # Flechas de aguja central
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPolygon([QPointF(center_x - 4, 0), QPointF(center_x + 4, 0), QPointF(center_x, 5)])
        painter.drawPolygon([QPointF(center_x - 4, h), QPointF(center_x + 4, h), QPointF(center_x, h - 5)])

    def _draw_deck_lane(self, painter: QPainter, deck_name: str, color: QColor,
                        pos_ms: int, bpm: float, top_y: float, lane_h: float,
                        center_x: float, width: float):
        # Duración de la ventana temporal visible en ms según zoom
        beat_ms = 60000.0 / bpm
        window_ms = self._zoom_bars * 4.0 * beat_ms
        ms_per_pixel = window_ms / float(width)

        lane_mid_y = top_y + lane_h / 2.0
        max_wave_h = (lane_h - 10) * 0.5

        # Dibujar barras de forma de onda (Espectro rítmico desplazable)
        bar_step_px = 4
        num_steps = int(width // bar_step_px) + 2
        for i in range(-num_steps // 2, num_steps // 2 + 1):
            x = center_x + i * bar_step_px
            if x < 0 or x > width:
                continue
            time_at_x = pos_ms + int(i * bar_step_px * ms_per_pixel)
            if time_at_x < 0:
                continue

            # Amplitud pseudo-espectral sincronizada al compás
            phase = (time_at_x / beat_ms) * math.pi
            harmonic = math.sin(phase) * 0.6 + math.sin(phase * 2.0) * 0.3 + math.sin(phase * 4.0) * 0.1
            envelope_amp = max(0.12, abs(harmonic))
            # Resaltar picos de bombos y transitorios rítmicos
            is_beat_peak = (abs(time_at_x % beat_ms) < 40) or (abs((time_at_x + 40) % beat_ms) < 40)
            if is_beat_peak:
                envelope_amp = min(1.0, envelope_amp * 1.5)

            h_peak = int(envelope_amp * max_wave_h)
            bar_color = QColor(color)
            if is_beat_peak:
                bar_color = QColor("#FFFFFF") if deck_name == "A" else QColor("#FFAA00")
            else:
                bar_color.setAlpha(190)

            painter.setPen(QPen(bar_color, 2))
            painter.drawLine(int(x), int(lane_mid_y - h_peak), int(x), int(lane_mid_y + h_peak))

        # Dibujar marcadores de Rejilla de Compás (Beatgrid: 1, 2, 3, 4)
        # Buscar el beat más cercano al inicio visible
        start_time = pos_ms - int(center_x * ms_per_pixel)
        end_time = pos_ms + int((width - center_x) * ms_per_pixel)

        first_beat_idx = int(start_time // beat_ms)
        last_beat_idx = int(end_time // beat_ms) + 1

        for b_idx in range(first_beat_idx, last_beat_idx):
            beat_time = b_idx * beat_ms
            bx = center_x + (beat_time - pos_ms) / ms_per_pixel
            if bx < 0 or bx > width:
                continue

            beat_in_bar = (b_idx % 4) + 1
            is_downbeat = (beat_in_bar == 1)

            if is_downbeat:
                # Golpe 1 del compás: línea más brillante y alta
                painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
                painter.drawLine(int(bx), int(top_y + 2), int(bx), int(top_y + lane_h - 2))
                painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
                painter.setPen(color)
                painter.drawText(int(bx) + 3, int(top_y + 11), "1")
            else:
                # Golpes 2, 3, 4
                painter.setPen(QPen(QColor("#454555"), 1, Qt.DashLine))
                painter.drawLine(int(bx), int(top_y + 4), int(bx), int(top_y + lane_h - 4))


class DjMasterWaveformDisplay(QFrame):
    """Contenedor superior completo estilo VirtualDJ con:
    - Encabezados de Deck A (Cyan) y Deck B (Rojo) con tiempos, BPM, Key y Pitch.
    - Medidor de Fase rítmico y Botón central '🔗 JUNTAR BEATS / SYNC'.
    - Minimapas de recorrido de ambas canciones (Overview Waveforms).
    - Doble forma de onda desplazable en paralelo (DjRunningWaveformView) con rejilla beatgrid."""
    juntarBeatsRequested = Signal()
    nudgeRequested = Signal(str, int)  # deck, delta_ms
    seekRequested = Signal(str, int)   # deck, target_ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MasterWaveformDisplay")
        self.setStyleSheet("""
            QFrame#MasterWaveformDisplay {
                background-color: #0E0E14;
                border: 1px solid #20202E;
                border-radius: 8px;
            }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        # 1. FILA DE CABECERA Y CENTRO DE EMPAREJAMIENTO DE BEATS
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        # --- Deck A Header (Izquierda - Cyan) ---
        deck_a_box = QHBoxLayout()
        deck_a_box.setSpacing(6)
        self.badge_a = QLabel(" A ")
        self.badge_a.setStyleSheet("background-color: #00D2FF; color: #000000; font-weight: 900; font-size: 11px; border-radius: 3px; padding: 2px 5px;")
        deck_a_box.addWidget(self.badge_a)

        self.lbl_title_a = QLabel("Deck A: Sin pista")
        self.lbl_title_a.setStyleSheet("color: #FFFFFF; font-weight: bold; font-size: 11px;")
        deck_a_box.addWidget(self.lbl_title_a)

        self.lbl_time_a = QLabel("-00:00")
        self.lbl_time_a.setStyleSheet("color: #00D2FF; font-family: monospace; font-size: 11px; font-weight: 800;")
        deck_a_box.addWidget(self.lbl_time_a)

        self.lbl_bpm_a = QLabel("128.0 BPM")
        self.lbl_bpm_a.setStyleSheet("color: #00D2FF; font-size: 10px; font-weight: 800; background: #162432; border-radius: 3px; padding: 1px 4px;")
        deck_a_box.addWidget(self.lbl_bpm_a)
        header_row.addLayout(deck_a_box, 2)

        # --- Centro de Beatmatching & Juntar Pistas ---
        center_tools = QHBoxLayout()
        center_tools.setSpacing(4)

        btn_nudge_back = QPushButton("◀")
        btn_nudge_back.setCursor(Qt.PointingHandCursor)
        btn_nudge_back.setToolTip("Nudge: Desplazar Deck B atrás")
        btn_nudge_back.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A24; color: #FF3344; font-weight: bold; border: 1px solid #FF3344; border-radius: 3px; padding: 2px 6px; font-size: 10px; }")
        btn_nudge_back.clicked.connect(lambda: self.nudgeRequested.emit("B", -20))
        center_tools.addWidget(btn_nudge_back)

        self.btn_juntar = QPushButton("🔗 JUNTAR BEATS")
        self.btn_juntar.setCursor(Qt.PointingHandCursor)
        self.btn_juntar.setToolTip("Sincroniza y alinea automáticamente los bombos de ambas canciones al milisegundo exacto.")
        self.btn_juntar.setStyleSheet("""
            QPushButton {
                min-width: 0px;
                background-color: #1A3828;
                color: #00FF66;
                font-weight: 900;
                font-size: 10px;
                letter-spacing: 0.5px;
                border: 1.5px solid #00FF66;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background-color: #244C36; }
            QPushButton:pressed { background-color: #00FF66; color: #000; }
        """)
        self.btn_juntar.clicked.connect(self.juntarBeatsRequested.emit)
        center_tools.addWidget(self.btn_juntar)

        btn_nudge_fwd = QPushButton("▶")
        btn_nudge_fwd.setCursor(Qt.PointingHandCursor)
        btn_nudge_fwd.setToolTip("Nudge: Desplazar Deck B adelante")
        btn_nudge_fwd.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A24; color: #FF3344; font-weight: bold; border: 1px solid #FF3344; border-radius: 3px; padding: 2px 6px; font-size: 10px; }")
        btn_nudge_fwd.clicked.connect(lambda: self.nudgeRequested.emit("B", 20))
        center_tools.addWidget(btn_nudge_fwd)

        header_row.addLayout(center_tools, 1)

        # --- Deck B Header (Derecha - Rojo) ---
        deck_b_box = QHBoxLayout()
        deck_b_box.setSpacing(6)
        deck_b_box.addStretch()

        self.lbl_bpm_b = QLabel("128.0 BPM")
        self.lbl_bpm_b.setStyleSheet("color: #FF3344; font-size: 10px; font-weight: 800; background: #32161E; border-radius: 3px; padding: 1px 4px;")
        deck_b_box.addWidget(self.lbl_bpm_b)

        self.lbl_time_b = QLabel("-00:00")
        self.lbl_time_b.setStyleSheet("color: #FF3344; font-family: monospace; font-size: 11px; font-weight: 800;")
        deck_b_box.addWidget(self.lbl_time_b)

        self.lbl_title_b = QLabel("Deck B: Sin pista")
        self.lbl_title_b.setStyleSheet("color: #FFFFFF; font-weight: bold; font-size: 11px;")
        deck_b_box.addWidget(self.lbl_title_b)

        self.badge_b = QLabel(" B ")
        self.badge_b.setStyleSheet("background-color: #FF3344; color: #FFFFFF; font-weight: 900; font-size: 11px; border-radius: 3px; padding: 2px 5px;")
        deck_b_box.addWidget(self.badge_b)
        header_row.addLayout(deck_b_box, 2)

        lay.addLayout(header_row)

        # 2. MEDIDOR DE FASE (PHASE METER)
        self.phase_meter = DjPhaseMeter()
        self.phase_meter.alignRequested.connect(self.juntarBeatsRequested.emit)
        lay.addWidget(self.phase_meter)

        # 3. OVERVIEWS WAVEFORM (Minimapas completos)
        overviews_row = QHBoxLayout()
        overviews_row.setSpacing(4)
        self.overview_a = DjOverviewWaveform(color="#00D2FF")
        self.overview_b = DjOverviewWaveform(color="#FF3344")
        self.overview_a.seekRequested.connect(lambda ms: self.seekRequested.emit("A", ms))
        self.overview_b.seekRequested.connect(lambda ms: self.seekRequested.emit("B", ms))
        overviews_row.addWidget(self.overview_a, 1)
        overviews_row.addWidget(self.overview_b, 1)
        lay.addLayout(overviews_row)

        # 4. RUNNING DUAL WAVEFORMS EN PARALELO
        self.running_waves = DjRunningWaveformView()
        self.running_waves.nudgeRequested.connect(self.nudgeRequested.emit)
        self.running_waves.seekRequested.connect(self.seekRequested.emit)
        lay.addWidget(self.running_waves)

    def updateDecks(self, title_a: str, bpm_a: float, pos_a: int, dur_a: int, playing_a: bool,
                     title_b: str, bpm_b: float, pos_b: int, dur_b: int, playing_b: bool):
        # Textos y etiquetas
        self.lbl_title_a.setText(title_a or "Deck A: Sin pista")
        self.lbl_title_b.setText(title_b or "Deck B: Sin pista")
        self.lbl_bpm_a.setText(f"{bpm_a:.1f} BPM" if bpm_a > 0 else "--- BPM")
        self.lbl_bpm_b.setText(f"{bpm_b:.1f} BPM" if bpm_b > 0 else "--- BPM")

        rem_a = max(0, (dur_a - pos_a)) // 1000
        rem_b = max(0, (dur_b - pos_b)) // 1000
        self.lbl_time_a.setText(f"-{rem_a // 60:02d}:{rem_a % 60:02d}")
        self.lbl_time_b.setText(f"-{rem_b // 60:02d}:{rem_b % 60:02d}")

        # Overviews
        self.overview_a.setProgress(pos_a, dur_a)
        self.overview_b.setProgress(pos_b, dur_b)

        # Running dual waveforms
        self.running_waves.setPlaybackState(pos_a, dur_a, bpm_a, playing_a,
                                           pos_b, dur_b, bpm_b, playing_b)

        # Medidor de fase
        beat_ms = 60000.0 / max(30.0, bpm_a)
        phase_a = pos_a % beat_ms
        phase_b = pos_b % (60000.0 / max(30.0, bpm_b))
        offset = phase_b - phase_a
        if offset > (beat_ms * 0.5):
            offset -= beat_ms
        elif offset < (-beat_ms * 0.5):
            offset += beat_ms
        self.phase_meter.setPhaseOffset(offset, beat_ms)


# =====================================================================================================
# 10. EXPLORADOR / BIBLIOTECA INFERIOR INTEGRADO ESTILO VIRTUALDJ
# =====================================================================================================
class DjVirtualBrowser(QWidget):
    """Explorador de música y biblioteca integrado en la mesa DJ estilo VirtualDJ.
    Permite navegar carpetas, playlists y descargas, y cargar con un clic en Deck A o Deck B."""
    loadDeckRequested = Signal(str, dict)  # deck ("A"|"B"), item_dict

    def __init__(self, parent_window=None, parent=None):
        super().__init__(parent)
        self.parent_window = parent_window
        self._tracks = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        # Barra superior del navegador: Buscador rápido y filtros de compatibilidad
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Buscar en tu música por título, artista o BPM...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #12121A;
                color: #FFFFFF;
                font-size: 11px;
                border: 1px solid #222230;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus { border-color: #00E5FF; }
        """)
        self.search_input.textChanged.connect(self._filter_tracks)
        top_bar.addWidget(self.search_input, 1)

        self.btn_compat_bpm = QPushButton("±4 BPM")
        self.btn_compat_bpm.setCheckable(True)
        self.btn_compat_bpm.setCursor(Qt.PointingHandCursor)
        self.btn_compat_bpm.setStyleSheet("QPushButton { min-width: 0px; background-color: #1A1A24; color: #AAA; font-size: 10px; font-weight: bold; border: 1px solid #282836; border-radius: 3px; padding: 3px 6px; } QPushButton:checked { background-color: #00D2FF; color: #000; }")
        self.btn_compat_bpm.toggled.connect(self._filter_tracks)
        top_bar.addWidget(self.btn_compat_bpm)

        lay.addLayout(top_bar)

        # Contenedor central dividido: Lista de categorías / fuentes a la izquierda + Tabla de canciones
        split_lay = QHBoxLayout()
        split_lay.setSpacing(6)

        # Panel izquierdo de navegación (Fuentes estilo VirtualDJ)
        sources_box = QVBoxLayout()
        sources_box.setSpacing(2)
        sources = [
            ("library", "📁 Tu Música"),
            ("downloads", "📥 Descargas"),
            ("favorites", "⭐ Favoritos"),
            ("playlists", "📜 Playlists"),
            ("history", "🕒 Historial"),
            ("queue", "🔀 Cola DJ"),
        ]
        self._src_buttons = {}
        for s_id, s_lbl in sources:
            btn = QPushButton(s_lbl)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    min-width: 90px;
                    text-align: left;
                    background-color: #14141C;
                    color: #CCCCCC;
                    font-size: 10px;
                    font-weight: bold;
                    border: 1px solid #20202A;
                    border-radius: 3px;
                    padding: 4px 8px;
                }
                QPushButton:hover { background-color: #1E1E28; color: #FFFFFF; }
            """)
            btn.clicked.connect(lambda _=False, sid=s_id: self._on_source_selected(sid))
            sources_box.addWidget(btn)
            self._src_buttons[s_id] = btn
        sources_box.addStretch()
        split_lay.addLayout(sources_box, 1)

        # Tabla central de canciones estilo VirtualDJ
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Título", "Artista", "Álbum", "Duración", "BPM", "Deck A", "Deck B"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0E0E14;
                alternate-background-color: #12121A;
                border: 1px solid #1C1C26;
                border-radius: 4px;
                color: #FFFFFF;
                gridline-color: #181822;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #181824;
                color: #888899;
                font-size: 10px;
                font-weight: 800;
                border: none;
                padding: 4px 6px;
            }
            QTableWidget::item:selected {
                background-color: #242436;
            }
        """)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        split_lay.addWidget(self.table, 5)

        lay.addLayout(split_lay)

    def setTracks(self, track_list: list):
        self._tracks = list(track_list or [])
        self._filter_tracks()

    def _filter_tracks(self):
        query = self.search_input.text().strip().lower()
        filtered = []
        for t in self._tracks:
            title = str(t.get("title", "")).lower()
            uploader = str(t.get("uploader", "")).lower()
            if query and (query not in title and query not in uploader):
                continue
            filtered.append(t)

        self.table.setRowCount(len(filtered))
        for row_idx, item in enumerate(filtered):
            t_item = QTableWidgetItem(item.get("title", "Desconocido"))
            u_item = QTableWidgetItem(item.get("uploader", "---"))
            a_item = QTableWidgetItem(item.get("album", "---"))
            d_item = QTableWidgetItem(item.get("duration_str", "0:00"))
            d_item.setTextAlignment(Qt.AlignCenter)

            bpm_val = item.get("bpm") or 0.0
            bpm_str = f"{bpm_val:.1f}" if bpm_val > 0 else "---"
            b_item = QTableWidgetItem(bpm_str)
            b_item.setTextAlignment(Qt.AlignCenter)

            self.table.setItem(row_idx, 0, t_item)
            self.table.setItem(row_idx, 1, u_item)
            self.table.setItem(row_idx, 2, a_item)
            self.table.setItem(row_idx, 3, d_item)
            self.table.setItem(row_idx, 4, b_item)

            btn_load_a = QPushButton("◀ LOAD A")
            btn_load_a.setCursor(Qt.PointingHandCursor)
            btn_load_a.setStyleSheet("QPushButton { min-width: 0px; background-color: #122432; color: #00D2FF; font-size: 9px; font-weight: 900; border: 1px solid #00D2FF; border-radius: 3px; padding: 2px 4px; }")
            btn_load_a.clicked.connect(lambda _=False, it=item: self.loadDeckRequested.emit("A", it))
            self.table.setCellWidget(row_idx, 5, btn_load_a)

            btn_load_b = QPushButton("LOAD B ▶")
            btn_load_b.setCursor(Qt.PointingHandCursor)
            btn_load_b.setStyleSheet("QPushButton { min-width: 0px; background-color: #321218; color: #FF3344; font-size: 9px; font-weight: 900; border: 1px solid #FF3344; border-radius: 3px; padding: 2px 4px; }")
            btn_load_b.clicked.connect(lambda _=False, it=item: self.loadDeckRequested.emit("B", it))
            self.table.setCellWidget(row_idx, 6, btn_load_b)

    def _on_source_selected(self, source_id: str):
        # Cargar pistas según la fuente seleccionada
        if not self.parent_window:
            return
        items = []
        try:
            if source_id == "library" and hasattr(self.parent_window, "all_music_tracks"):
                items = self.parent_window.all_music_tracks()
            elif source_id == "favorites" and hasattr(self.parent_window, "get_favorite_tracks"):
                items = self.parent_window.get_favorite_tracks()
            elif source_id == "downloads" and hasattr(self.parent_window, "downloaded_tracks"):
                items = self.parent_window.downloaded_tracks()
            elif source_id == "queue" and hasattr(self.parent_window, "batch_queue"):
                items = list(self.parent_window.batch_queue)
        except Exception:
            pass
        if items:
            self.setTracks(items)

    def _on_row_double_clicked(self, index):
        row = index.row()
        if 0 <= row < len(self._tracks):
            item = self._tracks[row]
            # Por defecto carga en Deck A si está parado, o en Deck B
            self.loadDeckRequested.emit("A", item)
