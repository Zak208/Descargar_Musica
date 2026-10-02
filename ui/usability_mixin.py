"""Comodidad de uso: deshacer, pegar enlaces, manejo de las listas con el teclado y nombres para lectores de pantalla."""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from services.spotify_service import is_spotify_url
from services.youtube_service import is_youtube_url

UNDO_SECONDS = 90


class UsabilityMixin:
    """Mezcla para MainWindow. Requiere: toast, player_bar, notify(), perform_search(), topbar y page_playlist."""

    def init_usability_state(self):
        self._undo = None

    # ------------------------------------------------------------ deshacer
    def notify_undo(self, text: str, undo_fn, label: str = "Deshacer"):
        """Avisa de lo que se acaba de quitar y ofrece «Deshacer» (también con Ctrl+Z durante 90 segundos)."""
        self._undo = (time.time(), undo_fn)
        margin = (self.player_bar.height() + 24) if self.player_bar.isVisible() else 40
        self.toast.show_message(text, bottom_margin=margin, action=(label, self.perform_undo))

    def perform_undo(self):
        pending, self._undo = self._undo, None
        if not pending or time.time() - pending[0] > UNDO_SECONDS:
            self.notify("No hay nada que deshacer")
            return
        try:
            pending[1]()
            self.notify("Hecho: se ha deshecho")
        except Exception:
            self.notify("No se pudo deshacer")

    # ------------------------------------------------------------ pegar enlace
    def paste_link_from_clipboard(self):
        """Ctrl+V fuera de un cuadro de texto: si hay un enlace de YouTube o Spotify, lo busca."""
        text = (QApplication.clipboard().text() or "").strip()
        if text and len(text) < 400 and (is_youtube_url(text) or is_spotify_url(text)):
            self.topbar.set_text(text, silent=True)
            self.perform_search(text)
        else:
            self.notify("Copia primero un enlace de YouTube o Spotify y pulsa Ctrl+V.")

    # ----------------------------------------------- teclado en las listas
    def list_key_navigation(self, event) -> bool:
        """↑ ↓ mueven la selección, Intro reproduce, Supr quita de la lista. True si se atendió la tecla."""
        if self.stacked_widget.currentIndex() != 4:
            return False
        return self.page_playlist.handle_key(event)

    # ------------------------------------------- lectores de pantalla
    def apply_accessibility_names(self):
        """Los botones que solo llevan un icono reciben como nombre su ayuda emergente (para lectores de pantalla)."""
        for btn in self.findChildren(QPushButton):
            if not btn.text().strip() and not btn.accessibleName():
                tip = btn.toolTip()
                if tip:
                    btn.setAccessibleName(tip)
