"""Una línea de letra, pintada a mano: la frase que suena se rellena de izquierda a derecha y crece un poco, las demás
se apagan según lo lejos que están, y al pasar el ratón se aclaran (al pulsarla salta a ese momento).

No usa hojas de estilo por estado: cambiar de frase solo cambia unos números y repinta esa línea."""
from PySide6.QtCore import Qt, QPointF, QRectF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QFont, QTextLayout, QTextOption
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ui import motion

# opacidad base de cada estado
ALPHA = {"past": 0.34, "idle": 0.82, "active": 1.0}
SCALE_ACTIVE = 1.045


def _parse_pad(pad: str):
    """«6px 2px» → (vertical, horizontal) en píxeles."""
    nums = [int(p[:-2]) for p in pad.replace(",", " ").split() if p.endswith("px") and p[:-2].isdigit()]
    if not nums:
        return 0, 0
    return nums[0], (nums[1] if len(nums) > 1 else nums[0])


class LyricLine(QLabel):
    def __init__(self, ms: int, text: str, on_seek=None, size: int = 19, pad: str = "0px", parent=None):
        super().__init__(text, parent)
        self.ms = ms
        self.on_seek = on_seek
        self.size = size
        self.state = "idle"
        self._hover = False
        self._hover_t = 0.0
        self._alpha = ALPHA["idle"]          # opacidad que se está mostrando (se anima al cambiar de estado)
        self._emph = 0.0                      # 0 = normal, 1 = frase activa (crece)
        self._fill = 1.0                      # parte ya cantada de la frase activa (0 a 1)
        self._falloff = 1.0                   # atenuación por distancia a la frase activa
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(motion.DUR_FAST)
        self._hover_anim.valueChanged.connect(self._on_hover)
        v, h = _parse_pad(pad)
        self.setContentsMargins(h, v, h + 6, v)     # el margen derecho deja sitio al crecimiento de la frase activa
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self._apply_font()
        if on_seek is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Pulsa para ir a este momento de la canción")
            self.setAttribute(Qt.WA_Hover, True)

    # ------------------------------------------------------------------ estado
    def _apply_font(self):
        font = QFont(self.font())
        font.setPixelSize(self.size)
        font.setWeight(QFont.ExtraBold)
        self.setFont(font)
        self.updateGeometry()

    def set_size(self, size: int):
        if size != self.size:
            self.size = size
            self._apply_font()
            self.update()

    def set_state(self, state: str, distance: int = 0):
        """`distance`: lo lejos que está de la frase que suena (en frases); las que vienen se apagan más cuanto más lejos."""
        falloff = (1.0, 0.88, 0.66, 0.5)[min(distance, 3)] if (state == "idle" and distance > 0) else 1.0
        if state == self.state and abs(falloff - self._falloff) < 0.01:
            return
        previous = self.state
        self.state = state
        self._falloff = falloff
        target_alpha = ALPHA[state] * falloff
        target_emph = 1.0 if state == "active" else 0.0
        if state != "active":
            self._fill = 1.0
        elif previous != "active":
            self._fill = 0.0
        if not motion.enabled() or not self.isVisible():
            self._alpha, self._emph = target_alpha, target_emph
            self.update()
            return
        self._from = (self._alpha, self._emph)
        self._to = (target_alpha, target_emph)
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_anim(self, v):
        t = float(v)
        self._alpha = self._from[0] + (self._to[0] - self._from[0]) * t
        self._emph = self._from[1] + (self._to[1] - self._from[1]) * t
        self.update()

    def set_fill(self, fraction: float):
        """Parte de la frase ya cantada (barrido de izquierda a derecha); solo se repinta esta línea."""
        fraction = max(0.0, min(1.0, fraction))
        if abs(fraction - self._fill) >= 0.012:
            self._fill = fraction
            self.update()

    # ------------------------------------------------------------------ ratón
    def _on_hover(self, v):
        self._hover_t = float(v)
        self.update()

    def _go_hover(self, on: bool):
        target = 1.0 if on else 0.0
        if not motion.enabled():
            self._hover_t = target
            self.update()
            return
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_t)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, event):
        self._hover = True
        if self.on_seek is not None:
            self._go_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._go_hover(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.on_seek is not None:
            self.on_seek(self.ms)
            event.accept()
            return
        super().mousePressEvent(event)

    # ------------------------------------------------------------------ dibujo
    def paintEvent(self, _event):
        text = self.text()
        if not text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        area = self.contentsRect()
        layout = QTextLayout(text, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WordWrap)
        option.setAlignment(Qt.AlignLeft)
        layout.setTextOption(option)
        width = max(10, int(area.width() * 0.97))
        layout.beginLayout()
        y = 0.0
        lines = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            line.setPosition(QPointF(0, y))
            y += line.height()
            lines.append(line)
        layout.endLayout()
        total_h = y
        p.translate(area.left(), area.top() + max(0.0, (area.height() - total_h) / 2))
        scale = 1.0 + (SCALE_ACTIVE - 1.0) * self._emph
        if scale != 1.0:
            p.translate(0, total_h / 2)
            p.scale(scale, scale)
            p.translate(0, -total_h / 2)
        alpha = self._alpha + (1.0 - self._alpha) * 0.55 * self._hover_t
        base = QColor(255, 255, 255)
        if self.state == "active" and self._fill < 0.999 and motion.enabled():
            dim = QColor(base)
            dim.setAlphaF(0.55)
            p.setPen(dim)
            layout.draw(p, QPointF(0, 0))
            bright = QColor(base)
            bright.setAlphaF(1.0)
            p.setPen(bright)
            chars = max(1, len(text))
            done = self._fill * chars
            for line in lines:
                start, length = line.textStart(), max(1, line.textLength())
                part = max(0.0, min(1.0, (done - start) / length))
                if part <= 0:
                    continue
                p.save()
                p.setClipRect(QRectF(0, line.y(), line.naturalTextWidth() * part + 2, line.height() + 2))
                layout.draw(p, QPointF(0, 0))
                p.restore()
        else:
            base.setAlphaF(max(0.0, min(1.0, alpha)))
            p.setPen(base)
            layout.draw(p, QPointF(0, 0))


class GapDots(QWidget):
    """Tres puntos que se rellenan de uno en uno durante una pausa instrumental (intro, solo): se sabe que la letra
    no se ha parado, y cuánto falta."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFixedSize(76, 26)
        self._progress = 0.0
        self.hide()

    def set_progress(self, fraction: float):
        fraction = max(0.0, min(1.0, fraction))
        if abs(fraction - self._progress) >= 0.01:
            self._progress = fraction
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawRoundedRect(QRectF(self.rect()), 13, 13)
        for i in range(3):
            k = max(0.0, min(1.0, self._progress * 3 - i))
            c = QColor(255, 255, 255)
            c.setAlphaF(0.28 + 0.72 * k)
            p.setBrush(c)
            r = 5.0 + 2.0 * k
            p.drawEllipse(QPointF(13 + i * 25, 13), r, r)
