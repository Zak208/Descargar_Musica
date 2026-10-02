"""Ecualizador: aplicarlo a la canción que suena (copia procesada) y cambiar de fuente sin cortes."""
import os
import logging
from PySide6.QtCore import (
    QUrl, QTimer
)
from PySide6.QtMultimedia import QMediaPlayer
from services.equalizer_service import (
    EqRenderWorker, active_bands, rendered_path_for
)
from ui.equalizer_dialog import EqualizerDialog


class EqualizerMixin:
    """Mezcla para MainWindow."""

    def open_equalizer(self):
        if not self.equalizer_dialog:
            self.equalizer_dialog = EqualizerDialog(self)
            self.equalizer_dialog.eq_changed.connect(self.on_eq_changed)
        self.equalizer_dialog.exec()

    def _eq_source(self, path: str):
        """(archivo que debe sonar, versión con ecualizador si ya existe)."""
        bands = active_bands(self.eq_settings)
        if bands is not None:
            out = rendered_path_for(path, bands)
            if out.exists():
                return str(out), str(out)
        return path, None

    # ---------- ecualizador ----------
    def _apply_eq_if_needed(self):
        path = self._eq_source_path
        if not path:
            return
        bands = active_bands(self.eq_settings)
        if bands is None:
            if self._eq_active_render:
                self._swap_source(path)
                self._eq_active_render = None
            return
        out = rendered_path_for(path, bands)
        if out.exists():
            if self._eq_active_render != str(out):
                self._swap_source(str(out))
                self._eq_active_render = str(out)
            return
        if self._eq_worker is not None and self._eq_worker.isRunning():
            self._eq_worker.is_cancelled = True
        self._eq_worker = EqRenderWorker(path, bands)
        self._eq_worker.done.connect(self._on_eq_rendered)
        self._eq_worker.failed.connect(lambda msg: logging.warning(f"Ecualizador: {msg}"))
        self._eq_worker.start()

    def _on_eq_rendered(self, src: str, rendered: str):
        if src != self._eq_source_path or active_bands(self.eq_settings) is None:
            return
        if str(rendered_path_for(src, active_bands(self.eq_settings))) != str(rendered):
            return  # el ajuste cambió mientras se procesaba
        self._swap_source(rendered)
        self._eq_active_render = rendered

    def _swap_source(self, file_path: str):
        """Cambia el archivo que suena (original <-> con ecualizador) conservando el punto de la canción."""
        if not os.path.isfile(file_path):
            return
        pos = self.player.position()
        resume = self.player.playbackState() != QMediaPlayer.PausedState
        self._swap_token = getattr(self, '_swap_token', 0) + 1
        token = self._swap_token
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(file_path))
        # El reproductor necesita un instante tras cambiar de archivo; si se le pide sonar de inmediato se queda parado.
        QTimer.singleShot(300, lambda: self._swap_resume(token, pos, resume))

    def _swap_resume(self, token: int, pos: int, resume: bool):
        if token != getattr(self, '_swap_token', 0):
            return  # mientras tanto empezó otra canción
        if resume:
            self.player.play()
        if pos > 500:
            QTimer.singleShot(500, lambda: token == self._swap_token and self.player.setPosition(pos))

    def on_eq_changed(self, data: dict):
        self.eq_settings = data
        playing_local = bool(self._eq_source_path) and self.player_bar.isVisible()
        if active_bands(data) is None:
            self.notify("Sonido normal")
        elif playing_local:
            self.notify("Aplicando el ajuste de sonido...")
        else:
            self.notify("Listo. Se notará en las canciones de tu biblioteca.")
        self._apply_eq_if_needed()
