"""Botón «guardar» (círculo con un «+») y la listita para elegir en qué listas está cada canción, como en Spotify."""
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QScrollArea, QWidget

from services.playlist_service import PlaylistService
from ui.icons import icon
from ui.styles import accent


def save_icon(saved: bool, idle_color: str = "#B3B3B3"):
    """Círculo con un «+» o, si la canción ya está guardada en alguna lista, círculo verde con un tick."""
    return icon("added.svg", accent()) if saved else icon("plus_circle.svg", idle_color)


class _Row(QFrame):
    def __init__(self, name: str, saved: bool, on_click, leading_icon: str, parent=None):
        super().__init__(parent)
        self.setObjectName("SaveRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)
        self.lead = QLabel()
        self.lead.setPixmap(icon(leading_icon, "#B3B3B3").pixmap(18, 18))
        self.lead.setFixedSize(20, 20)
        self.lead.setStyleSheet("background: transparent;")
        lay.addWidget(self.lead)
        self.name = QLabel(name)
        self.name.setStyleSheet("background: transparent; font-size: 13px; font-weight: 600;")
        lay.addWidget(self.name, stretch=1)
        self.mark = QLabel()
        self.mark.setFixedSize(22, 22)
        self.mark.setStyleSheet("background: transparent;")
        lay.addWidget(self.mark)
        self.set_saved(saved)

    def set_saved(self, saved: bool):
        self.mark.setPixmap(save_icon(saved, "#B3B3B3").pixmap(20, 20))
        self.name.setStyleSheet("background: transparent; font-size: 13px; font-weight: 600;"
                                + (f" color: {accent()};" if saved else ""))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class SavePopup(QFrame):
    """Ventanita flotante con «Canciones que te gustan» y tus listas (sin «Mis descargas»)."""

    def __init__(self, window, info: dict):
        super().__init__(window, Qt.Popup | Qt.FramelessWindowHint)
        self.window_ref = window
        self.info = dict(info)
        self.setObjectName("SavePopup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFixedWidth(280)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 8, 6, 6)
        outer.setSpacing(2)

        head = QLabel("Guardar en…")
        head.setStyleSheet("background: transparent; font-size: 12px; font-weight: 700; color: #B3B3B3; padding: 2px 10px 6px 10px;")
        outer.addWidget(head)

        self.rows = {}
        member = PlaylistService.lists_containing(self.info)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(2)
        entries = [("favorites", "Canciones que te gustan", "heart_filled.svg")]
        for p_id, data in PlaylistService.get_playlists().items():
            entries.append((p_id, data.get("name", "Lista"), "playlist.svg"))
        for key, name, lead in entries:
            row = _Row(name, key in member, lambda k=key: self._toggle(k), lead)
            self.rows[key] = row
            body_lay.addWidget(row)

        if len(entries) > 7:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setFixedHeight(7 * 38)
            scroll.setWidget(body)
            outer.addWidget(scroll)
        else:
            outer.addWidget(body)

        new = _Row("Nueva lista", False, self._new_list, "plus.svg")
        new.mark.clear()
        outer.addWidget(new)

    def _toggle(self, key: str):
        if key == "favorites":
            now_in = PlaylistService.toggle_favorite(self.info)
        else:
            now_in = PlaylistService.toggle_in_playlist(key, self.info)
        self.rows[key].set_saved(now_in)
        self.window_ref.after_save_change(self.info, key, now_in)

    def _new_list(self):
        self.close()
        self.window_ref.create_playlist_with_track(self.info)

    def popup_at(self, button):
        """Se coloca encima del botón si abajo no cabe (la barra de reproducción está al fondo)."""
        self.adjustSize()
        below = button.mapToGlobal(QPoint(0, button.height() + 4))
        screen = button.screen().availableGeometry()
        x = min(max(screen.left(), below.x() - 20), screen.right() - self.width())
        if below.y() + self.sizeHint().height() > screen.bottom():
            y = button.mapToGlobal(QPoint(0, 0)).y() - self.sizeHint().height() - 4
        else:
            y = below.y()
        self.move(x, max(screen.top(), y))
        self.show()
