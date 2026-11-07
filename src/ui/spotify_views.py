from ui.imageloader import ImageLoaderThread
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QVBoxLayout, QLabel,
    QFrame, QScrollArea
)


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
    clicked = Signal(object)  # album_id (int o str)

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

        year = album_info.get('year', '')
        t_cnt = int(album_info.get('track_count', 0) or 0)
        is_sgl = album_info.get('type') == 'single' or t_cnt <= 2
        type_str = "Sencillo" if is_sgl else (f"{t_cnt} canciones" if t_cnt > 0 else "Álbum")
        year_text = f"{year} • {type_str}" if year else type_str
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
            self.clicked.emit(self.album_info if isinstance(self.album_info, dict) else self.album_info.get("id", 0))
        super().mousePressEvent(ev)
