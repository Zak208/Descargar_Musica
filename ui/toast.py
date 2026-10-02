"""Avisos flotantes breves (en lugar de ventanas emergentes que obligan a pulsar «Aceptar»). Pueden llevar un botón,
por ejemplo «Deshacer»."""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QGraphicsOpacityEffect


class Toast(QFrame):
    """Aviso centrado en la parte inferior de la ventana que se desvanece solo."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("QFrame#Toast { background-color: #FFFFFF; border-radius: 20px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 8, 14, 8)
        lay.setSpacing(12)
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
        self.hide()

    def show_message(self, text: str, msec: int = 2800, bottom_margin: int = 120, action=None):
        """`action` = (texto del botón, función) para ofrecer algo como «Deshacer»."""
        parent = self.parentWidget()
        if parent is None:
            return
        self.label.setText(text)
        self._action = action[1] if action else None
        self.action_btn.setVisible(bool(action))
        if action:
            self.action_btn.setText(action[0])
            msec = max(msec, 6500)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not action)
        width = min(600, max(260, parent.width() - 80))
        self.setFixedWidth(width)
        self.label.setFixedWidth(width - 36 - (110 if action else 0))
        self.layout().activate()
        self.setFixedHeight(max(46, self.layout().sizeHint().height()))
        target = QPoint((parent.width() - self.width()) // 2, parent.height() - self.height() - bottom_margin)
        self.move(target.x(), target.y() + 24)
        self.raise_()
        self.show()
        self._slide.stop()
        self._slide.setStartValue(QPoint(target.x(), target.y() + 24))
        self._slide.setEndValue(target)
        self._slide.start()
        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(msec)

    def _on_action(self):
        action, self._action = self._action, None
        self._timer.stop()
        self._fade_out()
        if action:
            action()

    def _fade_out(self):
        self._anim.stop()
        self._anim.setDuration(350)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_finished(self):
        if self._effect.opacity() <= 0.01:
            self.hide()
