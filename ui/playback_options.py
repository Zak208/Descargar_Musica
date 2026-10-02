"""Más opciones de reproducción: temporizador para dormir, velocidad, repetir un tramo, fundido entre canciones,
igualar el volumen entre canciones, control multimedia de Windows y controles en la bandeja del sistema."""
import logging
import math
import os
import time

from PySide6.QtCore import QBuffer, QIODevice, QEasingCurve, QTimer, QUrl, QVariantAnimation, Qt
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from config import load_settings, save_settings
from services import library_db, loudness_service
from services.smtc_service import MediaControls
from ui.icons import icon
from ui.styles import accent

SLEEP_CHOICES = ((15, "15 minutos"), (30, "30 minutos"), (45, "45 minutos"), (60, "1 hora"), (120, "2 horas"))
SPEEDS = ((0.75, "0,75×"), (1.0, "Normal"), (1.25, "1,25×"), (1.5, "1,5×"), (2.0, "2×"))
FADES = ((0, "Sin fundido"), (2, "2 segundos"), (4, "4 segundos"), (6, "6 segundos"), (8, "8 segundos"),
         (10, "10 segundos"), (12, "12 segundos"))
SLEEP_FADE_SECONDS = 20          # el volumen baja poco a poco durante los últimos 20 s del temporizador
MANUAL_CROSSFADE_MS = 1500       # al saltar tú de canción, el fundido cruzado es más corto


class ActivePlayer:
    """Para las ventanas que necesitan el reproductor (letra, editor): apunta siempre al que suena ahora,
    aunque el fundido cruzado haya cambiado de reproductor."""

    def __init__(self, window):
        self._w = window

    def position(self):
        return self._w.player.position()

    def duration(self):
        return self._w.player.duration()

    def setPosition(self, ms):
        self._w.player.setPosition(ms)

    def play(self):
        self._w.player.play()

    def pause(self):
        self._w.player.pause()

    def playbackState(self):
        return self._w.player.playbackState()


def _setting(name, default):
    return load_settings().get(name, default)


def _store(name, value):
    settings = load_settings()
    settings[name] = value
    save_settings(settings)


