THEME_CONFIGS = {
    "spotify": {
        "name": "Verde clásico",
        "accent": "#1ED760",
        "accent_hover": "#22E567",
        "bg_main": "#121212",
        "bg_card": "#181818",
        "border": "#282828"
    },
    "midnight": {
        "name": "Azul noche",
        "accent": "#2979FF",
        "accent_hover": "#448AFF",
        "bg_main": "#0A1128",
        "bg_card": "#0F1A3C",
        "border": "#1C2D5A"
    },
    "cyberpunk": {
        "name": "Violeta",
        "accent": "#BB86FC",
        "accent_hover": "#D7B3FF",
        "bg_main": "#130A24",
        "bg_card": "#1E1138",
        "border": "#311E56"
    },
    "rose": {
        "name": "Rosa",
        "accent": "#FF4D8D", "accent_hover": "#FF73A6",
        "bg_main": "#160D12", "bg_card": "#20131A", "border": "#33202B"
    },
    "sunset": {
        "name": "Naranja",
        "accent": "#FF8A3D", "accent_hover": "#FFA166",
        "bg_main": "#150F0A", "bg_card": "#1F1610", "border": "#35251A"
    },
    "ruby": {
        "name": "Rojo",
        "accent": "#FF4B55", "accent_hover": "#FF6F77",
        "bg_main": "#150B0C", "bg_card": "#201214", "border": "#361E21"
    },
    "ocean": {
        "name": "Turquesa",
        "accent": "#19D3C5", "accent_hover": "#4DE0D5",
        "bg_main": "#0A1514", "bg_card": "#102120", "border": "#1B3836"
    },
    "gold": {
        "name": "Dorado",
        "accent": "#F5C542", "accent_hover": "#F8D36B",
        "bg_main": "#14120A", "bg_card": "#1E1B10", "border": "#353018"
    },
    "lime": {
        "name": "Lima",
        "accent": "#B6F23C", "accent_hover": "#C9F76A",
        "bg_main": "#11140A", "bg_card": "#181D0F", "border": "#2B3318"
    },
    "sky": {
        "name": "Celeste",
        "accent": "#4FC3F7", "accent_hover": "#7DD3F9",
        "bg_main": "#0A1219", "bg_card": "#101B25", "border": "#1D3043"
    },
    "graphite": {
        "name": "Grafito",
        "accent": "#E8E8E8", "accent_hover": "#F4F4F4",
        "bg_main": "#0E0E0E", "bg_card": "#171717", "border": "#2D2D2D"
    },
    "emerald": {
        "name": "Esmeralda",
        "accent": "#00E676",
        "accent_hover": "#33EB8F",
        "bg_main": "#141715",
        "bg_card": "#1C211E",
        "border": "#28312C"
    }
}


