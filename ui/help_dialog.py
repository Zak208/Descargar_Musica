"""Ventana de Ayuda: recorrido, atajos de teclado, informe de problemas y reparación."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGridLayout, QApplication, QScrollArea, QWidget, QCheckBox,
    QProgressBar
)

from config import load_settings, save_settings

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
    ("Ctrl + ↑  ↓", "Subir o bajar el volumen"),
    ("F11", "Pantalla completa «Ahora suena» con la portada y la letra (Esc para salir)"),
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

        self.updates_box, upd = _group(
            "Actualizaciones",
            "El motor de descargas (yt-dlp) se actualiza por separado: así las descargas siguen funcionando cuando "
            "YouTube cambia algo, sin esperar a una versión nueva del programa.")
        self.lbl_app = QLabel("")
        self.lbl_app.setObjectName("SettingsHint")
        self.lbl_app.setWordWrap(True)
        upd.addWidget(self.lbl_app)
        self.lbl_engine = QLabel("")
        self.lbl_engine.setObjectName("SettingsHint")
        self.lbl_engine.setWordWrap(True)
        upd.addWidget(self.lbl_engine)
        self.update_progress = QProgressBar()
        self.update_progress.setTextVisible(False)
        self.update_progress.setFixedHeight(6)
        self.update_progress.setVisible(False)
        upd.addWidget(self.update_progress)
        urow = QHBoxLayout()
        self.btn_check = _button("Buscar actualizaciones")
        self.btn_check.clicked.connect(lambda: self.window_ref.check_updates(manual=True))
        self.btn_engine = _button("Actualizar el motor de descargas")
        self.btn_engine.clicked.connect(lambda: self.window_ref.update_engine())
        self.btn_engine.setVisible(False)
        self.btn_app = _button("Ver la versión nueva")
        self.btn_app.clicked.connect(self.window_ref.open_app_releases)
        self.btn_app.setVisible(False)
        urow.addWidget(self.btn_check)
        urow.addWidget(self.btn_engine)
        urow.addWidget(self.btn_app)
        urow.addStretch()
        upd.addLayout(urow)
        self.chk_auto_engine = QCheckBox("Mantener el motor de descargas al día automáticamente")
        self.chk_auto_engine.setChecked(bool(load_settings().get("ytdlp_auto_update", True)))
        self.chk_auto_engine.toggled.connect(lambda on: self._save("ytdlp_auto_update", on))
        upd.addWidget(self.chk_auto_engine)
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

    @staticmethod
    def _save(name: str, value):
        settings = load_settings()
        settings[name] = bool(value)
        save_settings(settings)

    def refresh_updates(self):
        """Pone al día los textos de la parte de actualizaciones."""
        from services import ytdlp_loader
        self.lbl_app.setText(f"Aplicación: versión {__version__}")
        self.lbl_engine.setText(f"Motor de descargas (yt-dlp): versión {ytdlp_loader.active_version()}")

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
