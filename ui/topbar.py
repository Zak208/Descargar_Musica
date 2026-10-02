"""Barra superior estilo Spotify, de lado a lado de la ventana: marca, inicio + buscador centrados, info y descargas."""
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel

from ui.icons import icon
from ui.styles import accent


class TopBar(QWidget):
    search_submitted = Signal(str)
    home_clicked = Signal()
    downloads_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setMinimumHeight(48)
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 0, 6, 0)
        root.setSpacing(12)

        # --- izquierda: marca ---
        left = QWidget()
        left_lay = QHBoxLayout(left)
        left_lay.setContentsMargins(4, 0, 0, 0)
        left_lay.setSpacing(10)
        self.logo = QLabel()
        self.logo.setPixmap(icon("music.svg", accent(), 64).pixmap(26, 26))
        self.brand = QLabel("Descargador de Música")
        self.brand.setObjectName("BrandLabel")
        left_lay.addWidget(self.logo)
        left_lay.addWidget(self.brand)
        left_lay.addStretch()
        root.addWidget(left, 1)

        # --- centro: inicio + buscador ---
        center = QWidget()
        center_lay = QHBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(10)
        self.btn_home = QPushButton("")
        self.btn_home.setObjectName("TopIconBtn")
        self.btn_home.setIcon(icon("home.svg"))
        self.btn_home.setIconSize(QSize(20, 20))
        self.btn_home.setToolTip("Inicio")
        self.btn_home.setCursor(Qt.PointingHandCursor)
        self.btn_home.clicked.connect(self.home_clicked.emit)
        center_lay.addWidget(self.btn_home)

        self.search = QLineEdit()
        self.search.setObjectName("TopSearch")
        self.search.setPlaceholderText("¿Qué quieres escuchar? Busca o pega un enlace")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(44)
        self.search.setMinimumWidth(300)
        self.search.setMaximumWidth(520)
        self.search.addAction(icon("search.svg", "#B3B3B3"), QLineEdit.LeadingPosition)
        self.search.returnPressed.connect(self._submit_now)
        self.search.textEdited.connect(self._on_edited)
        center_lay.addWidget(self.search, 1)
        center.setMaximumWidth(620)
        root.addWidget(center, 2)

        # --- derecha: información general y descargas ---
        right = QWidget()
        right_lay = QHBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 4, 0)
        right_lay.setSpacing(12)
        right_lay.addStretch()
        self.info = QLabel("")
        self.info.setObjectName("TopInfo")
        right_lay.addWidget(self.info)
        self.btn_downloads = QPushButton(" Descargas")
        self.btn_downloads.setObjectName("TopPillBtn")
        self.btn_downloads.setIcon(icon("download.svg"))
        self.btn_downloads.setIconSize(QSize(16, 16))
        self.btn_downloads.setToolTip("Ver las descargas en curso")
        self.btn_downloads.setCursor(Qt.PointingHandCursor)
        self.btn_downloads.clicked.connect(self.downloads_clicked.emit)
        right_lay.addWidget(self.btn_downloads)
        root.addWidget(right, 1)

        # Buscar automáticamente cuando el usuario deja de escribir un momento
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self._submit_typed)

    # ---------------------------------------------------------------- búsqueda
    def _on_edited(self, text: str):
        if len(text.strip()) >= 2:
            self._timer.start()
        else:
            self._timer.stop()

    def _submit_typed(self):
        text = self.search.text().strip()
        if len(text) >= 2:
            self.search_submitted.emit(text)

    def _submit_now(self):
        self._timer.stop()
        self.search_submitted.emit(self.search.text().strip())

    def set_offline(self, offline: bool):
        """Sin conexión la búsqueda mira solo en tu música (y responde más deprisa porque no hay red de por medio)."""
        self.search.setPlaceholderText("Buscar en tu música descargada" if offline
                                       else "¿Qué quieres escuchar? Busca o pega un enlace")
        self._timer.setInterval(350 if offline else 900)

    def set_text(self, text: str, silent: bool = True):
        self.search.blockSignals(silent)
        self.search.setText(text)
        self.search.blockSignals(False)

    def text(self) -> str:
        return self.search.text()

    # ------------------------------------------------------------------ estado
    def refresh_accent(self):
        self.logo.setPixmap(icon("music.svg", accent(), 64).pixmap(26, 26))

    def set_info(self, text: str):
        self.info.setText(text)

    def set_download_count(self, count: int):
        self.btn_downloads.setText(f" Descargas · {count}" if count else " Descargas")
        self.btn_downloads.setProperty("busy", bool(count))
        self.btn_downloads.style().unpolish(self.btn_downloads)
        self.btn_downloads.style().polish(self.btn_downloads)
