"""Avisos flotantes breves (en lugar de ventanas emergentes que obligan a pulsar «Aceptar»). Pueden llevar un botón,
por ejemplo «Deshacer». Según el mensaje llevan un icono (hecho, aviso, error), una barra fina que se vacía para saber
cuándo desaparecen, se quedan quietos mientras el ratón está encima y se apilan (hasta 3) si llega otro."""
import re

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRectF
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QGraphicsOpacityEffect

from ui import motion
from ui.anim_clock import clock
from ui.icons import icon
from ui.styles import accent

_ERROR = re.compile(r"no se pudo|no hemos|no se encontr|error|falló|no se puede|no es una", re.I)
_WARN = re.compile(r"sin conexi|poco espacio|va justo|pendiente|detenid|en pausa", re.I)
_OK = re.compile(r"descargad|guardad|añadid|creada|listo|al día|actualizad|restaurad|copia|conexión recuperada|se detendrá"
                 r"|aplicad|quitad|sonará|reanudad|desactivad|pegado", re.I)


def infer_kind(text: str) -> str:
    """Tipo de aviso según lo que dice: «error», «warning», «success» o «info»."""
    if _ERROR.search(text):
        return "error"
    if _WARN.search(text):
        return "warning"
    if _OK.search(text):
        return "success"
    return "info"


KIND_ICON = {"success": ("check_circle.svg", None), "warning": ("info.svg", "#E5A000"), "error": ("x.svg", "#E5484D")}
MAX_STACK = 3


