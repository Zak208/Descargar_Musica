"""Modo fiesta (fases 30 y 31): la pantalla de botones grandes (`PartyPage`), «más / menos energía», el VIGILANTE que mantiene
la música sonando y los votos del público desde el móvil (`services/crowd_server.py`).

EL VIGILANTE (requisito de oro del plan: «nunca se cae: si algo falla, sigue sonando con un fundido simple»). Un `QTimer` de 1 s
mientras dura la fiesta mira, con una sesión DJ sonando:
  * que la posición avance: si está en «reproduciendo» y no se mueve durante `STALL_S` (5 s), es un fallo;
  * que el motor propio siga vivo: el flujo de PortAudio abierto (`stream_active`), su aviso de flujo perdido (que fuera de la
    fiesta deja la canción en pausa; aquí se recupera sola) y que la sesión del motor no se quede «parada» con canciones por
    delante (un `ended` inesperado) durante `STOPPED_TICKS` vueltas;
  * los errores del reproductor (`errorOccurred`, o un archivo que no se puede abrir: `InvalidMedia`), con el motor o sin él;
  * que el reproductor no se quede «detenido» solo (dos vueltas seguidas) o «cargando» más de `LOADING_MAX_S`.
Lo que NO cuenta como fallo: la pausa (la del usuario, la del temporizador o cualquier otra: en pausa no se vigila nada), una
canción que está cargando (el motor en «loading» o el reproductor en `LoadingMedia`), los `GRACE_S` que siguen a empezar o a
una recuperación, la última canción de la sesión que llega a su final y un parón de la propia interfaz (si entre dos vueltas
del vigilante pasan más de `FROZEN_UI_S`, el que estuvo parado fue el hilo de la ventana, no el sonido: se empieza a contar
de nuevo). Lo nuevo del motor tampoco lo confunde: el limitador de salida solo redondea picos (nunca deja en silencio ni para
la posición); los tipos de transición y los bucles antes de la mezcla siguen moviendo la posición (un bucle la hace volver
atrás, y eso cuenta como movimiento); y el puntuador (`audio_check`) trabaja en el hilo de la sesión al preparar la mezcla, sin
tocar lo que suena ni la posición que ve la ventana.

Cómo se recupera, por escalones (si el fallo anterior fue hace menos de `ESCALATE_S`, 2 minutos, se sube un escalón):
  1. con el motor propio: se reinicia la sesión del motor (y su flujo de audio si se cerró) en la siguiente canción;
  2. si vuelve a fallar: se apaga el motor propio (`dj_engine_leave`) y la cola sigue con el reproductor de siempre y su
     fundido cruzado de QMediaPlayer;
  3. sin motor: se salta a la siguiente canción;
  4. si la siguiente no existe o no carga, la siguiente (las borradas del disco se quitan antes con `_dj_prune_next`).
Si hay más de `STORM_ACTIONS` recuperaciones en `STORM_S`, se espera `STORM_PAUSE_S` antes de volver a intentarlo (todo
fallaría igual: no se pasa por toda la lista en segundos). Nada de esto deja salir una excepción: todo va al registro
(`logging`, «fiesta: …») y al historial «Eventos» de la pantalla. El indicador dice «Recuperándose» durante `RECOVERING_S` tras
cada recuperación (o mientras la posición lleva más de 2 s quieta) y «Todo bien» el resto del tiempo.

«MÁS / MENOS ENERGÍA»: `dj_planner.retarget` reordena lo que queda para que las próximas canciones suban o bajen de energía, con
las mismas reglas de tempo y tono que el orden inteligente. La siguiente que ya está preparada (o mezclándose) no se toca si
quedan menos de `LOCK_S` para su mezcla; si queda tiempo, se cambia también y el motor rehace la mezcla (`session.replan()`).
Si al terminar el análisis el DJ reordena la sesión entera (`dj_replan`), el último «más / menos energía» de los 15 minutos
anteriores se vuelve a aplicar encima.

VOTOS DEL PÚBLICO: apagados por defecto; los enciende el interruptor de la pantalla y se apagan al salir de la fiesta, al cerrar
la aplicación o si la sesión DJ termina. Ver los riesgos en `services/crowd_server.py`. El umbral de «Pasar» salta a la
siguiente igual que el botón «Siguiente» (no antes de `CROWD_MIN_SONG_S` de canción ni más de una vez cada
`CROWD_SKIP_COOLDOWN_S`); el de «Más energía» hace lo mismo que el botón (una vez por minuto como mucho). Los 👍 del público
(y un «Pasar» que se cumple) poco después de una mezcla se guardan como voto de esa mezcla en `transition_votes`, con
`source="crowd"` si ese módulo lo admite y, si no, `source="live"` con «público» en la nota y una sesión «publico-…»: así no se
mezclan con los votos del propio usuario."""
import logging
import os
import time
from collections import deque

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtMultimedia import QMediaPlayer

