"""Barra lateral estilo Spotify: panel de navegación y panel 'Tu biblioteca' con las portadas de tus listas."""

from PySide6.QtCore import Qt, QSize, Signal, QVariantAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea, QWidget
)

from ui.controls import CoverLabel
from ui.covers import list_cover_pixmap
from ui.icons import icon
from ui.settings_dialog import SettingsDialog
from ui.widgets import ElidedLabel
from ui.pages import Page

SIDEBAR_WIDTH = 300
SIDEBAR_COMPACT_WIDTH = 76          # plegada: solo iconos y portadas
THUMB = 48


def nav_button(text: str, icon_name: str, slot) -> QPushButton:
    b = QPushButton(" " + text)
    b.setProperty("fullText", " " + text)
    b.setProperty("shortName", text)
    b.setIcon(icon(icon_name))
    b.setIconSize(QSize(20, 20))
    b.setObjectName("SidebarBtn")
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(slot)
    return b


class SideListItem(QFrame):
    """Fila de la biblioteca: portada, nombre y tipo de lista (como en Spotify)."""
    clicked = Signal()
    context_requested = Signal(object)
    track_dropped = Signal(object)       # canciones (lista) arrastradas y soltadas sobre esta lista

    def __init__(self, kind: str, list_id: str, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setObjectName("SideListItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.accepts_tracks = kind in ("playlist", "favorites")
        self.setAcceptDrops(self.accepts_tracks)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(THUMB + 14)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 7, 8, 7)
        lay.setSpacing(12)

        cover = CoverLabel(radius=8 if kind != "artist" else THUMB // 2, placeholder="#00000000")
        cover.setFixedSize(THUMB, THUMB)
        cover.setPixmap(list_cover_pixmap(kind, list_id, THUMB, 8))
        self.cover = cover
        lay.addWidget(cover)

        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.setAlignment(Qt.AlignVCenter)
        name = ElidedLabel(title)
        name.setObjectName("SideItemTitle")
        name.setToolTip(title)
        sub = ElidedLabel(subtitle)
        sub.setObjectName("SideItemSub")
        texts.addWidget(name)
        texts.addWidget(sub)
        lay.addLayout(texts, stretch=1)
        self._lay, self._name, self._sub, self._title, self._subtitle = lay, name, sub, title, subtitle

    def set_compact(self, compact: bool):
        """Plegada: solo la portada, centrada; el nombre sale en una burbuja al pasar el ratón."""
        self._name.setVisible(not compact)
        self._sub.setVisible(not compact)
        self._lay.setContentsMargins(0, 7, 0, 7) if compact else self._lay.setContentsMargins(8, 7, 8, 7)
        self._lay.setAlignment(self.cover, Qt.AlignHCenter if compact else Qt.AlignLeft)
        self.setToolTip(f"{self._title}\n{self._subtitle}" if compact else "")

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)

    def contextMenuEvent(self, ev):
        self.context_requested.emit(ev.globalPos())

    # ---- soltar canciones
    def _set_drop(self, on: bool):
        self.setProperty("drop", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, ev):
        from ui.dragdrop import TRACK_MIME
        if self.accepts_tracks and ev.mimeData().hasFormat(TRACK_MIME):
            ev.acceptProposedAction()
            self._set_drop(True)
        else:
            ev.ignore()

    def dragLeaveEvent(self, ev):
        self._set_drop(False)
        super().dragLeaveEvent(ev)

    def dropEvent(self, ev):
        from ui.dragdrop import read_dropped_tracks
        self._set_drop(False)
        infos = read_dropped_tracks(ev.mimeData())
        if infos:
            ev.acceptProposedAction()
            self.track_dropped.emit(infos)


def _panel() -> tuple:
    frame = QFrame()
    frame.setObjectName("SidePanel")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(10, 12, 10, 12)
    lay.setSpacing(2)
    return frame, lay


def build_sidebar(self):
    """Construye la barra lateral."""
    self.sidebar = QFrame()
    self.sidebar.setObjectName("Sidebar")
    self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
    outer = QVBoxLayout(self.sidebar)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(8)

    # --- Panel 1: navegación ---
    nav_panel, nav_lay = _panel()
    toggle_row = QHBoxLayout()
    toggle_row.setContentsMargins(0, 0, 0, 2)
    self.btn_sidebar_toggle = QPushButton("")
    self.btn_sidebar_toggle.setObjectName("IconBtn")
    self.btn_sidebar_toggle.setIcon(icon("chevron_left.svg", "#B3B3B3"))
    self.btn_sidebar_toggle.setIconSize(QSize(18, 18))
    self.btn_sidebar_toggle.setToolTip("Reducir la barra lateral")
    self.btn_sidebar_toggle.setCursor(Qt.PointingHandCursor)
    self.btn_sidebar_toggle.clicked.connect(self.toggle_sidebar)
    toggle_row.addStretch()
    toggle_row.addWidget(self.btn_sidebar_toggle)
    self._sidebar_toggle_row = toggle_row
    nav_lay.addLayout(toggle_row)
    self.btn_nav_home = nav_button("Inicio", "home.svg", lambda: self.switch_to_page(Page.HOME))
    self.btn_nav_downloads = nav_button("Abrir carpeta de música", "folder.svg", self.open_music_folder)
    self.btn_nav_settings = nav_button("Ajustes", "settings.svg", self.open_settings)
    self.btn_nav_help = nav_button("Ayuda", "info.svg", self.open_help)
    for b in (self.btn_nav_home, self.btn_nav_downloads, self.btn_nav_settings, self.btn_nav_help):
        nav_lay.addWidget(b)
    outer.addWidget(nav_panel)

    # --- Panel 2: tu biblioteca ---
    lib_panel, lib_lay = _panel()
    head = QHBoxLayout()
    head.setContentsMargins(0, 0, 0, 4)
    self.btn_nav_library = nav_button("Tu biblioteca", "library.svg", self.open_library)
    head.addWidget(self.btn_nav_library, stretch=1)
    btn_add = self.btn_add_list = QPushButton("")
    btn_add.setObjectName("IconBtn")
    btn_add.setIcon(icon("plus.svg", "#B3B3B3"))
    btn_add.setIconSize(QSize(18, 18))
    btn_add.setToolTip("Crear una lista nueva")
    btn_add.setCursor(Qt.PointingHandCursor)
    btn_add.clicked.connect(self.create_new_playlist_dialog)
    head.addWidget(btn_add)
    lib_lay.addLayout(head)

    # Filtros (Todo / Listas / Artistas)
    chips = QHBoxLayout()
    chips.setContentsMargins(4, 0, 0, 6)
    chips.setSpacing(6)
    self.library_chips = {}
    for key, label in (("all", "Todo"), ("lists", "Listas"), ("artists", "Artistas")):
        chip = QPushButton(label)
        chip.setObjectName("ChipBtn")
        chip.setCheckable(True)
        chip.setChecked(key == "all")
        chip.setCursor(Qt.PointingHandCursor)
        chip.clicked.connect(lambda _=False, k=key: self.set_library_filter(k))
        chips.addWidget(chip)
        self.library_chips[key] = chip
    chips.addStretch()
    lib_lay.addLayout(chips)
    self._chips_layout = chips

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lists_widget = QWidget()
    lists_widget.setObjectName("SideLists")
    lists_widget.setStyleSheet("#SideLists { background: transparent; }")
    self.playlists_container = QVBoxLayout(lists_widget)
    self.playlists_container.setContentsMargins(0, 0, 0, 0)
    self.playlists_container.setSpacing(2)
    self.playlists_container.setAlignment(Qt.AlignTop)
    scroll.setWidget(lists_widget)
    lib_lay.addWidget(scroll, stretch=1)
    self.side_hint = QLabel("Aún no sigues a ningún artista.\nEntra en el perfil de uno y pulsa «Seguir».")
    self.side_hint.setObjectName("SectionSubtitle")
    self.side_hint.setWordWrap(True)
    self.side_hint.setStyleSheet("padding: 8px 6px;")
    self.side_hint.setVisible(False)
    lib_lay.addWidget(self.side_hint)
    outer.addWidget(lib_panel, stretch=1)
    self.refresh_playlists_sidebar()

    # Ajustes (calidad, carpeta, colores...) en su propia ventana
    self.settings_dialog = SettingsDialog(self.current_theme, self)
    self.quality_combo = self.settings_dialog.quality_combo
    self.theme_combo = self.settings_dialog.theme_combo
    self.btn_change_dir = self.settings_dialog.btn_change_dir
    self.btn_format_info = self.settings_dialog.btn_format_info
    self.quality_combo.currentIndexChanged.connect(self.on_quality_changed)
    self.theme_combo.currentIndexChanged.connect(self.on_theme_changed)
    self.btn_change_dir.clicked.connect(self.choose_custom_download_dir)
    self.btn_format_info.clicked.connect(self.show_format_info_dialog)
    self.settings_dialog.chk_offline.setChecked(self.network.forced_offline)
    self.settings_dialog.chk_offline.toggled.connect(self.network.set_forced_offline)

    self.top_hbox.addWidget(self.sidebar)
    self._sidebar_compact = False
    self._sidebar_anim = QVariantAnimation(self)
    self._sidebar_anim.setDuration(180)
    self._sidebar_anim.setEasingCurve(QEasingCurve.OutCubic)
    self._sidebar_anim.valueChanged.connect(lambda v: self.sidebar.setFixedWidth(int(v)))
    self._sidebar_anim.finished.connect(self._on_sidebar_anim_finished)


class SidebarMixin:
    """Mezcla para MainWindow: plegar la barra lateral izquierda a solo iconos (y volver a abrirla)."""

    def init_sidebar_state(self):
        from config import load_settings
        self.set_sidebar_compact(bool(load_settings().get("sidebar_compact", False)), animate=False)

    def toggle_sidebar(self):
        self.set_sidebar_compact(not self._sidebar_compact)

    def set_sidebar_compact(self, compact: bool, animate: bool = True):
        from config import load_settings, save_settings
        from ui import motion
        self._sidebar_compact = compact
        settings = load_settings()
        settings["sidebar_compact"] = compact
        save_settings(settings)
        target = SIDEBAR_COMPACT_WIDTH if compact else SIDEBAR_WIDTH
        self._sidebar_anim.stop()
        if compact:
            self._apply_sidebar_widgets(True)           # primero se esconden los textos y luego se encoge
        if animate and motion.enabled() and self.isVisible():
            self._sidebar_anim.setStartValue(self.sidebar.width())
            self._sidebar_anim.setEndValue(target)
            self._sidebar_anim.start()
        else:
            self.sidebar.setFixedWidth(target)
            self._on_sidebar_anim_finished()

    def _on_sidebar_anim_finished(self):
        self._apply_sidebar_widgets(self._sidebar_compact)
        if hasattr(self, "_fit_minimum_size"):
            self._fit_minimum_size()

    def _apply_sidebar_widgets(self, compact: bool):
        """Textos de los botones, filtros y filas: completos o solo iconos (con el nombre en la burbuja de ayuda)."""
        for b in (self.btn_nav_home, self.btn_nav_downloads, self.btn_nav_settings, self.btn_nav_help, self.btn_nav_library):
            b.setText("" if compact else b.property("fullText"))
            b.setToolTip(b.property("shortName") if compact else "")
            b.setProperty("compact", compact)
            b.style().unpolish(b)
            b.style().polish(b)
        self.btn_add_list.setVisible(not compact)
        for chip in self.library_chips.values():
            chip.setVisible(not compact)
        self.btn_sidebar_toggle.setIcon(icon("chevron_right.svg" if compact else "chevron_left.svg", "#B3B3B3"))
        self.btn_sidebar_toggle.setToolTip("Ampliar la barra lateral" if compact else "Reducir la barra lateral")
        self._sidebar_toggle_row.setAlignment(self.btn_sidebar_toggle, Qt.AlignHCenter if compact else Qt.AlignRight)
        for item, _sig in self._side_items.values():
            item.set_compact(compact)
        hint = getattr(self, "side_hint", None)
        if hint is not None and compact:
            hint.setVisible(False)
