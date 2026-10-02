"""Lógica de reproducción estilo Spotify: contexto (lista que suena), historial, anterior/siguiente y aleatorio."""
import os
import random

from PySide6.QtMultimedia import QMediaPlayer

RESTART_THRESHOLD_MS = 20000  # 'anterior' reinicia la canción si ya han pasado 20 s


def track_key(info: dict) -> str:
    """Identificador estable de una canción, sea local o de internet."""
    local = info.get('local_path')
    if local:
        return 'L:' + os.path.normcase(os.path.abspath(local))
    return 'I:' + str(info.get('id') or info.get('url') or info.get('title'))


class PlaybackMixin:
    """Mezcla para MainWindow. Requiere: player, current_item_info, player_thumb, playback_queue,
    is_shuffle_enabled, play_local_file(), play_preview() y notify()."""

    def init_playback_state(self):
        self._history = []        # canciones anteriores (la última es la más reciente)
        self._forward = []        # canciones a las que se puede volver con 'siguiente' tras usar 'anterior'
        self._navigating = False  # True mientras se salta usando el historial
        self._context = []        # lista de canciones de la que se está reproduciendo (álbum, playlist, biblioteca...)

    # ---------- contexto ----------
    def set_context(self, tracks: list):
        """Define la lista de la que se está reproduciendo; 'siguiente' y 'anterior' se mueven solo dentro de ella."""
        self._context = list(tracks)

    def set_context_from_card(self, card):
        """El contexto son todas las canciones visibles junto a la tarjeta pulsada (misma lista o misma página)."""
        from ui.song_card import SongResultCard
        from ui.track_row import TrackRow
        parent = card.parentWidget()
        if parent is None:
            self._context = [card.item_info]
            return
        siblings = [c for c in parent.findChildren((SongResultCard, TrackRow)) if c.parentWidget() is parent]
        siblings.sort(key=lambda c: c.y())
        self._context = [c.item_info for c in siblings] or [card.item_info]

    def is_current(self, info: dict) -> bool:
        """True si `info` es la canción que está sonando ahora."""
        cur = self.current_item_info
        if not cur or not info:
            return False
        if track_key(cur) == track_key(info):
            return True
        return bool(cur.get("id")) and str(cur.get("id")) == str(info.get("id"))

    def _context_position(self) -> int:
        if not self.current_item_info or not self._context:
            return -1
        key = track_key(self.current_item_info)
        for i, t in enumerate(self._context):
            if track_key(t) == key:
                return i
        # canción descargada que en la lista figuraba por su id de internet
        cur_id = str(self.current_item_info.get('id'))
        for i, t in enumerate(self._context):
            if str(t.get('id')) == cur_id:
                return i
        return -1

    def upcoming_tracks(self, limit: int = 30) -> list:
        pos = self._context_position()
        if pos < 0:
            return []
        return self._context[pos + 1: pos + 1 + limit]

    # ---------- historial ----------
    def _snapshot(self) -> dict:
        return {'info': dict(self.current_item_info), 'pixmap': self.player_thumb.pixmap()}

    def _remember_current(self, new_info_or_key):
        """Guarda la canción actual antes de pasar a otra (si el cambio lo hace el usuario o la lista)."""
        if self._navigating or not self.current_item_info:
            return
        if isinstance(new_info_or_key, dict) and track_key(new_info_or_key) == track_key(self.current_item_info):
            return
        self._history.append(self._snapshot())
        del self._history[:-50]
        self._forward.clear()

    def _play_entry(self, info: dict, pixmap=None):
        if info.get('local_path'):
            self.play_local_file(info['local_path'])
        else:
            self.play_preview(info, None, pixmap)

    def _play_navigating(self, entry: dict):
        self._navigating = True
        try:
            self._play_entry(entry['info'], entry.get('pixmap'))
        finally:
            self._navigating = False

    # ---------- botones ----------
    def play_previous(self):
        """Como en Spotify: pasados 20 s reinicia la canción; antes de eso vuelve a la anterior."""
        if not self.current_item_info:
            return
        if self.player.position() > RESTART_THRESHOLD_MS:
            self._restart_current()
            return
        while self._history:
            entry = self._history.pop()
            if not self.playable(entry["info"]):      # sin conexión se saltan las que no están descargadas
                continue
            self._forward.append(self._snapshot())
            self._play_navigating(entry)
            return
        pos = self._context_position()
        for i in range(pos - 1, -1, -1):
            if self.playable(self._context[i]):
                self._play_entry(self._context[i])
                return
        self._restart_current()

    def _restart_current(self):
        self.player.setPosition(0)
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            self.player.play()

    def play_next(self):
        """Siguiente: primero la cola manual, luego lo que se dejó atrás con 'anterior', luego la lista."""
        if not self.current_item_info:
            return
        while self.playback_queue:
            nxt = self.playback_queue.pop(0)
            if self.playable(nxt):
                self._play_entry(nxt)
                return
        while self._forward:
            entry = self._forward.pop()
            if not self.playable(entry["info"]):
                continue
            self._history.append(self._snapshot())
            self._play_navigating(entry)
            return
        pos = self._context_position()
        if self.is_shuffle_enabled and len(self._context) > 1:
            options = [t for i, t in enumerate(self._context) if i != pos and self.playable(t)]
            if options:
                self._play_entry(random.choice(options))
                return
        elif pos >= 0:
            nxt = self.first_playable_index(self._context, pos + 1)
            if nxt >= 0:
                self._play_entry(self._context[nxt])
                return
        # Fin de la lista: se detiene pero el reproductor sigue visible
        self.player.stop()
        self.player_status.setText("Fin de la lista")
