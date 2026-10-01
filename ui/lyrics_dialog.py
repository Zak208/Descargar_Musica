from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QSizePolicy
)
from services.lyrics_service import LyricsWorker
from ui.styles import accent
from ui.icons import icon

LINE_PAD = "padding: 8px 4px;"
STYLE_INACTIVE = "color: #7A7A7A; font-size: 18px; font-weight: 600; " + LINE_PAD
STYLE_PLAIN = "color: #D0D0D0; font-size: 16px; font-weight: 500; " + LINE_PAD


def style_active() -> str:
    # Mismo tamaño que las demás líneas: así el texto nunca se corta al cambiar de línea.
    return f"color: {accent()}; font-size: 18px; font-weight: 800; " + LINE_PAD


class ClickableLyricLabel(QLabel):
    def __init__(self, ms: int, text: str, on_seek_callback, parent=None):
        super().__init__(text, parent)
        self.ms = ms
        self.on_seek_callback = on_seek_callback
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(STYLE_INACTIVE)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.on_seek_callback:
            self.on_seek_callback(self.ms)
        super().mousePressEvent(ev)


class LyricsDialog(QDialog):
    def __init__(self, title: str, artist: str = "", player=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.artist = artist
        self.player = player
        self.lyrics_data = None
        self.line_widgets = []
        self.active_index = -1

        self.setWindowTitle(f"Letras: {title} - {artist}")
        self.setObjectName("LyricsDialog")
        self.setMinimumSize(540, 600)
        self.init_ui()
        self.fetch_lyrics()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Encabezado
        header_layout = QHBoxLayout()
        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        self.lbl_title = QLabel(self.title)
        self.lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #FFFFFF;")
        self.lbl_artist = QLabel(self.artist or "Artista")
        self.lbl_artist.setStyleSheet(f"font-size: 13px; color: {accent()}; font-weight: 600;")

        info_col.addWidget(self.lbl_title)
        info_col.addWidget(self.lbl_artist)
        header_layout.addLayout(info_col, stretch=1)

        self.btn_close = QPushButton("")
        self.btn_close.setObjectName("IconBtn")
        self.btn_close.setIcon(icon("x.svg", "#B3B3B3"))
        self.btn_close.setIconSize(QSize(16, 16))
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)
        header_layout.addWidget(self.btn_close)

        layout.addLayout(header_layout)

        # Estado / Carga
        self.status_label = QLabel("Buscando letra sincronizada...")
        self.status_label.setStyleSheet("color: #888888; font-size: 13px; margin: 10px 0px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Área de desplazamiento para las letras
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background-color: transparent; border: none;")

        self.lyrics_container = QWidget()
        self.lyrics_layout = QVBoxLayout(self.lyrics_container)
        self.lyrics_layout.setContentsMargins(8, 120, 8, 160)
        self.lyrics_layout.setSpacing(4)
        self.scroll_area.setWidget(self.lyrics_container)

        layout.addWidget(self.scroll_area, stretch=1)

    def fetch_lyrics(self):
        self.worker = LyricsWorker(self.title, self.artist)
        self.worker.lyrics_ready.connect(self.on_lyrics_loaded)
        self.worker.lyrics_error.connect(self.on_lyrics_error)
        self.worker.start()

    def on_lyrics_loaded(self, data: dict):
        self.lyrics_data = data
        self.status_label.setVisible(False)

        # Limpiar contenedor
        for i in reversed(range(self.lyrics_layout.count())):
            w = self.lyrics_layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        self.line_widgets.clear()

        if data.get("is_synced") and data.get("synced_lines"):
            for ms, line_text in data["synced_lines"]:
                lbl = ClickableLyricLabel(ms, line_text, self.seek_to_position)
                self.lyrics_layout.addWidget(lbl)
                self.line_widgets.append((ms, lbl))
        else:
            plain = data.get("plain_text", "Sin letras disponibles.")
            self.status_label.setText("Esta letra no avanza sola con la música.")
            self.status_label.setVisible(True)
            for line_text in plain.splitlines():
                if line_text.strip():
                    lbl = QLabel(line_text.strip())
                    lbl.setStyleSheet(STYLE_PLAIN)
                    lbl.setWordWrap(True)
                    lbl.setAlignment(Qt.AlignCenter)
                    lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
                    self.lyrics_layout.addWidget(lbl)
            self.lyrics_layout.addStretch()

    def on_lyrics_error(self, err_msg: str):
        self.status_label.setText(err_msg)

    def seek_to_position(self, ms: int):
        if self.player:
            self.player.setPosition(ms)

    def update_position(self, current_ms: int):
        """Actualiza la línea activa y desplaza la vista para mantenerla centrada."""
        if not self.line_widgets:
            return

        new_index = -1
        for i, (ms, _) in enumerate(self.line_widgets):
            if current_ms >= ms:
                new_index = i
            else:
                break

        if new_index != self.active_index and new_index >= 0:
            # Desactivar anterior
            if 0 <= self.active_index < len(self.line_widgets):
                _, old_lbl = self.line_widgets[self.active_index]
                old_lbl.setStyleSheet(STYLE_INACTIVE)

            # Activar nueva
            self.active_index = new_index
            _, active_lbl = self.line_widgets[self.active_index]
            active_lbl.setStyleSheet(style_active())
            active_lbl.updateGeometry()

            # Auto-scroll: deja la línea activa en el centro de la ventana
            QTimer.singleShot(0, lambda lbl=active_lbl: self._center_on(lbl))

    def _center_on(self, lbl):
        try:
            bar = self.scroll_area.verticalScrollBar()
            target = lbl.y() + lbl.height() // 2 - self.scroll_area.viewport().height() // 2
            bar.setValue(max(0, target))
        except RuntimeError:
            pass
