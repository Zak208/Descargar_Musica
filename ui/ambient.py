"""Fondos con ambiente: degradado con el color de la portada, la portada desenfocada (reduciéndola a unos píxeles y
ampliándola con suavizado: un desenfoque casi gratis, sin efectos de Qt que son caros) y, solo en el nivel de
animación «Completas», unas manchas de luz que derivan muy despacio a pocos fotogramas por segundo.

Los cambios de canción se mezclan con un fundido de 400 ms."""
import math

from PySide6.QtCore import Qt, QPointF, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QLinearGradient, QPixmap, QRadialGradient, QPainter

from ui import motion
from ui.anim_clock import clock


def blurred(pix: QPixmap, small: int = 14) -> QPixmap:
    """Versión muy desenfocada de una imagen (se reduce a `small` píxeles; al pintarla se amplía con suavizado)."""
    if pix is None or pix.isNull():
        return QPixmap()
    tiny = pix.scaled(small, small, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return tiny


def with_lightness(color: QColor, lightness: float) -> QColor:
    out = QColor(color)
    out.setHslF(max(out.hslHueF(), 0.0), out.hslSaturationF(), lightness)
    return out


class AmbientBackdrop:
    """Mezcla para un QWidget: pinta el fondo ambiental en su `paintEvent`.

        self.init_backdrop(QColor(...))                  # en __init__
        paintEvent → self.paint_backdrop(QPainter(self), self.rect())
        showEvent → self.start_backdrop()      hideEvent → self.stop_backdrop()
        self.set_backdrop(color, cover_pixmap)           # al cambiar de canción
    """

    def init_backdrop(self, color: QColor):
        self._bd_color = QColor(color)
        self._bd_old_color = QColor(color)
        self._bd_cover = None
        self._bd_old_cover = None
        self._bd_t = 1.0
        self._bd_phase = 0.0
        self._bd_token = None
        self._bd_anim = QVariantAnimation(self)
        self._bd_anim.setDuration(400)
        self._bd_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bd_anim.valueChanged.connect(self._bd_on_value)

    def _bd_on_value(self, v):
        self._bd_t = float(v)
        self.update()

    def set_backdrop(self, color: QColor = None, cover: QPixmap = None):
        new_color = QColor(color) if color is not None else self._bd_color
        new_cover = blurred(cover) if cover is not None and not cover.isNull() else self._bd_cover
        if new_color == self._bd_color and new_cover is self._bd_cover:
            return
        self._bd_old_color, self._bd_old_cover = self._bd_color, self._bd_cover
        self._bd_color, self._bd_cover = new_color, new_cover
        if motion.enabled() and self.isVisible():
            self._bd_t = 0.0
            self._bd_anim.stop()
            self._bd_anim.setStartValue(0.0)
            self._bd_anim.setEndValue(1.0)
            self._bd_anim.start()
        else:
            self._bd_t = 1.0
            self.update()

    # ------------------------------------------------------------ aurora
    def start_backdrop(self):
        if self._bd_token is None and motion.full():
            self._bd_token = clock().subscribe(self._bd_tick, 10)

    def stop_backdrop(self):
        if self._bd_token is not None:
            clock().unsubscribe(self._bd_token)
            self._bd_token = None

    def _bd_tick(self, dt):
        self._bd_phase += dt / 9000.0
        self.update()

    # ------------------------------------------------------------- dibujo
    def paint_backdrop(self, p: QPainter, rect):
        t = self._bd_t
        r = QRectF(rect)
        for color, cover, alpha in ((self._bd_old_color, self._bd_old_cover, 1.0 - t), (self._bd_color, self._bd_cover, t)):
            if alpha <= 0.002:
                continue
            p.setOpacity(alpha)
            grad = QLinearGradient(0, r.top(), 0, r.bottom())
            grad.setColorAt(0.0, color)
            grad.setColorAt(1.0, with_lightness(color, 0.16))
            p.fillRect(r, grad)
            if cover is not None and not cover.isNull():
                p.setOpacity(alpha * 0.42)
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawPixmap(r, cover, QRectF(cover.rect()))
        p.setOpacity(1.0)
        if self._bd_token is not None:
            self._paint_aurora(p, r)

    def _paint_aurora(self, p: QPainter, r: QRectF):
        base = self._bd_color
        radius = max(r.width(), r.height()) * 0.6
        p.setPen(Qt.NoPen)
        for i in range(3):
            ph = self._bd_phase * (1.0 + 0.3 * i) + i * 2.1
            cx = r.left() + r.width() * (0.5 + 0.38 * math.sin(ph))
            cy = r.top() + r.height() * (0.5 + 0.32 * math.cos(ph * 0.8 + i))
            c = QColor(base)
            hue = (max(c.hslHueF(), 0.0) + 0.07 * (i - 1)) % 1.0
            c.setHslF(hue, min(1.0, c.hslSaturationF() + 0.15), 0.52)
            c.setAlphaF(0.30)
            grad = QRadialGradient(QPointF(cx, cy), radius)
            grad.setColorAt(0.0, c)
            c2 = QColor(c)
            c2.setAlpha(0)
            grad.setColorAt(1.0, c2)
            p.setBrush(grad)
            p.drawRect(r)


class IdleHider:
    """Tras unos segundos sin mover el ratón ni pulsar nada, los controles se funden y el cursor se oculta; al mover el
    ratón vuelven. Mientras no pasa nada no hay ningún temporizador en marcha salvo el de un solo disparo."""

    def __init__(self, window, controls, delay: int = 3000):
        from PySide6.QtCore import QObject, QTimer, QEvent
        from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect
        self._QEvent = QEvent
        self._QApplication = QApplication
        self._Effect = QGraphicsOpacityEffect
        self.window = window
        self.controls = controls
        self.hidden = False
        self.active = False

        class _Filter(QObject):
            def __init__(self, owner):
                super().__init__()
                self.owner = owner

            def eventFilter(self, obj, event):
                if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel):
                    self.owner.wake()
                return False

        self._filter = _Filter(self)
        self._timer = QTimer(window)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay)
        self._timer.timeout.connect(self._sleep)
        self._anim = QVariantAnimation(window)
        self._anim.setDuration(300)
        self._anim.valueChanged.connect(self._on_value)
        self._k = 1.0

    def start(self):
        if not self.active:
            self.active = True
            self._QApplication.instance().installEventFilter(self._filter)
            self._timer.start()

    def stop(self):
        if self.active:
            self.active = False
            self._QApplication.instance().removeEventFilter(self._filter)
            self._timer.stop()
            self._set(1.0, immediate=True)
            self.window.unsetCursor()
            self.hidden = False

    def wake(self):
        if not self.active:
            return
        if self.hidden:
            self.hidden = False
            self.window.unsetCursor()
            self._set(1.0)
        self._timer.start()

    def _sleep(self):
        if not self.active or any(c.underMouse() for c in self.controls):
            self._timer.start()
            return
        self.hidden = True
        self.window.setCursor(Qt.BlankCursor)
        self._set(0.0)

    def _set(self, target: float, immediate: bool = False):
        if immediate or not motion.enabled():
            self._k = target
            self._apply()
            return
        self._anim.stop()
        self._anim.setStartValue(self._k)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_value(self, v):
        self._k = float(v)
        self._apply()

    def _apply(self):
        for w in self.controls:
            effect = w.graphicsEffect()
            if self._k >= 0.999:
                if effect is not None:
                    w.setGraphicsEffect(None)
                continue
            if not isinstance(effect, self._Effect):
                effect = self._Effect(w)
                w.setGraphicsEffect(effect)
            effect.setOpacity(self._k)
