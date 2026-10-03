"""Ecualizador: ajuste del sonido con tres bandas (graves, medios y agudos) y ajustes predefinidos."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QFrame
)

from ui.controls import NoWheelComboBox
from ui.overlay import InlineDialog
from services.equalizer_service import PRESETS, load_eq_settings, save_eq_settings


class StepSlider(QSlider):
    """Deslizador cuya rueda del ratón avanza de 1 en 1."""

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.setValue(self.value() + (1 if delta > 0 else -1))
            event.accept()
        else:
            event.ignore()


class EqualizerDialog(InlineDialog):
    eq_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent, auto_delete=False)
        self.setWindowTitle("Ecualizador")
        self.setMinimumWidth(460)
        self.sliders = {}
        self.value_labels = {}
        self._loading = False
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel("Ecualizador")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        hint = QLabel("Da forma al sonido de tu música. Siempre está activo: con todo en 0 la música suena tal cual. "
                      "Se aplica a las canciones de tu biblioteca (las que ya has descargado).")
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        box = QFrame()
        box.setObjectName("SettingsGroup")
        box_lay = QVBoxLayout(box)
        box_lay.setContentsMargins(18, 14, 18, 16)
        box_lay.setSpacing(12)

        preset_row = QHBoxLayout()
        preset_lbl = QLabel("Ajuste")
        preset_lbl.setObjectName("SettingsLabel")
        preset_row.addWidget(preset_lbl)
        self.preset_combo = NoWheelComboBox()
        for name in PRESETS:
            self.preset_combo.addItem(name)
        self.preset_combo.currentTextChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self.preset_combo, stretch=1)
        box_lay.addLayout(preset_row)

        for key, label in (("bass", "Graves"), ("mid", "Medios"), ("treble", "Agudos")):
            row = QHBoxLayout()
            name = QLabel(label)
            name.setObjectName("SettingsLabel")
            name.setFixedWidth(64)
            slider = StepSlider(Qt.Horizontal)
            slider.setRange(-10, 10)
            slider.setValue(0)
            slider.setFixedHeight(20)
            slider.valueChanged.connect(lambda v, k=key: self._on_slider_changed(k, v))
            val = QLabel("0")
            val.setObjectName("SettingsHint")
            val.setFixedWidth(34)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(name)
            row.addWidget(slider, stretch=1)
            row.addWidget(val)
            box_lay.addLayout(row)
            self.sliders[key] = slider
            self.value_labels[key] = val

        layout.addWidget(box)

        btn_row = QHBoxLayout()
        btn_reset = QPushButton("Restablecer")
        btn_reset.setCursor(Qt.PointingHandCursor)
        btn_reset.clicked.connect(lambda: self.preset_combo.setCurrentText("Normal"))
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        btn_apply = QPushButton("Aplicar")
        btn_apply.setObjectName("GiantActionBtn")
        btn_apply.setCursor(Qt.PointingHandCursor)
        btn_apply.clicked.connect(self.apply_and_close)
        btn_row.addWidget(btn_apply)
        layout.addLayout(btn_row)

    def _on_slider_changed(self, key: str, value: int):
        self.value_labels[key].setText(f"{value:+d}" if value else "0")
        if self._loading:
            return
        # Si se mueve a mano, el ajuste deja de ser uno de los predefinidos
        current = tuple(self.sliders[k].value() for k in ("bass", "mid", "treble"))
        match = next((n for n, v in PRESETS.items() if v == current), None)
        self.preset_combo.blockSignals(True)
        if match:
            self.preset_combo.setCurrentText(match)
        else:
            if self.preset_combo.findText("Personalizado") < 0:
                self.preset_combo.addItem("Personalizado")
            self.preset_combo.setCurrentText("Personalizado")
        self.preset_combo.blockSignals(False)

    def _on_preset_selected(self, name: str):
        if name in PRESETS:
            bass, mid, treble = PRESETS[name]
            self._loading = True
            self.sliders["bass"].setValue(bass)
            self.sliders["mid"].setValue(mid)
            self.sliders["treble"].setValue(treble)
            self._loading = False

    def load_settings(self):
        data = load_eq_settings()
        self._loading = True
        for key in ("bass", "mid", "treble"):
            self.sliders[key].setValue(int(data.get(key, 0)))
        self._loading = False
        current = tuple(int(data.get(k, 0)) for k in ("bass", "mid", "treble"))
        match = next((n for n, v in PRESETS.items() if v == current), None)
        if not match:
            self.preset_combo.addItem("Personalizado")
            match = "Personalizado"
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentText(match)
        self.preset_combo.blockSignals(False)

    def apply_and_close(self):
        data = {
            "enabled": True,
            "preset": self.preset_combo.currentText(),
            "bass": self.sliders["bass"].value(),
            "mid": self.sliders["mid"].value(),
            "treble": self.sliders["treble"].value(),
        }
        save_eq_settings(data)
        self.eq_changed.emit(data)
        self.accept()
