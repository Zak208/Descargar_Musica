"""Letras: abrirlas, editarlas, generarlas con el reconocedor de voz, sincronizarlas y medir el tiempo de cada palabra."""
import os
import time
from PySide6.QtCore import (
    Qt, QTimer
)
from PySide6.QtWidgets import (
    QWidget
)
from ui.dialogs import ask_confirm
from ui.friendly import friendly_error
from ui.lyrics_dialog import LyricsDialog
from ui.lyrics_editor import LyricsEditorDialog
from services import lyric_align, lyrics_store, transcribe_service
from services import word_timing


class LyricsMixin:
    """Mezcla para MainWindow."""

    def open_lyrics(self):
        """Abre la ventana de letras. Solo puede haber una: si ya está abierta, se trae al frente."""
        if not self.current_item_info:
            self.notify("Reproduce una canción primero para ver su letra.")
            return

        existing = self.lyrics_dialog
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.raise_()
                    existing.activateWindow()
                    return
            except RuntimeError:
                pass
            self.lyrics_dialog = None

        title = self.current_item_info.get('title', '')
        artist = self.current_item_info.get('uploader', '')
        dlg = LyricsDialog(title, artist, player=self.active_player, color=self._cover_color(), parent=self)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.destroyed.connect(lambda *_: setattr(self, 'lyrics_dialog', None))
        self.lyrics_dialog = dlg
        dlg.set_backdrop(None, self.player_thumb.pixmap())
        dlg.show()

    # ---------- letras propias y generadas por el sistema ----------
    def lyrics_key(self) -> str:
        """Identificador con el que se guardan las letras de la canción actual."""
        info = self.current_item_info
        if not info:
            return ""
        return lyrics_store.key_for(info.get("title", ""), info.get("uploader", ""))

    def _lyrics_host(self, origin=None):
        """Dónde mostrar los avisos y el editor: dentro de la ventana de letras si el usuario pulsó desde ella
        (si no, quedarían escondidos detrás), o en la ventana principal."""
        dlg = self.lyrics_dialog
        try:
            if isinstance(origin, QWidget) and dlg is not None and dlg.isVisible() and origin is dlg:
                return dlg
        except RuntimeError:
            self.lyrics_dialog = None
        self.raise_()
        self.activateWindow()
        return self

    def reload_lyrics(self):
        """Vuelve a cargar la letra en el panel y en la ventana de letras (tras editarla o generarla)."""
        if self.now_panel.isVisible():
            self.now_panel.lyrics.reload()
        else:
            self.now_panel._key = None
        dlg = self.lyrics_dialog
        try:
            if dlg is not None and dlg.isVisible():
                dlg.reload()
        except RuntimeError:
            self.lyrics_dialog = None

    def _lyrics_busy(self, text: str, percent: int = -1):
        """Aviso de trabajo en las dos vistas de la letra. percent: -1 sin barra, -2 barra que avanza sin porcentaje."""
        if self.lyrics_key() != getattr(self, "_busy_key", self.lyrics_key()):
            return      # mientras tanto cambió la canción: el aviso ya no corresponde a la que se ve
        self.now_panel.lyrics.set_busy(text, percent)
        dlg = self.lyrics_dialog
        try:
            if dlg is not None and dlg.isVisible():
                dlg.set_busy(text, percent)
        except RuntimeError:
            self.lyrics_dialog = None

    def _lyrics_result(self, message: str):
        """Resultado de generar la letra: toast en la ventana principal y nota visible también en la ventana de letras."""
        self.notify(message)
        self._lyrics_note = message

    def generate_lyrics(self, origin=None):
        """El programa escucha la canción descargada y escribe su letra (la primera vez descarga el reconocedor de voz)."""
        info = self.current_item_info
        path = info.get("local_path") if info else None
        if not path or not os.path.isfile(path):
            self._lyrics_result("Solo se puede generar la letra de canciones descargadas.")
            return
        job = getattr(self, "_lyrics_job", None)
        if job is not None and job.isRunning():
            self._lyrics_result("Ya se está generando una letra. Espera a que termine.")
            return
        self._busy_key = self.lyrics_key()
        self._lyrics_note = ""
        if not transcribe_service.is_ready():
            host = self._lyrics_host(origin)
            if not ask_confirm(
                    host, "Generar letras con el sistema",
                    f"Para escuchar las canciones el programa necesita un reconocedor de voz (unos {transcribe_service.DOWNLOAD_MB} MB). "
                    "Se descarga una sola vez, se guarda en tu equipo y después funciona sin internet.\n\n"
                    "La letra generada puede tener errores; podrás corregirla con «Editar». ¿Descargarlo ahora?",
                    ok="Descargar"):
                return
            setup = transcribe_service.SetupWorker(self)
            setup.progress.connect(lambda pct: self._lyrics_busy(f"Descargando el reconocedor de voz… {pct}%", pct))
            setup.done.connect(lambda: self._start_transcription(path))
            setup.failed.connect(lambda msg: self._on_lyrics_generation_failed(self._busy_key, f"No se pudo descargar: {friendly_error(msg)}"))
            self._lyrics_job = setup
            self._lyrics_busy("Descargando el reconocedor de voz… 0%", 0)
            setup.start()
            return
        self._start_transcription(path)

    # ---------- tiempo de cada palabra (para que el karaoke siga la voz) ----------
    _words_worker = None

    def ensure_word_timing(self, follower):
        """Aplica al karaoke los tiempos de cada palabra medidos con la voz. Si ya se midieron en esta canción se usan
        al momento; si no, y el reconocedor de voz ya está instalado, se miden una vez en segundo plano."""
        try:
            info = self.current_item_info or {}
            path = info.get("local_path")
            lines = [(ms, lbl.text()) for ms, lbl in follower.lines]
            if not lines or not path or not os.path.isfile(path):
                return
            key = self.lyrics_key()
            cached = word_timing.load_spans(key, lines)
            if cached is not None:
                follower.set_spans(cached)
                return
            worker = self._words_worker
            if worker is not None and worker.isRunning():
                if worker.key == key:
                    return
                worker.cancel()                 # otra canción: lo que se estaba midiendo ya no interesa
            if not transcribe_service.is_ready():
                return
            worker = word_timing.WordTimingWorker(path, key, lines, self)
            worker.done.connect(self._on_word_timing)
            self._words_worker = worker
            worker.start()
        except RuntimeError:
            pass

    def _on_word_timing(self, key: str, spans: list):
        if key != self.lyrics_key():
            return
        followers = [self.now_panel.lyrics.follower]
        dlg = self.lyrics_dialog
        try:
            if dlg is not None:
                followers.append(dlg.follower)
        except RuntimeError:
            self.lyrics_dialog = None
        for follower in followers:
            try:
                follower.set_spans(spans)
            except RuntimeError:
                pass

    # ---------- sincronizar una letra con la canción (tiempos automáticos) ----------
    _align_worker = None

    def _sync_lyrics(self, editor, phrases: list, audio_path: str):
        """El sistema escucha la canción y pone el tiempo a cada frase del editor."""
        if not audio_path or not os.path.isfile(audio_path):
            editor.set_sync_busy("Solo se puede con canciones descargadas.")
            return

        def go():
            worker = lyric_align.AlignWorker(audio_path, phrases, self)
            worker.progress.connect(lambda pct: editor.set_sync_busy(f"El sistema está escuchando la canción… {pct}%", pct))
            worker.done.connect(editor.apply_times)
            worker.failed.connect(lambda msg: editor.set_sync_busy(msg))
            self._align_worker = worker
            editor.set_sync_busy("El sistema está escuchando la canción…", -2)
            worker.start()

        if transcribe_service.is_ready():
            go()
            return
        if not ask_confirm(
                editor, "Poner los tiempos automáticamente",
                f"Para escuchar la canción el programa necesita un reconocedor de voz (unos {transcribe_service.DOWNLOAD_MB} MB). "
                "Se descarga una sola vez y después funciona sin internet. ¿Descargarlo ahora?", ok="Descargar"):
            editor.set_sync_busy("")
            return
        setup = transcribe_service.SetupWorker(self)
        setup.progress.connect(lambda pct: editor.set_sync_busy(f"Descargando el reconocedor de voz… {pct}%", pct))
        setup.done.connect(go)
        setup.failed.connect(lambda msg: editor.set_sync_busy(f"No se pudo descargar: {friendly_error(msg)}"))
        self._lyrics_job = setup
        editor.set_sync_busy("Descargando el reconocedor de voz… 0%", 0)
        setup.start()

    def _start_transcription(self, path: str):
        key = self.lyrics_key()
        worker = transcribe_service.TranscribeWorker(path, key, self)
        worker.progress.connect(self._on_transcription_progress)
        worker.done.connect(self._on_lyrics_generated)
        worker.failed.connect(self._on_lyrics_generation_failed)
        self._lyrics_job = worker
        self._transcribe_started = time.time()
        self._transcribe_percent = -2
        if not hasattr(self, "_transcribe_timer"):
            self._transcribe_timer = QTimer(self)
            self._transcribe_timer.setInterval(1000)
            self._transcribe_timer.timeout.connect(self._tick_transcription)
        self._transcribe_timer.start()
        self._tick_transcription()
        worker.start()

    def _on_transcription_progress(self, pct: int):
        self._transcribe_percent = pct
        self._tick_transcription()

    def _tick_transcription(self):
        """Mientras el sistema escucha, se ve que está trabajando: porcentaje y segundos transcurridos."""
        elapsed = int(time.time() - getattr(self, "_transcribe_started", time.time()))
        pct = getattr(self, "_transcribe_percent", -2)
        head = f"Escuchando la canción… {pct}%" if pct > 0 else "Escuchando la canción…"
        self._lyrics_busy(f"{head} ({elapsed} s). Puedes seguir usando la aplicación.", pct if pct > 0 else -2)

    def _stop_transcription_timer(self):
        timer = getattr(self, "_transcribe_timer", None)
        if timer is not None:
            timer.stop()

    def _on_lyrics_generated(self, key: str, _data: dict):
        self._stop_transcription_timer()
        self._lyrics_result("Letra generada. Revísala: puede tener errores.")
        if key == self.lyrics_key():
            self.reload_lyrics()

    def _on_lyrics_generation_failed(self, key: str, reason: str):
        self._stop_transcription_timer()
        self._lyrics_result(reason or "No se pudo generar la letra.")
        if key == self.lyrics_key():
            self.reload_lyrics()

    def edit_lyrics(self, origin=None):
        """Editor de letra: sirve para escribirla desde cero o corregir la que hay (la propia queda guardada y manda)."""
        info = self.current_item_info
        if not info:
            self.notify("Reproduce una canción primero.")
            return
        key = self.lyrics_key()
        data = self.now_panel.lyrics.data
        dlg_open = self.lyrics_dialog
        try:
            if data is None and dlg_open is not None and dlg_open.isVisible():
                data = dlg_open.lyrics_data
        except RuntimeError:
            self.lyrics_dialog = None
        text = ""
        if data:
            if data.get("is_synced") and data.get("synced_lines"):
                text = "\n".join(f"{lyrics_store.format_ms(ms)} {t}" for ms, t in data["synced_lines"])
            else:
                text = data.get("plain_text", "")
        stored = lyrics_store.load(key)
        host = self._lyrics_host(origin)
        local = info.get("local_path") or ""
        editor = LyricsEditorDialog(host, info.get("title", ""), text, player=self.active_player,
                                    can_restore=bool(stored and stored.get("source") == "user"),
                                    audio_path=local if os.path.isfile(local) else "")
        editor.sync_requested.connect(lambda phrases: self._sync_lyrics(editor, phrases, local))
        if editor.exec() != 1:
            if self._align_worker is not None and self._align_worker.isRunning():
                self._align_worker.cancel()
            return
        if editor.restore:
            lyrics_store.delete(key, "user")
            self.notify("Se ha vuelto a la letra original.")
        else:
            lyrics_store.save(key, editor.text, "user")
            self.notify("Letra guardada.")
        self.reload_lyrics()

    def _refresh_lyrics_if_open(self):
        """Si la ventana de letras está abierta, la cambia a la canción que acaba de empezar."""
        dlg = self.lyrics_dialog
        try:
            if dlg is not None and dlg.isVisible() and self.current_item_info:
                dlg.set_track(self.current_item_info.get('title', ''), self.current_item_info.get('uploader', ''),
                              self._cover_color())
                QTimer.singleShot(900, lambda: self._recolor_lyrics(dlg))   # la portada puede tardar en cargar
        except RuntimeError:
            self.lyrics_dialog = None

    def _recolor_lyrics(self, dlg):
        try:
            color = self._cover_color()
            if color is not None and dlg is self.lyrics_dialog:
                dlg.set_color(color, self.player_thumb.pixmap())
        except RuntimeError:
            pass
