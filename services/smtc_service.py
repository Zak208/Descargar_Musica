"""Integración con el control multimedia de Windows (SMTC): título y portada en el panel de volumen y la pantalla de
bloqueo, y botones de reproducir/pausa/siguiente/anterior de auriculares Bluetooth o teclados.

Es opcional: si los componentes de Windows (paquetes winrt) no están, la aplicación funciona igual."""
import logging

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class MediaControls(QObject):
    """Emite `button('play'|'pause'|'next'|'previous'|'stop')` cuando se pulsa un botón multimedia del sistema."""
    button = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.available = False
        self._smtc = None
        self._player = None
        self._streams = None
        try:
            from winrt.windows.media.playback import MediaPlayer
            from winrt.windows.media import SystemMediaTransportControlsButton as B
            self._B = B
            self._player = MediaPlayer()
            self._player.command_manager.is_enabled = False       # los botones los gestionamos nosotros
            smtc = self._player.system_media_transport_controls
            smtc.is_enabled = True
            smtc.is_play_enabled = True
            smtc.is_pause_enabled = True
            smtc.is_next_enabled = True
            smtc.is_previous_enabled = True
            smtc.is_stop_enabled = False
            self._token = smtc.add_button_pressed(self._on_button)
            self._smtc = smtc
            self.available = True
        except Exception as e:
            logger.info(f"Control multimedia de Windows no disponible: {e}")

    # ---- botones del sistema → señal de Qt (se emite desde otro hilo; Qt la entrega en el principal)
    def _on_button(self, _sender, args):
        try:
            B = self._B
            names = {B.PLAY: "play", B.PAUSE: "pause", B.NEXT: "next", B.PREVIOUS: "previous", B.STOP: "stop"}
            name = names.get(args.button)
            if name:
                self.button.emit(name)
        except Exception:
            pass

    # ---- información de lo que suena
    def update(self, title: str, artist: str, album: str = "", cover_bytes: bytes | None = None, playing: bool = True):
        if not self.available:
            return
        try:
            from winrt.windows.media import MediaPlaybackType, MediaPlaybackStatus
            updater = self._smtc.display_updater
            updater.type = MediaPlaybackType.MUSIC
            props = updater.music_properties
            props.title = title or ""
            props.artist = artist or ""
            props.album_title = album or ""
            if cover_bytes:
                self._set_thumbnail(updater, cover_bytes)
            updater.update()
            self._smtc.playback_status = MediaPlaybackStatus.PLAYING if playing else MediaPlaybackStatus.PAUSED
        except Exception as e:
            logger.info(f"No se pudo actualizar el control multimedia: {e}")

    def _set_thumbnail(self, updater, data: bytes):
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream, RandomAccessStreamReference
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(data)
        writer.store_async().get()          # escribir en memoria es instantáneo
        writer.detach_stream()
        stream.seek(0)
        self._streams = stream            # se mantiene viva mientras el sistema la use
        updater.thumbnail = RandomAccessStreamReference.create_from_stream(stream)

    def set_status(self, playing: bool, stopped: bool = False):
        if not self.available:
            return
        try:
            from winrt.windows.media import MediaPlaybackStatus
            if stopped:
                self._smtc.playback_status = MediaPlaybackStatus.STOPPED
            else:
                self._smtc.playback_status = MediaPlaybackStatus.PLAYING if playing else MediaPlaybackStatus.PAUSED
        except Exception:
            pass

    def shutdown(self):
        try:
            if self._smtc is not None:
                self._smtc.remove_button_pressed(self._token)
                self._smtc.is_enabled = False
            if self._player is not None:
                self._player.close()
        except Exception:
            pass
