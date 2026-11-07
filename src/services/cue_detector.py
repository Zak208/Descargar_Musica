"""Detector inteligente de puntos de entrada (Cue Points) para canciones en el modo DJ.

En una sesión DJ profesional, las canciones NUNCA se mezclan empezando en el segundo 0.0:
los primeros segundos casi siempre contienen silencio digital, ruido ambiente, una intro
lenta o una cuenta de baquetas sin ritmo. Un DJ profesional coloca el punto de entrada (Cue)
en la primera bajada con fuerza (drop), en el final de la intro o en el primer compás donde
la batería y el bajo marcan el ritmo con energía.
"""
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_CUE_S = 15.0       # caída típica al compás 16 en música pop / urbana / electrónica
MIN_DROP_S = 4.0           # un drop a menos de 4s es casi el principio
MAX_CUE_SHARE = 0.40       # el punto de cue no puede pasar del 40% de la canción


def get_track_cue_point(analysis: dict | None, track_path: str = None, duration_s: float = None) -> float:
    """Calcula el mejor punto de entrada (Cue Point en segundos) para mezclar la pista que entra.

    Prioridad:
    1. Primer 'drop' relevante detectado en la estructura musical (entre 4s y 45s).
    2. Final de la intro calculada por análisis de envolvente (intro_ms / 1000.0).
    3. Primer golpe de compás detectado (beat_first_s) si no hay drop.
    4. Compás 8 o 16 según el tempo estimado.
    """
    analysis = analysis or {}
    dur = float(duration_s or analysis.get("duration_s") or (analysis.get("duration_ms", 0) / 1000.0) or 0.0)
    max_s = dur * MAX_CUE_SHARE if dur > 0 else 60.0

    # 1. Buscar en los eventos de estructura: caídas de ritmo (drops)
    structure = analysis.get("structure")
    if isinstance(structure, str) and structure:
        try:
            import json
            structure = json.loads(structure)
        except Exception:
            structure = None

    if isinstance(structure, dict):
        events = structure.get("events") or []
        drops = [float(e.get("t", 0.0)) for e in events if e.get("type") == "drop"]
        # Filtrar drops que estén en la primera mitad/tercio de la canción
        valid_drops = [d for d in drops if MIN_DROP_S <= d <= max_s and d <= 45.0]
        if valid_drops:
            cue = valid_drops[0]
            logger.debug(f"Cue point detectado por drop de estructura: {cue:.2f}s")
            return round(cue, 3)

        # Si hay secciones identificadas, buscar inicio de 'verse' o 'drop' tras intro
        sections = structure.get("sections") or []
        for sec in sections:
            kind = sec.get("kind")
            start = float(sec.get("start", 0.0))
            if kind in ("verse", "drop", "build") and MIN_DROP_S <= start <= max_s:
                logger.debug(f"Cue point detectado por inicio de sección '{kind}': {start:.2f}s")
                return round(start, 3)

    # 2. Intro detectada por energía de envolvente (track_analysis.analyze_envelope)
    intro_ms = analysis.get("intro_ms") or (analysis.get("intro_s", 0) * 1000.0)
    if intro_ms and intro_ms > 0:
        intro_s = float(intro_ms) / 1000.0
        if MIN_DROP_S <= intro_s <= max_s and intro_s <= 45.0:
            logger.debug(f"Cue point detectado por fin de intro energética: {intro_s:.2f}s")
            return round(intro_s, 3)

    # 3. Primer golpe de compás registrado por la rejilla (beat_first_s)
    beat_first = analysis.get("beat_first_s")
    bpm = analysis.get("beat_bpm") or analysis.get("bpm")
    if bpm and bpm > 0:
        bar_s = (60.0 / bpm) * 4.0
        # Típicamente los compases 4, 8 o 16 marcan el inicio del groove
        for candidate_bars in (16, 8, 4):
            candidate_s = (beat_first or 0.0) + (bar_s * candidate_bars)
            if MIN_DROP_S <= candidate_s <= min(max_s, 35.0):
                logger.debug(f"Cue point calculado por compás {candidate_bars}: {candidate_s:.2f}s")
                return round(candidate_s, 3)

    if beat_first and MIN_DROP_S <= float(beat_first) <= max_s:
        return round(float(beat_first), 3)

    # 4. Si hay archivo en disco y aún no está analizado, estimar con análisis rápido
    if track_path and os.path.isfile(track_path):
        try:
            from services import track_analysis
            quick = track_analysis.stored(track_path)
            if quick and quick is not analysis:
                return get_track_cue_point(quick, None, dur)
        except Exception as e:
            logger.debug(f"No se pudo consultar análisis almacenado para cue: {e}")

    # 5. Si la canción tiene duración suficiente pero sin análisis, usar 12s-16s por defecto
    if dur > 60.0:
        fallback = min(DEFAULT_CUE_S, dur * 0.15)
        return round(fallback, 3)

    return 0.0
