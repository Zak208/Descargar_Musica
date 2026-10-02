import os
from ui.icons import icon
from ui.imageloader import ImageLoaderThread
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QScrollArea
)


def resource_path(relative_path):
    import sys
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class HorizontalCarouselScrollArea(QScrollArea):
    """Carrusel horizontal: sin barra. Se mueve con las flechas (animado) o con la rueda lateral del ratón.
    La rueda normal (arriba/abajo) sigue desplazando la página."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._anim = QPropertyAnimation(self.horizontalScrollBar(), b"value", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def _animate_to(self, target: int, duration: int):
        """Desplazamiento suave (se anima siempre: es barato y es la respuesta a una pulsación del usuario)."""
        bar = self.horizontalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), target))
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()

    def wheelEvent(self, event):
        dx = event.angleDelta().x()
        if dx and abs(dx) >= abs(event.angleDelta().y()):
            bar = self.horizontalScrollBar()
            if bar.maximum() > bar.minimum():
                base = self._anim.endValue() if self._anim.state() == QPropertyAnimation.Running else bar.value()
                self._animate_to(int(base) - int(dx * 1.4), 160)
                event.accept()
                return
        event.ignore()   # la rueda normal es para desplazar la página

    def scroll_page(self, direction: int):
        """Mueve el carrusel una 'página' a la izquierda (-1) o a la derecha (+1)."""
        bar = self.horizontalScrollBar()
        step = max(220, int(self.viewport().width() * 0.85))
        self._animate_to(bar.value() + direction * step, 360)


class AlbumCard(QFrame):
    clicked = Signal(int)  # album_id

    def __init__(self, album_info: dict, parent=None):
        super().__init__(parent)
        self.album_info = album_info
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(155, 220)
        self.setObjectName("AlbumCard")
        self.setStyleSheet("""
            QFrame#AlbumCard {
                background-color: #161616;
                border-radius: 12px;
                border: 1px solid #222222;
            }
            QFrame#AlbumCard:hover {
                background-color: #222222;
                border: 1px solid #1ED760;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)

        # Carátula Cuadrada
        from ui.controls import CoverLabel
        self.cover_label = CoverLabel(radius=8, placeholder="#202020")
        self.cover_label.setFixedSize(120, 120)
        self.cover_label.setStyleSheet("background-color: #202020; border-radius: 8px;")
        layout.addWidget(self.cover_label)

        # Nombre Álbum
        name_label = QLabel(album_info.get("name", "Álbum"))
        name_label.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: bold;")
        name_label.setAlignment(Qt.AlignLeft)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        year_text = f"{album_info.get('year', '')} • {album_info.get('artist', '')}"
        sub_label = QLabel(year_text)
        sub_label.setStyleSheet("color: #888888; font-size: 11px;")
        sub_label.setAlignment(Qt.AlignLeft)
        sub_label.setWordWrap(True)
        layout.addWidget(sub_label)

        cover_url = album_info.get("cover")
        if cover_url:
            self.loader = ImageLoaderThread(cover_url, is_circular=False, size=(120, 120))
            self.loader.image_loaded.connect(self.cover_label.setPixmap)
            self.loader.start()

    def enterEvent(self, event):
        self.cover_label.zoom_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.cover_label.zoom_hover(False)
        super().leaveEvent(event)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            win = self.window()
            if hasattr(win, "remember_cover_source"):
                win.remember_cover_source(self.cover_label)       # la portada «viaja» a la página del álbum
            self.clicked.emit(self.album_info.get("id", 0))
        super().mousePressEvent(ev)


class AlbumDetailsPage(QWidget):
    back_clicked = Signal()
    download_all_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.album_data = {}
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(16)

        # Botón Volver
        nav_bar = QHBoxLayout()
        self.btn_back = QPushButton(" Volver")
        self.btn_back.setIcon(QIcon(resource_path("assets/icons/prev.svg")))
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.clicked.connect(self.back_clicked.emit)
        nav_bar.addWidget(self.btn_back)
        nav_bar.addStretch()
        main_layout.addLayout(nav_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 0, 20)
        self.content_layout.setSpacing(20)

        # Cabecera de Álbum
        self.header_frame = QFrame()
        self.header_frame.setObjectName("AlbumHeader")
        self.header_frame.setStyleSheet("#AlbumHeader { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #282828, stop:1 #121212); border-radius: 16px; }")
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(24, 24, 24, 24)
        header_layout.setSpacing(24)

        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(160, 160)
        self.cover_lbl.setStyleSheet("background-color: #202020; border-radius: 8px;")
        self.cover_lbl.setScaledContents(True)
        header_layout.addWidget(self.cover_lbl)

        info_box = QVBoxLayout()
        info_box.setAlignment(Qt.AlignVCenter)
        info_box.setSpacing(6)

        badge_lbl = QLabel("ÁLBUM")
        badge_lbl.setStyleSheet("color: #B3B3B3; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        info_box.addWidget(badge_lbl)

        self.title_lbl = QLabel("Nombre del Álbum")
        self.title_lbl.setStyleSheet("font-size: 32px; font-weight: bold; color: #FFFFFF;")
        self.title_lbl.setWordWrap(True)
        info_box.addWidget(self.title_lbl)

        self.meta_lbl = QLabel("Artista • Año • 0 canciones")
        self.meta_lbl.setStyleSheet("color: #B3B3B3; font-size: 13px;")
        info_box.addWidget(self.meta_lbl)

        btn_box = QHBoxLayout()
        btn_box.setSpacing(12)

        self.btn_download_album = QPushButton(" Descargar álbum completo")
        self.btn_download_album.setIcon(icon("download_black.svg"))
        self.btn_download_album.setObjectName("DownloadBtn")
        self.btn_download_album.setCursor(Qt.PointingHandCursor)
        self.btn_download_album.clicked.connect(self._on_download_album)
        btn_box.addWidget(self.btn_download_album)
        btn_box.addStretch()

        info_box.addLayout(btn_box)
        header_layout.addLayout(info_box, stretch=1)
        self.content_layout.addWidget(self.header_frame)

        # Lista de canciones del Álbum
        tracks_title = QLabel("Canciones del Álbum")
        tracks_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #FFFFFF; margin-top: 10px;")
        self.content_layout.addWidget(tracks_title)

        self.tracks_container = QVBoxLayout()
        self.tracks_container.setSpacing(10)
        self.content_layout.addLayout(self.tracks_container)

        scroll.setWidget(content)
        main_layout.addWidget(scroll, stretch=1)

    def load_album_data(self, data: dict, main_window):
        self.album_data = data
        self.title_lbl.setText(data.get("name", "Álbum"))
        artist = data.get("artist", "")
        year = data.get("year", "")
        tracks = data.get("tracks", [])
        self.meta_lbl.setText(f"{artist} • {year} • {len(tracks)} canciones")

        cover_url = data.get("cover")
        if cover_url:
            self.loader = ImageLoaderThread(cover_url, is_circular=False, size=(160, 160))
            self.loader.image_loaded.connect(self.cover_lbl.setPixmap)
            self.loader.start()

        # Limpiar tracks previos
        for i in reversed(range(self.tracks_container.count())):
            w = self.tracks_container.itemAt(i).widget()
            if w:
                w.deleteLater()

        from ui.song_card import SongResultCard
        for item in tracks:
            card = SongResultCard(item, parent_window=main_window)
            self.tracks_container.addWidget(card)

    def _on_download_album(self):
        tracks = self.album_data.get("tracks", [])
        if tracks:
            self.download_all_requested.emit(tracks)
