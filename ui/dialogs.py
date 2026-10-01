"""Diálogos sencillos que se muestran dentro de la propia aplicación (en español y con su estilo)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from ui.overlay import InlineDialog


class _SimpleDialog(InlineDialog):
    def __init__(self, parent, title: str, message: str = "", ok: str = "Aceptar",
                 cancel: str | None = "Cancelar", danger: bool = False, with_input: bool = False,
                 text: str = "", placeholder: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 22)
        lay.setSpacing(14)

        head = QLabel(title)
        head.setObjectName("SectionTitle")
        head.setStyleSheet("font-size: 20px;")
        head.setWordWrap(True)
        lay.addWidget(head)

        if message:
            body = QLabel(message)
            body.setWordWrap(True)
            body.setObjectName("DialogBody")
            lay.addWidget(body)

        self.input = None
        if with_input:
            self.input = QLineEdit(text)
            self.input.setObjectName("DialogInput")
            self.input.setPlaceholderText(placeholder)
            self.input.setMinimumHeight(40)
            self.input.selectAll()
            self.input.returnPressed.connect(self.accept)
            lay.addWidget(self.input)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        if cancel:
            btn_cancel = QPushButton(cancel)
            btn_cancel.setCursor(Qt.PointingHandCursor)
            btn_cancel.setMinimumHeight(44)
            btn_cancel.clicked.connect(self.reject)
            row.addWidget(btn_cancel)
        self.btn_ok = QPushButton(ok)
        self.btn_ok.setObjectName("DangerBtn" if danger else "GiantActionBtn")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        row.addWidget(self.btn_ok)
        lay.addLayout(row)

        if self.input:
            self.input.setFocus()


def ask_text(parent, title: str, label: str = "", text: str = "", ok: str = "Aceptar",
             placeholder: str = "") -> tuple[str, bool]:
    """Pide un texto al usuario. Devuelve (texto, aceptado)."""
    dlg = _SimpleDialog(parent, title, label, ok=ok, with_input=True, text=text, placeholder=placeholder)
    accepted = dlg.exec() == 1
    return (dlg.input.text() if accepted else ""), accepted


def ask_confirm(parent, title: str, message: str, ok: str = "Aceptar", cancel: str = "Cancelar",
                danger: bool = False) -> bool:
    """Pregunta de confirmación. Devuelve True si el usuario acepta."""
    return _SimpleDialog(parent, title, message, ok=ok, cancel=cancel, danger=danger).exec() == 1


def show_message(parent, title: str, message: str, ok: str = "Entendido"):
    """Mensaje informativo con un solo botón."""
    _SimpleDialog(parent, title, message, ok=ok, cancel=None).exec()
