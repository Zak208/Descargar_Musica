"""Ventanas internas: en lugar de abrir ventanas aparte, los cuadros de diálogo se muestran encima de la propia
aplicación (como una capa), con el resto de la ventana atenuado."""
from PySide6.QtCore import Qt, QEvent, QEventLoop, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget, QFrame, QApplication, QPushButton

from ui import motion
from ui.animations import install_ripples, slide_fade_in

DIM_ALPHA = 175.0


class _Veil(QWidget):
    """Velo oscuro que se desvanece cuando se cierra una ventana interna (no recibe clics)."""

    def __init__(self, parent, alpha: float):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.alpha = alpha

    def paintEvent(self, _event):
        if self.alpha > 0.5:
            QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, int(self.alpha)))


def _main_window(parent) -> QWidget:
    win = parent.window() if parent is not None else QApplication.activeWindow()
    if win is None:
        for w in QApplication.topLevelWidgets():
            if w.isVisible():
                win = w
                break
    return win


def get_host(parent) -> "OverlayHost":
    win = _main_window(parent)
    host = getattr(win, "_overlay_host", None)
    if host is None:
        host = OverlayHost(win)
        win._overlay_host = host
    return host


class OverlayHost(QWidget):
    """Capa transparente que cubre toda la ventana y contiene las ventanas internas."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.window_ref = window
        self.setObjectName("OverlayHost")
        self.setFocusPolicy(Qt.StrongFocus)
        self._stack: list = []
        self._dim = 0.0                  # oscurecimiento actual (0 a DIM_ALPHA); se pinta a mano y se anima
        self._dim_target = 0.0
        self._dim_anim = QVariantAnimation(self)
        self._dim_anim.valueChanged.connect(self._on_dim)
        self._dim_anim.finished.connect(self._dim_done)
        self.hide()
        window.installEventFilter(self)   # solo se vigila el redimensionado de la ventana principal

    # -- geometría
    def eventFilter(self, obj, event):
        if obj is self.window_ref and event.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(self.window_ref.rect())
            self._layout_all()
        return False

    def _layout_all(self):
        for dlg in self._stack:
            self._place(dlg)

    def _place(self, dlg: "InlineDialog"):
        dlg.adjustSize()
        if dlg._anchor is not None:
            pos = dlg._anchor()
            x = max(8, min(pos.x(), self.width() - dlg.width() - 8))
            y = max(8, min(pos.y(), self.height() - dlg.height() - 8))
        else:
            x = (self.width() - dlg.width()) // 2
            y = max(12, (self.height() - dlg.height()) // 2)
        dlg.move(x, y)

    # -- oscurecimiento del fondo (pintado a mano: sin reinterpretar hojas de estilo y con transición)
    def paintEvent(self, _event):
        if self._dim > 0.5:
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 0, int(self._dim)))

    def _on_dim(self, v):
        self._dim = float(v)
        self.update()

    def _dim_done(self):
        if self._dim_target <= 0.5 and not self._stack:
            self.hide()

    def _set_dim(self, target: float, duration: int):
        self._dim_target = target
        if not motion.enabled() or not self.isVisible():
            self._dim_anim.stop()
            self._dim = target
            self.update()
            return
        self._dim_anim.stop()
        self._dim_anim.setDuration(duration)
        self._dim_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._dim_anim.setStartValue(self._dim)
        self._dim_anim.setEndValue(target)
        self._dim_anim.start()

    # -- pila de ventanas
    def push(self, dlg: "InlineDialog"):
        self.setGeometry(self.window_ref.rect())
        dlg.setParent(self)
        for other in self._stack:
            other.hide()
        self._stack.append(dlg)
        install_ripples(dlg)
        first = not self.isVisible()
        self.show()
        self.raise_()
        self._set_dim(DIM_ALPHA if dlg._modal else 0.0, motion.DUR_FAST + 20)
        dlg.show()
        self._place(dlg)
        dlg.raise_()
        dlg.setFocus()
        if first or dlg._anchor is not None:
            # la ventana entra con un fundido y un desplazamiento corto (desde su botón si es un menú anclado)
            slide_fade_in(dlg, -8 if dlg._anchor is not None else 10, motion.DUR_FAST + 50)

    def pop(self, dlg: "InlineDialog"):
        if dlg in self._stack:
            self._stack.remove(dlg)
        dlg.hide()
        if self._stack:
            top = self._stack[-1]
            top.show()
            self._place(top)
            top.setFocus()
            self._set_dim(DIM_ALPHA if top._modal else 0.0, motion.DUR_FAST)
        else:
            self._dim_anim.stop()
            was_dim = self._dim
            self._dim = 0.0
            self._dim_target = 0.0
            self.hide()                                     # la capa deja de tapar la ventana al instante...
            if motion.enabled() and was_dim > 1 and self.window_ref.isVisible():
                self._fade_veil(was_dim)                    # ...y un velo transparente al ratón se desvanece (salir es rápido)

    def _fade_veil(self, start_alpha: float):
        veil = _Veil(self.window_ref, start_alpha)
        veil.setGeometry(self.window_ref.rect())
        veil.show()
        veil.raise_()
        anim = QVariantAnimation(veil)
        anim.setStartValue(float(start_alpha))
        anim.setEndValue(0.0)
        anim.setDuration(motion.DUR_EXIT - 20)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def on_value(v):
            veil.alpha = float(v)
            veil.update()

        def done():
            veil.hide()
            veil.deleteLater()

        anim.valueChanged.connect(on_value)
        anim.finished.connect(done)
        veil._anim = anim
        anim.start()

    # -- interacción
    def mousePressEvent(self, event):
        """Pulsar fuera de la ventana interna la cierra (si se puede cerrar)."""
        if self._stack:
            top = self._stack[-1]
            if top.closable and not top.geometry().contains(event.pos()):
                top.reject()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self._stack and event.key() == Qt.Key_Escape and self._stack[-1].closable:
            self._stack[-1].reject()
            return
        super().keyPressEvent(event)


class InlineDialog(QFrame):
    """Sustituto de QDialog que se muestra dentro de la ventana principal (misma interfaz: exec, accept, reject)."""
    accepted = Signal()
    rejected = Signal()
    finished = Signal(int)

    def __init__(self, parent=None, auto_delete: bool = True, closable: bool = True, modal: bool = True,
                 anchor=None):
        host = get_host(parent)
        super().__init__(host)
        self.setObjectName("InlineDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._host = host
        self._loop: QEventLoop | None = None
        self._result = 0
        self._auto_delete = auto_delete
        self.closable = closable
        self._modal = modal
        self._anchor = anchor
        self.hide()

    # -- compatibilidad con QDialog
    def setWindowTitle(self, _title: str):
        pass

    def exec(self) -> int:
        """Muestra la ventana y espera a que se cierre. Devuelve 1 si se aceptó y 0 si se cerró."""
        self._loop = QEventLoop(self)
        self._host.push(self)
        self._loop.exec()
        return self._result

    def open(self):
        self._host.push(self)

    def accept(self):
        self.done(1)

    def reject(self):
        self.done(0)

    def done(self, result: int):
        self._result = result
        self._host.pop(self)
        if result:
            self.accepted.emit()
        else:
            self.rejected.emit()
        self.finished.emit(result)
        if self._loop is not None:
            loop, self._loop = self._loop, None
            loop.quit()
        if self._auto_delete:
            self.deleteLater()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            for btn in self.findChildren(QPushButton):
                if btn.isDefault() and btn.isEnabled() and btn.isVisible():
                    btn.click()
                    return
        elif event.key() == Qt.Key_Escape and self.closable:
            self.reject()
            return
        super().keyPressEvent(event)
