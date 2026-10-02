"""Asistente de primer uso: tres pasos sencillos (carpeta, calidad y color) y, al final, el recorrido por la aplicación."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QWidget, QRadioButton, QButtonGroup, QGridLayout
)

from config import get_download_dir, get_audio_quality, set_audio_quality
from ui import motion, snapshot
from ui.controls import ProgressDots
from ui.overlay import InlineDialog
from ui.styles import THEME_CONFIGS

# Solo tres opciones, con palabras de andar por casa
SIMPLE_QUALITIES = (
    ("320", "Alta calidad", "Suena muy bien. Unos 9 MB por canción. Es lo que recomendamos."),
    ("128", "Ahorrar espacio", "Suena bien y ocupa poco: unos 4 MB por canción."),
    ("m4a", "Fidelidad original", "El audio tal cual llega de internet, sin tocarlo. Unos 5 MB por canción."),
)


class WelcomeDialog(InlineDialog):
    """Resultado: `start_tour` (True si quiere ver el recorrido)."""

    def __init__(self, window):
        super().__init__(window, closable=False)
        self.window_ref = window
        self.start_tour = False
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 28, 30, 24)
        root.setSpacing(14)
        self.steps = QStackedWidget()
        root.addWidget(self.steps)

        # ---- paso 1: carpeta
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(10)
        t1 = QLabel("¡Bienvenido!")
        t1.setObjectName("SectionTitle")
        t1.setStyleSheet("font-size: 26px;")
        l1.addWidget(t1)
        b1 = QLabel("Vamos a dejarlo listo en un minuto. Primero, ¿dónde guardamos tu música?")
        b1.setObjectName("DialogBody")
        b1.setWordWrap(True)
        l1.addWidget(b1)
        self.dir_lbl = QLabel(str(get_download_dir()))
        self.dir_lbl.setObjectName("SettingsHint")
        self.dir_lbl.setWordWrap(True)
        l1.addWidget(self.dir_lbl)
        btn_dir = QPushButton("Elegir otra carpeta...")
        btn_dir.setCursor(Qt.PointingHandCursor)
        btn_dir.setMinimumHeight(40)
        btn_dir.clicked.connect(self._choose_dir)
        l1.addWidget(btn_dir, alignment=Qt.AlignLeft)
        l1.addStretch()
        self.steps.addWidget(p1)

        # ---- paso 2: calidad
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(10)
        t2 = QLabel("¿Cómo quieres tu música?")
        t2.setObjectName("SectionTitle")
        t2.setStyleSheet("font-size: 26px;")
        l2.addWidget(t2)
        self.group = QButtonGroup(self)
        current = get_audio_quality()
        for key, name, desc in SIMPLE_QUALITIES:
            rb = QRadioButton(f"{name}")
            rb.setStyleSheet("font-size: 15px; font-weight: 700;")
            rb.setChecked(key == current or (key == "320" and current not in [k for k, *_ in SIMPLE_QUALITIES]))
            rb.setProperty("quality", key)
            self.group.addButton(rb)
            l2.addWidget(rb)
            d = QLabel(desc)
            d.setObjectName("SettingsHint")
            d.setWordWrap(True)
            d.setContentsMargins(26, 0, 0, 6)
            l2.addWidget(d)
        l2.addStretch()
        self.steps.addWidget(p2)

        # ---- paso 3: color
        p3 = QWidget()
        l3 = QVBoxLayout(p3)
        l3.setContentsMargins(0, 0, 0, 0)
        l3.setSpacing(10)
        t3 = QLabel("Elige tu color")
        t3.setObjectName("SectionTitle")
        t3.setStyleSheet("font-size: 26px;")
        l3.addWidget(t3)
        b3 = QLabel("Se cambia al instante y puedes volver a cambiarlo cuando quieras en Ajustes.")
        b3.setObjectName("DialogBody")
        b3.setWordWrap(True)
        l3.addWidget(b3)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(12)
        self.swatches = {}
        for i, (key, cfg) in enumerate(THEME_CONFIGS.items()):
            sw = QPushButton("")
            sw.setObjectName("Swatch")
            sw.setCheckable(True)
            sw.setToolTip(cfg["name"])
            sw.setProperty("noRetheme", True)
            sw.setCursor(Qt.PointingHandCursor)
            sw.setFixedSize(40, 40)
            sw.setStyleSheet(f"QPushButton#Swatch {{ background-color: {cfg['accent']}; }}")
            sw.setChecked(key == window.current_theme)
            sw.clicked.connect(lambda _=False, k=key: self._pick_theme(k))
            grid.addWidget(sw, i // 6, i % 6)
            self.swatches[key] = sw
        l3.addLayout(grid)
        l3.addStretch()
        self.steps.addWidget(p3)

        # ---- paso 4: listo
        p4 = QWidget()
        l4 = QVBoxLayout(p4)
        l4.setContentsMargins(0, 0, 0, 0)
        l4.setSpacing(10)
        t4 = QLabel("¡Todo listo!")
        t4.setObjectName("SectionTitle")
        t4.setStyleSheet("font-size: 26px;")
        l4.addWidget(t4)
        b4 = QLabel("Escribe en la barra de arriba el nombre de una canción o artista, escucha un adelanto y "
                    "pulsa «Descargar». ¿Quieres que te enseñemos dónde está cada cosa? Son menos de 1 minuto.")
        b4.setObjectName("DialogBody")
        b4.setWordWrap(True)
        l4.addWidget(b4)
        l4.addStretch()
        self.steps.addWidget(p4)

        # ---- botones
        row = QHBoxLayout()
        self.dots = ProgressDots(self.steps.count())
        row.addWidget(self.dots)
        row.addStretch()
        self.btn_skip = QPushButton("Saltar")
        self.btn_skip.setCursor(Qt.PointingHandCursor)
        self.btn_skip.setMinimumHeight(44)
        self.btn_skip.clicked.connect(self._skip)
        row.addWidget(self.btn_skip)
        self.btn_next = QPushButton("Siguiente")
        self.btn_next.setObjectName("GiantActionBtn")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self._next)
        row.addWidget(self.btn_next)
        root.addLayout(row)
        self._refresh_buttons()

    # ------------------------------------------------------------ acciones
    def _choose_dir(self):
        self.window_ref.choose_custom_download_dir()
        self.dir_lbl.setText(str(get_download_dir()))

    def _pick_theme(self, key: str):
        for k, sw in self.swatches.items():
            sw.setChecked(k == key)
        self.window_ref.settings_dialog._pick_theme(key)

    def _refresh_buttons(self):
        i, n = self.steps.currentIndex(), self.steps.count()
        self.dots.set_index(i)
        last = i == n - 1
        self.btn_next.setText("Ver el recorrido" if last else "Siguiente")
        self.btn_skip.setText("Ahora no" if last else "Saltar")

    def _apply_quality(self):
        btn = self.group.checkedButton()
        if btn is not None:
            set_audio_quality(btn.property("quality"))
            combo = self.window_ref.quality_combo
            idx = combo.findData(btn.property("quality"))
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

    def _next(self):
        i = self.steps.currentIndex()
        if i == 1:
            self._apply_quality()
        if i >= self.steps.count() - 1:
            self.start_tour = True
            self.accept()
            return
        old = snapshot.grab(self.steps) if motion.enabled() else None
        self.steps.setCurrentIndex(i + 1)
        if old is not None:
            snapshot.crossfade(self.steps, old, motion.DUR_BASE, dx=-36.0)      # el paso anterior sale deslizando
        self._refresh_buttons()

    def _skip(self):
        if self.steps.currentIndex() == 1:
            self._apply_quality()
        self.start_tour = False
        self.accept()
