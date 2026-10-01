"""Ventana de Ajustes: formato/calidad, destino de descargas, organización y tema visual."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QFrame, QGridLayout, QCheckBox
)

from config import (
    get_download_dir, get_audio_quality
)
from ui.styles import THEME_CONFIGS
from ui.icons import icon
from ui.overlay import InlineDialog
from ui.perf import eco, set_eco


def _group(title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("SettingsGroup")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(8)
    lbl = QLabel(title)
    lbl.setObjectName("SettingsLabel")
    lay.addWidget(lbl)
    if hint:
        h = QLabel(hint)
        h.setObjectName("SettingsHint")
        h.setWordWrap(True)
        lay.addWidget(h)
    return frame, lay


class SettingsDialog(InlineDialog):
    """Contenedor de los controles de ajustes. La ventana principal conecta sus señales."""

    def __init__(self, current_theme: str, parent=None):
        super().__init__(parent, auto_delete=False)
        self.setWindowTitle("Ajustes")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        header = QLabel("Ajustes")
        header.setObjectName("SectionTitle")
        root.addWidget(header)

        # --- Formato y calidad ---
        fmt_box, fmt_lay = _group(
            "Calidad de la música",
            "Si dudas, deja «Alta calidad». «Fidelidad original» conserva el audio tal como llega de internet. "
            "Sin pérdida y Estudio no suenan mejor (el audio de origen ya viene comprimido): solo ocupan más."
        )
        row = QHBoxLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("Alta calidad (recomendado)", "320")
        self.quality_combo.addItem("Calidad normal (ocupa menos espacio)", "192")
        self.quality_combo.addItem("Fidelidad original (sin recomprimir)", "m4a")
        self.quality_combo.addItem("Sin pérdida · FLAC (ocupa mucho)", "flac")
        self.quality_combo.addItem("Estudio · WAV (ocupa muchísimo)", "wav")
        idx = self.quality_combo.findData(get_audio_quality())
        if idx >= 0:
            self.quality_combo.setCurrentIndex(idx)
        row.addWidget(self.quality_combo, stretch=1)

        self.btn_format_info = QPushButton("")
        self.btn_format_info.setObjectName("IconBtn")
        self.btn_format_info.setIcon(icon("info.svg", "#B3B3B3"))
        self.btn_format_info.setIconSize(QSize(18, 18))
        self.btn_format_info.setToolTip("¿Cuál me conviene?")
        self.btn_format_info.setCursor(Qt.PointingHandCursor)
        row.addWidget(self.btn_format_info)
        fmt_lay.addLayout(row)
        root.addWidget(fmt_box)

        # --- Destino y organización ---
        dest_box, dest_lay = _group("¿Dónde se guardan las canciones?")
        self.lbl_download_dir = QLabel(str(get_download_dir()))
        self.lbl_download_dir.setObjectName("SettingsHint")
        self.lbl_download_dir.setWordWrap(True)
        self.lbl_download_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dest_lay.addWidget(self.lbl_download_dir)

        self.btn_change_dir = QPushButton(" Cambiar carpeta...")
        self.btn_change_dir.setObjectName("SidebarSecondaryBtn")
        self.btn_change_dir.setIcon(icon("folder.svg"))
        self.btn_change_dir.setIconSize(QSize(16, 16))
        self.btn_change_dir.setCursor(Qt.PointingHandCursor)
        self.btn_change_dir.setMinimumHeight(36)
        dest_lay.addWidget(self.btn_change_dir, alignment=Qt.AlignLeft)

        root.addWidget(dest_box)

        # --- Rendimiento ---
        perf_box, perf_lay = _group(
            "Rendimiento",
            "El modo ahorro reduce animaciones y memoria. Es lo mejor para ordenadores modestos. "
            "Algunos cambios se notan por completo al reiniciar la aplicación.")
        self.chk_eco = QCheckBox("Modo ahorro de recursos (recomendado)")
        self.chk_eco.setChecked(eco())
        self.chk_eco.toggled.connect(set_eco)
        perf_lay.addWidget(self.chk_eco)
        root.addWidget(perf_box)

        # --- Apariencia ---
        look_box, look_lay = _group("Colores de la aplicación", "Elige el color principal. Se cambia al instante.")
        # El selector real es un desplegable oculto; las muestras de color lo controlan.
        self.theme_combo = QComboBox()
        self.theme_combo.setVisible(False)
        for key, cfg in THEME_CONFIGS.items():
            self.theme_combo.addItem(cfg["name"], key)
        t_idx = self.theme_combo.findData(current_theme)
        if t_idx >= 0:
            self.theme_combo.setCurrentIndex(t_idx)
        look_lay.addWidget(self.theme_combo)

        self.swatches = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        for i, (key, cfg) in enumerate(THEME_CONFIGS.items()):
            sw = QPushButton("")
            sw.setObjectName("Swatch")
            sw.setCheckable(True)
            sw.setToolTip(cfg["name"])
            sw.setProperty("noRetheme", True)  # su color propio no debe adaptarse al tema activo
            sw.setCursor(Qt.PointingHandCursor)
            sw.setFixedSize(36, 36)
            sw.setStyleSheet(
                f"QPushButton#Swatch {{ background-color: {cfg['accent']}; }}"
            )
            sw.setChecked(key == current_theme)
            sw.clicked.connect(lambda _=False, k=key: self._pick_theme(k))
            grid.addWidget(sw, i // 6, i % 6)
            self.swatches[key] = sw
        look_lay.addLayout(grid)
        self.theme_name_lbl = QLabel(THEME_CONFIGS.get(current_theme, {}).get("name", ""))
        self.theme_name_lbl.setObjectName("SettingsHint")
        look_lay.addWidget(self.theme_name_lbl)
        root.addWidget(look_box)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.setObjectName("GiantActionBtn")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        root.addLayout(close_row)

    def _pick_theme(self, key: str):
        for k, sw in self.swatches.items():
            sw.setChecked(k == key)
        self.theme_name_lbl.setText(THEME_CONFIGS[key]["name"])
        idx = self.theme_combo.findData(key)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

    def refresh_download_dir(self):
        self.lbl_download_dir.setText(str(get_download_dir()))
