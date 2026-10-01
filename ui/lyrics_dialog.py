"""Ventana de letras al estilo Spotify: fondo con el color de la portada y texto grande que crece con la ventana."""
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QSizePolicy
)
from services.lyrics_service import LyricsWorker
from ui.icons import icon

MIN_FONT, MAX_FONT = 20, 68
DEFAULT_COLOR = QColor("#3D5A4A")


def line_style(size: int, active: bool) -> str:
    # El tamaño es el mismo en la línea activa y en las demás: así el texto nunca se corta al cambiar de línea.
    color = "#FFFFFF" if active else "rgba(255, 255, 255, 0.50)"
    return f"color: {color}; font-size: {size}px; font-weight: 800; background: transparent; padding: 6px 2px;"


class ClickableLyricLabel(QLabel):
    def __init__(self, ms: int, text: str, on_seek_callback, parent=None):
        super().__init__(text, parent)
        self.ms = ms
        self.on_seek_callback = on_seek_callback
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.on_seek_callback:
            self.on_seek_callback(self.ms)
        super().mousePressEvent(ev)


class LyricsDialog(QDialog):
    def __init__(self, title: str, artist: str = "", player=None, color: QColor = None, parent=None):
        super().__init__(parent)
        self.title = title
        self.artist = artist
        self.player = player
        self.color = color or DEFAULT_COLOR
        self.lyrics_data = None
        self.line_widgets = []      # [(ms, QLabel)] (solo letras con tiempos)
        self.plain_widgets = []
        self.active_index = -1
        self.worker = None
        self._key = 0
        self.font_px = 0

        self.setObjectName("LyricsDialog")
        self.setMinimumSize(520, 560)
        self.resize(760, 760)
        self.init_ui()
        self._apply_color()
        self.set_track(title, artist, self.color, force=True)

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 12)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF; background: transparent;")
        self.lbl_artist = QLabel("")
        self.lbl_artist.setStyleSheet("font-size: 14px; color: rgba(255,255,255,0.75); font-weight: 600; background: transparent;")
        info_col.addWidget(self.lbl_title)
        info_col.addWidget(self.lbl_artist)
        header_layout.addLayout(info_col, stretch=1)

        self.btn_close = QPushButton("")
        self.btn_close.setObjectName("IconBtn")
        self.btn_close.setIcon(icon("x.svg", "#FFFFFF"))
        self.btn_close.setIconSize(QSize(16, 16))
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)
        header_layout.addWidget(self.btn_close)
        layout.addLayout(header_layout)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: rgba(255,255,255,0.75); font-size: 14px; margin: 10px 0px; background: transparent;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        self.scroll_area.viewport().setStyleSheet("background: transparent;")

        self.lyrics_container = QWidget()
        self.lyrics_container.setStyleSheet("background: transparent;")
        self.lyrics_layout = QVBoxLayout(self.lyrics_container)
        self.lyrics_layout.setContentsMargins(4, 90, 4, 160)
        self.lyrics_layout.setSpacing(10)
        self.scroll_area.setWidget(self.lyrics_container)
        layout.addWidget(self.scroll_area, stretch=1)

    def set_color(self, color: QColor):
        if color != self.color:
            self.color = color
            self._apply_color()

    def _apply_color(self):
        top = QColor(self.color)
        bottom = QColor(self.color)
        bottom.setHslF(bottom.hslHueF(), bottom.hslSaturationF(), 0.16)
        self.setStyleSheet(
            "QDialog#LyricsDialog { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {top.name()}, stop:1 {bottom.name()}); }}")

    # ------------------------------------------------------------- tamaño
    def _target_font(self) -> int:
        return max(MIN_FONT, min(MAX_FONT, int(min(self.width() / 17, self.height() / 13))))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        QTimer.singleShot(0, self._refresh_font)

    def _refresh_font(self):
        """Cuanto más grande es la ventana, más grande es la letra."""
        size = self._target_font()
        if size == self.font_px:
            return
        self.font_px = size
        for i, (_ms, lbl) in enumerate(self.line_widgets):
            lbl.setStyleSheet(line_style(size, i == self.active_index))
        for lbl in self.plain_widgets:
            lbl.setStyleSheet(line_style(size, True))
        if 0 <= self.active_index < len(self.line_widgets):
            QTimer.singleShot(0, lambda: self._center_on(self.line_widgets[self.active_index][1]))

    # ------------------------------------------------------------- datos
    def set_track(self, title: str, artist: str, color: QColor = None, force: bool = False):
        """Cambia la ventana a otra canción sin cerrarla."""
        if not force and (title, artist) == (self.title, self.artist):
            return
        self.title, self.artist = title, artist
        self.setWindowTitle(f"Letra: {title} - {artist}")
        self.lbl_title.setText(title)
        self.lbl_artist.setText(artist or "Artista")
        if color is not None and color != self.color:
            self.color = color
            self._apply_color()
        self._clear()
        self.status_label.setText("Buscando la letra...")
        self.status_label.setVisible(True)
        self._key += 1
        key = self._key
        if self.worker is not None:
            try:
                self.worker.lyrics_ready.disconnect()
                self.worker.lyrics_error.disconnect()
            except (RuntimeError, TypeError):
                pass
        self.worker = LyricsWorker(title, artist)
        self.worker.lyrics_ready.connect(lambda data, k=key: self.on_lyrics_loaded(data, k))
        self.worker.lyrics_error.connect(lambda msg, k=key: self.on_lyrics_error(msg, k))
        self.worker.start()

    def _clear(self):
        self.line_widgets = []
        self.plain_widgets = []
        self.active_index = -1
        while self.lyrics_layout.count():
            widget = self.lyrics_layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.scroll_area.verticalScrollBar().setValue(0)

    def on_lyrics_loaded(self, data: dict, key: int = None):
        if key is not None and key != self._key:
            return
        self.lyrics_data = data
        self.status_label.setVisible(False)
        self._clear()
        size = self.font_px = self._target_font()

        if data.get("is_synced") and data.get("synced_lines"):
            for ms, line_text in data["synced_lines"]:
                lbl = ClickableLyricLabel(ms, line_text, self.seek_to_position)
                lbl.setStyleSheet(line_style(size, False))
                self.lyrics_layout.addWidget(lbl)
                self.line_widgets.append((ms, lbl))
            if self.player is not None:      # se coloca en la línea que toca ahora mismo
                self.update_position(self.player.position())
        else:
            plain = data.get("plain_text", "Sin letras disponibles.")
            self.status_label.setText("Esta letra no avanza sola con la música.")
            self.status_label.setVisible(True)
            for line_text in plain.splitlines():
                if line_text.strip():
                    lbl = QLabel(line_text.strip())
                    lbl.setStyleSheet(line_style(size, True))
                    lbl.setWordWrap(True)
                    lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
                    self.lyrics_layout.addWidget(lbl)
                    self.plain_widgets.append(lbl)
            self.lyrics_layout.addStretch()

    def on_lyrics_error(self, err_msg: str, key: int = None):
        if key is None or key == self._key:
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
            if 0 <= self.active_index < len(self.line_widgets):
                self.line_widgets[self.active_index][1].setStyleSheet(line_style(self.font_px, False))
            self.active_index = new_index
            active_lbl = self.line_widgets[new_index][1]
            active_lbl.setStyleSheet(line_style(self.font_px, True))
            QTimer.singleShot(0, lambda lbl=active_lbl: self._center_on(lbl))

    def _center_on(self, lbl):
        try:
            bar = self.scroll_area.verticalScrollBar()
            target = lbl.y() + lbl.height() // 2 - self.scroll_area.viewport().height() // 2
            bar.setValue(max(0, target))
        except RuntimeError:
            pass
