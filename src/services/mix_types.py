"""Tipos compartidos del motor de mezcla del modo DJ (fases 8 a 15): la rejilla de golpes de una canción y el plan de una transición.

Son datos y un poco de aritmética, sin Qt ni numpy, para que los módulos del motor (rejilla, planificador de mezclas,
ecualizador, estiramiento, reproductor) se hablen con el mismo idioma sin depender unos de otros.

Ficha de canción (`TrackInfo`, un dict) que reciben los planificadores; todas las claves son opcionales (None = no se sabe):
    path           ruta del archivo
    duration_s     duración en segundos
    intro_s        segundos hasta que entra el cuerpo de la canción (de `track_analysis`, intro_ms / 1000)
    outro_s        segundos del final que ya no es el cuerpo (outro_ms / 1000)
    bpm            tempo en pulsos por minuto (corregido a mano si el usuario lo hizo)
    beatgrid       un `BeatGrid`
    tone           tono Camelot («8A»)
    energy         energía 0 a 1
    lufs           volumen medido en LUFS (para igualar el volumen)"""
from dataclasses import dataclass
from math import floor

SAMPLE_RATE = 44100             # el audio del motor del DJ: estéreo, float32, a esta frecuencia
KIND_BLEND, KIND_CUT = "blend", "cut"


@dataclass(frozen=True)
class BeatGrid:
    """Dónde caen los golpes de una canción: el primero, el tempo exacto y qué golpe abre cada compás."""
    first_beat_s: float                 # instante del primer golpe (segundos desde el principio de la canción)
    bpm: float                          # tempo exacto (con decimales)
    beats_per_bar: int = 4
    downbeat_offset: int = 0            # qué golpe, contando desde el primero (0 a beats_per_bar - 1), abre un compás
    confidence: float = 0.0             # 0 a 1

    @property
    def beat_s(self) -> float:
        """Duración de un golpe, en segundos."""
        return 60.0 / self.bpm

    @property
    def bar_s(self) -> float:
        """Duración de un compás, en segundos."""
        return self.beat_s * self.beats_per_bar

    def beat_time(self, n: int) -> float:
        """Instante del golpe número `n` (0 = el primero; puede ser negativo)."""
        return self.first_beat_s + n * self.beat_s

    def beat_at(self, t: float) -> float:
        """Número de golpe (con decimales) que corresponde al instante `t`."""
        return (t - self.first_beat_s) / self.beat_s

    def nearest_beat_time(self, t: float) -> float:
        """Instante del golpe más cercano a `t`."""
        return self.beat_time(round(self.beat_at(t)))

    def bar_time(self, bar: int) -> float:
        """Instante en que empieza el compás número `bar` (0 = el primer compás completo desde el primer golpe)."""
        return self.beat_time(self.downbeat_offset + bar * self.beats_per_bar)

    def bar_at(self, t: float) -> float:
        """Número de compás (con decimales) que corresponde al instante `t`."""
        return (self.beat_at(t) - self.downbeat_offset) / self.beats_per_bar

    def next_bar_time(self, t: float, bars_multiple: int = 1) -> float:
        """Instante del primer comienzo de compás igual o posterior a `t` (con `bars_multiple` = 4, 8 o 16: solo los
        compases que son múltiplo de ese número contando desde el primero, o sea, el principio de una frase)."""
        bar = floor(self.bar_at(t) + 1e-9)
        if abs(self.bar_time(bar) - t) > 1e-6:
            bar += 1
        if bars_multiple > 1:
            bar += (-bar) % bars_multiple
        return self.bar_time(bar)


@dataclass(frozen=True)
class TransitionPlan:
    """Cómo pasar de una canción A (la que suena) a otra B (la que entra)."""
    a_start_s: float                    # dónde empieza la mezcla, en segundos de A
    b_start_s: float                    # desde dónde entra B, en segundos de B (en su tiempo original, sin estirar)
    length_s: float                     # lo que dura la mezcla, en segundos de salida (0 en un corte)
    tempo_ratio_b: float = 1.0          # factor de tempo que se aplica a B para igualarla a A (1,0 = sin cambios)
    bass_swap_s: float = None           # momento del cambio de graves, en segundos desde el principio de la mezcla (None = a la mitad)
    kind: str = KIND_BLEND              # KIND_BLEND (mezcla) o KIND_CUT (corte limpio)
    reason: str = ""                    # por qué se eligió así (para depurar y para enseñar en la página)

    @property
    def bass_swap_at(self) -> float:
        """Momento del cambio de graves, en segundos desde el principio de la mezcla."""
        return self.length_s / 2.0 if self.bass_swap_s is None else self.bass_swap_s
