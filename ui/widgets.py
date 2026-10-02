"""Widgets reutilizables pequeños."""
import unicodedata

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter, QColor, QPalette, QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy, QSlider, QWidget, QGridLayout

from ui import motion
from ui.anim_clock import clock


def _fold(text: str) -> str:
    """Minúsculas y sin tildes, letra a letra (mantiene la longitud para poder marcar las coincidencias)."""
    out = []
    for ch in text:
        base = unicodedata.normalize("NFD", ch)[0]
        out.append(base.lower())
    return "".join(out)


class ElidedLabel(QLabel):
    """QLabel de una sola línea que recorta con '…' en vez de ensanchar su layout.

    Extras (apagados por defecto):
      · `set_marquee(True)`: si el texto no cabe, al pasar el ratón por encima se desplaza despacio para poder leerlo entero.
      · `set_highlight("texto")`: las letras que coinciden con lo buscado se ven en negrita y con el color del tema.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self._marquee = False
        self._highlight = ()
        self._token = None
        self._off = 0.0
        self._state = "idle"
        self._wait = 0.0
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        super().setText(text)

    def setText(self, text: str):
        self._full_text = text
        self._stop_marquee()
        super().setText(text)
        self.update()

    def fullText(self) -> str:
        return self._full_text

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    # ------------------------------------------------------------ marquesina
    def set_marquee(self, on: bool = True):
        self._marquee = bool(on)
        if on:
            self.setAttribute(Qt.WA_Hover, True)

    def _overflow(self) -> float:
        return max(0.0, self.fontMetrics().horizontalAdvance(self._full_text) - self.width())

    def enterEvent(self, event):
        if self._marquee and motion.enabled() and self._overflow() > 2 and self._token is None:
            self._off, self._state, self._wait = 0.0, "wait", 0.0
            self._token = clock().subscribe(self._tick, 30)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._stop_marquee()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._stop_marquee()
        super().hideEvent(event)

    def _stop_marquee(self):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None
            self._off = 0.0
            self.update()

    def _tick(self, dt):
        limit = self._overflow() + 6
        if self._state == "wait":
            self._wait += dt
            if self._wait >= 700:
                self._state = "go"
        elif self._state == "go":
            self._off = min(limit, self._off + dt * 0.04)          # unos 40 píxeles por segundo
            if self._off >= limit:
                self._state, self._wait = "end", 0.0
        elif self._state == "end":
            self._wait += dt
            if self._wait >= 1200:
                self._off, self._state, self._wait = 0.0, "wait", 0.0
        self.update()

    # ------------------------------------------------------------ resaltado
    def set_highlight(self, query: str):
        words = [w for w in _fold(query or "").split() if len(w) >= 2]
        words = tuple(words)
        if words != self._highlight:
            self._highlight = words
            self.update()

    def _marks(self, text: str) -> list:
        """Posiciones de `text` que coinciden con alguna palabra buscada."""
        if not self._highlight:
            return []
        folded = _fold(text)
        marks = [False] * len(text)
        for word in self._highlight:
            start = 0
            while True:
                i = folded.find(word, start)
                if i < 0:
                    break
                for k in range(i, min(len(text), i + len(word))):
                    marks[k] = True
                start = i + len(word)
        return marks

    # ----------------------------------------------------------------- dibujo
    def paintEvent(self, event):
        painter = QPainter(self)
        fm = self.fontMetrics()
        scrolling = self._token is not None and (self._state in ("go", "end") or self._off > 0)
        text = self._full_text if scrolling else fm.elidedText(self._full_text, Qt.ElideRight, self.width())
        color = self.palette().color(QPalette.WindowText)
        painter.setPen(color)
        align = int(self.alignment()) | Qt.AlignVCenter
        marks = self._marks(text)
        if not any(marks):
            if scrolling:
                painter.setClipRect(self.rect())
                painter.drawText(self.rect().translated(-int(self._off), 0).adjusted(0, 0, int(self._off) + 400, 0), align, text)
            else:
                painter.drawText(self.rect(), align, text)
            return
        # con resaltado: se dibuja por tramos (normal / negrita con el color del tema)
        from ui.styles import accent
        bold = painter.font()
        bold.setBold(True)
        fm_bold = QFontMetrics(bold)
        runs = []
        for i, ch in enumerate(text):
            if runs and runs[-1][1] == marks[i]:
                runs[-1][0] += ch
            else:
                runs.append([ch, marks[i]])
        widths = [(fm_bold if hot else fm).horizontalAdvance(t) for t, hot in runs]
        total = sum(widths)
        x = 0.0
        if self.alignment() & Qt.AlignRight:
            x = self.width() - total
        elif self.alignment() & Qt.AlignHCenter:
            x = (self.width() - total) / 2
        x -= self._off if scrolling else 0
        painter.setClipRect(self.rect())
        normal_font = painter.font()
        for (t, hot), w in zip(runs, widths):
            painter.setFont(bold if hot else normal_font)
            painter.setPen(QColor(accent()) if hot else color)
            painter.drawText(int(x), 0, int(w) + 2, self.height(), Qt.AlignLeft | Qt.AlignVCenter, t)
            x += w


class ClickableSlider(QSlider):
    """Deslizador en el que se puede hacer clic en cualquier punto de la barra para saltar a esa posición."""

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.width() > 0:
            val = self.minimum() + ((self.maximum() - self.minimum()) * ev.pos().x()) / self.width()
            self.setValue(int(val))
            ev.accept()
        super().mousePressEvent(ev)


class ReflowGrid(QWidget):
    """Cuadrícula que reparte sus elementos (de ancho fijo) en tantas columnas como quepan."""

    def __init__(self, cell_width: int, spacing: int = 14, parent=None):
        super().__init__(parent)
        self._cell = cell_width
        self._spacing = spacing
        self._items: list = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 4, 0, 8)
        self._grid.setSpacing(spacing)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    def _wanted_columns(self) -> int:
        return max(1, (self.width() + self._spacing) // (self._cell + self._spacing))

    def add(self, widget: QWidget):
        self._items.append(widget)
        self._place(len(self._items) - 1, self._columns or self._wanted_columns())

    def _place(self, index: int, columns: int):
        self._grid.addWidget(self._items[index], index // columns, index % columns)

    def _relayout(self):
        columns = self._wanted_columns()
        if columns == self._columns:
            return
        self._columns = columns
        for w in self._items:
            self._grid.removeWidget(w)
        for i in range(len(self._items)):
            self._place(i, columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()
