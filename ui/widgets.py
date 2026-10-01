"""Widgets reutilizables pequeños."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QSlider, QWidget, QGridLayout


class ElidedLabel(QLabel):
    """QLabel de una sola línea que recorta con '…' en vez de ensanchar su layout."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        super().setText(text)

    def setText(self, text: str):
        self._full_text = text
        super().setText(text)
        self.update()

    def fullText(self) -> str:
        return self._full_text

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event):
        painter = QPainter(self)
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, self.width())
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.rect(), int(self.alignment()) | Qt.AlignVCenter, elided)


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
