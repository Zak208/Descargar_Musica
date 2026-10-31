"""Sesión de votos (fase 27) desde la ventana: reúne las canciones analizadas de la carpeta del DJ, abre la ventana de votos
(ui/vote_dialog.py) y, al salir de la aplicación, espera a que acaben los renders en marcha.

numpy y el modelo se cargan solo al abrir la sesión (no al arrancar la aplicación)."""
import os
import sys

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from services import dj_service

MIN_TRACKS = 2


class VoteSessionMixin:
    """Mezcla para MainWindow. Requiere: _dj_summary, _dj_source(), _dj_analysis, _dj_engine_info(), _dj_title(),
    refresh_dj_folder(), notify(), player, _volume_master y _sleep_factor."""

    def init_vote_session_state(self):
        self._vote_dialog = None
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.vote_session_shutdown)

    def vote_session_infos(self) -> list:
        """Las fichas (con su ruta y su título) de las canciones analizadas de lo que suena en el DJ."""
        if self._dj_summary is None:
            return []
        infos = []
        for path in dj_service.without_blocked(dj_service.tracks_for(self._dj_summary, self._dj_source())):
            if path in self._dj_analysis and os.path.isfile(path):
                info = self._dj_engine_info(path)
                info["path"] = path
                info["title"] = self._dj_title(path)
                infos.append(info)
        return infos

    def vote_session_volume(self) -> float:
        """El volumen del programa (el de la barra de abajo, con el temporizador de dormir si está bajando)."""
        return max(0.0, min(1.0, float(getattr(self, "_volume_master", 1.0)) * float(getattr(self, "_sleep_factor", 1.0))))

    def open_vote_session(self):
        """Abre la sesión de votos (o avisa de qué falta). Devuelve la ventana, o None."""
        if self._vote_dialog is not None:
            self.notify("La sesión de votos ya está abierta.")
            return None
        from services.ffmpeg_service import FFmpegService
        if not FFmpegService.get_ffmpeg_path():
            self.notify("Hace falta FFmpeg para preparar las mezclas: instálalo desde los ajustes.")
            return None
        infos = self.vote_session_infos()
        if len(infos) < MIN_TRACKS:
            if self._dj_summary is None:
                self.refresh_dj_folder()
            self.notify("Hacen falta al menos 2 canciones analizadas en la carpeta del DJ: espera a que termine el análisis "
                        "(se ve en la página DJ) y vuelve a probar.")
            return None
        from services import vote_session
        from ui.vote_dialog import VoteDialog
        session = vote_session.VoteSession(infos, info_for=self._dj_engine_info)
        if not session.candidates:
            self.notify("No se han podido preparar mezclas con estas canciones.")
            return None
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        dialog = VoteDialog(self, session, volume=self.vote_session_volume, music_playing=playing)
        dialog.finished.connect(self._on_vote_session_closed)
        self._vote_dialog = dialog
        dialog.open()
        dialog.start()
        return dialog

    def _on_vote_session_closed(self, _result=0):
        dialog, self._vote_dialog = self._vote_dialog, None
        if dialog is None:
            return
        votes = dialog.session.votes_here
        if votes:
            st = dialog.session.status
            self.notify(f"Sesión de votos terminada: {votes} " + ("voto" if votes == 1 else "votos") + f" nuevos. Modelo: {st['text']}.")

    def vote_session_shutdown(self):
        """Al salir: cierra la ventana de votos y espera (como mucho 10 s) a que acaben los renders en marcha."""
        if self._vote_dialog is not None:
            self._vote_dialog.reject()
        module = sys.modules.get("ui.vote_dialog")
        if module is not None:
            module.wait_workers(10000)
