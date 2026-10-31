"""Sesión de votos (fase 27): ventana que va enseñando clips de transiciones (las que más dudas le crean al modelo de gusto) para
votarlos 👍 / 👎. La lógica está en services/vote_session.py; aquí solo se reproduce, se vota y se avisa.

  * Reproduce cada clip con un `QMediaPlayer` propio, al volumen del programa: no toca el motor DJ ni el reproductor de la
    ventana (si la música sigue sonando, se avisa para que la pause).
  * Mientras se escucha un clip, el siguiente se renderiza en un hilo (`ClipRenderWorker`); al votar o saltar suena al momento.
  * Atajos: 1 o → buena, 2 o ← mala (sin motivo), R repetir, S o ↓ saltar, espacio pausa. 👎 con el ratón abre los motivos.
  * A los 35 minutos avisa de que conviene descansar (el plan: cansado se vota distinto y el modelo se confunde).
  * Los hilos de render sobreviven a la ventana (si se cierra a medio renderizar, el clip se acaba y se tira) y se esperan al
    salir de la aplicación (`wait_workers`)."""
import logging
import time

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout

from services import vote_session
from services.transition_votes import TAGS
from ui.dj_votes_mixin import TAG_LABELS
from ui.overlay import InlineDialog
from ui.widgets import ElidedLabel

logger = logging.getLogger(__name__)

ACCENT = "#F8C700"              # amarillo corporativo: solo para el aviso de descanso
LIVE = "#1ED760"                # el verde de la cuenta atrás de la página DJ: «suena la mezcla»
BREAK_CHECK_MS = 15000
MAX_FAILS = 5                   # clips seguidos que no se pudieron preparar antes de rendirse
KIND_LABELS = {"blend": "mezcla larga", "cut_bar": "corte en el compás", "echo_out": "eco de salida", "filter": "filtro",
               "cut": "corte limpio"}

_RUNNING = set()                # hilos de render vivos (de cualquier ventana de votos)


class ClipRenderWorker(QThread):
    """Renderiza un clip (`vote_session.render_clip`) en segundo plano."""
    done = Signal(object)                    # la candidata ya con su clip
    failed = Signal(object, str)             # (candidata, motivo)

    def __init__(self, candidate: dict, protect=()):
        super().__init__(None)
        self.candidate, self.protect = candidate, tuple(protect)

    def run(self):
        self.setPriority(QThread.LowPriority)
        try:
            result = vote_session.render_clip(self.candidate, protect=self.protect)
        except Exception as e:
            logger.warning("no se pudo preparar el clip: %s", e)
            self.failed.emit(self.candidate, str(e))
            return
        self.done.emit(result)


class _Reaper(QObject):
    """Recoge los hilos que terminan (vive en el hilo de la interfaz, aunque la ventana de votos ya no exista)."""

    @Slot()
    def reap(self):
        worker = self.sender()
        _RUNNING.discard(worker)
        if worker is not None:
            worker.deleteLater()


_reaper = None


def _start_worker(candidate, on_done, on_failed, protect=()) -> ClipRenderWorker:
    global _reaper
    if _reaper is None:
        _reaper = _Reaper()
    worker = ClipRenderWorker(candidate, protect)
    worker.done.connect(on_done)
    worker.failed.connect(on_failed)
    worker.finished.connect(_reaper.reap)
    _RUNNING.add(worker)
    worker.start()
    return worker


def running_workers() -> int:
    return sum(1 for w in list(_RUNNING) if w.isRunning())


