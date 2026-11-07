"""Lógica de reproducción estilo Spotify: contexto (lista que suena), historial, anterior/siguiente y aleatorio."""
import logging
import os
import random

from PySide6.QtMultimedia import QMediaPlayer

logger = logging.getLogger(__name__)

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
        self._shuffle_plan = []   # con el aleatorio: el orden ya decidido de lo que viene (el que se muestra es el que suena)
        self._xf_request = 0      # >0 mientras se pide pasar a la siguiente canción con fundido cruzado (milisegundos)

    # ---------- contexto ----------
    def set_context(self, tracks: list):
        """Define la lista de la que se está reproduciendo; 'siguiente' y 'anterior' se mueven solo dentro de ella."""
        self._context = list(tracks)
        self._shuffle_plan = []

    def set_context_from_card(self, card):
        """El contexto son todas las canciones visibles junto a la tarjeta pulsada (misma lista o misma página)."""
        from ui.song_card import SongResultCard
        from ui.track_row import TrackRow
        self._shuffle_plan = []
        parent = card.parentWidget()
        if parent is None:
            self._context = [card.item_info]
            return
        cards = parent.findChildren(SongResultCard) if hasattr(parent, "findChildren") else []
        rows = parent.findChildren(TrackRow) if hasattr(parent, "findChildren") else []
        siblings = [c for c in (cards + rows) if c.parentWidget() is parent]
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

    @staticmethod
    def _same_track(a: dict, b: dict) -> bool:
        if not a or not b:
            return False
        if track_key(a) == track_key(b):
            return True
        return bool(a.get("id")) and str(a.get("id")) == str(b.get("id"))

    def _shuffle_active(self) -> bool:
        return bool(self.is_shuffle_enabled and len(self._context) > 1)

    def reset_shuffle(self):
        """El aleatorio se activó, se apagó o cambió la lista: el orden de lo que viene se decide de nuevo."""
        self._shuffle_plan = []

    def _ensure_shuffle_plan(self) -> list:
        """Con el aleatorio, el orden de las canciones que vienen se decide de antemano, una sola vez. Así lo que
        muestran «A continuación» y la cola es exactamente lo que va a sonar (y no se repite hasta agotar la lista)."""
        cur = self.current_item_info
        # qué está en la lista, por clave y por id (lo mismo que `_same_track`, sin comparar cada una con todas: con
        # miles de canciones, como en el modo DJ, comparar todas con todas congelaba la ventana varios segundos)
        keys = {track_key(c) for c in self._context}
        ids = {str(c.get("id")) for c in self._context if c.get("id")}
        plan = [t for t in self._shuffle_plan
                if not self._same_track(t, cur) and (track_key(t) in keys or (t.get("id") and str(t.get("id")) in ids))]
        if not any(self.playable(t) for t in plan):
            pool = [t for t in self._context if not self._same_track(t, cur) and self.playable(t)]
            random.shuffle(pool)
            plan = pool
        self._shuffle_plan = plan
        return plan

    def upcoming_tracks(self, limit: int = 30) -> list:
        if self._shuffle_active():
            return [t for t in self._ensure_shuffle_plan() if self.playable(t)][:limit]
        pos = self._context_position()
        if pos < 0:
            return []
        return self._context[pos + 1: pos + 1 + limit]

    def _next_in_context(self):
        """La siguiente canción de la lista (en orden, o la que ya tocaba en el aleatorio) que se puede reproducir."""
        if self._shuffle_active():
            return next((t for t in self._ensure_shuffle_plan() if self.playable(t)), None)
        pos = self._context_position()
        if pos >= 0:
            idx = self.first_playable_index(self._context, pos + 1)
            if idx >= 0:
                return self._context[idx]
        return None

    def peek_next(self):
        """Qué sonará después, sin cambiar nada: primero la cola que has añadido, luego lo que se dejó atrás con
        «anterior» y luego la lista. Es lo mismo que decide `play_next`."""
        for nxt in self.playback_queue:
            if self.playable(nxt):
                return nxt
        for entry in reversed(self._forward):
            if self.playable(entry["info"]):
                return entry["info"]
        return self._next_in_context()

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

    def _play_entry(self, info: dict, pixmap=None, crossfade_ms: int = 0):
        if not info.get('local_path') and hasattr(self, "resolve_local"):
            try:
                local = self.resolve_local(info)
                if local:
                    info['local_path'] = local
                    info['already_downloaded'] = True
            except Exception:
                pass
        if info.get('local_path'):
            self._xf_request = int(crossfade_ms) if crossfade_ms > 0 else getattr(self, "_xf_request", 0)
            try:
                self.play_local_file(info['local_path'])
            finally:
                self._xf_request = 0
        else:
            self.play_preview(info, None, pixmap)

    def _play_navigating(self, entry: dict, crossfade_ms: int = 0):
        self._navigating = True
        try:
            self._play_entry(entry['info'], entry.get('pixmap'), crossfade_ms)
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
        xf = self.crossfade_ms(natural=False)
        while self._history:
            entry = self._history.pop()
            if not self.playable(entry["info"]):      # sin conexión se saltan las que no están descargadas
                continue
            self._forward.append(self._snapshot())
            self._play_navigating(entry, xf)
            return
        pos = self._context_position()
        for i in range(pos - 1, -1, -1):
            if self.playable(self._context[i]):
                self._play_entry(self._context[i], crossfade_ms=xf)
                return
        self._restart_current()

    def _restart_current(self):
        self.player.setPosition(0)
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            self.player.play()

    def _try_autoplay(self, xf: int = 0) -> bool:
        from config import load_settings
        if not load_settings().get("autoplay_enabled", True):
            return False
        info = self.current_item_info
        if not info:
            return False
        artist = info.get("uploader") or info.get("artist") or ""
        title = info.get("title") or ""
        if not artist and not title:
            return False

        if not hasattr(self, "_autoplay_history"):
            self._autoplay_history = set()
        current_key = (title.lower().strip(), artist.lower().strip())
        self._autoplay_history.add(current_key)

        candidates = []
        from services.network_service import is_online, private_mode
        if is_online() and not private_mode() and artist:
            try:
                from services import http
                r = http.get(
                    "https://api.deezer.com/search",
                    params={"q": artist, "order": "RANKING", "limit": 15},
                    timeout=3
                )
                if r.status_code == 200:
                    for it in r.json().get("data", []):
                        t_name = it.get("title", "").strip()
                        art_name = it.get("artist", {}).get("name", "").strip()
                        key = (t_name.lower(), art_name.lower())
                        if key in self._autoplay_history:
                            continue
                        self._autoplay_history.add(key)
                        album_obj = it.get("album", {})
                        art_w = album_obj.get("cover_big") or album_obj.get("cover_medium") or ""
                        dur = int(it.get("duration", 0) or 0)
                        from services.timefmt import format_duration
                        candidates.append({
                            "title": t_name,
                            "uploader": art_name,
                            "album": album_obj.get("title", ""),
                            "duration_secs": dur,
                            "duration_str": format_duration(dur, blank_zero=False),
                            "thumbnail": art_w,
                            "url": f"ytsearch1:{art_name} {t_name}",
                            "id": str(it.get("id", "")),
                            "is_autoplay": True
                        })
                        if len(candidates) >= 5:
                            break
            except Exception as e:
                logger.debug(f"Error buscando autoplay online: {e}")

        if not candidates and hasattr(self, "_lib_items") and self._lib_items:
            import random
            available = [
                i for i in self._lib_items
                if (i.get("title", "").lower().strip(), (i.get("uploader") or "").lower().strip()) not in self._autoplay_history
            ]
            if available:
                random.shuffle(available)
                candidates = available[:5]

        if not candidates:
            return False

        nxt = candidates[0]
        nxt["is_autoplay"] = True
        self.playback_queue.extend(candidates[1:])
        self._context.append(nxt)
        if hasattr(self, "notify"):
            self.notify(f"Reproducción automática · {nxt.get('title', '')}")
        self._play_entry(nxt, crossfade_ms=xf)
        return True

    def play_next(self, natural: bool = False, force_crossfade_ms: int = 0):
        """Siguiente: primero la cola manual, luego lo que se dejó atrás con 'anterior', luego la lista.
        `natural`: lo pide el fundido cruzado al acercarse el final de la canción.
        `force_crossfade_ms`: si es > 0, fuerza la duración de mezcla (DJ 'Mezclar Ahora')."""
        if not self.current_item_info:
            return
        xf = int(force_crossfade_ms) if force_crossfade_ms > 0 else self.crossfade_ms(natural)
        while self.playback_queue:
            nxt = self.playback_queue.pop(0)
            if self.playable(nxt):
                self._play_entry(nxt, crossfade_ms=xf)
                return
        while self._forward:
            entry = self._forward.pop()
            if not self.playable(entry["info"]):
                continue
            self._history.append(self._snapshot())
            self._play_navigating(entry, xf)
            return
        nxt = self._next_in_context()
        if nxt is not None:
            self._shuffle_plan = [t for t in self._shuffle_plan if not self._same_track(t, nxt)]
            self._play_entry(nxt, crossfade_ms=xf)
            return
        # Si no hay más temas, continuar con Autoplay inteligente
        if self._try_autoplay(xf):
            return
        # Fin de la lista: se detiene pero el reproductor sigue visible
        self.player.stop()
        self.player_status.setText("Fin de la lista")
