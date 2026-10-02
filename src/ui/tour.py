"""Recorrido guiado: oscurece la ventana, resalta un elemento cada vez y lo explica en una burbuja."""
from PySide6.QtCore import Qt, QRectF, QPoint, QPointF, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPainterPath
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from ui import motion


class TourOverlay(QWidget):
    finished = Signal()

    def __init__(self, window, steps: list):
        """steps: [(función que devuelve el widget a resaltar o None, título, texto)]"""
        super().__init__(window)
        self.window_ref = window
        self.steps = steps
        self.index = -1
        self.hole = QRectF()
        self.setGeometry(window.rect())
        self.setFocusPolicy(Qt.StrongFocus)

        self.bubble = QFrame(self)
        self.bubble.setObjectName("TourBubble")
        self.bubble.setAttribute(Qt.WA_StyledBackground, True)
        self.bubble.setFixedWidth(340)
        lay = QVBoxLayout(self.bubble)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)
        self.step_lbl = QLabel("")
        self.step_lbl.setObjectName("SectionSubtitle")
        self.title_lbl = QLabel("")
        self.title_lbl.setObjectName("SectionTitle")
        self.title_lbl.setStyleSheet("font-size: 18px;")
        self.title_lbl.setWordWrap(True)
        self.text_lbl = QLabel("")
        self.text_lbl.setObjectName("DialogBody")
        self.text_lbl.setWordWrap(True)
        lay.addWidget(self.step_lbl)
        lay.addWidget(self.title_lbl)
        lay.addWidget(self.text_lbl)
        row = QHBoxLayout()
        self.btn_skip = QPushButton("Saltar")
        self.btn_skip.setCursor(Qt.PointingHandCursor)
        self.btn_skip.clicked.connect(self.close_tour)
        self.btn_next = QPushButton("Siguiente")
        self.btn_next.setObjectName("GiantActionBtn")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self.next_step)
        row.addWidget(self.btn_skip)
        row.addStretch()
        row.addWidget(self.btn_next)
        lay.addLayout(row)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(motion.DUR_BASE + 60)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_glide)
        self._glide = None
        window.installEventFilter(self)

    def _on_glide(self, v):
        t = float(v)
        (h0, b0), (h1, b1) = self._glide
        self.hole = QRectF(h0.x() + (h1.x() - h0.x()) * t, h0.y() + (h1.y() - h0.y()) * t,
                           h0.width() + (h1.width() - h0.width()) * t, h0.height() + (h1.height() - h0.height()) * t)
        self.bubble.move(int(b0.x() + (b1.x() - b0.x()) * t), int(b0.y() + (b1.y() - b0.y()) * t))
        self.update()

    def _go(self, hole: QRectF, bubble_pos: QPoint):
        """El foco y la burbuja se deslizan hasta el siguiente elemento (si no, saltan)."""
        if (motion.enabled() and self.isVisible() and not self.hole.isNull() and not hole.isNull()):
            self._glide = ((QRectF(self.hole), QPointF(self.bubble.pos())), (hole, QPointF(bubble_pos)))
            self._anim.stop()
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self._anim.stop()
            self.hole = hole
            self.bubble.move(bubble_pos)
            self.update()

    # ------------------------------------------------------------ pasos
    def start(self):
        self.show()
        self.raise_()
        self.setFocus()
        self.next_step()

    def next_step(self):
        self.index += 1
        while self.index < len(self.steps):
            target_fn, title, text = self.steps[self.index]
            target = target_fn() if target_fn else None
            if target is not None and not target.isVisible():
                self.index += 1      # el elemento no está a la vista: se salta el paso
                continue
            self._show_step(target, title, text)
            return
        self.close_tour()

    def _show_step(self, target, title: str, text: str):
        n = len(self.steps)
        self.step_lbl.setText(f"{self.index + 1} de {n}")
        self.title_lbl.setText(title)
        self.text_lbl.setText(text)
        last = self.index >= n - 1
        self.btn_next.setText("Terminar" if last else "Siguiente")
        self.btn_skip.setVisible(not last)
        self.bubble.adjustSize()
        W, H = self.width(), self.height()
        if target is None:
            self._go(QRectF(), QPoint((W - self.bubble.width()) // 2, (H - self.bubble.height()) // 2))
        else:
            top_left = target.mapTo(self.window_ref, QPoint(0, 0))
            hole = QRectF(top_left.x() - 6, top_left.y() - 6, target.width() + 12, target.height() + 12)
            bw, bh = self.bubble.width(), self.bubble.height()
            x = min(max(12, int(hole.center().x() - bw / 2)), W - bw - 12)
            if hole.bottom() + bh + 16 < H:
                y = int(hole.bottom() + 12)
            elif hole.top() - bh - 16 > 0:
                y = int(hole.top() - bh - 12)
            else:       # a un lado
                y = min(max(12, int(hole.center().y() - bh / 2)), H - bh - 12)
                x = int(hole.right() + 12) if hole.right() + bw + 24 < W else max(12, int(hole.left() - bw - 12))
            self._go(hole, QPoint(x, y))
        self.update()

    def close_tour(self):
        self.window_ref.removeEventFilter(self)
        self.hide()
        self.finished.emit()
        self.deleteLater()

    # ----------------------------------------------------------- dibujo
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if not self.hole.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(self.hole, 12, 12)
            path = path.subtracted(hole)
        p.fillPath(path, QColor(0, 0, 0, 185))
        if not self.hole.isNull():
            p.setPen(QColor(255, 255, 255, 200))
            p.drawRoundedRect(self.hole, 12, 12)

    def eventFilter(self, obj, event):
        if obj is self.window_ref and event.type() == event.Type.Resize:
            self.setGeometry(self.window_ref.rect())
            if 0 <= self.index < len(self.steps):
                self.index -= 1
                self.next_step()
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_tour()
        elif event.key() in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.next_step()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        event.accept()      # se bloquean los clics en el resto de la aplicación mientras dura el recorrido
