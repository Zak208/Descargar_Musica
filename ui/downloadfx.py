"""Piezas visuales de las descargas: barra de progreso suavizada, pasos con puntitos, anillo de progreso en botones y
un icono de descarga que se convierte en anillo y luego en un ✓ que se dibuja. Todo pintado a mano; en reposo no gasta."""
import math

from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QWidget, QPushButton

from ui import motion
from ui.anim_clock import clock
from ui.styles import accent


class SmoothProgress(QWidget):
    """Barra de progreso: el valor se acerca al nuevo en 250 ms (en vez de saltar) y, si no se sabe cuánto falta
    (`setRange(0, 0)`), una franja de luz la recorre. Es un sustituto de QProgressBar (setValue, setRange, value)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min, self._max = 0, 100
        self._target = 0.0
        self._shown = 0.0
        self._indet = False
        self._phase = 0.0
        self._token = None
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self.setFixedHeight(6)

    # -- API parecida a QProgressBar
    def setTextVisible(self, _visible):
        pass

    def setRange(self, lo, hi):
        self._min, self._max = lo, hi
        self._set_indeterminate(lo == hi)

    def value(self) -> int:
        return int(self._target)

    def setValue(self, value):
        span = max(1, self._max - self._min)
        target = max(0.0, min(1.0, (value - self._min) / span))
        self._target = target * span + self._min
        self._set_indeterminate(self._max == self._min)
        if not motion.enabled() or not self.isVisible():
            self._shown = target
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._shown)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_value(self, v):
        self._shown = float(v)
        self.update()

    # -- franja indeterminada
    def _set_indeterminate(self, on: bool):
        self._indet = on
        if on and self._token is None and self.isVisible() and motion.enabled():
            self._token = clock().subscribe(self._tick, 12)
        elif not on and self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
        self.update()

    def showEvent(self, event):
        if self._indet and self._token is None and motion.enabled():
            self._token = clock().subscribe(self._tick, 12)
        super().showEvent(event)

    def hideEvent(self, event):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
        super().hideEvent(event)

    def _tick(self, dt):
        self._phase = (self._phase + dt / 1300.0) % 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.height() / 2
        rect = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(rect, r, r)
        p.setBrush(QColor(accent()))
        if self._indet:
            w = rect.width() * 0.3
            x = -w + (rect.width() + w) * self._phase
            clip = QPainterPath()
            clip.addRoundedRect(rect, r, r)
            p.setClipPath(clip)
            p.drawRoundedRect(QRectF(x, 0, w, rect.height()), r, r)
        elif self._shown > 0:
            p.drawRoundedRect(QRectF(0, 0, max(rect.height(), rect.width() * self._shown), rect.height()), r, r)


STEPS = ("Buscando", "Descargando", "Preparando", "Lista")


class StepDots(QWidget):
    """Pasos de una descarga en lenguaje sencillo (Buscando › Descargando › Preparando › Lista). El paso actual late
    despacio, los anteriores quedan rellenos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._step = 0
        self._failed = False
        self._pulse = 0.0
        self._token = None
        self.setFixedHeight(16)

    def set_step(self, step: int, failed: bool = False):
        step = max(0, min(len(STEPS) - 1, step))
        if step != self._step or failed != self._failed:
            self._step, self._failed = step, failed
            self._sync_clock()
            self.update()

    def _sync_clock(self):
        want = self._step < len(STEPS) - 1 and not self._failed and self.isVisible() and motion.enabled()
        if want and self._token is None:
            self._token = clock().subscribe(self._tick, 6)
        elif not want and self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None

    def showEvent(self, event):
        self._sync_clock()
        super().showEvent(event)

    def hideEvent(self, event):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
        super().hideEvent(event)

    def _tick(self, dt):
        self._pulse = (self._pulse + dt / 1200.0) % 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x = 2.0
        font = self.font()
        font.setPixelSize(11)
        p.setFont(font)
        fm = p.fontMetrics()
        acc = QColor(accent())
        for i, name in enumerate(STEPS):
            done = i < self._step or (i == self._step == len(STEPS) - 1 and not self._failed)
            active = i == self._step and not done
            color = QColor("#FF6B6B") if (active and self._failed) else acc
            if done:
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawEllipse(QPointF(x + 4, 8), 4, 4)
                p.setPen(QPen(QColor("#000000"), 1.4))
                p.drawLine(QPointF(x + 2.2, 8), QPointF(x + 3.6, 9.4))
                p.drawLine(QPointF(x + 3.6, 9.4), QPointF(x + 6, 6.4))
            elif active:
                c = QColor(color)
                c.setAlphaF(0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse * 2 * math.pi)) if motion.enabled() else 1.0)
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawEllipse(QPointF(x + 4, 8), 4, 4)
            else:
                p.setPen(QPen(QColor(255, 255, 255, 70), 1.2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x + 4, 8), 3.5, 3.5)
            p.setPen(QColor("#FFFFFF") if active else QColor(255, 255, 255, 120 if not done else 170))
            p.drawText(QPointF(x + 12, 12), name)
            x += 12 + fm.horizontalAdvance(name) + 12
            if i < len(STEPS) - 1:
                p.setPen(QColor(255, 255, 255, 60))
                p.drawText(QPointF(x - 9, 12), "›")


