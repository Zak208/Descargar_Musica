"""Ventana de Ayuda: recorrido, atajos de teclado, informe de problemas y reparación."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGridLayout, QApplication, QScrollArea, QWidget
)

from services import diagnostics_service, storage_service
from ui.dialogs import ask_confirm
from ui.overlay import InlineDialog
from ui.settings_dialog import _group, _button
from version import __version__

SHORTCUTS = (
    ("Espacio", "Pausar o reanudar"),
    ("←  →", "Retroceder o avanzar 5 segundos"),
    ("M", "Silenciar o quitar el silencio"),
    ("Ctrl + F", "Ir al buscador"),
    ("Ctrl + V", "Pegar un enlace de YouTube o Spotify para descargarlo"),
    ("Ctrl + Z", "Deshacer lo último que quitaste de una lista"),
    ("Teclas multimedia", "Reproducir, siguiente y anterior desde el teclado"),
    ("F11", "Letra a pantalla completa (Esc para salir)"),
    ("Doble clic", "Reproducir una canción de una lista"),
)


class HelpDialog(InlineDialog):
    def __init__(self, window):
        super().__init__(window, auto_delete=False)
        self.window_ref = window
        self.setMinimumWidth(600)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(12)
        header = QLabel("Ayuda")
        header.setObjectName("SectionTitle")
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(380)
        scroll.setMaximumHeight(540)
        body = QWidget()
        body.setObjectName("HelpBody")
        body.setStyleSheet("#HelpBody { background: transparent; }")
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)

        tour_box, tour_lay = _group("Recorrido por la aplicación",
                                    "Te enseñamos dónde está cada cosa en menos de un minuto.")
        self.btn_tour = _button("Ver el recorrido")
        self.btn_tour.clicked.connect(self._tour)
        tour_lay.addWidget(self.btn_tour, alignment=Qt.AlignLeft)
        root.addWidget(tour_box)

        keys_box, keys_lay = _group("Atajos de teclado")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        for i, (key, text) in enumerate(SHORTCUTS):
            k = QLabel(key)
            k.setStyleSheet("font-weight: 700; background: transparent;")
            t = QLabel(text)
            t.setObjectName("SettingsHint")
            t.setWordWrap(True)
            grid.addWidget(k, i, 0)
            grid.addWidget(t, i, 1)
        grid.setColumnStretch(1, 1)
        keys_lay.addLayout(grid)
        root.addWidget(keys_box)

        self.updates_box, self.updates_lay = _group("Actualizaciones")
        self.updates_box.setVisible(False)       # lo rellena la ventana principal cuando hay servicio de actualizaciones
        root.addWidget(self.updates_box)

        help_box, help_lay = _group(
            "¿Algo no va bien?",
            "El informe no incluye tus canciones, listas ni datos personales: solo versiones y los últimos avisos.")
        row = QHBoxLayout()
        self.btn_report = _button("Copiar informe de problemas")
        self.btn_report.clicked.connect(self._report)
        self.btn_repair = _button("Reparar la aplicación")
        self.btn_repair.setToolTip("Vacía las cachés que se reconstruyen solas. No toca tu música, listas ni letras.")
        self.btn_repair.clicked.connect(self._repair)
        row.addWidget(self.btn_report)
        row.addWidget(self.btn_repair)
        row.addStretch()
        help_lay.addLayout(row)
        root.addWidget(help_box)
        root.addStretch(1)

        footer = QHBoxLayout()
        v = QLabel(f"Descargador de Música · versión {__version__}")
        v.setObjectName("SettingsHint")
        footer.addWidget(v)
        footer.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.setObjectName("GiantActionBtn")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        outer.addLayout(footer)

    def _tour(self):
        self.accept()
        self.window_ref.start_tour()

    def _report(self):
        QApplication.clipboard().setText(diagnostics_service.build_report())
        self.window_ref.notify("Informe copiado. Pégalo donde te lo pidan (no lleva datos personales).")

    def _repair(self):
        if not ask_confirm(self, "Reparar la aplicación",
                           "Se vaciarán las cachés (imágenes, copias del ecualizador y datos de la biblioteca) y se volverán "
                           "a crear solas. Tu música, listas, favoritos y letras no se tocan. ¿Continuar?", ok="Reparar"):
            return
        freed = diagnostics_service.repair_caches()
        self.window_ref.notify(f"Listo: se liberaron {storage_service.format_bytes(freed)}")
        self.window_ref.invalidate_library()
        self.window_ref.rescan_library()
