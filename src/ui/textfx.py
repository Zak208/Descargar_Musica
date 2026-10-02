"""Animaciones de texto baratas: cambio de texto con cruce, cifras que cuentan, puntos que avanzan, dígitos que ruedan,
cifras de ancho fijo, subrayado que crece y títulos que suben desde una máscara. Todas se pintan a mano y solo se mueven
mientras ocurre el cambio."""
from PySide6.QtCore import Qt, QRectF, QVariantAnimation, QEasingCurve, QTimer, QEvent, QSize, QObject
from PySide6.QtGui import QPainter, QColor, QFontMetrics, QPalette
from PySide6.QtWidgets import QLabel, QWidget

from ui import motion
from ui.anim_clock import clock
from ui.widgets import ElidedLabel


def _text_color(label: QLabel) -> QColor:
    return label.palette().color(QPalette.WindowText)


class SwapLabel(ElidedLabel):
    """Etiqueta de una línea que, al cambiar el texto, hace subir el anterior mientras se desvanece y entra el nuevo
    desde abajo (como el título de la canción que suena). Si el texto no cabe se recorta con «…» y, con la marquesina
    activada, se desplaza al pasar el ratón."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._old = ""
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(motion.DUR_BASE + 40)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._done)

    def setText(self, text: str):
        previous = self.fullText()
        super().setText(text)
        if text == previous or not previous or not motion.enabled() or not motion.visible_ok(self):
            self._t = 1.0
            return
        self._old = previous
        self._t = 0.0
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_value(self, v):
        self._t = float(v)
        self.update()

    def _done(self):
        self._t = 1.0
        self._old = ""
        self.update()

    def paintEvent(self, event):
        if self._t >= 1.0:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setFont(self.font())
        color = _text_color(self)
        rect = QRectF(self.rect())
        fm = self.fontMetrics()
        shift = rect.height() * 0.45
        p.setClipRect(rect)
        old_c = QColor(color)
        old_c.setAlphaF(max(0.0, 1.0 - self._t * 1.6))
        p.setPen(old_c)
        p.drawText(rect.translated(0, -shift * self._t), int(self.alignment()) | Qt.AlignVCenter,
                   fm.elidedText(self._old, Qt.ElideRight, int(rect.width())))
        new_c = QColor(color)
        new_c.setAlphaF(min(1.0, self._t * 1.4))
        p.setPen(new_c)
        p.drawText(rect.translated(0, shift * (1.0 - self._t)), int(self.alignment()) | Qt.AlignVCenter,
                   fm.elidedText(self.fullText(), Qt.ElideRight, int(rect.width())))


class CountLabel(QLabel):
    """Cifra que cuenta desde 0 hasta su valor (solo la primera vez que se muestra cada dato)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._shown = set()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fmt = str
        self._anim.valueChanged.connect(lambda v: QLabel.setText(self, self._fmt(int(v))))

    def count_to(self, value: int, fmt=str, key=None):
        """`key` identifica el dato: la animación solo ocurre la primera vez que se enseña."""
        self._anim.stop()
        self._fmt = fmt
        key = key if key is not None else "_"
        if key in self._shown or not motion.enabled() or not motion.visible_ok(self) or value <= 0:
            QLabel.setText(self, fmt(int(value)))
            self._shown.add(key)
            return
        self._shown.add(key)
        self._anim.setStartValue(0)
        self._anim.setEndValue(int(value))
        self._anim.start()


class DotsLabel(QLabel):
    """Texto de espera con puntos suspensivos que avanzan («Buscando.», «Buscando..», «Buscando...»): da sensación de
    vida sin gastar un círculo giratorio. `animate("Buscando")` lo activa; `setText(...)` lo detiene con un texto fijo.
    Solo se mueve mientras se ve."""

    def __init__(self, base: str = "", parent=None):
        super().__init__(parent)
        self._base = ""
        self._n = 3
        self._running = False
        self._token = None
        if base:
            QLabel.setText(self, base)

    def animate(self, base: str):
        self._base = base.rstrip(". …")
        self._running = True
        self._n = 3
        self._render()
        self._sync()

    def setText(self, text: str):
        self._running = False
        QLabel.setText(self, text)
        self._sync()

    def _render(self):
        QLabel.setText(self, self._base + "." * self._n)

    def _sync(self):
        want = self._running and self.isVisible() and motion.enabled()
        if want and self._token is None:
            self._token = clock().subscribe(self._tick, 3)
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

    def _tick(self, _dt):
        if self._running:
            self._n = self._n % 3 + 1
            self._render()