def step_for(entry: dict) -> int:
    """Paso de una descarga según su estado (para los puntitos)."""
    state = entry.get("state")
    if state == "done":
        return len(STEPS) - 1
    if state == "converting":
        return 2
    if state == "error":
        return 1 if entry.get("percent", 0) > 0 else 0
    return 0 if entry.get("percent", 0) <= 0 else 1


class RingButton(QPushButton):
    """Botón con icono que puede llevar un anillo de progreso alrededor del icono (descargas en curso)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._ring = None
        self._flash = 0.0
        self._flash_anim = QVariantAnimation(self)
        self._flash_anim.setDuration(700)
        self._flash_anim.setStartValue(1.0)
        self._flash_anim.setEndValue(0.0)
        self._flash_anim.valueChanged.connect(self._on_flash)

    def set_ring(self, progress):
        """Progreso 0..1 (o None para quitar el anillo)."""
        if progress is None:
            if self._ring is not None:
                self._ring = None
                self.update()
            return
        progress = max(0.0, min(1.0, progress))
        if self._ring is None or abs(progress - self._ring) >= 0.01:
            self._ring = progress
            self.update()

    def finished_flash(self):
        """El anillo se completa y parpadea una vez."""
        if motion.enabled():
            self._ring = 1.0
            self._flash_anim.stop()
            self._flash_anim.start()
        else:
            self._ring = None
        self.update()

    def _on_flash(self, v):
        self._flash = float(v)
        if self._flash <= 0.01:
            self._ring = None
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._ring is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        iw = self.iconSize().width()
        size = iw + 8
        total = iw + 4 + self.fontMetrics().horizontalAdvance(self.text())
        cx = (self.width() - total) / 2 + iw / 2          # el icono y el texto van centrados juntos
        rect = QRectF(cx - size / 2, (self.height() - size) / 2, size, size)
        c = QColor(accent())
        track = QColor(255, 255, 255, 40)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(track, 2))
        p.drawEllipse(rect)
        if self._flash > 0:
            c.setAlphaF(0.4 + 0.6 * self._flash)
        pen = QPen(c, 2.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 90 * 16, int(-360 * 16 * self._ring))


class DownloadStateButton(QPushButton):
    """Botón de descarga de una fila: flecha → anillo de progreso (o girando si no se sabe) → ✓ que se dibuja."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._mode = "idle"            # idle | busy | done
        self._progress = None
        self._spin = 0.0
        self._token = None
        self._check_t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_check)

    def set_busy(self, progress=None):
        """Descargando; `progress` 0..1 si se conoce."""
        self._progress = progress
        if self._mode != "busy":
            self._mode = "busy"
            self._sync_clock()
        self.update()

    def set_idle(self):
        self._mode = "idle"
        self._sync_clock()
        self.update()

    def set_done(self, animate: bool = True):
        was = self._mode
        self._mode = "done"
        self._sync_clock()
        if animate and was == "busy" and motion.enabled() and self.isVisible():
            self._anim.stop()
            self._check_t = 0.0
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self._check_t = 1.0
        self.update()

    def _on_check(self, v):
        self._check_t = float(v)
        self.update()

    def _sync_clock(self):
        want = self._mode == "busy" and self._progress is None and self.isVisible() and motion.enabled()
        if want and self._token is None:
            self._token = clock().subscribe(self._tick, 15)
        elif not want and self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None

    def showEvent(self, event):
        self._sync_clock()
        super().showEvent(event)

    def hideEvent(self, event):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
        super().hideEvent(event)

    def _tick(self, dt):
        self._spin = (self._spin + dt * 0.36) % 360.0
        self.update()

    def paintEvent(self, event):
        if self._mode == "idle":
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = min(self.width(), self.height()) * 0.28
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        c = QColor(accent())
        if self._mode == "busy":
            p.setPen(QPen(QColor(255, 255, 255, 45), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect)
            pen = QPen(c, 2.4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            if self._progress is None:
                p.drawArc(rect, int(-self._spin * 16), 100 * 16)
            else:
                p.drawArc(rect, 90 * 16, int(-360 * 16 * max(0.03, self._progress)))
        else:
            pen = QPen(c, 2.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(cx - r * 0.55, cy + r * 0.05)
            path.lineTo(cx - r * 0.1, cy + r * 0.5)
            path.lineTo(cx + r * 0.6, cy - r * 0.4)
            if self._check_t < 1.0:
                shown = QPainterPath()
                shown.moveTo(path.pointAtPercent(0))
                steps = 24
                for i in range(1, int(steps * self._check_t) + 1):
                    shown.lineTo(path.pointAtPercent(i / steps))
                path = shown
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
