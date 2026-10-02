"""Ventana de letras al estilo Spotify: fondo con el color de la portada y texto grande que crece con la ventana."""
import os

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QProgressBar
)
from services.lyrics_service import LyricsWorker
from ui.ambient import AmbientBackdrop, IdleHider
from ui.icons import icon
from ui.lyric_line import LyricLine
from ui.lyric_follow import LyricsFollower

MIN_FONT, MAX_FONT = 20, 92
DEFAULT_COLOR = QColor("#3D5A4A")


class LyricsDialog(QDialog, AmbientBackdrop):
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
        self.init_backdrop(self.color)
        self.setMinimumSize(680, 560)
        # el botón del sistema para maximizar también está disponible (además del de pantalla completa)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self.resize(760, 760)
        self.init_ui()
        self._apply_color()
        self.set_track(title, artist, self.color, force=True)

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 12)
        layout.setSpacing(10)

        self.header_box = QWidget()
        self.header_box.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(self.header_box)
        header_layout.setContentsMargins(0, 0, 0, 0)
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF; background: transparent;")
        self.lbl_artist = QLabel("")
        self.lbl_artist.setStyleSheet("font-size: 14px; color: rgba(255,255,255,0.75); font-weight: 600; background: transparent;")
        info_col.addWidget(self.lbl_title)
        info_col.addWidget(self.lbl_artist)
        header_layout.addLayout(info_col, stretch=1)

        self.btn_edit = QPushButton("Editar")
        self.btn_edit.setStyleSheet("color: #FFFFFF; background: transparent; border: none; font-weight: 700; font-size: 14px;")
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.clicked.connect(lambda: self._call("edit_lyrics"))
        self.btn_edit.setVisible(False)
        header_layout.addWidget(self.btn_edit)

        self.btn_full = QPushButton("")
        self.btn_full.setObjectName("IconBtn")
        self.btn_full.setIcon(icon("fullscreen.svg", "#FFFFFF"))
        self.btn_full.setIconSize(QSize(18, 18))
        self.btn_full.setFixedSize(32, 32)
        self.btn_full.setCursor(Qt.PointingHandCursor)
        self.btn_full.setToolTip("Pantalla completa (F11)")
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        header_layout.addWidget(self.btn_full)

        self.btn_close = QPushButton("")
        self.btn_close.setObjectName("IconBtn")
        self.btn_close.setIcon(icon("x.svg", "#FFFFFF"))
        self.btn_close.setIconSize(QSize(16, 16))
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.close)
        header_layout.addWidget(self.btn_close)
        layout.addWidget(self.header_box)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: rgba(255,255,255,0.75); font-size: 14px; margin: 10px 0px; background: transparent;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet("QProgressBar { background: rgba(0,0,0,0.3); border: none; border-radius: 3px; }"
                                    "QProgressBar::chunk { background: #FFFFFF; border-radius: 3px; }")
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        pill = ("QPushButton { color: #FFFFFF; background: rgba(0,0,0,0.30); border: 1px solid rgba(255,255,255,0.35); "
                "border-radius: 18px; padding: 9px 18px; font-weight: 700; font-size: 14px; }"
                "QPushButton:hover { background: rgba(0,0,0,0.45); border-color: #FFFFFF; }")
        self.actions = QWidget()
        self.actions.setStyleSheet("background: transparent;")
        act = QHBoxLayout(self.actions)
        act.setContentsMargins(0, 0, 0, 0)
        act.addStretch()
        self.btn_generate = QPushButton("Generar con el sistema")
        self.btn_generate.setStyleSheet(pill)
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.clicked.connect(lambda: self._call("generate_lyrics"))
        act.addWidget(self.btn_generate)
        self.btn_write = QPushButton("Escribir la letra yo")
        self.btn_write.setStyleSheet(pill)
        self.btn_write.setCursor(Qt.PointingHandCursor)
        self.btn_write.clicked.connect(lambda: self._call("edit_lyrics"))
        act.addWidget(self.btn_write)
        act.addStretch()
        self.actions.setVisible(False)
        layout.addWidget(self.actions)

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
        self.follower = LyricsFollower(self.scroll_area)

    def set_color(self, color: QColor, cover=None):
        if color != self.color:
            self.color = color
        self.set_backdrop(color, cover)

    def _apply_color(self):
        self.set_backdrop(self.color)

    def paintEvent(self, event):
        p = QPainter(self)
        self.paint_backdrop(p, self.rect())

    def showEvent(self, event):
        self.start_backdrop()
        super().showEvent(event)

    def hideEvent(self, event):
        self.stop_backdrop()
        if getattr(self, "_idle", None) is not None:
            self._idle.stop()
        super().hideEvent(event)

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
        for _ms, lbl in self.line_widgets:
            lbl.set_size(size)
        for lbl in self.plain_widgets:
            lbl.set_size(size)
        if 0 <= self.active_index < len(self.line_widgets):
            QTimer.singleShot(0, self.follower.recenter)

    def toggle_fullscreen(self):
        """Pantalla completa como en Spotify: la letra se agranda con la ventana."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        full = self.isFullScreen()
        if getattr(self, "_idle", None) is None:
            self._idle = IdleHider(self, [self.header_box])
        if full:
            self._idle.start()           # en pantalla completa, los controles y el cursor se ocultan solos
        else:
            self._idle.stop()
        self.btn_full.setIcon(icon("fullscreen_exit.svg" if full else "fullscreen.svg", "#FFFFFF"))
        self.btn_full.setToolTip("Salir de pantalla completa (Esc)" if full else "Pantalla completa (F11)")

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        elif ev.key() == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()       # Esc primero sale de pantalla completa; otra vez cierra la ventana
        else:
            super().keyPressEvent(ev)

    def _call(self, name: str):
        """Acciones de la ventana principal (generar o editar la letra)."""
        owner = self.parent()
        if owner is not None:
            getattr(owner, name)(self)       # se pasa a sí misma para que los avisos salgan dentro de esta ventana

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
            self.set_backdrop(color)
        self.reload()

    def reload(self):
        """Busca otra vez la letra de la canción que muestra (tras editarla o generarla)."""
        self._clear()
        self.btn_edit.setVisible(False)
        self.actions.setVisible(False)
        self.progress.setVisible(False)
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
        owner = self.parent()
        store_key = owner.lyrics_key() if owner is not None and hasattr(owner, "lyrics_key") else ""
        info = getattr(owner, "current_item_info", None) or {}
        self.worker = LyricsWorker(self.title, self.artist, store_key, info.get("local_path") or "")
        self.worker.lyrics_ready.connect(lambda data, k=key: self.on_lyrics_loaded(data, k))
        self.worker.lyrics_error.connect(lambda msg, k=key: self.on_lyrics_error(msg, k))
        self.worker.start()

    def set_busy(self, text: str, percent: int = -1):
        self.status_label.setText(text)
        self.status_label.setVisible(True)
        self.actions.setVisible(False)
        self.progress.setVisible(percent != -1)
        if percent == -2:
            self.progress.setRange(0, 0)
        elif percent >= 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)

    def _clear(self):
        self.line_widgets = []
        self.plain_widgets = []
        self.active_index = -1
        self.follower.clear()
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
        self.progress.setVisible(False)
        self.actions.setVisible(False)
        self.btn_edit.setVisible(True)
        self._clear()
        size = self.font_px = self._target_font()
        source_note = {"auto": "Letra generada por el sistema: puede tener errores. Pulsa «Editar» para corregirla.",
                       "user": "Letra escrita por ti."}.get(data.get("source"), "")
        self.status_label.setText(source_note)
        self.status_label.setVisible(bool(source_note))

        if data.get("is_synced") and data.get("synced_lines"):
            for ms, line_text in data["synced_lines"]:
                lbl = LyricLine(ms, line_text, self.seek_to_position, size=size, pad="6px 2px")
                self.lyrics_layout.addWidget(lbl)
                self.line_widgets.append((ms, lbl))
            self.follower.set_lines(self.line_widgets)
            owner = self.parent()
            if hasattr(owner, "ensure_word_timing"):
                owner.ensure_word_timing(self.follower)
            for delay in (0, 80, 300):
                QTimer.singleShot(delay, self._ensure_layout)
            if self.player is not None:      # se coloca en la línea que toca ahora mismo
                self.update_position(self.player.position())
        else:
            plain = data.get("plain_text", "Sin letras disponibles.")
            self.status_label.setText(((source_note + " ") if source_note else "") + "Esta letra no avanza sola con la música.")
            self.status_label.setVisible(True)
            for line_text in plain.splitlines():
                if line_text.strip():
                    lbl = LyricLine(0, line_text.strip(), None, size=size, pad="6px 2px")
                    lbl.set_state("active")
                    lbl.set_fill(1.0)
                    self.lyrics_layout.addWidget(lbl)
                    self.plain_widgets.append(lbl)
            self.lyrics_layout.addStretch()

    def on_lyrics_error(self, err_msg: str, key: int = None):
        if key is not None and key != self._key:
            return
        owner = self.parent()
        info = getattr(owner, "current_item_info", None) or {}
        local = info.get("local_path")
        has_file = bool(local and os.path.isfile(local))
        note = getattr(owner, "_lyrics_note", "")
        if owner is not None:
            owner._lyrics_note = ""
        self.status_label.setText((note + " " if note else "") + err_msg
                                  + ("" if has_file else " Descárgala para que el sistema pueda generarla, o escríbela tú."))
        self.btn_generate.setVisible(has_file)
        self.actions.setVisible(True)
        self.btn_edit.setVisible(False)

    def _ensure_layout(self):
        """Si las frases quedaron con altura 0 (se midieron con la zona oculta), se vuelven a colocar."""
        try:
            if self.line_widgets and self.line_widgets[0][1].height() < 4:
                self.lyrics_layout.invalidate()
                self.lyrics_layout.activate()
                self.lyrics_container.adjustSize()
                self.follower.recenter()
        except RuntimeError:
            pass

    def seek_to_position(self, ms: int):
        if self.player:
            self.player.setPosition(ms)

    def update_position(self, current_ms: int):
        """Actualiza la línea activa (las anteriores se apagan) y mantiene la vista centrada en ella."""
        if not self.line_widgets:
            return
        self.follower.update(current_ms)
        self.active_index = self.follower.active
