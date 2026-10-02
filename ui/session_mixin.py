"""Sesión: recordar y recuperar lo que sonaba, el tamaño y la posición de la ventana."""
import os
import logging
from PySide6.QtCore import (
    QByteArray
)
from services import session_service
from ui.pages import Page


class SessionMixin:
    """Mezcla para MainWindow."""

    # ---------- seguir donde lo dejaste ----------
    def _session_snapshot(self) -> dict:
        data = {
            "volume": self.volume_slider.value(),
            "shuffle": self.is_shuffle_enabled,
            "loop": self.is_loop_enabled,
            "panel_open": self.now_panel.isVisible() or (self.is_mini_mode and getattr(self, "_panel_was_open", False)),
            "page": self.stacked_widget.currentIndex(),
            "list": list(self._current_list) if self._current_list and self.stacked_widget.currentIndex() == Page.LIST else None,
        }
        if not self.is_mini_mode:
            data["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        info = self.current_item_info
        if info and info.get("local_path") and self.player_bar.isVisible():
            data["track"] = info["local_path"]
            data["position"] = int(self.player.position())
            data["context"] = session_service.local_paths(self._context, session_service.MAX_CONTEXT)
            data["queue"] = session_service.local_paths(self.playback_queue, session_service.MAX_QUEUE)
        return data

    def save_session(self):
        if not getattr(self, "_session_restored", False):
            return      # aún no se leyó la sesión anterior: no se debe pisar
        try:
            session_service.save(self._session_snapshot())
        except Exception as e:
            logging.warning(f"No se pudo guardar la sesión: {e}")

    def restore_geometry_early(self):
        """Tamaño y posición de la ventana de la última vez (antes de mostrarla)."""
        geo = session_service.load().get("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            except Exception:
                pass

    def restore_session(self):
        """Vuelve a poner el volumen y la canción que sonaba (en pausa, en el punto en que iba) y su cola."""
        if getattr(self, "_session_restored", False):
            return
        self._session_restored = True      # a partir de aquí ya se puede guardar la sesión sin pisar la anterior
        data = session_service.load()
        if not data:
            return
        try:
            if "volume" in data:
                self.volume_slider.setValue(max(0, min(100, int(data["volume"]))))
            if data.get("shuffle") and not self.is_shuffle_enabled:
                self.toggle_shuffle()
            if data.get("loop") and not self.is_loop_enabled:
                self.toggle_loop()
            self._panel_user_closed = not data.get("panel_open", True)
            by_path = {it["local_path"]: it for it in self.library_items()}
            as_items = lambda paths: [by_path[p] for p in paths if p in by_path]
            track = data.get("track")
            if track and os.path.isfile(track):
                self.set_context(as_items(data.get("context", [])))
                self.playback_queue = as_items(data.get("queue", []))
                self._resume_pending = True
                self.play_local_file(track, autoplay=False, start_ms=int(data.get("position", 0) or 0))
            lst = data.get("list")
            if lst and self.stacked_widget.currentIndex() == Page.HOME:
                self.open_list(lst[0], lst[1])
            elif data.get("page") == Page.LIBRARY and self.stacked_widget.currentIndex() == Page.HOME:
                self.open_library()
        except Exception as e:
            logging.warning(f"No se pudo restaurar la sesión: {e}")
