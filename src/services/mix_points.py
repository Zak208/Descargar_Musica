"""Punto de mezcla del modo DJ (fase 8): dónde empieza a irse la canción que suena (A), desde dónde entra la siguiente
(B) y cuánto dura la mezcla, a partir del análisis de cada una (intro y final, ver `track_analysis`).

Es aritmética pura, sin Qt ni numpy. La regla, como la aplicaría un DJ:

1. **Salida de A.** Si A tiene un final claro (`outro`) de al menos 8 s que no empieza antes de la mitad de la canción,
   la mezcla empieza justo al principio de ese final: es la parte que la canción deja para mezclar (suele ser solo ritmo).
   Si no lo tiene, la mezcla es corta (6 s) y acaba con la canción.
2. **Entrada de B.** La idea es que la intro de B suene encima del final de A y que el cuerpo de B (donde entra la
   canción de verdad) llegue justo cuando A termina de irse, para que nunca suenen dos cuerpos a la vez:
   - si la intro de B es más larga que la mezcla, B no entra desde el segundo 0 sino desde el punto de su intro que hace
     que su cuerpo caiga al final de la mezcla (así tampoco se oye el silencio o el arranque del principio);
   - si la intro de B es más corta, B entra desde el principio y la mezcla se acorta a lo que dura su intro;
   - si B no tiene intro clara (o no se sabe), entra desde el principio con una mezcla corta (6 s como mucho), porque
     entra con todo y una mezcla larga pisaría A.
3. **Límites.** La mezcla dura de 2 a 32 s y nunca más de un tercio de cualquiera de las dos canciones (con canciones
   muy cortas, la mezcla se las comería). Si así no llega a 2 s, o no se sabe cuánto dura A, **corte limpio**: B entra
   cuando A termina.

El tempo (`bpm`) no se usa aquí: sin rejilla de golpes no se puede cuadrar la mezcla con los compases. Eso lo hace
`mix_planner` (fase 13), que parte de este mismo punto.

Las canciones llegan como un dict con el análisis de `track_analysis` (`duration_ms`, `intro_ms`, `outro_ms`...) o como la
ficha de `mix_types` (`duration_s`, `intro_s`, `outro_s`); lo que falte o no sea un número se toma como «no se sabe»."""
import math

from services.mix_types import KIND_BLEND, KIND_CUT, TransitionPlan

MIN_OUTRO_S = 8.0           # un final más corto no da para mezclar: mezcla corta al acabar
MIN_INTRO_S = 2.0           # una intro más corta es como no tener intro
DEFAULT_MIX_S = 6.0         # mezcla corta cuando no hay final o intro claros
MIN_MIX_S = 2.0
MAX_MIX_S = 32.0
TRACK_SHARE = 3.0           # la mezcla no pasa de un tercio de ninguna de las dos canciones


def seconds(info: dict, name: str):
    """`name` («duration», «intro», «outro») de una canción, en segundos (de `name_s` o de `name_ms`), o None si no se
    sabe (falta, no es un número o es negativo)."""
    if not isinstance(info, dict):
        return None
    value = info.get(name + "_s")
    if value is None and info.get(name + "_ms") is not None:
        value = info.get(name + "_ms")
        value = value / 1000.0 if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def cut(a_end_s: float, b_start_s: float, reason: str) -> TransitionPlan:
    """Corte limpio: A suena hasta `a_end_s` y B entra entera desde `b_start_s`."""
    return TransitionPlan(a_start_s=round(max(0.0, a_end_s or 0.0), 3), b_start_s=round(max(0.0, b_start_s or 0.0), 3),
                          length_s=0.0, kind=KIND_CUT, reason=reason)


def fmt_seconds(s: float) -> str:
    return f"{s:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " s"


def plan(a: dict, b: dict, a_duration_s: float = None) -> TransitionPlan:
    """Punto de mezcla de A (la que suena) hacia B (la que entra). `a_duration_s`: duración real de A si se sabe mejor que
    la del análisis (por ejemplo, la que da el reproductor). Nunca falla: con datos que faltan devuelve un corte limpio."""
    a_dur = a_duration_s if isinstance(a_duration_s, (int, float)) and a_duration_s > 0 else seconds(a, "duration")
    if not a_dur:
        return cut(0.0, 0.0, "corte limpio: no se sabe cuánto dura la canción que suena")
    b_dur = seconds(b, "duration") or None
    outro, intro = seconds(a, "outro"), seconds(b, "intro")

    # 1. Salida de A
    good_outro = outro is not None and outro >= MIN_OUTRO_S and a_dur - outro >= a_dur / 2
    if good_outro:
        length = min(outro, MAX_MIX_S)
        why = [f"final de {fmt_seconds(outro)}"]
    else:
        length = DEFAULT_MIX_S
        why = ["sin final claro: mezcla corta"]

    # 2. Entrada de B
    good_intro = intro is not None and intro >= MIN_INTRO_S and (b_dur is None or intro <= b_dur / 2)
    if not good_intro:
        length = min(length, DEFAULT_MIX_S)
        why.append("la que entra no tiene intro clara")

    # 3. Límites
    length = min(length, a_dur / TRACK_SHARE)
    if b_dur:
        length = min(length, b_dur / TRACK_SHARE)
    if good_intro and intro < length:
        length = intro                          # la mezcla dura lo que la intro de B: su cuerpo entra al acabar A
        why.append(f"intro de {fmt_seconds(intro)} (marca la duración)")
    elif good_intro:
        why.append(f"intro de {fmt_seconds(intro)}")
    if length < MIN_MIX_S:                      # solo puede pasar por el tercio: la intro buena ya mide 2 s o más
        return cut(a_dur, 0.0, "corte limpio: canción demasiado corta para mezclar")
    a_start = a_dur - outro if good_outro else a_dur - length
    b_start = intro - length if good_intro else 0.0
    return TransitionPlan(a_start_s=round(a_start, 3), b_start_s=round(b_start, 3), length_s=round(length, 3),
                          kind=KIND_BLEND, reason=f"mezcla de {fmt_seconds(length)}: " + ", ".join(why))
