"""Ventanas internas: en lugar de abrir ventanas aparte, los cuadros de diálogo se muestran encima de la propia
aplicación (como una capa), con el resto de la ventana atenuado."""
from PySide6.QtCore import Qt, QEvent, QEventLoop, Signal
from PySide6.QtWidgets import QWidget, QFrame, QApplication, QPushButton


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
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._stack: list = []
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

    # -- pila de ventanas
    def push(self, dlg: "InlineDialog"):
        self.setGeometry(self.window_ref.rect())
        dlg.setParent(self)
        for other in self._stack:
            other.hide()
        self._stack.append(dlg)
        dim = "rgba(0, 0, 0, 175)" if dlg._modal else "transparent"
        self.setStyleSheet(f"#OverlayHost {{ background-color: {dim}; }}")
        self.show()
        self.raise_()
        dlg.show()
        self._place(dlg)
        dlg.raise_()
        dlg.setFocus()

    def pop(self, dlg: "InlineDialog"):
        if dlg in self._stack:
            self._stack.remove(dlg)
        dlg.hide()
        if self._stack:
            top = self._stack[-1]
            top.show()
            self._place(top)
            top.setFocus()
            dim = "rgba(0, 0, 0, 175)" if top._modal else "transparent"
            self.setStyleSheet(f"#OverlayHost {{ background-color: {dim}; }}")
        else:
            self.hide()

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
