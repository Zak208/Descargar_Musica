"""Ventana de Ajustes: calidad, destino de descargas, espacio, copia de seguridad, rendimiento y tema visual."""
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGridLayout, QScrollArea, QWidget, QFileDialog
)

from config import (
    get_download_dir, get_audio_quality, get_organize_mode, load_settings, save_settings
)
from services import backup_service, m3u_service, quality, storage_service
from ui.dialogs import ask_confirm, show_message
from ui.styles import THEME_CONFIGS
from ui.icons import icon
from version import __version__
from ui.overlay import InlineDialog
from ui import motion, perf
from ui.controls import NoWheelComboBox, SegmentedControl, ToggleSwitch as QCheckBox
from ui.perf import eco, set_eco, visualizer_enabled, set_visualizer
from ui.playback_options import FADES


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


def _button(text: str, icon_name: str | None = None) -> QPushButton:
    b = QPushButton(" " + text if icon_name else text)
    b.setObjectName("SidebarSecondaryBtn")
    if icon_name:
        b.setIcon(icon(icon_name))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(36)
    return b


class SettingsDialog(InlineDialog):
    """Contenedor de los controles de ajustes. La ventana principal conecta sus señales."""

    def __init__(self, current_theme: str, parent=None):
        super().__init__(parent, auto_delete=False)
        self.window_ref = parent
        self.setWindowTitle("Ajustes")
        self.setMinimumWidth(600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 22)
        outer.setSpacing(12)

        header = QLabel("Ajustes")
        header.setObjectName("SectionTitle")
        outer.addWidget(header)

        # Los grupos van en una zona con desplazamiento: así la ventana nunca se sale de la pantalla
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(420)
        scroll.setMaximumHeight(560)
        body = QWidget()
        body.setObjectName("SettingsBody")
        body.setStyleSheet("#SettingsBody { background: transparent; }")
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)

        # --- Formato y calidad ---
        fmt_box, fmt_lay = _group(
            "Calidad de la música",
            "Si dudas, deja «Alta calidad». Verás cuánto ocupa una canción de unos 4 minutos. "
            "Sin pérdida y Estudio no suenan mejor (el audio de origen ya viene comprimido): solo ocupan más."
        )
        row = QHBoxLayout()
        self.quality_combo = NoWheelComboBox()
        for key, *_rest in quality.QUALITIES:
            self.quality_combo.addItem(quality.label(key), key)
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

        self.btn_change_dir = _button("Cambiar carpeta...", "folder.svg")
        dest_lay.addWidget(self.btn_change_dir, alignment=Qt.AlignLeft)
        org_row = QHBoxLayout()
        org_row.addWidget(QLabel("Organizar las canciones"))
        self.organize_combo = NoWheelComboBox()
        for value, text in (("flat", "Todas juntas en la carpeta (recomendado)"), ("artist", "En una carpeta por artista"),
                            ("artist_album", "Carpeta de artista y de álbum")):
            self.organize_combo.addItem(text, value)
        self.organize_combo.setCurrentIndex(max(0, self.organize_combo.findData(get_organize_mode())))
        self.organize_combo.currentIndexChanged.connect(lambda _i: self._save_value("organize", self.organize_combo.currentData()))
        org_row.addWidget(self.organize_combo, stretch=1)
        dest_lay.addLayout(org_row)
        org_hint = QLabel("Solo afecta a las canciones que descargues desde ahora; las que ya tienes no se mueven.")
        org_hint.setObjectName("SettingsHint")
        org_hint.setWordWrap(True)
        dest_lay.addWidget(org_hint)
        root.addWidget(dest_box)

        # --- Rendimiento ---
        perf_box, perf_lay = _group(
            "Rendimiento",
            "El modo ahorro reduce la memoria y el trabajo en segundo plano. Es lo mejor para ordenadores modestos. "
            "Algunos cambios se notan por completo al reiniciar la aplicación.")
        self.chk_eco = QCheckBox("Modo ahorro de recursos (recomendado)")
        self.chk_eco.setChecked(eco())
        self.chk_eco.toggled.connect(set_eco)
        perf_lay.addWidget(self.chk_eco)
        self.chk_visualizer = QCheckBox("Barras animadas junto a la canción que suena")
        self.chk_visualizer.setChecked(visualizer_enabled())
        self.chk_visualizer.toggled.connect(set_visualizer)
        perf_lay.addWidget(self.chk_visualizer)
        mot_label = QLabel("Animaciones")
        mot_label.setStyleSheet("background: transparent; margin-top: 6px;")
        perf_lay.addWidget(mot_label)
        self.motion_seg = SegmentedControl([(k, motion.LEVEL_NAMES[k]) for k in motion.LEVELS], motion.stored_level())
        self.motion_seg.changed.connect(self._motion_changed)
        perf_lay.addWidget(self.motion_seg)
        mot_hint = QLabel("«Suaves» solo anima lo que haces (apenas gasta). «Completas» añade detalles continuos. "
                          "«Ninguna» lo deja todo instantáneo. Con la batería baja se reducen solas.")
        mot_hint.setObjectName("SettingsHint")
        mot_hint.setWordWrap(True)
        perf_lay.addWidget(mot_hint)
        meter_row = QHBoxLayout()
        self.lbl_meter = QLabel("")
        self.lbl_meter.setObjectName("SettingsHint")
        meter_row.addWidget(self.lbl_meter, stretch=1)
        self.btn_calibrate = _button("Probar animaciones")
        self.btn_calibrate.setToolTip("Mide cuánto gasta tu equipo con las animaciones y elige el nivel que mejor le va")
        self.btn_calibrate.clicked.connect(self._calibrate)
        meter_row.addWidget(self.btn_calibrate)
        perf_lay.addLayout(meter_row)
        self._asking_contrast = False
        self._meter = None
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(2000)
        self._meter_timer.timeout.connect(self._update_meter)
        self.perf_extra_lay = perf_lay
        root.addWidget(perf_box)

        # --- Reproducción ---
        play_box, play_lay = _group(
            "Reproducción",
            "Estas opciones también están en el botón del reloj de la barra de reproducción.")
        self.chk_normalize = QCheckBox("Igualar el volumen entre canciones")
        self.chk_normalize.setChecked(bool(load_settings().get("normalize_volume", True)))
        self.chk_normalize.toggled.connect(lambda on: self.window_ref.set_normalize(on))
        play_lay.addWidget(self.chk_normalize)
        fade_row = QHBoxLayout()
        fade_row.addWidget(QLabel("Fundido entre canciones"))
        self.fade_combo = NoWheelComboBox()
        for seconds, text in FADES:
            self.fade_combo.addItem(text, seconds)
        self.fade_combo.setCurrentIndex(max(0, self.fade_combo.findData(int(load_settings().get("fade_seconds", 0)))))
        self.fade_combo.currentIndexChanged.connect(lambda _i: self.window_ref.set_fade_seconds(self.fade_combo.currentData()))
        fade_row.addWidget(self.fade_combo)
        fade_row.addStretch()
        play_lay.addLayout(fade_row)
        self.chk_notify = QCheckBox("Avisar al cambiar de canción")
        self.chk_notify.setChecked(bool(load_settings().get("notify_track_change", True)))
        self.chk_notify.toggled.connect(lambda on: self._save_flag("notify_track_change", on))
        play_lay.addWidget(self.chk_notify)
        self.chk_tray = QCheckBox("Al cerrar la ventana, seguir sonando en la bandeja del sistema")
        self.chk_tray.setChecked(bool(load_settings().get("close_to_tray", False)))
        self.chk_tray.toggled.connect(lambda on: self._save_flag("close_to_tray", on))
        play_lay.addWidget(self.chk_tray)
        root.addWidget(play_box)

        # --- Accesibilidad ---
        acc_box, acc_lay = _group(
            "Accesibilidad",
            "Hazlo todo más grande o con más contraste. El tamaño se aplica al reiniciar; el contraste, al instante. "
            "Con las flechas ↑ ↓, Intro y Supr puedes mover las listas sin ratón.")
        row_scale = QHBoxLayout()
        row_scale.addWidget(QLabel("Tamaño de la aplicación"))
        self.scale_combo = NoWheelComboBox()
        for label, value in (("Normal", 1.0), ("Grande", 1.15), ("Muy grande", 1.3)):
            self.scale_combo.addItem(label, value)
        current_scale = float(load_settings().get("ui_scale", 1.0) or 1.0)
        idx_scale = min(range(3), key=lambda i: abs(self.scale_combo.itemData(i) - current_scale))
        self.scale_combo.setCurrentIndex(idx_scale)
        self._scale_at_start = self.scale_combo.itemData(idx_scale)
        self.scale_combo.currentIndexChanged.connect(self._scale_changed)
        row_scale.addWidget(self.scale_combo)
        row_scale.addStretch()
        acc_lay.addLayout(row_scale)
        self.btn_restart = _button("Reiniciar para aplicar el tamaño")
        self.btn_restart.setVisible(False)
        self.btn_restart.clicked.connect(lambda: self.window_ref.restart_app())
        acc_lay.addWidget(self.btn_restart, alignment=Qt.AlignLeft)
        self.chk_contrast = QCheckBox("Alto contraste (textos y bordes más claros)")
        self.chk_contrast.setChecked(bool(load_settings().get("high_contrast", False)))
        self.chk_contrast.toggled.connect(self._contrast_toggled)
        acc_lay.addWidget(self.chk_contrast)
        root.addWidget(acc_box)

        # --- Conexión ---
        net_box, net_lay = _group(
            "Conexión",
            "Sin internet la aplicación sigue funcionando con tu música descargada y tus listas. "
            "Con el modo sin conexión puedes forzarlo para no gastar datos.")
        self.chk_offline = QCheckBox("Modo sin conexión (no usar internet)")
        net_lay.addWidget(self.chk_offline)
        self.chk_private = QCheckBox("Modo privado: no buscar letras, recomendaciones ni datos de artistas por mi cuenta")
        self.chk_private.setToolTip("Solo se usa internet cuando tú lo pides (buscar, descargar, escuchar un adelanto).")
        self.chk_private.setChecked(bool(load_settings().get("private_mode", False)))
        self.chk_private.toggled.connect(lambda on: self._save_flag("private_mode", on))
        net_lay.addWidget(self.chk_private)
        root.addWidget(net_box)

        # --- Actualizaciones ---
        upd_box, upd_lay = _group(
            "Actualizaciones",
            "La aplicación mira sola si hay una versión nueva y te lo dice con un botón azul arriba a la izquierda. "
            "Aquí puedes buscar a mano.")
        self.lbl_update_status = QLabel(f"Versión instalada: {__version__}")
        self.lbl_update_status.setObjectName("SettingsHint")
        self.lbl_update_status.setWordWrap(True)
        upd_lay.addWidget(self.lbl_update_status)
        upd_row = QHBoxLayout()
        self.btn_check_updates = _button("Buscar actualizaciones", "refresh.svg")
        self.btn_check_updates.clicked.connect(self._check_updates)
        upd_row.addWidget(self.btn_check_updates)
        upd_row.addStretch()
        upd_lay.addLayout(upd_row)
        self.chk_auto_engine = QCheckBox("Mantener el descargador de canciones (yt-dlp) al día automáticamente")
        self.chk_auto_engine.setChecked(bool(load_settings().get("ytdlp_auto_update", True)))
        self.chk_auto_engine.toggled.connect(lambda on: self._save_flag("ytdlp_auto_update", on))
        upd_lay.addWidget(self.chk_auto_engine)
        root.addWidget(upd_box)

        # --- Avanzado (YouTube) ---
        adv_box, adv_lay = _group(
            "Avanzado: acceso a YouTube",
            "Si YouTube empieza a rechazar descargas, prueba el modo automático. Las cookies del navegador sirven para vídeos "
            "con restricción de edad; solo se leen en tu equipo y nunca se guardan ni se envían a ningún otro sitio.")
        self.yt_client_combo = NoWheelComboBox()
        self.yt_client_combo.addItem("Normal (recomendado)", "android_web")
        self.yt_client_combo.addItem("Automático (que elija yt-dlp)", "auto")
        self.yt_client_combo.setCurrentIndex(max(0, self.yt_client_combo.findData(load_settings().get("yt_client", "android_web"))))
        self.yt_client_combo.currentIndexChanged.connect(lambda _i: self._save_value("yt_client", self.yt_client_combo.currentData()))
        adv_lay.addWidget(self.yt_client_combo)
        self.cookies_combo = NoWheelComboBox()
        self.cookies_combo.addItem("No usar cookies del navegador", "")
        for key, name in (("chrome", "Google Chrome"), ("edge", "Microsoft Edge"), ("firefox", "Firefox"),
                          ("brave", "Brave"), ("opera", "Opera"), ("vivaldi", "Vivaldi")):
            self.cookies_combo.addItem(f"Usar las cookies de {name}", key)
        self.cookies_combo.setCurrentIndex(max(0, self.cookies_combo.findData(load_settings().get("cookies_browser", ""))))
        self.cookies_combo.currentIndexChanged.connect(lambda _i: self._save_value("cookies_browser", self.cookies_combo.currentData()))
        adv_lay.addWidget(self.cookies_combo)
        root.addWidget(adv_box)

        # --- Espacio ---
        space_box, space_lay = _group(
            "Espacio que ocupa la aplicación",
            "Aquí puedes liberar espacio sin perder tu música, tus listas ni tus letras.")
        self.space_grid = QGridLayout()
        self.space_grid.setHorizontalSpacing(10)
        self.space_grid.setVerticalSpacing(4)
        space_lay.addLayout(self.space_grid)
        root.addWidget(space_box)

        # --- Copia de seguridad ---
        bk_box, bk_lay = _group(
            "Copia de seguridad",
            "Guarda en un archivo tus listas, favoritos, artistas que sigues, ajustes y letras. "
            "Además, la aplicación hace una copia automática cada semana.")
        bk_row = QHBoxLayout()
        self.btn_backup = _button("Guardar una copia...", "download.svg")
        self.btn_backup.clicked.connect(self.save_backup)
        self.btn_restore = _button("Restaurar una copia...", "refresh.svg")
        self.btn_restore.clicked.connect(self.restore_backup)
        bk_row.addWidget(self.btn_backup)
        bk_row.addWidget(self.btn_restore)
        bk_row.addStretch()
        bk_lay.addLayout(bk_row)
        m3u_row = QHBoxLayout()
        self.btn_export_m3u = _button("Exportar mis listas (M3U)...", "download.svg")
        self.btn_export_m3u.setToolTip("Guarda cada lista como un archivo .m3u8 que puedes abrir en casi cualquier reproductor.")
        self.btn_export_m3u.clicked.connect(self.export_m3u)
        self.btn_import_m3u = _button("Importar listas (M3U)...", "refresh.svg")
        self.btn_import_m3u.clicked.connect(self.import_m3u)
        m3u_row.addWidget(self.btn_export_m3u)
        m3u_row.addWidget(self.btn_import_m3u)
        m3u_row.addStretch()
        bk_lay.addLayout(m3u_row)
        root.addWidget(bk_box)

        # --- Apariencia ---
        look_box, look_lay = _group("Colores de la aplicación", "Elige el color principal. Se cambia al instante.")
        # El selector real es un desplegable oculto; las muestras de color lo controlan.
        self.theme_combo = NoWheelComboBox()
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
        self.chk_dynamic = QCheckBox("La barra de reproducción toma el color de la portada de cada canción")
        self.chk_dynamic.setChecked(bool(load_settings().get("dynamic_accent", False)))
        self.chk_dynamic.toggled.connect(self._dynamic_toggled)
        look_lay.addWidget(self.chk_dynamic)
        self.look_extra_lay = look_lay
        root.addWidget(look_box)
        root.addStretch(1)

        footer = QHBoxLayout()
        version_lbl = QLabel(f"Descargador de Música · versión {__version__}")
        version_lbl.setObjectName("SettingsHint")
        footer.addWidget(version_lbl)
        footer.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.setObjectName("GiantActionBtn")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        outer.addLayout(footer)

        self.refresh_space()

    def _check_updates(self):
        self.lbl_update_status.setText("Buscando…")
        self.window_ref.check_updates(manual=True)

    def set_update_status(self, text: str):
        self.lbl_update_status.setText(text)

    def _dynamic_toggled(self, on: bool):
        self._save_flag("dynamic_accent", on)
        self.window_ref._update_live_accent()

    def _contrast_toggled(self, on: bool):
        """Se aplica al instante y se pregunta «¿se ve bien?»: si nadie responde en 10 s, se deshace solo."""
        from ui.keep_change import ask_keep_change
        self.window_ref.set_high_contrast(on)
        if self._asking_contrast:
            return
        self._asking_contrast = True
        try:
            keep = ask_keep_change(self.window_ref, "Se ha " + ("activado" if on else "desactivado") + " el alto contraste.")
        finally:
            self._asking_contrast = False
        if not keep:
            self.chk_contrast.blockSignals(True)
            self.chk_contrast.setChecked(not on)
            self.chk_contrast.blockSignals(False)
            self.window_ref.set_high_contrast(not on)

    # ------------------------------------------------------- animaciones y consumo
    def _motion_changed(self, key: str):
        motion.set_level(key)
        if self.window_ref is not None and hasattr(self.window_ref, "notify"):
            self.window_ref.notify(f"Animaciones: {motion.LEVEL_NAMES[key].lower()}")

    def showEvent(self, event):
        if hasattr(self, "_meter_timer"):
            self._meter = perf.CpuMeter()
            self._update_meter()
            self._meter_timer.start()         # solo mientras esta ventana se ve
        super().showEvent(event)

    def hideEvent(self, event):
        if hasattr(self, "_meter_timer"):
            self._meter_timer.stop()
        super().hideEvent(event)

    def _update_meter(self):
        if self._meter is None:
            self._meter = perf.CpuMeter()
        cpu = self._meter.read()
        self.lbl_meter.setText(f"La aplicación está usando ahora: {cpu:.1f} % de CPU · {perf.memory_mb():.0f} MB de memoria")

    def _calibrate(self):
        from ui.calibrate import run_calibration
        self.btn_calibrate.setEnabled(False)
        self.btn_calibrate.setText("Midiendo...")

        def done(level_key: str, cpu: float):
            self.btn_calibrate.setEnabled(True)
            self.btn_calibrate.setText("Probar animaciones")
            self.motion_seg.set_current(level_key)
            if self.window_ref is not None and hasattr(self.window_ref, "notify"):
                self.window_ref.notify(f"Listo: tu equipo va bien con animaciones {motion.LEVEL_NAMES[level_key].lower()} "
                                       f"({cpu:.0f} % de CPU en la prueba)")

        run_calibration(self.window_ref, done)

    @staticmethod
    def _save_value(name: str, value):
        settings = load_settings()
        settings[name] = value
        save_settings(settings)

    @staticmethod
    def _save_flag(name: str, value: bool):
        settings = load_settings()
        settings[name] = bool(value)
        save_settings(settings)

    # ------------------------------------------------------------- tamaño
    def _scale_changed(self, _index: int):
        settings = load_settings()
        settings["ui_scale"] = float(self.scale_combo.currentData())
        save_settings(settings)
        self.btn_restart.setVisible(abs(self.scale_combo.currentData() - self._scale_at_start) > 0.01)

    # ------------------------------------------------------------- tema
    def _pick_theme(self, key: str):
        for k, sw in self.swatches.items():
            sw.setChecked(k == key)
        self.theme_name_lbl.setText(THEME_CONFIGS[key]["name"])
        idx = self.theme_combo.findData(key)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

    def refresh_download_dir(self):
        self.lbl_download_dir.setText(str(get_download_dir()))
        self.refresh_space()

    # ------------------------------------------------------------ espacio
    def refresh_space(self):
        while self.space_grid.count():
            w = self.space_grid.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        rows = storage_service.usage()
        total = sum(r["bytes"] for r in rows)
        for i, r in enumerate(rows):
            if r["bytes"] == 0 and not r["clearable"]:
                continue
            name = QLabel(r["name"])
            name.setToolTip(r["hint"])
            name.setStyleSheet("background: transparent;")
            size = QLabel(storage_service.format_bytes(r["bytes"]))
            size.setObjectName("SettingsHint")
            size.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.space_grid.addWidget(name, i, 0)
            self.space_grid.addWidget(size, i, 1)
            if r["clearable"] and r["bytes"] > 0:
                btn = _button("Liberar")
                btn.setMinimumHeight(28)
                btn.clicked.connect(lambda _=False, k=r["key"], n=r["name"]: self._free(k, n))
                self.space_grid.addWidget(btn, i, 2)
        self.space_grid.setColumnStretch(0, 1)
        n = self.space_grid.rowCount()
        tot = QLabel(f"Total: {storage_service.format_bytes(total)}")
        tot.setObjectName("SettingsHint")
        self.space_grid.addWidget(tot, n, 0, 1, 3)

    def _free(self, key: str, name: str):
        freed = storage_service.clear(key)
        if self.window_ref is not None and hasattr(self.window_ref, "notify"):
            self.window_ref.notify(f"Liberados {storage_service.format_bytes(freed)} ({name})")
            if key in ("biblioteca",):
                self.window_ref.rescan_library()
        self.refresh_space()

    # ------------------------------------------------------ copia de seguridad
    def export_m3u(self):
        folder = QFileDialog.getExistingDirectory(self, "¿Dónde guardo las listas?", str(get_download_dir()))
        if not folder:
            return
        try:
            result = m3u_service.export_all(folder)
        except Exception as e:
            show_message(self, "No se pudieron exportar las listas", str(e))
            return
        extra = f" ({result['omitidas']} sin descargar no se incluyen)" if result["omitidas"] else ""
        self.window_ref.notify(f"{result['listas']} listas exportadas con {result['canciones']} canciones{extra}")

    def import_m3u(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Elige listas M3U", str(get_download_dir()), "Listas (*.m3u *.m3u8)")
        if not paths:
            return
        result = m3u_service.import_files(paths)
        if not result["listas"]:
            show_message(self, "No se importó nada", "No se encontró ninguna canción de tu equipo en esos archivos.")
            return
        self.window_ref.refresh_playlists_sidebar()
        self.window_ref.notify(f"{result['listas']} listas importadas con {result['canciones']} canciones")

    def save_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar copia de seguridad", backup_service.default_backup_name(),
                                              "Copia de seguridad (*.zip)")
        if not path:
            return
        try:
            n = backup_service.create_backup(path)
        except Exception as e:
            show_message(self, "No se pudo guardar la copia", str(e))
            return
        self.window_ref.notify(f"Copia guardada ({n} archivos)")
        self.window_ref.celebrate("copia")

    def restore_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir una copia de seguridad", "", "Copia de seguridad (*.zip)")
        if not path:
            return
        info = backup_service.inspect_backup(path)
        if info is None:
            show_message(self, "Ese archivo no sirve", "No es una copia de seguridad de esta aplicación.")
            return
        if not ask_confirm(self, "Restaurar la copia",
                           "Se sustituirán tus listas, favoritos, artistas, ajustes y letras por los de la copia. "
                           "Antes se guarda una copia de lo que tienes ahora, por si te arrepientes.\n\n"
                           "La aplicación se reiniciará. ¿Continuar?", ok="Restaurar"):
            return
        try:
            backup_service.restore_backup(path)
        except Exception as e:
            show_message(self, "No se pudo restaurar", str(e))
            return
        self.accept()
        self.window_ref.restart_app()