class Toast(QFrame):
    """Aviso centrado en la parte inferior de la ventana que se desvanece solo."""

    def __init__(self, parent, primary: bool = True):
        super().__init__(parent)
        self.primary = primary
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("QFrame#Toast { background-color: #FFFFFF; border-radius: 20px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(10)
        self.icon_lbl = QLabel("")
        self.icon_lbl.setFixedSize(20, 20)
        self.icon_lbl.setStyleSheet("background: transparent;")
        self.icon_lbl.setVisible(False)
        lay.addWidget(self.icon_lbl)
        self.label = QLabel("")
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.label.setStyleSheet("background: transparent; color: #000000; font-size: 14px; font-weight: bold;")
        lay.addWidget(self.label, stretch=1)
        self.action_btn = QPushButton("")
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setStyleSheet(
            "QPushButton { background: #121212; color: #FFFFFF; border: none; border-radius: 14px; padding: 6px 14px; "
            "font-weight: 800; font-size: 13px; } QPushButton:hover { background: #333333; }")
        self.action_btn.clicked.connect(self._on_action)
        self.action_btn.hide()
        lay.addWidget(self.action_btn)
        self._action = None
        self.kind = "info"
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.finished.connect(self._on_anim_finished)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(260)
        self._slide.setEasingCurve(QEasingCurve.OutBack)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._total = 1
        self._left = 0.0              # milisegundos que le quedan (la barra fina lo enseña)
        self._token = None
        self._hover = False
        self._clones = []
        self.hide()

    # --------------------------------------------------------------- contenido
    def _set_content(self, text: str, action, kind: str):
        self.kind = kind
        self.label.setText(text)
        self._action = action[1] if action else None
        self.action_btn.setVisible(bool(action))
        if action:
            self.action_btn.setText(action[0])
        name, color = KIND_ICON.get(kind, (None, None))
        if name:
            self.icon_lbl.setPixmap(icon(name, color or accent()).pixmap(20, 20))
        self.icon_lbl.setVisible(bool(name))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not action)

    def _fit(self, parent, action):
        width = min(600, max(260, parent.width() - 80))
        self.setFixedWidth(width)
        self.label.setFixedWidth(width - 28 - (30 if self.icon_lbl.isVisible() else 0) - (110 if action else 0) - 10)
        self.layout().activate()
        self.setFixedHeight(max(46, self.layout().sizeHint().height()))

    def show_message(self, text: str, msec: int = 2800, bottom_margin: int = 120, action=None, kind: str = None):
        """`action` = (texto del botón, función) para ofrecer algo como «Deshacer»."""
        parent = self.parentWidget()
        if parent is None:
            return
        if action:
            msec = max(msec, 6500)
        kind = kind or infer_kind(text)
        if self.primary and self.isVisible() and self.label.text() and self._effect.opacity() > 0.4 and text != self.label.text():
            self._stack_previous()
        self._set_content(text, action, kind)
        self._fit(parent, action)
        target = QPoint((parent.width() - self.width()) // 2, parent.height() - self.height() - bottom_margin)
        self._home = target
        self.move(target.x(), target.y() + 24)
        self.raise_()
        self.show()
        if motion.enabled():
            self._slide.stop()
            self._slide.setStartValue(QPoint(target.x(), target.y() + 24))
            self._slide.setEndValue(target)
            self._slide.start()
            self._anim.stop()
            self._anim.setDuration(160)
            self._anim.setStartValue(self._effect.opacity())
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self.move(target)
            self._effect.setOpacity(1.0)
        self._start_countdown(msec)
        self._reposition_clones()

    # -------------------------------------------------------------- apilado
    def _stack_previous(self):
        """El aviso que se estaba viendo sube y se queda un momento más encima del nuevo."""
        clone = Toast(self.parentWidget(), primary=False)
        clone._set_content(self.label.text(), None, self.kind)
        clone._fit(self.parentWidget(), None)
        clone.move(self.pos())
        clone._effect.setOpacity(1.0)
        clone.show()
        clone.raise_()
        clone._start_countdown(1800, clone_mode=True)
        self._clones.insert(0, clone)
        while len(self._clones) > MAX_STACK - 1:
            old = self._clones.pop()
            old.dismiss_now()

    def _reposition_clones(self):
        self._clones = [c for c in self._clones if c.isVisible()]
        y = self._home.y()
        for clone in self._clones:
            y -= clone.height() + 8
            if clone.pos().y() != y or clone.pos().x() != self._home.x():
                clone.slide_to(QPoint(self._home.x(), y))

    def slide_to(self, pos: QPoint):
        if not motion.enabled():
            self.move(pos)
            return
        self._slide.stop()
        self._slide.setDuration(180)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.setStartValue(self.pos())
        self._slide.setEndValue(pos)
        self._slide.start()

    def dismiss_now(self):
        self._stop_clock()
        self.hide()
        self.deleteLater()

    # ------------------------------------------------- cuenta atrás y barra
    def _start_countdown(self, msec: int, clone_mode: bool = False):
        self._total = max(1, msec)
        self._left = float(msec)
        self._timer.start(msec)
        if motion.enabled() and self._token is None:
            self._token = clock().subscribe(self._tick, 10)
        self.update()

    def _stop_clock(self):
        if self._token is not None:
            clock().unsubscribe(self._token)
            self._token = None

    def _tick(self, dt):
        if not self._hover:
            self._left = max(0.0, self._left - dt)
        self.update()

    def enterEvent(self, event):
        if not self.testAttribute(Qt.WA_TransparentForMouseEvents) and self._timer.isActive():
            self._hover = True
            self._timer.stop()           # con el ratón encima, el aviso no se va
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hover:
            self._hover = False
            self._timer.start(int(max(1500, self._left)))
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._left <= 0 or not motion.enabled():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width() - 36
        k = max(0.0, min(1.0, self._left / self._total))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 38))
        p.drawRoundedRect(QRectF(18, self.height() - 5, w * k, 2), 1, 1)

    # --------------------------------------------------------------- final
    def _on_action(self):
        action, self._action = self._action, None
        self._timer.stop()
        self._fade_out()
        if action:
            action()

    def _fade_out(self):
        self._stop_clock()
        self._left = 0.0
        if not motion.enabled():
            self._effect.setOpacity(0.0)
            self._on_anim_finished()
            return
        self._anim.stop()
        self._anim.setDuration(350)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_finished(self):
        if self._effect.opacity() <= 0.01:
            self.hide()
            if not self.primary:
                self.deleteLater()
