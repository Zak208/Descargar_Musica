"""Modo DJ con el motor de mezcla propio (fases 9 a 15): activa y desactiva el `EnginePlayer` de la ventana.

Mientras dura la sesión DJ, `self.player` es un `EnginePlayer` (ver ui/engine_player.py) y el sonido sale de `MixEngine`, con
las transiciones preparadas por `mix_planner` + `dj_dsp`. Fuera de la sesión, o si algo falta (numpy, sounddevice, rubberband,
un dispositivo de salida), todo sigue con el reproductor de siempre y el fundido cruzado de QMediaPlayer.

Lo que el motor no hace (y por eso la ventana lo deja quieto mientras está activo): el ecualizador de sonido, la velocidad de
reproducción y el volumen igualado de la ventana (el motor iguala el volumen de cada plato con `deck_gain`)."""
import logging
import math
import os

from PySide6.QtCore import QTimer

from config import get_setting, update_settings
from services import audio_engine, dj_engine, pcm_loader, track_analysis
from ui.engine_player import EnginePlayer

logger = logging.getLogger(__name__)

SETTING = "dj_engine"
BPM_DISAGREE = 0.03             # si el BPM puesto a mano se aparta más de esto del de la rejilla (mitad y doble aparte), se descarta la rejilla


class DjEngineMixin:
    """Mezcla para MainWindow. Requiere: player, audio_output, _wire_player(), _finish_crossfade(), _apply_volume(), notify(),
    peek_next(), current_item_info, dj_session_active(), _dj_analysis, _dj_effective_bpm(), is_loop_enabled, _sleep_end_of_track."""

    def init_dj_engine_state(self):
        self._dj_engine = None                 # MixEngine
        self._dj_engine_session = None         # EngineSession
        self._dj_engine_player = None          # EnginePlayer (el que hace de self.player mientras el motor está activo)
        self._dj_real_deck = None              # (QMediaPlayer, QAudioOutput) de siempre, a salvo mientras tanto

    # ---- ajustes y estado -------------------------------------------------------------------------------------------
    def dj_engine_wanted(self) -> bool:
        return bool(get_setting(SETTING, True))

    def set_dj_engine_wanted(self, enabled: bool):
        update_settings(**{SETTING: bool(enabled)})
        if not enabled and self.dj_engine_on():
            self.notify("Motor de mezcla apagado: se usará al empezar la próxima sesión DJ.")

    def dj_engine_on(self) -> bool:
        return self._dj_engine_player is not None

    @staticmethod
    def dj_engine_unavailable_reason() -> str:
        """Por qué no se puede usar el motor propio (texto para el usuario), o '' si se puede."""
        if not audio_engine.available():
            return "sin salida de audio o sin sounddevice/numpy"
        if not pcm_loader.rubberband_available():
            return "el FFmpeg de la aplicación no trae el filtro rubberband (para igualar el ritmo)"
        return ""

    # ---- activar y desactivar ---------------------------------------------------------------------------------------
    def dj_engine_enter(self) -> bool:
        """Cambia el reproductor de la ventana por el del motor. False (sin cambiar nada) si no se puede o no se quiere."""
        if self.dj_engine_on():
            return True
        if not self.dj_engine_wanted():
            return False
        reason = self.dj_engine_unavailable_reason()
        if reason:
            logger.info(f"Motor DJ no disponible: {reason}")
            self.notify(f"Se usa el fundido de siempre: {reason}.")
            return False
        try:
            engine = audio_engine.MixEngine()
            if not engine.start():
                self.notify(f"Se usa el fundido de siempre: no se pudo abrir la salida de audio ({engine.last_error}).")
                return False
            session = dj_engine.EngineSession(engine, self._dj_engine_info, self._dj_engine_next)
        except Exception as e:                  # el DJ nunca debe quedarse sin sonido por esto
            logger.warning(f"No se pudo iniciar el motor DJ: {e}")
            self.notify("Se usa el fundido de siempre: no se pudo iniciar el motor de mezcla.")
            return False
        engine.on_stream_finished = lambda why: QTimer.singleShot(0, lambda: self._dj_engine_lost(why))
        self._finish_crossfade()
        real_player, real_output = self.player, self.audio_output
        real_player.stop()
        player = EnginePlayer(session, self)
        player.foreign_source.connect(self._dj_engine_foreign)
        self._wire_player(player)
        self._dj_engine, self._dj_engine_session, self._dj_engine_player = engine, session, player
        self._dj_real_deck = (real_player, real_output)
        self.player, self.audio_output = player, player.audio_output
        self._apply_volume()
        return True

    def dj_engine_leave(self):
        """Devuelve el reproductor de siempre a la ventana y apaga el motor (con un fundido corto)."""
        player = self._dj_engine_player
        if player is None:
            return
        engine = self._dj_engine
        self._dj_engine = self._dj_engine_session = self._dj_engine_player = None
        real_player, real_output = self._dj_real_deck
        self._dj_real_deck = None
        self.player, self.audio_output = real_player, real_output
        try:
            player.close()
            engine.stop(fade=True)
        except Exception as e:
            logger.warning(f"Error al apagar el motor DJ: {e}")
        player.deleteLater()
        self._apply_volume()

    def _dj_engine_foreign(self, url):
        """Algo que no es una canción local (vista previa en línea): lo toca el reproductor de siempre."""
        self.dj_engine_leave()
        self.player.setSource(url)

    def _dj_engine_lost(self, reason: str):
        """El dispositivo de salida se perdió (auriculares desconectados...): se vuelve al reproductor de siempre."""
        if not self.dj_engine_on():
            return
        self.notify(f"Se perdió la salida de audio del motor de mezcla ({reason}). Pulsa reproducir para seguir.")
        self.dj_engine_leave()

    # ---- lo que el motor pregunta a la aplicación -------------------------------------------------------------------
    def _dj_engine_info(self, path: str) -> dict:
        """La ficha de una canción para el planificador de mezclas: su análisis, con el BPM puesto a mano si lo hay."""
        info = dict(self._dj_analysis.get(path) or {})
        grid = track_analysis.grid_from(info)
        bpm, manual = self._dj_effective_bpm(path)
        if bpm:
            info["bpm"] = bpm
        if manual and grid is not None and not _same_tempo(bpm, grid.bpm):
            grid = None                         # la rejilla se calculó con otro tempo: no se fía de ella
        info["beatgrid"] = grid
        return info

    def _dj_engine_next(self, path: str):
        """La canción que sigue a `path` (solo si es la que suena ahora y la sesión DJ sigue)."""
        if not self.dj_session_active() or self.is_loop_enabled or self._sleep_end_of_track:
            return None
        if not _same_path((self.current_item_info or {}).get("local_path"), path):
            return self._dj_engine_after_in_list(path)         # el motor salta una canción que no se pudo cargar
        nxt = (self.peek_next() or {}).get("local_path")
        return nxt if nxt and os.path.isfile(nxt) else None

    def _dj_engine_after_in_list(self, path: str):
        """La canción de la lista de la sesión que sigue a `path` (existente), o None."""
        paths = [t.get("local_path") for t in (self._dj_context or [])]
        at = next((i for i, p in enumerate(paths) if _same_path(p, path)), -1)
        if at < 0:
            return None
        return next((p for p in paths[at + 1:] if p and os.path.isfile(p)), None)

    def dj_engine_plan(self):
        """La transición planificada de lo que suena a lo siguiente, o None."""
        player = self._dj_engine_player
        return None if player is None else player.last_info.get("plan")


def _same_path(a, b) -> bool:
    return bool(a) and bool(b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _same_tempo(a: float, b: float) -> bool:
    """¿Dos tempos son el mismo ritmo (contando la mitad y el doble)? Dentro de BPM_DISAGREE."""
    if not a or not b:
        return True
    return min(abs(math.log(a / (b * k))) for k in (0.5, 1.0, 2.0)) <= BPM_DISAGREE