BASE_STYLE = """
/* DARK SOFT THEME */

QMainWindow {
    background-color: #050505;
    color: #FFFFFF;
    font-family: 'Poppins', 'Segoe UI', system-ui, sans-serif;
}

QWidget {
    font-family: 'Poppins', 'Segoe UI', system-ui, sans-serif;
    color: #FFFFFF;
}

/* SIDEBAR */
#Sidebar {
    background-color: transparent;
    border: none;
}

/* PANELES REDONDEADOS (como Spotify) */
#SidePanel, #ContentPanel {
    background-color: #121212;
    border-radius: 14px;
}
#ContentPanel {
    border: none;
}

QFrame#SideListItem {
    background-color: transparent;
    border-radius: 10px;
}
QFrame#SideListItem:hover {
    background-color: rgba(255, 255, 255, 0.14);
}
QLabel#SideItemTitle {
    font-size: 13px;
    font-weight: 600;
    color: #FFFFFF;
    background: transparent;
}
QLabel#SideItemSub {
    font-size: 11px;
    color: #B3B3B3;
    background: transparent;
}

/* BARRA SUPERIOR */
QLabel#BrandLabel {
    font-size: 15px;
    font-weight: 700;
    color: #FFFFFF;
}
#TopBar {
    background: transparent;
}
QLineEdit#TopSearch {
    background-color: #242424;
    color: #FFFFFF;
    font-size: 13px;
    padding: 8px 16px;
    border-radius: 22px;
    border: 2px solid transparent;
}
QLineEdit#TopSearch:hover {
    background-color: #2C2C2C;
}
QLineEdit#TopSearch:focus {
    border: 2px solid #FFFFFF;
    background-color: #2C2C2C;
}
QPushButton#TopIconBtn {
    background-color: #242424;
    border: none;
    border-radius: 22px;
    padding: 0px;
    min-width: 44px;
    max-width: 44px;
    min-height: 44px;
    max-height: 44px;
}
QPushButton#TopIconBtn:hover {
    background-color: #333333;
}
QPushButton#TopPillBtn {
    background-color: #242424;
    color: #FFFFFF;
    border: none;
    border-radius: 20px;
    min-height: 40px;
    max-height: 40px;
    padding: 0px 18px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#TopPillBtn:hover {
    background-color: #333333;
}
QPushButton#TopPillBtn[busy="true"] {
    background-color: #1ED760;
    color: #000000;
}
QLabel#TopInfo {
    font-size: 12px;
    color: #B3B3B3;
    padding-right: 6px;
}

/* FILAS DE CANCIÓN ESTILO SPOTIFY */
QFrame#TrackRow {
    background-color: transparent;
    border-radius: 8px;
}
QFrame#TrackRow:hover {
    background-color: rgba(255, 255, 255, 0.10);
}
QFrame#TrackRow[selected="true"] {
    background-color: rgba(255, 255, 255, 0.20);
}
QLabel#RowIndex {
    color: #B3B3B3;
    font-size: 14px;
    background: transparent;
}

/* PANEL «EN REPRODUCCIÓN» */
QLabel#PanelTitle {
    font-size: 15px;
    font-weight: 700;
    color: #FFFFFF;
}
QLabel#PanelHeading {
    font-size: 15px;
    font-weight: 700;
    color: #FFFFFF;
    background: transparent;
}
QLabel#PanelArtistLink {
    font-size: 14px;
    color: #B3B3B3;
    background: transparent;
}
QLabel#PanelArtistLink:hover {
    color: #FFFFFF;
}
QFrame#SavePopup {
    background-color: #282828;
    border: 1px solid #3A3A3A;
    border-radius: 12px;
}
QFrame#SaveRow {
    background: transparent;
    border-radius: 8px;
}
QFrame#SaveRow:hover {
    background-color: rgba(255, 255, 255, 0.10);
}
QFrame#PanelCard {
    background-color: #1A1A1A;
    border-radius: 12px;
}
QPushButton#LinkBtn {
    background: transparent;
    border: none;
    color: #B3B3B3;
    font-size: 12px;
    font-weight: 700;
    padding: 4px 6px;
    border-radius: 6px;
}
QPushButton#LinkBtn:hover {
    color: #FFFFFF;
}

/* COLUMNAS Y ORDEN DE LAS LISTAS */
QFrame#ColumnHeader {
    background: transparent;
    border: none;
    border-bottom: 1px solid #282828;
}
QPushButton#ColumnBtn {
    background: transparent;
    color: #B3B3B3;
    border: none;
    border-radius: 0px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-align: left;
    padding: 6px 0px;
}
QPushButton#ColumnBtn:hover {
    color: #FFFFFF;
}
QPushButton#SortBtn {
    background: transparent;
    color: #B3B3B3;
    border: none;
    border-radius: 16px;
    min-height: 32px;
    max-height: 32px;
    padding: 0px 12px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#SortBtn:hover {
    color: #FFFFFF;
    background-color: rgba(255, 255, 255, 0.08);
}

/* FLECHAS DE LOS CARRUSELES */
QPushButton#ArrowBtn {
    background-color: rgba(255, 255, 255, 0.08);
    border: none;
    border-radius: 16px;
    padding: 0px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
}
QPushButton#ArrowBtn:hover {
    background-color: rgba(255, 255, 255, 0.18);
}
QPushButton#ArrowBtn:disabled {
    background-color: rgba(255, 255, 255, 0.03);
}

/* FILTROS DE LA BIBLIOTECA */
QPushButton#ChipBtn {
    background-color: #242424;
    color: #FFFFFF;
    border: none;
    border-radius: 14px;
    min-height: 28px;
    max-height: 28px;
    padding: 0px 14px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#ChipBtn:hover {
    background-color: #333333;
}
QPushButton#ChipBtn:checked {
    background-color: #FFFFFF;
    color: #000000;
}

/* BOTÓN DE REPRODUCIR SOBRE LAS PORTADAS */
QPushButton#TilePlayBtn {
    background-color: #1ED760;
    border: none;
    border-radius: 22px;
    padding: 0px;
    min-width: 44px;
    max-width: 44px;
    min-height: 44px;
    max-height: 44px;
}
QPushButton#TilePlayBtn:hover {
    background-color: #1FDF64;
}

/* ACCESOS RÁPIDOS DE INICIO */
QFrame#QuickTile {
    background-color: rgba(255, 255, 255, 0.07);
    border-radius: 8px;
}
QFrame#QuickTile:hover {
    background-color: rgba(255, 255, 255, 0.24);
}

/* BOTÓN SEGUIR */
QPushButton#FollowBtn {
    background-color: transparent;
    color: #FFFFFF;
    border: 1px solid #727272;
    border-radius: 18px;
    min-height: 36px;
    max-height: 36px;
    padding: 0px 22px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#FollowBtn:hover {
    border: 1px solid #FFFFFF;
}
QPushButton#FollowBtn:checked {
    border: 1px solid #1ED760;
    color: #1ED760;
}

/* PANEL DE DESCARGAS */
#DownloadsPanel {
    background-color: #181818;
    border: 1px solid #333333;
    border-radius: 14px;
}

/* VENTANAS INTERNAS (se muestran dentro de la aplicación) */
QFrame#InlineDialog {
    background-color: #181818;
    border: 1px solid #333333;
    border-radius: 18px;
}

/* DIÁLOGOS */
QLabel#DialogBody {
    font-size: 14px;
    color: #D0D0D0;
}
QPushButton#DangerBtn {
    background-color: #E5484D;
    color: #FFFFFF;
    border: none;
    border-radius: 22px;
    min-height: 44px;
    max-height: 44px;
    padding: 0px 28px;
    font-weight: bold;
}
QPushButton#DangerBtn:hover {
    background-color: #F0666B;
}

/* BOTONES SIDEBAR */
QPushButton#SidebarBtn {
    background-color: transparent;
    color: #B3B3B3;
    font-size: 14px;
    font-weight: 600;
    text-align: left;
    padding: 10px 14px;
    border: none;
    border-radius: 8px;
}
QPushButton#SidebarBtn:hover {
    background-color: #1A1A1A;
    color: #FFFFFF;
}
QPushButton#SidebarBtn:checked {
    background-color: #242424;
    color: #1ED760;
}

QPushButton#SidebarSecondaryBtn {
    background-color: #181818;
    color: #A0A0A0;
    font-size: 13px;
    font-weight: 500;
    text-align: left;
    padding: 8px 12px;
    border: 1px solid #2A2A2A;
    border-radius: 6px;
}
QPushButton#SidebarSecondaryBtn:hover {
    background-color: #222222;
    color: #FFFFFF;
    border-color: #3A3A3A;
}

/* BOTONES PRINCIPALES */
QPushButton {
    background-color: #1E1E1E;
    color: #FFFFFF;
    font-size: 14px;
    font-weight: bold;
    border-radius: 20px;
    padding: 10px 20px;
    border: 1px solid #333333;
}
QPushButton:hover {
    background-color: #2A2A2A;
    border: 1px solid #444444;
}
QPushButton:pressed {
    background-color: #000000;
}

/* BOTÓN DESCARGAR GIGANTE EN ÁREA CENTRAL */
QPushButton#GiantActionBtn {
    background-color: #FFFFFF;
    color: #000000;
    font-size: 14px;
    font-weight: bold;
    border-radius: 22px;
    padding: 0px 28px;
    min-height: 44px;
    max-height: 44px;
    border: none;
}
QPushButton#GiantActionBtn:hover {
    background-color: #E5E5E5;
}

QPushButton#DownloadedBtn {
    background-color: transparent;
    color: #1ED760;
    border: 1px solid #1ED760;
    font-weight: bold;
}
QPushButton#DownloadedBtn:hover {
    background-color: rgba(30, 215, 96, 0.12);
}

QPushButton#PreviewBtn {
    background-color: transparent;
    border: 1px solid #727272;
    color: #FFFFFF;
}
QPushButton#DownloadBtn, QPushButton#DownloadedBtn {
    border-radius: 18px;
    min-height: 36px;
    max-height: 36px;
    padding: 0px 16px;
    font-size: 13px;
}
QPushButton#PreviewBtn:hover {
    border-color: #FFFFFF;
    background-color: rgba(255, 255, 255, 0.05);
}

QPushButton#DownloadBtn {
    background-color: #1ED760;
    color: #000000;
    border: none;
}
QPushButton#DownloadBtn:hover {
    background-color: #1FDF64;
}

/* CAMPO DE ENTRADA / BÚSQUEDA GIGANTE */
QLineEdit#GiantSearchInput {
    background-color: #1E1E1E;
    color: #FFFFFF;
    font-size: 16px;
    padding: 14px 22px;
    border-radius: 28px;
    border: 1px solid #333333;
}
QLineEdit#GiantSearchInput:focus {
    border: 1px solid #FFFFFF;
    background-color: #242424;
}

/* COMBOBOX (CALIDAD DE AUDIO) */
QComboBox {
    background-color: #1E1E1E;
    color: #E0E0E0;
    font-size: 13px;
    font-weight: 500;
    padding: 6px 12px;
    border-radius: 10px;
    border: 1px solid #333333;
}
QComboBox:hover {
    border: 1px solid #555555;
    background-color: #262626;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #1E1E1E;
    color: #FFFFFF;
    selection-background-color: #282828;
    selection-color: #1ED760;
    border: 1px solid #333333;
    border-radius: 6px;
    padding: 4px;
}

/* TARJETA DE CANCIÓN */
#ResultCard {
    background-color: transparent;
    border-radius: 8px;
    border: none;
}
#ResultCard:hover {
    background-color: rgba(255, 255, 255, 0.07);
}

QPushButton#RoundPlayBtn {
    background-color: #FFFFFF;
    border: none;
    border-radius: 19px;
    padding: 0px;
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
}
QPushButton#RoundPlayBtn:hover {
    background-color: #1ED760;
}

QPushButton#IconBtn {
    background-color: transparent;
    border: none;
    border-radius: 15px;
    padding: 0px;
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
}
QPushButton#IconBtn:hover {
    background-color: rgba(255, 255, 255, 0.12);
}

#SectionTitle {
    font-size: 22px;
    font-weight: bold;
    color: #FFFFFF;
}
#SectionSubtitle {
    font-size: 13px;
    color: #B3B3B3;
}

/* TARJETAS DE CUADRÍCULA (HOME) */
#CoverCard {
    background-color: #181818;
    border-radius: 10px;
    border: 1px solid transparent;
}
#CoverCard:hover {
    background-color: #2A2A2A;
    border: 1px solid rgba(255, 255, 255, 0.18);
}
#CoverTitle {
    font-size: 14px;
    font-weight: bold;
    color: #FFFFFF;
}
#CoverSub {
    font-size: 12px;
    color: #B3B3B3;
}

/* VENTANA DE AJUSTES */
#SettingsGroup {
    background-color: #181818;
    border-radius: 10px;
    border: 1px solid #282828;
}
#SettingsLabel {
    font-size: 13px;
    font-weight: bold;
    color: #FFFFFF;
}
#SettingsHint {
    font-size: 11px;
    color: #B3B3B3;
}

#SongTitle {
    font-size: 16px;
    font-weight: bold;
    color: #FFFFFF;
}

#ArtistName {
    font-size: 14px;
    color: #B3B3B3;
}

#DurationBadge {
    font-size: 12px;
    color: #B3B3B3;
    background-color: #242424;
    padding: 4px 8px;
    border-radius: 6px;
}

#StatusDetail {
    font-size: 13px;
    color: #1ED760;
}

/* BARRA DE PROGRESO */
QProgressBar {
    background-color: #282828;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #1ED760;
    border-radius: 4px;
}

/* ÁREA DESPLAZABLE */
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}
QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background-color: #444444;
    border-radius: 5px;
    min-height: 30px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background-color: #777777;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

/* REPRODUCTOR FLOTANTE / INFERIOR */
#PlayerBar {
    background-color: transparent;
    border: none;
}

#PlayerTitle {
    font-size: 14px;
    font-weight: bold;
    color: #FFFFFF;
}
#PlayerArtist {
    font-size: 12px;
    color: #B3B3B3;
}
#PlayerStatus {
    font-size: 12px;
    color: #B3B3B3;
}

QPushButton#PlayPauseBtn {
    background-color: #FFFFFF;
    color: #000000;
    border-radius: 20px;
    padding: 0px;
    min-width: 40px;
    min-height: 40px;
    border: none;
}
QPushButton#PlayPauseBtn:hover {
    background-color: #E5E5E5;
}

QPushButton#ControlBtn {
    background-color: transparent;
    border: none;
    color: #B3B3B3;
    padding: 4px;
    border-radius: 16px;
    min-width: 32px;
    min-height: 32px;
}
QPushButton#ControlBtn:hover {
    color: #FFFFFF;
    background-color: rgba(255, 255, 255, 0.08);
}
QPushButton#ControlBtn:checked {
    background-color: rgba(30, 215, 96, 0.15);
}

/* SLIDER DE VOLUMEN Y REPRODUCCIÓN */
QSlider {
    background: transparent;
    max-height: 16px;
}
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background: #3E3E3E;
    border-radius: 2px;
    margin-top: 6px;
    margin-bottom: 6px;
}
QSlider::sub-page:horizontal {
    background: #FFFFFF;
    border-radius: 2px;
    margin-top: 6px;
    margin-bottom: 6px;
}
QSlider::add-page:horizontal {
    background: #3E3E3E;
    border-radius: 2px;
    margin-top: 6px;
    margin-bottom: 6px;
}
QSlider::handle:horizontal {
    background: #FFFFFF;
    width: 12px;
    height: 12px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 6px;
}
QSlider::sub-page:horizontal:hover {
    background: #1ED760;
}
QSlider::handle:horizontal:hover {
    background: #FFFFFF;
}

/* SIDEBAR TREEVIEW */
QTreeView {
    background-color: transparent;
    border: none;
    outline: 0;
    color: #B3B3B3;
    font-size: 13px;
    font-weight: 500;
}
QTreeView::item {
    padding: 6px 4px;
    background-color: transparent;
    border: none;
    border-radius: 4px;
}
QTreeView::item:hover {
    background-color: #1A1A1A;
    color: #FFFFFF;
}
QTreeView::item:selected {
    background-color: #222222;
    color: #1ED760;
    font-weight: bold;
}
QTreeView::item:selected:!active {
    background-color: #222222;
    color: #1ED760;
    font-weight: bold;
}
QTreeView::branch {
    background-color: transparent;
    border: none;
}

QTreeView QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}
QTreeView QScrollBar::handle:vertical {
    background: #444444;
    min-height: 20px;
    border-radius: 3px;
}

/* MENÚ CONTEXTUAL */
QMenu {
    background-color: #1A1A1A;
    color: #FFFFFF;
    border: 1px solid #333333;
    border-radius: 12px;
    padding: 8px 4px;
    font-size: 13px;
}
QMenu::item {
    padding: 8px 24px 8px 16px;
    border-radius: 4px;
    margin: 2px 6px;
    background-color: transparent;
}
QMenu::item:selected {
    background-color: #2A2A2A;
    color: #1ED760;
}
QMenu::separator {
    height: 1px;
    background-color: #333333;
    margin: 6px 0px;
}

/* CAJA NUMÉRICA Y CASILLAS */
QSpinBox {
    background-color: #1E1E1E;
    color: #FFFFFF;
    border: 1px solid #333333;
    border-radius: 6px;
    padding: 4px 8px;
    min-width: 48px;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 0px;
    border: none;
}
QCheckBox {
    color: #E0E0E0;
    font-size: 13px;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #727272;
    background-color: transparent;
}
QCheckBox::indicator:checked {
    background-color: #1ED760;
    border-color: #1ED760;
    image: url(assets/icons/check_black.svg);
}

/* BOTÓN GRANDE DE REPRODUCIR LISTA */
QPushButton#BigPlayBtn {
    background-color: #1ED760;
    border: none;
    border-radius: 28px;
    padding: 0px;
    min-width: 56px;
    max-width: 56px;
    min-height: 56px;
    max-height: 56px;
}
QPushButton#BigPlayBtn:hover {
    background-color: #1FDF64;
}
QPushButton#BigPlayBtn:disabled {
    background-color: #333333;
}

/* PESTAÑAS (Todas / Descargadas / Sin descargar) */
QPushButton#TabBtn {
    background-color: #242424;
    color: #FFFFFF;
    border: none;
    border-radius: 17px;
    min-height: 34px;
    max-height: 34px;
    padding: 0px 16px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#TabBtn:hover {
    background-color: #333333;
}
QPushButton#TabBtn:checked {
    background-color: #FFFFFF;
    color: #000000;
}

/* LISTAS Y CASILLAS DE ELEGIR CANCIONES */
QListWidget {
    background-color: #181818;
    border: 1px solid #282828;
    border-radius: 10px;
    padding: 6px;
    outline: 0;
}
QListWidget::item {
    padding: 8px 6px;
    border-radius: 6px;
    color: #E0E0E0;
}
QListWidget::item:hover {
    background-color: #242424;
}
QListWidget::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #727272;
}
QListWidget::indicator:checked {
    background-color: #1ED760;
    border-color: #1ED760;
    image: url(assets/icons/check_black.svg);
}

/* MUESTRAS DE COLOR (AJUSTES) */
QPushButton#Swatch {
    border-radius: 18px;
    padding: 0px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    border: 2px solid transparent;
}
QPushButton#Swatch:hover {
    border: 2px solid rgba(255, 255, 255, 0.6);
}
QPushButton#Swatch:checked {
    border: 3px solid #FFFFFF;
}

/* TOOLTIPS */
QToolTip {
    background-color: #222222;
    color: #FFFFFF;
    border: 1px solid #444444;
    border-radius: 6px;
    padding: 6px;
    font-size: 12px;
}

/* BANNER DE DESCARGA EN LOTE / PLAYLIST */
#BatchBanner {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a2a1f, stop:1 #141e17);
    border: 1px solid #1ED760;
    border-radius: 12px;
    padding: 12px 18px;
}

QPushButton#BatchDownloadBtn {
    background-color: #1ED760;
    color: #000000;
    font-weight: bold;
    font-size: 14px;
    border-radius: 20px;
    min-height: 40px;
    max-height: 40px;
    padding: 0px 24px;
    border: none;
}
QPushButton#BatchDownloadBtn:hover {
    background-color: #22ee6c;
}

/* MODAL DE LETRAS / KARAOKE */
#LyricsDialog {
    background-color: #121212;
}

#LyricLineActive {
    color: #1ED760;
    font-size: 20px;
    font-weight: bold;
    padding: 10px 0px;
}

#LyricLineInactive {
    color: #666666;
    font-size: 15px;
    font-weight: 500;
    padding: 6px 0px;
}
#LyricLineInactive:hover {
    color: #B3B3B3;
}

/* FILTRO DE BIBLIOTECA */
QLineEdit#SidebarFilterInput {
    background-color: #1A1A1A;
    color: #FFFFFF;
    font-size: 12px;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid #2A2A2A;
}
QLineEdit#SidebarFilterInput:focus {
    border: 1px solid #1ED760;
}

/* DIÁLOGO DE METADATOS */
QDialog {
    background-color: #181818;
    color: #FFFFFF;
}
QLabel#DialogHeader {
    font-size: 18px;
    font-weight: bold;
    color: #FFFFFF;
}
QLineEdit#DialogInput {
    background-color: #242424;
    color: #FFFFFF;
    font-size: 13px;
    padding: 8px 12px;
    border-radius: 6px;
    border: 1px solid #383838;
}
QLineEdit#DialogInput:focus {
    border: 1px solid #1ED760;
}
"""


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def get_theme_stylesheet(theme_key: str = "spotify") -> str:
    cfg = THEME_CONFIGS.get(theme_key, THEME_CONFIGS["spotify"])
    from config import BASE_DIR
    style = BASE_STYLE.replace("url(assets/", f"url({BASE_DIR.as_posix()}/assets/")
    if theme_key != "spotify":
        style = (style
            .replace("#1ED760", cfg["accent"])
            .replace("#1FDF64", cfg["accent_hover"])
            .replace("#22ee6c", cfg["accent_hover"])
            .replace("#121212", cfg["bg_main"])
            .replace("#181818", cfg["bg_card"])
            .replace("#282828", cfg["border"]))
    from PySide6.QtGui import QColor
    style = style.replace("#050505", QColor(cfg["bg_main"]).darker(260).name())
    r, g, b = _hex_to_rgb(cfg["accent"])
    style = style.replace("30, 215, 96", f"{r}, {g}, {b}")
    return style


