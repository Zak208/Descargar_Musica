"""Modo DJ: votos 👍 / 👎 de las mezclas (fase 24). Los datos se guardan con `services/transition_votes.py`; aquí se sabe de qué
mezcla se vota (la que está sonando o, si no hay ninguna en marcha, la última que acabó) y se le pasan sus parámetros.

La mezcla se «recuerda» cuando está planificada (con el motor propio, el plan de la sesión; con el fundido de siempre, el plan
de `dj_mix_plan`) y pasa a ser «la última» cuando la canción siguiente toma el relevo. Votar dos veces la misma mezcla cambia el
voto (y los motivos) en vez de duplicarlo."""
import os
import time

from services import transition_votes

TAG_LABELS = {"desfase": "Golpes desfasados", "graves": "Graves chocando", "voces": "Voces solapadas", "volumen": "Salto de volumen",
              "corte_brusco": "Corte brusco", "tono": "Tonos que desentonan", "duracion": "Duración mal", "otro": "Otro motivo"}


def _key(path) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


class DjVotesMixin:
    """Mezcla para MainWindow. Requiere: _dj_analysis, _dj_context, _dj_title(), _dj_effective_bpm(), page_dj, notify(),
    player, dj_session_active()."""

    def init_dj_votes_state(self):
        self._dj_mix_ctx = None              # (ruta de A, ruta de B, plan) de la mezcla planificada para lo que suena
        self._dj_last_mix = None             # la última que acabó (la siguiente canción ya tomó el relevo)
        self._dj_vote_of = None              # (clave de la mezcla, id del voto) para cambiar el voto en vez de repetirlo
        self._dj_vote_session = ("", None)   # (identificador de la sesión de escucha, lista a la que pertenece)

    # ---- qué mezcla se vota -----------------------------------------------------------------------------------------
    def dj_note_mix(self, a_path: str, b_path: str, plan):
        """La mezcla de `a_path` a `b_path` está planificada con este `plan`."""
        if a_path and b_path and plan is not None:
            self._dj_mix_ctx = (a_path, b_path, plan)

    def dj_mix_happened(self, new_path: str):
        """Cambió la canción que suena: si es la que iba a entrar en la mezcla planificada, esa mezcla pasa a ser la última."""
        ctx = self._dj_mix_ctx
        if ctx is not None and _key(ctx[1]) == _key(new_path):
            self._dj_last_mix = ctx
        self._dj_mix_ctx = None

    def dj_vote_target(self):
        """(ruta de A, ruta de B, plan) de la mezcla que se votaría ahora, o None. Si la mezcla planificada ya ha empezado
        (se está oyendo), esa; si no, la última que acabó."""
        if not self.dj_session_active():
            return None
        ctx = self._dj_mix_ctx
        if ctx is not None and self.player.position() / 1000.0 >= ctx[2].a_start_s:
            return ctx
        return self._dj_last_mix or None

    def dj_vote_text(self) -> str:
        target = self.dj_vote_target()
        if target is None:
            return ""
        return f"«{self._dj_title(target[0])}» → «{self._dj_title(target[1])}»"

    # ---- votar --------------------------------------------------------------------------------------------------------
    def _dj_vote_info(self, path: str) -> dict:
        found = self._dj_analysis.get(path) or {}
        return {"title": self._dj_title(path), "bpm": self._dj_effective_bpm(path)[0] or found.get("bpm"),
                "tone": found.get("tone"), "energy": found.get("energy")}

    def _dj_vote_session_id(self) -> str:
        sid, owner = self._dj_vote_session
        if owner is not self._dj_context or not sid:
            sid = time.strftime("%Y%m%d-%H%M%S")
            self._dj_vote_session = (sid, self._dj_context)
        return sid

    def dj_vote(self, vote: int, tags: list = None):
        """Guarda un voto (+1 o -1, con motivos opcionales) de la mezcla que toca; si ya se había votado, lo cambia."""
        target = self.dj_vote_target()
        if target is None:
            self.notify("Aún no hay ninguna mezcla que votar: espera a que suene una.")
            return
        a_path, b_path, plan = target
        tags = list(tags or [])
        key = (_key(a_path), _key(b_path), round(plan.a_start_s, 3))
        earlier = self._dj_vote_of
        if earlier is not None and earlier[0] == key:
            ok = transition_votes.change_vote(earlier[1], vote, tags=tags)
            vote_id = earlier[1] if ok else None
        else:
            vote_id = transition_votes.add_vote(plan, a_path, b_path, vote, source="live", session=self._dj_vote_session_id(),
                                                tags=tags, a_info=self._dj_vote_info(a_path), b_info=self._dj_vote_info(b_path))
        if vote_id is None:
            self.notify("No se pudo guardar el voto.")
            return
        self._dj_vote_of = (key, vote_id)
        total = transition_votes.count()["total"]
        reason = f" ({', '.join(TAG_LABELS.get(t, t) for t in tags)})" if tags else ""
        text = ("👍 Mezcla buena" if vote > 0 else "👎 Mezcla mala") + f"{reason} guardada · {total} " + ("voto" if total == 1 else "votos")
        if self.page_dj is not None:
            self.page_dj.set_vote_status(text)
        self.notify(text)
