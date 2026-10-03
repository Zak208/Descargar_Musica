"""Barra superior estilo Spotify, de lado a lado de la ventana: marca, inicio + buscador centrados, info y descargas."""
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel, QSizePolicy

from ui.animations import pop_icon
from ui.downloadfx import RingButton
from ui.icons import icon
from ui.styles import accent


class TopBar(QWidget):
    search_submitted = Signal(str)
    home_clicked = Signal()
    downloads_clicked = Signal()
    update_clicked = Signal()

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
        self.brand.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)      # no obliga a la ventana a ser más ancha
        left_lay.addWidget(self.logo)
        left_lay.addWidget(self.brand)
        # botón azul que aparece cuando hay una versión nueva de la aplicación
        self.btn_update = QPushButton("")
        self.btn_update.setObjectName("UpdateBtn")
        self.btn_update.setProperty("noRetheme", True)
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.setStyleSheet(
            "QPushButton#UpdateBtn { background-color: #2979FF; color: #FFFFFF; border: none; border-radius: 17px; "
            "padding: 0px 16px; min-height: 34px; max-height: 34px; font-size: 13px; font-weight: 800; }"
            "QPushButton#UpdateBtn:hover { background-color: #448AFF; }"
            "QPushButton#UpdateBtn:disabled { background-color: #1B4DB3; color: #D6E4FF; }")
        self.btn_update.clicked.connect(self.update_clicked.emit)
        self.btn_update.hide()
        left_lay.addSpacing(10)
        left_lay.addWidget(self.btn_update)
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
        self.info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        right_lay.addWidget(self.info)
        self.btn_downloads = RingButton(" Descargas")
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

    def error_flash(self):
        """La búsqueda falló o no encontró nada: el campo tiembla y se ve un instante con borde rojo."""
        from ui.animations import shake
        shake(self.search)
        self.search.setProperty("error", True)
        self.search.style().unpolish(self.search)
        self.search.style().polish(self.search)

        def clear():
            self.search.setProperty("error", False)
            self.search.style().unpolish(self.search)
            self.search.style().polish(self.search)

        QTimer.singleShot(700, clear)

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

    NARROW = 1150

    def resizeEvent(self, event):
        """En una ventana estrecha se esconden el nombre y el resumen para que lo importante no se corte."""
        super().resizeEvent(event)
        narrow = self.width() < self.NARROW
        self.info.setVisible(not narrow)
        self._brand_hidden_by_width = narrow
        self.brand.setVisible(not narrow and not self.btn_update.isVisible())

    def set_update_button(self, text: str, enabled: bool = True, tip: str = ""):
        """Botón azul de actualización (arriba a la izquierda). Texto vacío = oculto."""
        self.btn_update.setText(text)
        self.btn_update.setEnabled(enabled)
        self.btn_update.setToolTip(tip)
        self.btn_update.setVisible(bool(text))
        self.brand.setVisible(not text and not getattr(self, "_brand_hidden_by_width", False))   # el botón cede... o el nombre

    def set_download_progress(self, percent):
        """Anillo de progreso conjunto en el botón de descargas (None cuando no hay nada en marcha)."""
        self.btn_downloads.set_ring(None if percent is None else percent / 100.0)

    def download_finished_flash(self):
        self.btn_downloads.finished_flash()
        pop_icon(self.btn_downloads, 1.3, 260)

    def set_download_count(self, count: int):
        self.btn_downloads.setText(f" Descargas · {count}" if count else " Descargas")
        self.btn_downloads.setProperty("busy", bool(count))
        self.btn_downloads.style().unpolish(self.btn_downloads)
        self.btn_downloads.style().polish(self.btn_downloads)