class PlaybackOptionsMixin:
    """Mezcla para MainWindow. Requiere: player, audio_output, volume_slider, btn_options, player_thumb, tray_icon,
    current_item_info, notify(), play_next(), play_previous(), toggle_play_pause()."""

    def init_playback_options(self):
        self._fade_ms = int(_setting("fade_seconds", 0)) * 1000
        self._normalize = bool(_setting("normalize_volume", True))
        self._volume_master = 1.0
        self._fade_factor = 1.0
        self._gain_factor = 1.0
        self._sleep_factor = 1.0
        self._fading_out = False
        self._natural_advance = False
        self._sleep_deadline = None
        self._sleep_end_of_track = False
        self._ab = [None, None]
        self._loudness_worker = None
        self._quitting = False
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setInterval(1000)
        self._sleep_timer.timeout.connect(self._sleep_tick)
        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.valueChanged.connect(lambda v: self._set_fade(float(v)))
        # fundido cruzado: dos reproductores a la vez. El que suena (self.player) recibe la canción nueva y sube;
        # el anterior (_out_deck) sigue con la suya y baja, hasta que termina el fundido
        self._xf_active = False
        self._out_deck = None            # (reproductor, salida de audio) que se está apagando
        self._spare_deck = None          # reproductor libre, listo para el próximo fundido
        self._out_factor = 0.0
        self._out_gain = 1.0
        self._out_start = 1.0
        self.active_player = ActivePlayer(self)
        self._xf_anim = QVariantAnimation(self)
        self._xf_anim.setStartValue(0.0)
        self._xf_anim.setEndValue(1.0)
        self._xf_anim.setEasingCurve(QEasingCurve.Linear)
        self._xf_anim.valueChanged.connect(lambda v: self._on_xf_value(float(v)))
        self._xf_anim.finished.connect(self._finish_crossfade)
        self._credit_timer = QTimer(self)             # una reproducción cuenta tras 30 s escuchando (como en Spotify)
        self._credit_timer.setSingleShot(True)
        self._credit_timer.setInterval(30000)
        self._credit_timer.timeout.connect(self._credit_play)
        self._credit_path = None
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(700)
        self._thumb_timer.timeout.connect(self._update_system_cover)
        self.media_controls = MediaControls(self)
        self.media_controls.button.connect(self._on_media_button)
        self._setup_tray()

    # ---------------------------------------------------------------- volumen
    def change_volume(self, value):
        self._volume_master = value / 100.0
        self._apply_volume()
        self._update_volume_icon(value)

    def _update_volume_icon(self, value: int):
        """El icono del altavoz cambia con el nivel (silencio, bajo, alto) con un cruce breve."""
        level = 0 if value <= 0 else (1 if value < 35 else 2)
        if level == getattr(self, "_vol_level", None) or not hasattr(self, "vol_icon"):
            return
        self._vol_level = level
        name = ("volume_mute.svg", "volume_low.svg", "volume.svg")[level]
        self.vol_icon.setPixmap(icon(name, "#B3B3B3").pixmap(16, 16))

    def show_volume_osd(self):
        value = self.volume_slider.value()
        name = "volume_mute.svg" if value <= 0 else ("volume_low.svg" if value < 35 else "volume.svg")
        self.osd.show_osd(name, "Silencio" if value <= 0 else f"Volumen {value} %", value / 100.0)

    def show_seek_osd(self, seconds: int):
        self.osd.show_osd("forward.svg" if seconds > 0 else "rewind.svg", f"{'+' if seconds > 0 else '−'}{abs(seconds)} s")

    def _apply_volume(self):
        master = self._volume_master * self._sleep_factor
        self.audio_output.setVolume(max(0.0, min(1.0, master * self._fade_factor * self._gain_factor)))
        if self._out_deck is not None:
            self._out_deck[1].setVolume(max(0.0, min(1.0, master * self._out_factor * self._out_gain)))

    def _set_fade(self, value: float):
        self._fade_factor = max(0.0, min(1.0, value))
        self._apply_volume()

    # ------------------------------------------------- fundido cruzado (dos reproductores)
    @staticmethod
    def _new_deck():
        player = QMediaPlayer()
        output = QAudioOutput()
        player.setAudioOutput(output)
        return player, output

    def _wire_player(self, player):
        """Las señales de un reproductor solo cuentan mientras es el que suena: el otro está apagándose en el fundido."""
        player.errorOccurred.connect(lambda e, s, p=player: p is self.player and self.handle_player_error(e, s))
        player.mediaStatusChanged.connect(lambda st, p=player: p is self.player and self.handle_media_status(st))
        player.playbackStateChanged.connect(lambda st, p=player: p is self.player and self.handle_playback_state(st))
        player.positionChanged.connect(lambda v, p=player: p is self.player and self.update_position(v))
        player.durationChanged.connect(lambda v, p=player: p is self.player and self.update_duration(v))

    def crossfade_ms(self, natural: bool = False) -> int:
        """Cuánto dura el fundido cruzado del salto que se va a hacer (0 = sin fundido: corte normal).
        `natural`: la canción se acerca a su final y empieza la siguiente; si no, lo pediste tú con «siguiente»."""
        if self._fade_ms <= 0 or self._sleep_end_of_track:
            return 0
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            return 0
        if natural:
            remaining = int(self.player.duration() - self.player.position())
            return max(500, min(self._fade_ms, remaining))
        return min(self._fade_ms, MANUAL_CROSSFADE_MS)

    def _begin_crossfade(self, ms: int):
        """La canción que suena pasa a un reproductor aparte que baja el volumen; el reproductor libre queda como
        el principal para recibir la canción nueva, que sube a la vez. Se llama antes de cargar la nueva."""
        start = self._fade_factor
        self._finish_crossfade()
        out_player, out_audio = self.player, self.audio_output
        spare = self._spare_deck
        self._spare_deck = None
        if spare is None:
            spare = self._new_deck()
            self._wire_player(spare[0])
        self._out_deck = (out_player, out_audio)
        self._out_gain = self._gain_factor
        self._out_start = start
        self._out_factor = start
        self.player, self.audio_output = spare
        self.player.setPlaybackRate(out_player.playbackRate())
        self._fade_factor = 0.0
        self._fading_out = False
        self._fade_anim.stop()
        self._xf_active = True
        self._xf_anim.stop()
        self._xf_anim.setDuration(max(200, int(ms)))
        self._xf_anim.start()

    def _on_xf_value(self, t: float):
        t = max(0.0, min(1.0, t))
        self._fade_factor = math.sin(t * math.pi / 2)          # potencia constante: la suma suena pareja
        self._out_factor = self._out_start * math.cos(t * math.pi / 2)
        self._apply_volume()

    def _finish_crossfade(self):
        """Termina (o corta) el fundido: el reproductor que se apagaba se detiene y queda libre."""
        self._xf_anim.stop()
        out = self._out_deck
        if out is not None:
            player = out[0]
            try:
                player.stop()
                player.setSource(QUrl())
            except RuntimeError:
                pass
            self._spare_deck = out
            self._out_deck = None
        self._out_factor = 0.0
        if self._xf_active:
            self._xf_active = False
            self._fade_factor = 1.0
            self._apply_volume()

    # ---------------------------------------------- empieza una canción nueva
    def on_track_started(self):
        info = self.current_item_info
        self._ab = [None, None]
        self._fading_out = False
        self._fade_anim.stop()
        if self._xf_active:
            self._natural_advance = False       # el fundido cruzado ya lleva el volumen de la canción nueva
        elif self._natural_advance and self._fade_ms > 0 and info:
            self._natural_advance = False
            self._fade_factor = 0.0
            self._fade_anim.setDuration(self._fade_ms)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setEasingCurve(QEasingCurve.InQuad)
            self._fade_anim.start()
        else:
            self._natural_advance = False
            self._fade_factor = 1.0
        self._gain_factor = 1.0
        path = (info or {}).get("local_path")
        if self._normalize and path:
            lufs = loudness_service.stored(path)
            if lufs is not None:
                self._gain_factor = loudness_service.gain_for(lufs)
            else:
                self._measure_loudness(path)
            nxt = self._next_local_path()
            if nxt and loudness_service.stored(nxt) is None and self._loudness_worker is None:
                QTimer.singleShot(4000, lambda p=nxt: self._measure_loudness(p, quiet=True))
        self._apply_volume()
        self._refresh_options_icon()
        self._update_system_info()
        self._credit_path = path
        self._credited = False
        self._credit_timer.stop()
        if path and self.player.playbackState() == QMediaPlayer.PlayingState:
            self._credit_timer.start()

    def _credit_play(self):
        path = (self.current_item_info or {}).get("local_path")
        if path and path == self._credit_path and not self._credited                 and self.player.playbackState() == QMediaPlayer.PlayingState:
            self._credited = True
            library_db.register_play(path)

    def _next_local_path(self):
        try:
            nxt = self.peek_next()
            return nxt.get("local_path") if nxt else None
        except Exception:
            return None

    def _measure_loudness(self, path: str, quiet: bool = False):
        """Mide el volumen de una canción en segundo plano (una vez; el resultado queda guardado)."""
        if self._loudness_worker is not None and self._loudness_worker.isRunning():
            return
        worker = loudness_service.LoudnessWorker(path, self)
        worker.done.connect(self._on_loudness)
        self._loudness_worker = worker
        worker.finished.connect(lambda: setattr(self, "_loudness_worker", None))
        worker.start()

    def _on_loudness(self, path: str, lufs: float):
        current = (self.current_item_info or {}).get("local_path")
        if self._normalize and current and current == path:
            self._gain_factor = loudness_service.gain_for(lufs)
            self._apply_volume()

    def set_normalize(self, enabled: bool):
        self._normalize = bool(enabled)
        _store("normalize_volume", self._normalize)
        if not enabled:
            self._gain_factor = 1.0
            self._apply_volume()
        else:
            self.on_track_started()

    # --------------------------------------------- avance de la reproducción
    def playback_tick(self, position_ms: int):
        """Se llama con cada avance de la canción: repetir tramo A-B y fundido de salida."""
        a, b = self._ab
        if a is not None and b is not None and position_ms >= b:
            self.player.setPosition(a)
            return
        duration = self.player.duration()
        if self._fade_ms > 0 and duration > self._fade_ms * 3 and not self.is_loop_enabled and not self._xf_active:
            remaining = duration - position_ms
            if 0 < remaining <= self._fade_ms and not self._fading_out \
                    and self.player.playbackState() == QMediaPlayer.PlayingState:
                nxt = None if self._sleep_end_of_track else self.peek_next()
                path = (nxt or {}).get("local_path")
                if path and os.path.isfile(path):
                    self.play_next(natural=True)        # fundido cruzado: la siguiente empieza ya, mientras esta se apaga
                    return
                self._fading_out = True      # no hay siguiente en tu equipo: solo baja el volumen, como antes
                self._fade_anim.stop()
                self._fade_anim.setDuration(int(remaining))
                self._fade_anim.setStartValue(self._fade_factor)
                self._fade_anim.setEndValue(0.0)
                self._fade_anim.setEasingCurve(QEasingCurve.Linear)
                self._fade_anim.start()
            elif remaining > self._fade_ms and self._fading_out:    # se retrocedió dentro de la canción
                self._fading_out = False
                self._fade_anim.stop()
                self._set_fade(1.0)

    def on_end_of_track(self) -> bool:
        """Devuelve True si el temporizador pide parar aquí (no se pasa a la siguiente)."""
        if self._sleep_end_of_track:
            self.cancel_sleep_timer(quiet=True)
            self.player.pause()
            self.notify("Temporizador: la música se ha detenido al terminar la canción. ¡Buenas noches!")
            return True
        self._natural_advance = True
        return False

    # ------------------------------------------------------- temporizador
    def set_sleep_timer(self, minutes: int):
        self._sleep_end_of_track = False
        self._sleep_deadline = time.time() + minutes * 60
        self._sleep_factor = 1.0
        self._sleep_timer.start()
        self._refresh_options_icon()
        self.notify(f"La música se detendrá en {minutes} minutos")

    def set_sleep_end_of_track(self):
        self._sleep_deadline = None
        self._sleep_timer.stop()
        self._sleep_factor = 1.0
        self._sleep_end_of_track = True
        self._refresh_options_icon()
        self.notify("La música se detendrá al terminar esta canción")

    def cancel_sleep_timer(self, quiet: bool = False):
        self._sleep_deadline = None
        self._sleep_end_of_track = False
        self._sleep_timer.stop()
        self._sleep_factor = 1.0
        self._apply_volume()
        self._refresh_options_icon()
        if not quiet:
            self.notify("Temporizador desactivado")

    def sleep_remaining(self) -> int:
        return max(0, int(self._sleep_deadline - time.time())) if self._sleep_deadline else 0

    def _sleep_tick(self):
        remaining = self.sleep_remaining()
        if self._sleep_deadline is None:
            self._sleep_timer.stop()
            return
        if remaining <= 0:
            self.cancel_sleep_timer(quiet=True)
            self.player.pause()
            self.notify("Temporizador: música pausada. ¡Buenas noches!")
            return
        if remaining <= SLEEP_FADE_SECONDS:
            self._sleep_factor = remaining / SLEEP_FADE_SECONDS      # el volumen baja poco a poco
            self._apply_volume()
        self._refresh_options_icon()

    # ------------------------------------------------------ velocidad y tramo
    def set_playback_rate(self, rate: float):
        self.player.setPlaybackRate(rate)
        self._refresh_options_icon()
        self.notify("Velocidad normal" if abs(rate - 1.0) < 0.01 else f"Velocidad {rate:g}×".replace(".", ","))

    def mark_ab(self, which: str):
        pos = int(self.player.position())
        if which == "a":
            self._ab = [pos, None]
            self.notify("Inicio del tramo marcado. Ahora marca el final.")
        else:
            if self._ab[0] is None:
                self.notify("Marca primero el inicio del tramo.")
                return
            if pos <= self._ab[0] + 500:
                self.notify("El final debe estar después del inicio.")
                return
            self._ab[1] = pos
            self.notify("Repitiendo el tramo marcado")
        self._refresh_options_icon()

    def clear_ab(self):
        self._ab = [None, None]
        self._refresh_options_icon()
        self.notify("Repetición de tramo quitada")

    def set_fade_seconds(self, seconds: int):
        self._fade_ms = int(seconds) * 1000
        _store("fade_seconds", int(seconds))

    # ------------------------------------------------------------- menú
    def _refresh_options_icon(self):
        self.seek_slider.set_marks(*self._ab)          # el tramo que se repite se ve sobre la barra
        chip = getattr(self, "sleep_chip", None)
        if chip is not None:
            if self._sleep_deadline:
                left = self.sleep_remaining()
                chip.setText(f"{left // 60}:{left % 60:02d}")
                urgent = left <= 60
            elif self._sleep_end_of_track:
                chip.setText("Al terminar")
                urgent = False
            else:
                chip.setText("")
                urgent = False
            chip.setVisible(bool(chip.text()))
            if bool(chip.property("urgent")) != urgent:
                chip.setProperty("urgent", urgent)
                chip.style().unpolish(chip)
                chip.style().polish(chip)
        active = bool(self._sleep_deadline or self._sleep_end_of_track or self._ab[0] is not None
                      or abs(self.player.playbackRate() - 1.0) > 0.01)
        self.btn_options.setIcon(icon("timer.svg", accent() if active else "#B3B3B3"))
        tip = ["Temporizador, velocidad y más"]
        if self._sleep_deadline:
            left = self.sleep_remaining()
            tip.append(f"Se detendrá en {left // 60}:{left % 60:02d}")
        elif self._sleep_end_of_track:
            tip.append("Se detendrá al terminar la canción")
        if self._ab[1] is not None:
            tip.append("Repitiendo un tramo")
        self.btn_options.setToolTip(" · ".join(tip))

    def open_playback_options(self):
        menu = QMenu(self)
        rate = self.player.playbackRate()

        sleep = menu.addMenu(icon("timer.svg"), "Temporizador para dormir")
        if self._sleep_deadline:
            left = self.sleep_remaining()
            info = sleep.addAction(f"Quedan {left // 60}:{left % 60:02d}")
            info.setEnabled(False)
        for minutes, text in SLEEP_CHOICES:
            sleep.addAction(text).triggered.connect(lambda _=False, m=minutes: self.set_sleep_timer(m))
        sleep.addAction("Al terminar esta canción").triggered.connect(self.set_sleep_end_of_track)
        if self._sleep_deadline or self._sleep_end_of_track:
            sleep.addSeparator()
            sleep.addAction("Desactivar el temporizador").triggered.connect(self.cancel_sleep_timer)

        speed = menu.addMenu("Velocidad de reproducción")
        group = QActionGroup(speed)
        for value, text in SPEEDS:
            act = speed.addAction(text)
            act.setCheckable(True)
            act.setChecked(abs(rate - value) < 0.01)
            group.addAction(act)
            act.triggered.connect(lambda _=False, v=value: self.set_playback_rate(v))

        ab = menu.addMenu("Repetir un tramo de la canción")
        ab.addAction("Marcar el inicio aquí").triggered.connect(lambda: self.mark_ab("a"))
        ab.addAction("Marcar el final aquí").triggered.connect(lambda: self.mark_ab("b"))
        if self._ab[0] is not None:
            ab.addSeparator()
            ab.addAction("Quitar la repetición").triggered.connect(self.clear_ab)

        menu.addSeparator()
        norm = menu.addAction("Igualar el volumen entre canciones")
        norm.setCheckable(True)
        norm.setChecked(self._normalize)
        norm.toggled.connect(self.set_normalize)
        fade = menu.addMenu("Fundido entre canciones")
        fgroup = QActionGroup(fade)
        for seconds, text in FADES:
            act = fade.addAction(text)
            act.setCheckable(True)
            act.setChecked(self._fade_ms == seconds * 1000)
            fgroup.addAction(act)
            act.triggered.connect(lambda _=False, s=seconds: self.set_fade_seconds(s))
        menu.exec(self.btn_options.mapToGlobal(self.btn_options.rect().topLeft()))

    # --------------------------------------------- control multimedia de Windows
    def _on_media_button(self, name: str):
        if name == "play":
            self.player.play()
        elif name == "pause":
            self.player.pause()
        elif name == "next":
            self.play_next()
        elif name == "previous":
            self.play_previous()

    def _update_system_info(self):
        info = self.current_item_info
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        if info:
            title, artist = info.get("title", ""), info.get("uploader", "")
            self.tray_icon.setToolTip(f"{artist} - {title}" if artist else title)
            self.media_controls.update(title, artist, info.get("album", ""), None, playing)
            self._thumb_timer.start()           # la portada puede tardar un instante en cargar
        else:
            self.tray_icon.setToolTip("Descargador de Música")
            self.media_controls.set_status(False, stopped=True)

    def _update_system_cover(self):
        info = self.current_item_info
        pix = self.player_thumb.pixmap()
        if not info or pix is None or pix.isNull():
            return
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pix.save(buf, "PNG")
        self.media_controls.update(info.get("title", ""), info.get("uploader", ""), info.get("album", ""),
                                   bytes(buf.data()), self.player.playbackState() == QMediaPlayer.PlayingState)

    def update_system_status(self, playing: bool):
        if playing and self._credit_path and not getattr(self, "_credited", True) and not self._credit_timer.isActive():
            self._credit_timer.start()          # empezó a sonar: en 30 s cuenta como reproducción
        elif not playing:
            self._credit_timer.stop()
        self.media_controls.set_status(playing)
        if hasattr(self, "tray_play_action"):
            self.tray_play_action.setText("Pausa" if playing else "Reproducir")

    # -------------------------------------------------------- bandeja del sistema
    def _setup_tray(self):
        menu = QMenu()
        self.tray_play_action = QAction("Reproducir", menu)
        self.tray_play_action.triggered.connect(self.toggle_play_pause)
        prev_action = QAction("Anterior", menu)
        prev_action.triggered.connect(self.play_previous)
        next_action = QAction("Siguiente", menu)
        next_action.triggered.connect(self.play_next)
        open_action = QAction("Abrir Descargador de Música", menu)
        open_action.triggered.connect(self.show_from_tray)
        quit_action = QAction("Salir", menu)
        quit_action.triggered.connect(self.quit_app)
        for act in (self.tray_play_action, prev_action, next_action):
            menu.addAction(act)
        menu.addSeparator()
        menu.addAction(open_action)
        menu.addAction(quit_action)
        self._tray_menu = menu
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.setToolTip("Descargador de Música")
        self.tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
                self._set_background(True)
            else:
                self.show_from_tray()

    def show_from_tray(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self._set_background(False)

    def quit_app(self):
        self._quitting = True
        self.close()
        QApplication.quit()

    def should_close_to_tray(self) -> bool:
        return bool(_setting("close_to_tray", False)) and not self._quitting and self.tray_icon.isVisible() \
            and QSystemTrayIcon.isSystemTrayAvailable()

    def hide_to_tray(self):
        self.hide()
        self._set_background(True)
        if not _setting("tray_hint_shown", False):
            _store("tray_hint_shown", True)
            self.tray_icon.showMessage("Sigue sonando", "La aplicación sigue en la bandeja del sistema. "
                                       "Pulsa su icono para abrirla o elige «Salir» para cerrarla.",
                                       QSystemTrayIcon.Information, 6000)

    def shutdown_playback_options(self):
        self._finish_crossfade()
        if self._spare_deck is not None:
            self._spare_deck[0].setSource(QUrl())
        self.media_controls.shutdown()