class RollLabel(QLabel):
    """Número que cambia con los dígitos que ruedan hacia arriba (porcentajes, contadores)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._old = ""
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._done)

    def setText(self, text: str):
        previous = self.text()
        super().setText(text)
        if text == previous or not previous or not motion.enabled() or not motion.visible_ok(self):
            return
        self._old = previous
        self._t = 0.0
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_value(self, v):
        self._t = float(v)
        self.update()

    def _done(self):
        self._t = 1.0
        self.update()

    def paintEvent(self, event):
        if self._t >= 1.0:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setFont(self.font())
        color = _text_color(self)
        fm = self.fontMetrics()
        new = self.text()
        old = self._old.rjust(len(new)) if len(self._old) < len(new) else self._old
        width = fm.horizontalAdvance(new)
        x0 = (self.width() - width) / 2 if self.alignment() & Qt.AlignHCenter else (
            self.width() - width if self.alignment() & Qt.AlignRight else 0)
        h = self.height()
        p.setClipRect(self.rect())
        x = x0
        for i, ch in enumerate(new):
            oc = old[i] if i < len(old) else ch
            adv = fm.horizontalAdvance(ch)
            cell = QRectF(x, 0, adv + 1, h)
            if oc == ch:
                p.setPen(color)
                p.drawText(cell, Qt.AlignLeft | Qt.AlignVCenter, ch)
            else:
                c1 = QColor(color)
                c1.setAlphaF(1.0 - self._t)
                p.setPen(c1)
                p.drawText(cell.translated(0, -h * 0.5 * self._t), Qt.AlignLeft | Qt.AlignVCenter, oc)
                c2 = QColor(color)
                c2.setAlphaF(self._t)
                p.setPen(c2)
                p.drawText(cell.translated(0, h * 0.5 * (1 - self._t)), Qt.AlignLeft | Qt.AlignVCenter, ch)
            x += adv


class FixedDigitsLabel(QLabel):
    """Cifras de ancho fijo: «01:09 → 01:10» no hace temblar el texto (la fuente tiene dígitos de ancho distinto)."""

    def _cell(self) -> float:
        fm = self.fontMetrics()
        return max(fm.horizontalAdvance(str(d)) for d in range(10))

    def _advance(self, ch: str, fm: QFontMetrics, cell: float) -> float:
        return cell if ch.isdigit() else fm.horizontalAdvance(ch)

    def sizeHint(self):
        fm = self.fontMetrics()
        cell = self._cell()
        return QSize(int(sum(self._advance(c, fm, cell) for c in self.text())) + 2, fm.height() + 2)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(_text_color(self))
        fm = self.fontMetrics()
        cell = self._cell()
        text = self.text()
        total = sum(self._advance(c, fm, cell) for c in text)
        if self.alignment() & Qt.AlignRight:
            x = self.width() - total
        elif self.alignment() & Qt.AlignHCenter:
            x = (self.width() - total) / 2
        else:
            x = 0
        for ch in text:
            adv = self._advance(ch, fm, cell)
            if ch.isdigit():
                dx = (cell - fm.horizontalAdvance(ch)) / 2
                p.drawText(QRectF(x + dx, 0, fm.horizontalAdvance(ch) + 2, self.height()),
                           Qt.AlignLeft | Qt.AlignVCenter, ch)
            else:
                p.drawText(QRectF(x, 0, adv + 2, self.height()), Qt.AlignLeft | Qt.AlignVCenter, ch)
            x += adv


# ---------------------------------------------------------- subrayado que crece
class _Underline(QWidget):
    def __init__(self, target: QWidget):
        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.target = target
        self.k = 0.0
        self.color = QColor("#FFFFFF")
        self.setFixedHeight(2)
        self.hide()

    def paintEvent(self, _event):
        if self.k <= 0:
            return
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawRect(QRectF(0, 0, self.width() * self.k, 2))


def grow_underline(widget: QWidget, color: str = None):
    """El texto del widget se subraya con una línea que crece desde la izquierda al pasar el ratón."""
    class Filter(QObject):
        def __init__(self, w):
            super().__init__(w)
            self.w = w
            self.line = _Underline(w)
            self.anim = QVariantAnimation(self)
            self.anim.setDuration(motion.DUR_FAST + 20)
            self.anim.setEasingCurve(QEasingCurve.OutCubic)
            self.anim.valueChanged.connect(self._on_value)

        def _place(self):
            fm = self.w.fontMetrics()
            text_w = fm.horizontalAdvance(self.w.text()) if hasattr(self.w, "text") else self.w.width()
            align = getattr(self.w, "alignment", lambda: Qt.AlignLeft)()
            x = 0
            if isinstance(self.w, QLabel) and (align & Qt.AlignHCenter):
                x = max(0, (self.w.width() - text_w) // 2)
            self.line.setGeometry(x, self.w.height() - 3, min(text_w, self.w.width()), 2)

        def _on_value(self, v):
            self.line.k = float(v)
            self.line.update()

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Enter and motion.enabled():
                if color:
                    self.line.color = QColor(color)
                else:
                    self.line.color = self.w.palette().color(QPalette.WindowText) if not hasattr(self.w, "_ul_color") \
                        else QColor(self.w._ul_color)
                self._place()
                self.line.show()
                self.line.raise_()
                self._go(1.0)
            elif event.type() == QEvent.Leave:
                self._go(0.0)
            return False

        def _go(self, target):
            self.anim.stop()
            self.anim.setStartValue(self.line.k)
            self.anim.setEndValue(target)
            self.anim.start()

    f = Filter(widget)
    widget.installEventFilter(f)
    widget._grow_underline = f
    return widget


# ---------------------------------------------------- título que sube desde una máscara
def reveal_up(label: QWidget, delay: int = 0, duration: int = 280):
    """El texto sube desde una línea invisible mientras aparece. Se hace con una foto del widget en una capa recortada
    por sus propios bordes; el widget real reaparece al final (conserva su sitio en el diseño)."""
    if not motion.enabled():
        return

    def start():
        try:
            if not motion.visible_ok(label):
                return
            from ui import snapshot
            pix = snapshot.grab(label)
            if pix.isNull():
                return
            parent = label.parentWidget()
            if parent is None:
                return
            policy = label.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            label.setSizePolicy(policy)
            layer = snapshot.Layer(parent, pix, label.geometry())
            layer.opacity = 0.0
            layer.dy = label.height() * 0.8
            label.hide()

            def step(t):
                layer.opacity = min(1.0, t * 1.5)
                layer.dy = label.height() * 0.8 * (1.0 - t)

            def done():
                try:
                    label.show()
                except RuntimeError:
                    pass

            layer.animate(duration, step, QEasingCurve.OutCubic, done)
        except RuntimeError:
            pass

    if delay > 0:
        QTimer.singleShot(delay, start)
    else:
        start()



class WordsInLabel(QLabel):
    """Texto grande (el saludo de Inicio) cuyas palabras entran una a una, subiendo un poco. Solo ocurre la primera vez
    que se muestra en cada arranque; después es un texto normal."""
    played = False

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._t = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(750)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._done)

    def play(self):
        if WordsInLabel.played or not motion.enabled() or not motion.visible_ok(self):
            return
        WordsInLabel.played = True
        self._t = 0.0
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_value(self, v):
        self._t = float(v)
        self.update()

    def _done(self):
        self._t = 1.0
        self.update()

    def paintEvent(self, event):
        if self._t >= 1.0:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setFont(self.font())
        color = _text_color(self)
        fm = self.fontMetrics()
        words = self.text().split(" ")
        n = max(1, len(words))
        x = 0.0
        space = fm.horizontalAdvance(" ")
        for i, word in enumerate(words):
            k = max(0.0, min(1.0, self._t * (n + 0.6) - i * 0.9))
            c = QColor(color)
            c.setAlphaF(k)
            p.setPen(c)
            p.drawText(QRectF(x, (1.0 - k) * 8, fm.horizontalAdvance(word) + 4, self.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, word)
            x += fm.horizontalAdvance(word) + space
