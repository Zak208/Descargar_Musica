"""Ayudas emergentes propias: una burbuja oscura que aparece con un fundido breve y, si el control tiene atajo de
teclado, lo enseña a la derecha («Siguiente  →»). Enseña los atajos sin necesidad de un manual.

Se sirve de un único widget compartido; el filtro de eventos solo reacciona cuando Qt pide mostrar una ayuda."""
from PySide6.QtCore import Qt, QObject, QEvent, QPoint, QRectF, QTimer, QVariantAnimation
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QCursor
from PySide6.QtWidgets import QApplication, QWidget

from ui import motion

# atajos de las acciones más usadas (por el texto de su ayuda)
SHORTCUTS = {
    "Reproducir / pausa": "Espacio",
    "Reproducir": "Espacio",
    "Pausa": "Espacio",
    "Buscar": "Ctrl+F",
    "Silenciar": "M",
    "Volver arriba": "",
}


class _Bubble(QWidget):
    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.text = ""
        self.hint = ""
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(100)
        self._anim.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))

    def show_tip(self, text: str, hint: str, global_pos: QPoint):
        self.text, self.hint = text, hint
        font = self.font()
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        self.setFont(font)
        fm = QFontMetrics(font)
        text_w = min(360, fm.horizontalAdvance(text))
        hint_w = (fm.horizontalAdvance(hint) + 14) if hint else 0
        self.resize(text_w + hint_w + 26 + (8 if hint else 0), fm.height() + 16)
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(global_pos.x() + 12, geo.right() - self.width() - 4)
        y = global_pos.y() + 22
        if y + self.height() > geo.bottom():
            y = global_pos.y() - self.height() - 8
        self.move(max(geo.left() + 2, x), y)
        if motion.enabled():
            self.setWindowOpacity(0.0)
            self.show()
            self._anim.stop()
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self.setWindowOpacity(1.0)
            self.show()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(255, 255, 255, 38))
        p.setBrush(QColor(28, 28, 28, 245))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        fm = self.fontMetrics()
        p.setPen(QColor("#FFFFFF"))
        text_w = min(360, fm.horizontalAdvance(self.text))
        p.drawText(QRectF(13, 0, text_w + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self.text, Qt.ElideRight, text_w))
        if self.hint:
            hw = fm.horizontalAdvance(self.hint) + 12
            r = QRectF(self.width() - hw - 8, 5, hw, self.height() - 10)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawRoundedRect(r, 5, 5)
            p.setPen(QColor("#B3B3B3"))
            p.drawText(r, Qt.AlignCenter, self.hint)


class TooltipFilter(QObject):
    """Sustituye las ayudas de Qt por la burbuja propia."""

    def __init__(self):
        super().__init__()
        self.bubble = _Bubble()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(6000)
        self._timer.timeout.connect(self.bubble.hide)

    def eventFilter(self, obj, event):
        try:
            return self._filter(obj, event)
        except RuntimeError:                       # la ventana ya se está cerrando
            return False

    def _filter(self, obj, event):
        t = event.type()
        if t == QEvent.ToolTip and isinstance(obj, QWidget):
            text = obj.toolTip()
            if not text:
                self.bubble.hide()
                return False
            hint = obj.property("shortcut") or SHORTCUTS.get(text, "")
            self.bubble.show_tip(text, str(hint or ""), QCursor.pos())
            self._timer.start()
            return True                    # la ayuda de Qt no se muestra
        if t in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel, QEvent.WindowDeactivate,
                 QEvent.Hide):
            if self.bubble.isVisible():
                self.bubble.hide()
        return False


_filter = None


def uninstall():
    global _filter
    if _filter is not None:
        try:
            QApplication.instance().removeEventFilter(_filter)
            _filter.bubble.hide()
        except RuntimeError:
            pass
        _filter = None


def install():
    """Activa las ayudas propias en toda la aplicación (una sola vez)."""
    global _filter
    if _filter is None:
        _filter = TooltipFilter()
        QApplication.instance().installEventFilter(_filter)
    return _filter