def wait_workers(timeout_ms: int = 10000) -> bool:
    """Espera a que acaben los renders en marcha (al salir de la aplicación). True si no queda ninguno."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    for worker in list(_RUNNING):
        left = int(max(0.0, deadline - time.monotonic()) * 1000)
        if worker.isRunning():
            worker.wait(left)
    return running_workers() == 0


def _mmss(seconds) -> str:
    seconds = max(0, int(round(seconds or 0)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def describe(candidate: dict) -> str:
    """«Mezcla de 8 compases (16 s) · filtro · la que entra +2,1 % de tempo»."""
    plan = candidate.get("plan")
    kind = candidate.get("kind") or ""
    parts = []
    length = getattr(plan, "length_s", None) or candidate.get("length_s") or 0.0
    if kind == "cut" or length <= 0:
        parts.append("corte limpio, sin mezcla")
    else:
        bpm = candidate.get("a_bpm")
        bars = f"{round(length * bpm / 240)} compases " if bpm else ""
        parts.append(f"mezcla de {bars}({round(length)} s)")
        parts.append(KIND_LABELS.get(kind, kind))
        ratio = getattr(plan, "tempo_ratio_b", None) or candidate.get("tempo_ratio_b") or 1.0
        if abs(ratio - 1.0) >= 0.001:
            parts.append(f"la que entra {(ratio - 1) * 100:+.1f} % de tempo".replace(".", ","))
    text = " · ".join(parts)
    return text[:1].upper() + text[1:]


class VoteDialog(InlineDialog):
    """Ventana de la sesión de votos. `volume`: número de 0 a 1 o función que lo da (se lee al empezar cada clip)."""
    voted = Signal(int)                      # id del voto guardado

    def __init__(self, parent, session, volume=1.0, music_playing: bool = False):
        super().__init__(parent)
        self.session = session
        self._volume = volume
        self._current = None                 # clip que suena (candidata renderizada)
        self._next = None                    # el siguiente, ya renderizado
        self._pending = None                 # hilo que está renderizando
        self._fails = 0
        self._closing = False
        self._break_shown = False
        self.last_vote_id = None
        self.setWindowTitle("Sesión de votos")
        self.setMinimumWidth(560)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._on_position)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self._build(music_playing)
        self._break_timer = QTimer(self)
        self._break_timer.setInterval(BREAK_CHECK_MS)
        self._break_timer.timeout.connect(self.check_break)
        self._break_timer.start()

    # ---- interfaz
    def _build(self, music_playing):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 22)
        lay.setSpacing(12)
        head = QLabel("Sesión de votos")
        head.setObjectName("SectionTitle")
        head.setStyleSheet("font-size: 20px;")
        lay.addWidget(head)
        body = QLabel("Escucha cada mezcla y di si te gusta. El DJ te enseña las que más dudas le crean, así cada voto le enseña más. "
                      "Atajos: 1 o → buena, 2 o ← mala, R repetir, S saltar, espacio pausa.")
        body.setObjectName("DialogBody")
        body.setWordWrap(True)
        lay.addWidget(body)
        self.music_warning = QLabel("La música del reproductor sigue sonando: páusala para oír bien las mezclas.")
        self.music_warning.setObjectName("SectionSubtitle")
        self.music_warning.setWordWrap(True)
        self.music_warning.setVisible(bool(music_playing))
        lay.addWidget(self.music_warning)

        card = QFrame()
        card.setObjectName("PanelCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(20, 16, 20, 16)
        card_lay.setSpacing(4)
        cap = QLabel("ESTA MEZCLA")
        cap.setStyleSheet("font-size: 11px; font-weight: 800; color: #B3B3B3; letter-spacing: 1px; background: transparent;")
        card_lay.addWidget(cap)
        self.pair_label = ElidedLabel("")
        self.pair_label.setStyleSheet("font-size: 18px; font-weight: bold; background: transparent;")
        card_lay.addWidget(self.pair_label)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("SectionSubtitle")
        self.detail_label.setWordWrap(True)
        card_lay.addWidget(self.detail_label)
        self.time_label = QLabel("")
        self.time_label.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {LIVE}; background: transparent;")
        card_lay.addWidget(self.time_label)
        lay.addWidget(card)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_up = self._button("👍 Buena", "La mezcla te gusta (tecla 1 o →)", self.vote_up)
        self.btn_down = self._button("👎 Mala", "La mezcla no te gusta; puedes decir qué falló (tecla 2 o ← sin motivo)", None)
        menu = QMenu(self.btn_down)
        menu.addAction("Sin motivo").triggered.connect(lambda: self.vote_down([]))
        menu.addSeparator()
        for tag in TAGS:
            menu.addAction(TAG_LABELS.get(tag, tag)).triggered.connect(lambda _=False, t=tag: self.vote_down([t]))
        self.btn_down.setMenu(menu)
        self.btn_repeat = self._button("Repetir", "Volver a oír el clip desde el principio (tecla R)", self.repeat)
        self.btn_skip = self._button("Saltar", "Pasar a otra sin votar (tecla S o ↓)", self.skip)
        for btn in (self.btn_up, self.btn_down, self.btn_repeat, self.btn_skip):
            row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("SectionSubtitle")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)
        self.counter_label = QLabel("")
        self.counter_label.setObjectName("SectionSubtitle")
        self.counter_label.setWordWrap(True)
        lay.addWidget(self.counter_label)
        self.break_label = QLabel("Llevas más de 35 minutos votando: descansa un rato. Cansado se vota distinto y el modelo se confunde.")
        self.break_label.setWordWrap(True)
        self.break_label.setStyleSheet(f"font-weight: 700; color: {ACCENT}; background: transparent;")
        self.break_label.hide()
        lay.addWidget(self.break_label)

        bottom = QHBoxLayout()
        bottom.addStretch()
        close = QPushButton("Terminar")
        close.setObjectName("GiantActionBtn")
        close.setCursor(Qt.PointingHandCursor)
        close.setFocusPolicy(Qt.NoFocus)
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        self._set_buttons(False)

    def _button(self, text, tip, slot):
        btn = QPushButton(text)
        btn.setObjectName("TopPillBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tip)
        btn.setFocusPolicy(Qt.NoFocus)           # las teclas son para la ventana (las flechas no mueven el foco)
        if slot is not None:
            btn.clicked.connect(slot)
        return btn

    def _set_buttons(self, enabled: bool):
        for btn in (self.btn_up, self.btn_down, self.btn_repeat, self.btn_skip):
            btn.setEnabled(enabled)

    def _show_waiting(self, text: str):
        self.pair_label.setText(text)
        self.detail_label.setText("")
        self.time_label.setText("")

    def refresh_counter(self):
        st = self.session.status
        text = f"{self.session.progress_text()} · Modelo: {st['text']}"
        if st.get("detail"):
            text += f" ({st['detail']})"
        self.counter_label.setText(text)

    # ---- ciclo de clips
    def start(self):
        """Empieza: prepara el primer clip (y, en cuanto suene, el siguiente)."""
        self.refresh_counter()
        self._show_waiting("Preparando la primera mezcla…")
        self.setFocus()
        self._request_render()

    def is_busy(self) -> bool:
        return self._pending is not None

    @property
    def current(self):
        return self._current

    def _request_render(self):
        if self._closing or self._pending is not None:
            return
        candidate = self.session.take_next()
        if candidate is None:
            if self._current is None and self._next is None:
                self._show_waiting("No quedan mezclas nuevas con estas canciones. ¡Gracias por votar!")
            return
        protect = tuple(c["clip_path"] for c in (self._current, self._next) if c)
        self._pending = _start_worker(candidate, self._on_rendered, self._on_render_failed, protect)

    def _on_rendered(self, result):
        self._pending = None
        if self._closing:
            return
        self._fails = 0
        if self._current is None:
            self._play(result)
        else:
            self._next = result

    def _on_render_failed(self, candidate, message):
        self._pending = None
        if self._closing:
            return
        self.session.mark_failed(candidate)
        self._fails += 1
        if self._fails >= MAX_FAILS:
            if self._current is None:
                self._show_waiting("No se pudo preparar ninguna mezcla")
                self.status_label.setText(f"Último error: {message}")
            return
        self._request_render()

    def _current_volume(self) -> float:
        try:
            value = self._volume() if callable(self._volume) else self._volume
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return 1.0

    def set_volume(self, value: float):
        self._volume = value
        self.audio.setVolume(self._current_volume())

    def _play(self, result):
        self._current = result
        self.player.stop()
        self.audio.setVolume(self._current_volume())
        self.player.setSource(QUrl.fromLocalFile(result["clip_path"]))
        self.player.play()
        self.pair_label.setText(f"«{result.get('a_title', '')}» → «{result.get('b_title', '')}»")
        self.detail_label.setText(describe(result))
        self._on_position(0)
        self._set_buttons(True)
        if self._next is None:
            self._request_render()

    def _advance(self):
        self._current = None
        self._set_buttons(False)
        self.player.stop()
        if self._next is not None:
            nxt, self._next = self._next, None
            self._play(nxt)
        else:
            self._show_waiting("Preparando la siguiente mezcla…")
            self._request_render()

    def _on_position(self, ms):
        c = self._current
        if c is None:
            return
        pos = ms / 1000.0
        start, end = c.get("mix_start_s", 0.0), c.get("mix_end_s", 0.0)
        total = f"{_mmss(pos)} / {_mmss(c.get('clip_s', 0.0))}"
        if end - start < 0.05:
            where = "▶ Ahora: el corte" if abs(pos - start) < 1.0 else f"el corte llega a los {_mmss(start)}"
        elif start <= pos <= end:
            where = "▶ Ahora suena la mezcla"
        else:
            where = f"la mezcla va de {_mmss(start)} a {_mmss(end)}" if pos < start else "la mezcla ya pasó (R para repetir)"
        self.time_label.setText(f"{total} · {where}")

    def _on_media_status(self, status):
        if status == QMediaPlayer.InvalidMedia and self._current is not None:
            self.status_label.setText("No se pudo reproducir el clip: pulsa «Saltar».")

    # ---- acciones
    def vote_up(self):
        self._vote(1, [])

    def vote_down(self, tags=None):
        self._vote(-1, list(tags or []))

    def _vote(self, vote, tags):
        if self._current is None:
            return
        vote_id = self.session.vote(self._current, vote, tags)
        if vote_id is None:
            self.status_label.setText("No se pudo guardar el voto.")
            return
        self.last_vote_id = vote_id
        reason = f" ({', '.join(TAG_LABELS.get(t, t) for t in tags)})" if tags else ""
        self.status_label.setText(("👍 Buena" if vote > 0 else "👎 Mala") + reason + " · guardado")
        self.refresh_counter()
        self.voted.emit(vote_id)
        self._advance()

    def skip(self):
        if self._current is None:
            return
        self.session.skip(self._current)
        self.status_label.setText("Saltada: no cuenta como voto.")
        self._advance()

    def repeat(self):
        if self._current is None:
            return
        self.player.setPosition(0)
        self.player.play()

    def toggle_pause(self):
        if self._current is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def check_break(self):
        if not self._break_shown and self.session.needs_break():
            self._break_shown = True
            self.break_label.show()

    def keyPressEvent(self, event):
        key = event.key()
        actions = {Qt.Key_1: self.vote_up, Qt.Key_Right: self.vote_up, Qt.Key_2: self.vote_down, Qt.Key_Left: self.vote_down,
                   Qt.Key_R: self.repeat, Qt.Key_S: self.skip, Qt.Key_Down: self.skip, Qt.Key_Space: self.toggle_pause}
        action = actions.get(key)
        if action is not None and event.modifiers() in (Qt.NoModifier, Qt.KeypadModifier):
            action()
            event.accept()                   # que no llegue a la ventana (allí espacio y flechas mueven el reproductor)
            return
        super().keyPressEvent(event)

    def done(self, result: int):
        if not self._closing:
            self._closing = True
            self._break_timer.stop()
            self.player.stop()
            self.player.setSource(QUrl())    # suelta el archivo (en Windows, si no, no se puede borrar)
            if self._pending is not None:    # el render en marcha acaba solo; su resultado ya no se usa
                for signal in (self._pending.done, self._pending.failed):
                    try:
                        signal.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                self._pending = None
        super().done(result)