MAIN_STYLE = get_theme_stylesheet("spotify")

_active_theme = "spotify"


def set_active_theme(theme_key: str):
    """Registra el tema activo para que los estilos en línea puedan consultar sus colores."""
    global _active_theme
    _active_theme = theme_key if theme_key in THEME_CONFIGS else "spotify"


def theme_color(name: str) -> str:
    """Color del tema activo: 'accent', 'accent_hover', 'bg_main', 'bg_card' o 'border'."""
    return THEME_CONFIGS[_active_theme][name]


def accent() -> str:
    return theme_color("accent")


# ---------------------------------------------------------------------------
# Repintado de estilos en línea al cambiar de tema
# ---------------------------------------------------------------------------
import re as _re

_COLOR_KEYS = ("accent", "accent_hover", "bg_main", "bg_card", "border")
_EXTRA_SOURCES = {"accent_hover": ["#1FDF64", "#22ee6c"]}


def retheme_stylesheet(qss: str, target_key: str) -> str:
    """Sustituye en `qss` los colores de cualquier otro tema por los del tema `target_key`."""
    target = THEME_CONFIGS.get(target_key, THEME_CONFIGS["spotify"])
    mapping = {}
    for key, cfg in THEME_CONFIGS.items():
        if key == target_key:
            continue
        for ck in _COLOR_KEYS:
            mapping[cfg[ck].lower()] = target[ck]
            for extra in _EXTRA_SOURCES.get(ck, []) if key == "spotify" else []:
                mapping[extra.lower()] = target[ck]
    # el tema objetivo no debe volver a transformarse
    for ck in _COLOR_KEYS:
        mapping.pop(target[ck].lower(), None)
    if not mapping:
        return qss
    pattern = _re.compile("|".join(_re.escape(c) for c in mapping), _re.IGNORECASE)
    return pattern.sub(lambda m: mapping[m.group(0).lower()], qss)
