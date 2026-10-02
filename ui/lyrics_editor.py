"""Editor de letras dentro de la propia ventana: sirve para escribir una letra desde cero o corregir la que generó el sistema."""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton

from services.lyrics_store import format_ms
from ui.overlay import InlineDialog

_TIME_PREFIX = re.compile(r"^\s*\[\d+:\d+(?:\.\d+)?\]\s*")


class LyricsEditorDialog(InlineDialog):
    """Resultado: `text` (lo escrito) y `restore` (True si pidió volver a la letra original)."""

    def __init__(self, parent, title: str, text: str, player=None, can_restore: bool = False, note: str = ""):
        super().__init__(parent)
        self.player = player
        self.text = text
        self.restore = False
        self.setMinimumWidth(620)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 22)
        lay.setSpacing(12)

        head = QLabel(f"Letra de «{title}»")
        head.setObjectName("SectionTitle")
        head.setStyleSheet("font-size: 20px;")
        head.setWordWrap(True)
        lay.addWidget(head)

        hint = QLabel(note or "Escribe una frase por línea. Si quieres que la letra avance sola con la música, "
                      "pon el momento al principio de cada línea, por ejemplo [01:23.50] frase. "
                      "Mientras suena la canción, el botón «Poner el tiempo actual» lo escribe por ti.")
        hint.setObjectName("DialogBody")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.edit = QPlainTextEdit()
        self.edit.setPlainText(text)
        self.edit.setMinimumHeight(340)
        font = QFont("Consolas")
        font.setPointSize(11)
        self.edit.setFont(font)
        self.edit.setStyleSheet("QPlainTextEdit { background: #1A1A1A; color: #FFFFFF; border: 1px solid #3A3A3A; "
                                "border-radius: 10px; padding: 8px; }"
                                "QPlainTextEdit:focus { border-color: #FFFFFF; }")
        lay.addWidget(self.edit)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.btn_time = QPushButton("Poner el tiempo actual")
        self.btn_time.setCursor(Qt.PointingHandCursor)
        self.btn_time.setToolTip("Escribe al principio de la línea el momento en que va la canción y pasa a la siguiente línea")
        self.btn_time.setEnabled(player is not None)
        self.btn_time.clicked.connect(self._stamp)
        tools.addWidget(self.btn_time)
        btn_clear = QPushButton("Quitar los tiempos")
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.clicked.connect(self._strip_times)
        tools.addWidget(btn_clear)
        tools.addStretch()
        lay.addLayout(tools)

        row = QHBoxLayout()
        row.setSpacing(10)
        if can_restore:
            btn_restore = QPushButton("Volver a la original")
            btn_restore.setCursor(Qt.PointingHandCursor)
            btn_restore.setMinimumHeight(44)
            btn_restore.setToolTip("Borra tu versión y vuelve a la letra de internet o a la del sistema")
            btn_restore.clicked.connect(self._restore)
            row.addWidget(btn_restore)
        row.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setMinimumHeight(44)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        self.btn_ok = QPushButton("Guardar")
        self.btn_ok.setObjectName("GiantActionBtn")
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.clicked.connect(self._save)
        row.addWidget(self.btn_ok)
        lay.addLayout(row)
        self.edit.setFocus()

    # ------------------------------------------------------------ acciones
    def _stamp(self):
        """Pone el tiempo actual de la canción al principio de la línea del cursor y baja a la siguiente."""
        cur = self.edit.textCursor()
        cur.movePosition(QTextCursor.StartOfBlock)
        cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        line = _TIME_PREFIX.sub("", cur.selectedText())
        cur.insertText(f"{format_ms(self.player.position())} {line}")
        if not cur.movePosition(QTextCursor.NextBlock):
            cur.movePosition(QTextCursor.EndOfBlock)
        self.edit.setTextCursor(cur)
        self.edit.setFocus()

    def _strip_times(self):
        lines = [_TIME_PREFIX.sub("", ln) for ln in self.edit.toPlainText().splitlines()]
        self.edit.setPlainText("\n".join(lines))

    def _save(self):
        self.text = self.edit.toPlainText().strip()
        if not self.text:
            self.edit.setFocus()
            return
        self.accept()

    def _restore(self):
        self.restore = True
        self.accept()