from services import crowd_server, dj_planner, transition_votes
from ui.pages import Page
from ui.party_page import PartyPage
from ui.playback_mixin import track_key

log = logging.getLogger(__name__)

WATCH_MS = 1000                 # cada cuánto mira el vigilante
STALL_S = 5.0                   # «reproduciendo» y la posición quieta durante esto = fallo
STOPPED_TICKS = 2               # vueltas seguidas «detenido» (o el motor parado con canciones por delante) = fallo
LOADING_MAX_S = 25.0            # cargando una canción más de esto = fallo
ESCALATE_S = 120.0              # otro fallo antes de esto sube un escalón
GRACE_S = 6.0                   # tras empezar o recuperarse, lo que se deja para que la canción cargue antes de vigilar
RECOVERING_S = 15.0             # el indicador dice «Recuperándose» durante esto tras una recuperación
STORM_ACTIONS, STORM_S, STORM_PAUSE_S = 8, 60.0, 30.0
FROZEN_UI_S = 2.5               # un hueco mayor entre dos vueltas es que la interfaz estuvo parada (no el sonido)
END_MARGIN_MS = 2500            # la última canción a menos de esto de su final: es el fin de la sesión, no un fallo
SESSION_GONE_TICKS = 5          # sin sesión DJ durante esto (tras haberla), se apagan los votos del público
LOCK_S = 20.0                   # con menos de esto para la mezcla, la siguiente ya no se cambia
REAPPLY_ENERGY_S = 15 * 60
EVENT_MEMORY = 300
CROWD_MIN_SONG_S = 15.0
CROWD_SKIP_COOLDOWN_S = 30.0
CROWD_ENERGY_COOLDOWN_S = 60.0
CROWD_MIX_WINDOW_S = 45.0       # un 👍 del público cuenta como voto de la mezcla si llega en este tiempo tras ella
CROWD_WARNING = ("Sin cifrado (http): quien esté en esta wifi y tenga el enlace puede votar. Enciéndelo solo en una wifi de "
                 "confianza. La primera vez Windows preguntará por el cortafuegos: permite solo las redes privadas.")


class _CrowdBridge(QObject):
    """Pasa los avisos del servidor (que llegan en su hilo) al hilo de la ventana."""
    signal = Signal(str, dict)


def qr_pixmap(text: str, size: int = 220):
    """El código QR de `text` como QPixmap, o None si no está instalada la biblioteca `qrcode` (es opcional)."""
    try:
        import qrcode
    except ImportError:
        return None
    try:
        code = qrcode.QRCode(border=2)
        code.add_data(text)
        code.make(fit=True)
        matrix = code.get_matrix()
        n = len(matrix)
        img = QImage(n, n, QImage.Format_RGB32)
        black, white = QColor("#000000").rgb(), QColor("#FFFFFF").rgb()
        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                img.setPixel(x, y, black if dark else white)
        return QPixmap.fromImage(img).scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)
    except Exception as e:
        log.info("no se pudo dibujar el QR: %s", e)
        return None


