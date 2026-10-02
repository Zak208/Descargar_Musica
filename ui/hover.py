"""Resalte de fondo con transición (para filas y tarjetas) e indicador de «está sonando» de tres barras."""
import math

from PySide6.QtCore import Qt, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget

from ui import motion
from ui.anim_clock import clock
from ui.styles import accent, live_accent


class HoverFader:
    """Mezcla para QFrame: en vez de cambiar de golpe el fondo al pasar el ratón (hoja de estilos), se pinta un velo
    blanco cuya opacidad sube y baja en 120 ms. Solo se repinta la fila bajo el ratón. Uso:

        class Fila(QFrame, HoverFader): ...
        self.init_hover(alpha=0.10, radius=8)        # en __init__
        def enterEvent(self, e): self.hover_to(True); super().enterEvent(e)
        def leaveEvent(self, e): self.hover_to(False); super().leaveEvent(e)
        def paintEvent(self, e): super().paintEvent(e); self.paint_hover()
    """

    def init_hover(self, alpha: float = 0.10, radius: int = 8):
        self._hv_alpha = alpha
        self._hv_radius = radius
        self._hv_t = 0.0
        self._hv_anim = QVariantAnimation(self)
        self._hv_anim.setDuration(motion.DUR_FAST)
        self._hv_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hv_anim.valueChanged.connect(self._hv_on_value)

    def _hv_on_value(self, v):
        self._hv_t = float(v)
        self.update()

    def hover_to(self, on: bool):
        target = 1.0 if on else 0.0
        if not motion.enabled() or not self.isVisible():
            self._hv_anim.stop()
            self._hv_t = target
            self.update()
            return
        self._hv_anim.stop()
        self._hv_anim.setStartValue(self._hv_t)
        self._hv_anim.setEndValue(target)
        self._hv_anim.start()

    def paint_hover(self):
        if self._hv_t <= 0.003:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * self._hv_alpha * self._hv_t)))
        p.drawRoundedRect(QRectF(self.rect()), self._hv_radius, self._hv_radius)


class NowPlayingBars(QWidget):
    """Tres barritas que suben y bajan junto a la canción que suena (se quedan quietas en pausa). Solo hay una canción
    sonando a la vez, así que es un único widget animado, a 8 repintados por segundo, y solo mientras suena."""

    def __init__(self, window, parent=None, size: int = 16):
        super().__init__(parent)
        self._window = window
        self._phase = 0.0
        self._token = None
        self._playing = False
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        try:
            window.playing_changed.connect(self._on_playing)
            self._playing = bool(window.is_playing_now())
        except Exception:
            pass

    def _on_playing(self, playing: bool):
        self._playing = bool(playing)
        self._sync()
        self.update()

    def _sync(self):
        want = self._playing and self.isVisible() and motion.enabled()
        if want and self._token is None:
            self._token = clock().subscribe(self._tick, 8)
        elif not want and self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None

    def showEvent(self, event):
        self._sync()
        super().showEvent(event)

    def hideEvent(self, event):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
        super().hideEvent(event)

    def _tick(self, dt):
        self._phase += dt / 260.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(live_accent()))
        h = self.height()
        w = max(2.0, self.width() / 5.0)
        gap = (self.width() - 3 * w) / 2
        for i in range(3):
            level = 0.55 if not (self._playing and motion.enabled()) else 0.3 + 0.7 * abs(math.sin(self._phase + i * 1.3))
            bar_h = max(3.0, (h - 2) * level)
            p.drawRoundedRect(QRectF(i * (w + gap), h - bar_h - 1, w, bar_h), 1.2, 1.2)


class GlowHover:
    """Mezcla para tarjetas: una luz suave sigue al cursor dentro de la tarjeta (solo la que está bajo el ratón).
    Los repintados por movimiento se limitan a unos 30 por segundo.

        self.init_glow(radius=10)                      # en __init__ (activa el seguimiento del ratón)
        enterEvent → self.glow_to(True)   leaveEvent → self.glow_to(False)
        mouseMoveEvent → self.glow_move(ev)   paintEvent → super().paintEvent(e); self.paint_glow()
    """

    def init_glow(self, radius: int = 10):
        import time
        self._gl_radius = radius
        self._gl_t = 0.0
        self._gl_pos = None
        self._gl_last = 0.0
        self._gl_time = time.perf_counter
        self._gl_anim = QVariantAnimation(self)
        self._gl_anim.setDuration(motion.DUR_BASE)
        self._gl_anim.valueChanged.connect(self._gl_on_value)
        self.setMouseTracking(True)

    def _gl_on_value(self, v):
        self._gl_t = float(v)
        self.update()

    def glow_to(self, on: bool):
        if not motion.full():
            self._gl_t = 0.0
            return
        self._gl_anim.stop()
        self._gl_anim.setStartValue(self._gl_t)
        self._gl_anim.setEndValue(1.0 if on else 0.0)
        self._gl_anim.start()

    def glow_move(self, event):
        if not motion.full():
            return
        now = self._gl_time()
        if now - self._gl_last < 0.033:
            return
        self._gl_last = now
        self._gl_pos = event.position()
        self.update()

    def paint_glow(self):
        if self._gl_t <= 0.01 or self._gl_pos is None:
            return
        from PySide6.QtGui import QRadialGradient, QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self._gl_radius, self._gl_radius)
        p.setClipPath(clip)
        grad = QRadialGradient(self._gl_pos, 140)
        grad.setColorAt(0.0, QColor(255, 255, 255, int(26 * self._gl_t)))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRect(self.rect())


class TileHover(GlowHover):
    """Mezcla para tarjetas de cuadrícula (se pone ANTES de QFrame): luz que sigue al cursor y, si hay una portada
    (`self.tile_cover`, un CoverLabel), que crece un poco al pasar el ratón."""
    tile_cover = None

    def enterEvent(self, event):
        if self.tile_cover is not None:
            self.tile_cover.zoom_hover(True)
        self.glow_to(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.tile_cover is not None:
            self.tile_cover.zoom_hover(False)
        self.glow_to(False)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        self.glow_move(event)
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        self.paint_glow()