class PartyMixin:
    """Mezcla para MainWindow (va antes que DjEngineMixin: atiende el aviso de flujo perdido durante la fiesta). Requiere lo
    de DjMixin y DjEngineMixin, y: player, stacked_widget, switch_to_page(), peek_next(), upcoming_tracks(), play_next(),
    toggle_play_pause(), toggle_shuffle(), _shuffle_active(), reset_shuffle(), current_item_info, notify()."""

    def init_party_state(self):
        self.page_party = None
        self._party_on = False
        self._party_clock = time.monotonic          # las pruebas lo cambian para simular el paso del tiempo
        self._party_timer = QTimer(self)             # con la ventana como padre: se destruyen con ella, en orden
        self._party_timer.setInterval(WATCH_MS)
        self._party_timer.timeout.connect(self._party_watch)
        self._party_events = deque(maxlen=EVENT_MEMORY)
        self._party_bridge = _CrowdBridge(self)
        self._party_bridge.signal.connect(self._party_on_crowd)
        self._party_crowd = None
        self._party_qr = None
        self._party_crowd_session = ""
        self._party_crowd_vote = None                # (clave de la mezcla, id del voto, +1/-1) del público
        self._party_reset_watch()

    def _party_reset_watch(self):
        never = float("-inf")
        self._party_level = 0
        self._party_step = 0                         # último escalón aplicado (1 a 4), para el historial y las pruebas
        self._party_last_fail = never
        self._party_last_action = never
        self._party_actions = deque()
        self._party_storm_until = never
        self._party_grace_until = never
        self._party_last_pos = None
        self._party_last_change = None
        self._party_last_tick = None
        self._party_stopped_ticks = 0
        self._party_engine_stop_ticks = 0
        self._party_loading_since = None
        self._party_wired = []
        self._party_want_page = False
        self._party_was_active = False
        self._party_gone_ticks = 0
        self._party_track = None
        self._party_track_t = never
        self._party_last_energy = None               # (dirección, instante) del último «más / menos energía»
        self._party_crowd_skip_t = never
        self._party_crowd_energy_t = never
        self._party_crowd_told = None

    # ------------------------------------------------------------ página
    def build_party_page(self):
        page = self.page_party = PartyPage(self)
        page.next_requested.connect(self.party_next)
        page.energy_requested.connect(self.party_energy)
        page.pause_requested.connect(self.party_pause)
        page.exit_requested.connect(self.party_exit)
        page.start_requested.connect(self.party_start)
        page.crowd_toggled.connect(self.party_set_crowd)
        self.stacked_widget.addWidget(page)
        assert self.stacked_widget.indexOf(page) == Page.PARTY

    def party_active(self) -> bool:
        return self._party_on

    def open_party_page(self):
        """Entra en el modo fiesta (si no hay sesión DJ, la pantalla ofrece empezarla)."""
        self._party_begin()
        self.switch_to_page(Page.PARTY)
        self.refresh_party_page()

    def party_start(self):
        """«Empezar la fiesta»: empieza la sesión DJ y vuelve a esta pantalla (la sesión abre la página DJ al empezar)."""
        self._party_begin()
        self._party_want_page = True
        self.start_dj_session()
        if self.dj_session_active():
            self._party_follow_page()

    def _party_follow_page(self):
        self._party_want_page = False
        self.switch_to_page(Page.PARTY)
        self.refresh_party_page()

    def _party_begin(self):
        if self._party_on:
            return
        self._party_reset_watch()
        self._party_on = True
        self._party_grace_until = self._party_clock() + GRACE_S
        self._party_timer.start()
        self._party_event("Empieza el modo fiesta: el vigilante está atento")

    def party_exit(self):
        """«Salir de la fiesta»: apaga el vigilante y los votos del público, y vuelve a la página DJ."""
        self._party_end("Fin del modo fiesta")
        self.open_dj_page()

    def _party_end(self, reason: str):
        if not self._party_on:
            return
        self.party_set_crowd(False)
        self._party_timer.stop()
        self._party_on = False
        self._party_event(reason)

    def party_shutdown(self):
        """Al cerrar la aplicación: nada queda escuchando en la red."""
        try:
            self._party_end("La aplicación se cierra")
            if self._party_crowd is not None:
                self._party_crowd.stop()
                self._party_crowd = None
        except Exception:
            log.exception("fiesta: fallo al apagar")

    # ------------------------------------------------------------ teclado
    def party_key(self, event) -> bool:
        """Teclas de la fiesta (solo con su pantalla delante). True si la tecla era suya."""
        page = self.page_party
        if page is None or self.stacked_widget.currentWidget() is not page:
            return False
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        key = event.key()
        actions = {Qt.Key_Space: self.party_pause, Qt.Key_MediaTogglePlayPause: self.party_pause,
                   Qt.Key_Right: self.party_next, Qt.Key_N: self.party_next, Qt.Key_MediaNext: self.party_next,
                   Qt.Key_Up: lambda: self.party_energy(1), Qt.Key_Plus: lambda: self.party_energy(1),
                   Qt.Key_Down: lambda: self.party_energy(-1), Qt.Key_Minus: lambda: self.party_energy(-1),
                   Qt.Key_V: lambda: self.party_set_crowd(not self._party_crowd_running()),
                   Qt.Key_E: page.toggle_events, Qt.Key_Escape: self.party_exit}
        if key in (Qt.Key_Return, Qt.Key_Enter) and not self.dj_session_active():
            self.party_start()
            return True
        action = actions.get(key)
        if action is None:
            return False
        action()
        return True

    # ------------------------------------------------------------ botones
    def party_next(self, source: str = ""):
        if not self.dj_session_active():
            return
        self._party_event("Siguiente" + (f" ({source})" if source else ""))
        self.dj_skip()
        self.refresh_party_page()

    def party_pause(self):
        if not self.current_item_info:
            return
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.toggle_play_pause()
        self._party_event("Pausa" if playing else "Sigue la música")
        self.refresh_party_page()

    def party_energy(self, direction: int, quiet: bool = False) -> bool:
        """«Más energía» (+1) o «menos energía» (-1): reordena lo que queda con `dj_planner.retarget` (ver la explicación)."""
        if not self.dj_session_active() or not direction:
            return False
        pos = self._context_position()
        context = self._dj_context
        if pos < 0:
            return False
        if self._shuffle_active():
            self.toggle_shuffle()                    # el aleatorio del reproductor desharía el orden
        locked = self._party_next_locked()
        start = pos + (2 if locked else 1)
        if len(context) - start < 2:
            if not quiet:
                self.notify("No quedan canciones suficientes para cambiar la energía.")
            return False
        word = "Más energía" if direction > 0 else "Menos energía"
        try:
            tracks = [self._dj_track(info) for info in context[start:]]
            ordered = dj_planner.retarget(tracks, self._dj_track(context[start - 1]), direction)
            context[start:] = [t.ref for t in ordered]
        except Exception as e:                       # el orden de antes sigue valiendo: no se toca nada más
            log.exception("fiesta: no se pudo reordenar")
            self._party_event(f"{word}: no se pudo reordenar ({e})", logging.WARNING)
            return False
        self.reset_shuffle()
        if not quiet:
            self._party_last_energy = (1 if direction > 0 else -1, self._party_clock())
        if self.dj_engine_on() and not locked and self._dj_engine_session is not None:
            self._dj_engine_session.replan()         # la siguiente cambió y aún da tiempo: el motor rehace la mezcla
        self.dj_queue_changed()
        known = sum(t.energy is not None for t in tracks)
        note = " (la siguiente ya estaba preparada: cambia lo de después)" if locked else ""
        if not known:
            note += " Aún no se sabe la energía de las canciones: el cambio se notará cuando estén analizadas."
        if not quiet:
            self._party_event(f"{word}: cambia lo que viene{note}")
            self.notify(f"{word}.{note}")
        self.refresh_party_page()
        return True

    def _party_next_locked(self) -> bool:
        """¿La siguiente ya no se puede cambiar (su mezcla empieza en menos de `LOCK_S` o ya suena)?"""
        if self.playback_queue:
            return False                             # lo siguiente sale de la cola manual: la lista no lo toca
        position_s = self.player.position() / 1000.0
        if self.dj_engine_on():
            plan = self.dj_engine_plan()
            return plan is not None and plan.a_start_s - position_s < LOCK_S
        mix = self.dj_mix_plan()
        if mix is not None:
            return mix[1].a_start_s - position_s < LOCK_S
        duration = self.player.duration()
        return duration > 0 and (duration - self._fade_ms) / 1000.0 - position_s < LOCK_S

    def dj_replan(self, auto: bool = False) -> bool:
        """El orden inteligente de la sesión entera; en la fiesta, con el último «más / menos energía» reciente encima."""
        done = super().dj_replan(auto)
        last = self._party_last_energy
        if done and self._party_on and last is not None and self._party_clock() - last[1] < REAPPLY_ENERGY_S:
            self.party_energy(last[0], quiet=True)
        return done

    # ------------------------------------------------------------ historial
    def _party_event(self, text: str, level: int = logging.INFO):
        stamp = time.strftime("%H:%M:%S")
        self._party_events.append((stamp, text))
        log.log(level, "fiesta: %s", text)
        if self.page_party is not None:
            self.page_party.add_event(f"{stamp}  {text}")

    def party_events(self) -> list:
        return [text for _stamp, text in self._party_events]

    # ------------------------------------------------------------ vigilante
    def _party_watch(self):
        try:
            self._party_watch_step()
        except Exception as e:                       # el vigilante nunca rompe nada
            log.exception("fiesta: fallo en el vigilante")
            self._party_events.append((time.strftime("%H:%M:%S"), f"Fallo interno del vigilante: {e}"))
        try:
            self.refresh_party_page()
        except Exception:
            log.exception("fiesta: fallo al poner al día la pantalla")

    def _party_baseline(self):
        """Se empieza a contar de nuevo (tras pausa, carga, recuperación o un parón de la interfaz)."""
        self._party_last_pos = None
        self._party_last_change = None

    def _party_watch_step(self):
        now = self._party_clock()
        gap = None if self._party_last_tick is None else now - self._party_last_tick
        self._party_last_tick = now
        self._party_wire_player()
        active = self.dj_session_active()
        if self._party_want_page and active:
            self._party_follow_page()
        if not active:
            self._party_baseline()
            self._party_stopped_ticks = self._party_engine_stop_ticks = 0
            if self._party_was_active:
                self._party_gone_ticks += 1
                if self._party_gone_ticks >= SESSION_GONE_TICKS:
                    self._party_was_active = False
                    if self._party_crowd_running():
                        self.party_set_crowd(False)
                        self._party_event("La sesión DJ terminó: los votos del público se apagan")
            return
        self._party_was_active = True
        self._party_gone_ticks = 0
        key = track_key(self.current_item_info)
        if key != self._party_track:
            self._party_track, self._party_track_t = key, now
            if self._party_crowd is not None:
                self._party_crowd.reset(crowd_server.SKIP)      # los «pasar» eran de la canción anterior
        if gap is not None and gap > FROZEN_UI_S:
            self._party_baseline()                   # la interfaz estuvo parada, no el sonido
        if now < self._party_storm_until:
            return
        state = self.player.playbackState()
        has_next = self.peek_next() is not None
        if self.dj_engine_on() and self._party_check_engine(state, has_next):
            return
        if state == QMediaPlayer.PausedState:        # una pausa nunca es un fallo
            self._party_baseline()
            self._party_stopped_ticks = 0
            self._party_loading_since = None
            return
        if now < self._party_grace_until:
            self._party_baseline()
            return
        position, duration = self.player.position(), self.player.duration()
        at_end = not has_next and duration > 0 and position >= duration - END_MARGIN_MS
        if state == QMediaPlayer.StoppedState:
            self._party_baseline()
            if at_end or not has_next:
                return                               # se acabó la sesión
            self._party_stopped_ticks += 1
            if self._party_stopped_ticks >= STOPPED_TICKS:
                self._party_fail("el reproductor se ha parado solo")
            return
        self._party_stopped_ticks = 0
        if self._party_loading():
            self._party_baseline()
            if self._party_loading_since is None:
                self._party_loading_since = now
            elif now - self._party_loading_since > LOADING_MAX_S:
                self._party_fail(f"la canción no termina de cargar ({LOADING_MAX_S:.0f} s)")
            return
        self._party_loading_since = None
        if self._party_last_pos is None or abs(position - self._party_last_pos) > 40:
            self._party_last_pos, self._party_last_change = position, now
            return
        if now - self._party_last_change >= STALL_S:
            if at_end:
                self._party_baseline()
                return
            self._party_fail(f"la música no avanza desde hace {now - self._party_last_change:.0f} s")

    def _party_check_engine(self, state, has_next) -> bool:
        """Lo propio del motor: flujo perdido o sesión parada con canciones por delante. True si detectó un fallo. En pausa no
        se mira nada (si el flujo se perdiera en pausa, lo atiende `_dj_engine_lost`, que no quita la pausa)."""
        if state == QMediaPlayer.PausedState:
            self._party_engine_stop_ticks = 0
            return False
        engine = self._dj_engine
        if engine is not None and not engine.stream_active:
            self._party_fail("se ha cerrado la salida de audio del motor propio")
            return True
        player = self._dj_engine_player
        info = player.last_info if player is not None else {}
        if info.get("state") == "stopped" and has_next and self._party_clock() >= self._party_grace_until:
            self._party_engine_stop_ticks += 1
            if self._party_engine_stop_ticks >= STOPPED_TICKS:
                self._party_fail("la sesión del motor se ha quedado parada con canciones por delante")
                return True
        else:
            self._party_engine_stop_ticks = 0
        return False

    def _party_loading(self) -> bool:
        if self.dj_engine_on() and self._dj_engine_player is not None:
            if self._dj_engine_player.last_info.get("state") == "loading":
                return True
        return self.player.mediaStatus() in (QMediaPlayer.LoadingMedia, QMediaPlayer.BufferingMedia, QMediaPlayer.StalledMedia)

    def _party_wire_player(self):
        """Escucha los errores del reproductor que esté puesto (cambia al entrar y salir del motor propio)."""
        player = self.player
        if any(p is player for p in self._party_wired):
            return
        try:
            player.errorOccurred.connect(self._party_on_error)
            player.mediaStatusChanged.connect(self._party_on_status)
        except (AttributeError, RuntimeError, TypeError):
            return
        self._party_wired = [p for p in self._party_wired[-3:]] + [player]

    def _party_on_error(self, *args):
        if self._party_on and self.dj_session_active():
            text = next((a for a in args if isinstance(a, str) and a), "") or "sin detalle"
            track = track_key(self.current_item_info)
            QTimer.singleShot(0, lambda: self._party_fail(f"error del reproductor: {text}", force=True, track=track))

    def _party_on_status(self, status):
        if status == QMediaPlayer.InvalidMedia and self._party_on and self.dj_session_active():
            track = track_key(self.current_item_info)
            QTimer.singleShot(0, lambda: self._party_fail("no se pudo abrir la canción", force=True, track=track))

    def _dj_engine_lost(self, reason: str):
        """El flujo del motor se perdió: fuera de la fiesta se queda en pausa (ver DjEngineMixin); en la fiesta, se recupera
        (salvo si estaba en pausa: entonces también se queda en pausa, con el reproductor de siempre, en el mismo punto)."""
        paused = self.player.playbackState() == QMediaPlayer.PausedState
        if self._party_on and self.dj_session_active() and not paused:
            self._party_fail(f"se perdió la salida de audio del motor ({reason})", force=True)
            return
        super()._dj_engine_lost(reason)

    # ------------------------------------------------------------ recuperación
    def _party_fail(self, reason: str, force: bool = False, track=None):
        """Un fallo: se apunta y se aplica el escalón que toca. `force`: un error explícito (vale aunque se esté en el
        margen tras una recuperación: es justo el caso de «la siguiente no carga»). `track`: la canción que sonaba cuando
        llegó el error; si ya no es la actual, el error es de una canción que ya se dejó (un mismo archivo roto avisa dos
        veces: error y «no se puede abrir») y no cuenta."""
        try:
            if not self._party_on or not self.dj_session_active():
                return
            if track is not None and track != track_key(self.current_item_info):
                log.info("fiesta: aviso de error de una canción que ya no suena (%s): no cuenta", reason)
                return
            now = self._party_clock()
            if not force and now < self._party_grace_until:
                return
            while self._party_actions and now - self._party_actions[0] > STORM_S:
                self._party_actions.popleft()
            if len(self._party_actions) >= STORM_ACTIONS:
                self._party_storm_until = now + STORM_PAUSE_S
                self._party_actions.clear()
                self._party_event(f"Demasiados fallos seguidos: se espera {STORM_PAUSE_S:.0f} s antes de volver a intentarlo "
                                  f"({reason})", logging.ERROR)
                return
            self._party_level = self._party_level + 1 if now - self._party_last_fail < ESCALATE_S else 1
            self._party_last_fail = now
            self._party_event(f"Fallo: {reason}", logging.WARNING)
            self._party_recover(now)
        except Exception as e:
            log.exception("fiesta: fallo al recuperarse")
            self._party_event(f"No se pudo aplicar la recuperación: {e}", logging.ERROR)

    def _party_recover(self, now):
        level, previous = self._party_level, self._party_step
        self._party_actions.append(now)
        self._party_last_action = now
        self._party_grace_until = now + GRACE_S
        self._party_baseline()
        self._party_stopped_ticks = self._party_engine_stop_ticks = 0
        self._party_loading_since = None
        if self.dj_engine_on() and level <= 1:
            self._party_step = 1
            try:
                self._party_restart_engine()
                self._party_event("Escalón 1: se reinicia el motor de mezcla en la siguiente canción")
                return
            except Exception as e:
                log.warning("fiesta: no se pudo reiniciar el motor: %s", e)
                self._party_event(f"El motor no se pudo reiniciar ({e}): se pasa al reproductor de siempre", logging.WARNING)
        if self.dj_engine_on():
            self._party_step = 2
            self._party_leave_engine()
            self._party_event("Escalón 2: motor propio apagado; sigue el reproductor de siempre con su fundido")
            return
        self._party_step = 4 if previous in (3, 4) and level > 1 else 3
        if self._party_skip():
            self._party_event("Escalón 3: se salta a la siguiente canción" if self._party_step == 3
                              else "Escalón 4: la canción no cargaba; se salta a la siguiente")
        else:
            self._party_event("No quedan más canciones que poner", logging.ERROR)

    def _party_skip(self) -> bool:
        """Pasa a la siguiente que se pueda tocar. False si no queda ninguna."""
        for _ in range(50):
            self._dj_prune_next()
            nxt = self.peek_next()
            if nxt is None:
                return False
            try:
                self.play_next()
                self._party_wire_player()
                return True
            except Exception as e:
                log.warning("fiesta: no se pudo poner %s: %s", nxt.get("local_path"), e)
                self._dj_remove(nxt)
        return False

    def _party_restart_engine(self):
        """Escalón 1: el flujo de audio otra vez abierto si se cerró, la sesión del motor desde cero y la siguiente canción."""
        engine, session = self._dj_engine, self._dj_engine_session
        if engine is None or session is None:
            raise RuntimeError("el motor no está activo")
        if not engine.stream_active:
            engine.stop(fade=False)
            if not engine.start():
                raise RuntimeError(engine.last_error or "no se pudo abrir la salida de audio")
        session.stop(wait=False)
        if not self._party_skip():                   # era la última: la misma canción otra vez desde donde iba
            position = self.player.position()
            self.player.setPosition(position)
            self.player.play()

    def _party_leave_engine(self):
        """Escalón 2: fuera el motor propio; la cola sigue con el reproductor de siempre (y su fundido cruzado)."""
        path, position = (self.current_item_info or {}).get("local_path"), self.player.position()
        try:
            self.dj_engine_leave()
        except Exception as e:
            log.warning("fiesta: fallo al apagar el motor: %s", e)
        self._party_wire_player()
        if not self._party_skip() and path and os.path.isfile(path):
            self.play_local_file(path, start_ms=position)

    # ------------------------------------------------------------ votos del público
    def _party_crowd_running(self) -> bool:
        return self._party_crowd is not None and self._party_crowd.running

    @staticmethod
    def _party_crowd_host():
        return crowd_server.local_ip()

    def party_set_crowd(self, on: bool) -> bool:
        """Enciende o apaga el servidor de votos. Devuelve si quedó encendido."""
        on = bool(on)
        if on == self._party_crowd_running():
            self.refresh_party_page()
            return on
        if not on:
            server, self._party_crowd = self._party_crowd, None
            if server is not None:
                try:
                    server.stop()
                except Exception:
                    log.exception("fiesta: fallo al apagar los votos del público")
                self._party_event("Votos del público apagados")
            self.refresh_party_page()
            return False
        if not self._party_on:
            self._party_begin()
        host = self._party_crowd_host()
        try:
            if not host:
                raise ValueError("este equipo no está conectado a una red local (wifi o cable)")
            server = crowd_server.CrowdServer(host=host, on_signal=self._party_bridge.signal.emit)
            server.start()
        except (ValueError, OSError) as e:
            self._party_event(f"No se pudieron encender los votos del público: {e}", logging.WARNING)
            self.notify(f"No se pudieron encender los votos del público: {e}")
            if self.page_party is not None:
                self.page_party.set_crowd(False)
            return False
        self._party_crowd = server
        self._party_crowd_session = "publico-" + time.strftime("%Y%m%d-%H%M%S")
        self._party_crowd_vote = None
        self._party_qr = qr_pixmap(server.url)
        self._party_event(f"Votos del público encendidos en http://{server.host}:{server.port}/… (el enlace completo, en pantalla)")
        self.refresh_party_page()
        return True

    def _party_on_crowd(self, kind: str, counts: dict):
        """Un aviso del público (ya en el hilo de la ventana)."""
        try:
            if not self._party_on or not self.dj_session_active():
                return
            now = self._party_clock()
            if kind == crowd_server.LIKE:
                self._party_crowd_mix_vote(1, counts)
            elif kind == crowd_server.SKIP:
                song_s = now - self._party_track_t
                if song_s < CROWD_MIN_SONG_S or now - self._party_crowd_skip_t < CROWD_SKIP_COOLDOWN_S:
                    if self._party_crowd_told != self._party_track:          # se avisa una vez por canción
                        self._party_crowd_told = self._party_track
                        self._party_event("El público pide pasar, pero la canción acaba de empezar: se espera")
                    return
                self._party_crowd_skip_t = now
                self._party_crowd_mix_vote(-1, counts)
                self._party_crowd.reset(crowd_server.SKIP)
                self.party_next(source=f"lo pide el público: {counts.get('skip')} de {counts.get('connected')} conectados")
            elif kind == crowd_server.ENERGY:
                if now - self._party_crowd_energy_t < CROWD_ENERGY_COOLDOWN_S:
                    return
                self._party_crowd_energy_t = now
                self._party_crowd.reset(crowd_server.ENERGY)
                self._party_event(f"El público pide más energía ({counts.get('energy')} invitados)")
                self.party_energy(1)
        except Exception:
            log.exception("fiesta: fallo al atender un voto del público")

    def _party_crowd_mix_vote(self, vote: int, counts: dict):
        """El voto del público para la mezcla que suena o que acaba de sonar (ver la explicación del módulo)."""
        target = self.dj_vote_target()
        if target is None:
            return
        sounding = target is self._dj_mix_ctx
        if not sounding and self._party_clock() - self._party_track_t > CROWD_MIX_WINDOW_S:
            return
        a_path, b_path, plan = target
        key = (os.path.normcase(a_path), os.path.normcase(b_path), round(plan.a_start_s, 3))
        note = (f"público ({counts.get('connected', 0)} conectados): 👍 {counts.get('like', 0)} · "
                f"⏭ {counts.get('skip', 0)} · 🔥 {counts.get('energy', 0)}")
        source = "crowd" if "crowd" in transition_votes.SOURCES else "live"
        earlier = self._party_crowd_vote
        try:
            if earlier is not None and earlier[0] == key:
                if earlier[2] != vote and transition_votes.change_vote(earlier[1], vote, note=note):
                    self._party_crowd_vote = (key, earlier[1], vote)
                return
            vote_id = transition_votes.add_vote(plan, a_path, b_path, vote, source=source, session=self._party_crowd_session,
                                                note=note, a_info=self._dj_vote_info(a_path), b_info=self._dj_vote_info(b_path))
        except (ValueError, TypeError) as e:
            log.warning("fiesta: no se pudo guardar el voto del público: %s", e)
            return
        if vote_id is not None:
            self._party_crowd_vote = (key, vote_id, vote)

    # ------------------------------------------------------------ pantalla
    def _party_energy_text(self, info: dict) -> str:
        found = self._dj_analysis.get((info or {}).get("local_path")) or {}
        energy = found.get("energy") if found.get("loudness_db") is not None else None      # como `_dj_track`
        trend = ""
        last = self._party_last_energy
        if last is not None and self._party_clock() - last[1] < 180:
            trend = "   ▲ subiendo" if last[0] > 0 else "   ▼ bajando"
        if energy is None:
            return "Energía: sin analizar" + trend
        level = max(1, min(10, 1 + round(energy * 9)))
        return f"Energía {level}/10  " + "▮" * level + "▯" * (10 - level) + trend

    def refresh_party_page(self):
        page = self.page_party
        if page is None or self.stacked_widget.currentWidget() is not page:
            return
        if self.dj_session_active():
            info = self.current_item_info
            upcoming = self.upcoming_tracks(4)
            page.set_session(True, info, self.peek_next(), upcoming[1:4], self._party_energy_text(info),
                             playing=self.player.playbackState() != QMediaPlayer.PausedState)
        else:
            page.set_session(False)
        now = self._party_clock()
        stalled = self._party_last_change is not None and now - self._party_last_change > 2.0
        ok = now - self._party_last_action >= RECOVERING_S and now >= self._party_storm_until and not stalled
        page.set_status(ok, "Todo bien" if ok else "Recuperándose")
        server = self._party_crowd
        if server is not None and server.running:
            c = server.counts()
            counts = (f"👍 {c['like']}   ⏭ {c['skip']}/{c['skip_needed']}   🔥 {c['energy']}/{c['energy_needed']}   "
                      f"· {c['connected']} conectados")
            page.set_crowd(True, server.url, counts, CROWD_WARNING, self._party_qr)
        else:
            page.set_crowd(False)
