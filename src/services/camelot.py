"""Rueda Camelot: el tono de una canción como «8A» (menor) o «8B» (mayor), y qué tonos suenan bien mezclados.

Es la notación que usan los programas de DJ (Mixed In Key, Rekordbox, Traktor...). Dos canciones mezclan bien en armonía
si sus códigos son iguales, si cambia solo la letra (relativo mayor o menor: 8A y 8B) o si cambia solo el número en uno
(un paso por la rueda: 8A y 9A o 7A). Sin dependencias: lo usan el análisis y, más adelante, el orden inteligente."""
import re

# Nombre musical de cada código, por número (1 a 12): menores (A) y mayores (B), con la grafía habitual de los DJ
_MINOR_NAMES = ("A♭m", "E♭m", "B♭m", "Fm", "Cm", "Gm", "Dm", "Am", "Em", "Bm", "F♯m", "C♯m")
_MAJOR_NAMES = ("B", "F♯", "D♭", "A♭", "E♭", "B♭", "F", "C", "G", "D", "A", "E")

_NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_CAMELOT = re.compile(r"^\s*0?(\d{1,2})\s*([ABab])\s*$")
_OPEN_KEY = re.compile(r"^\s*0?(\d{1,2})\s*([dDmM])\s*$")             # Traktor: 1d = do mayor (8B), 1m = la bemol menor... 
_MUSICAL = re.compile(r"^\s*([A-Ga-g])\s*([#♯b♭]?)\s*(.*?)\s*$")
_MINOR_WORDS = {"m", "mi", "min", "minor", "menor", "moll"}
_MAJOR_WORDS = {"", "maj", "major", "mayor", "dur"}

# Valor de cada nivel de compatibilidad (para ordenar canciones)
SCORE_EQUAL, SCORE_GOOD, SCORE_FAIR, SCORE_BAD = 1.0, 0.8, 0.5, 0.0


def camelot(tonic: int, minor: bool) -> str:
    """Código Camelot de un tono: `tonic` es la nota (0 = do, 1 = do sostenido... 11 = si) y `minor` si es menor."""
    major_tonic = (tonic + 3) % 12 if minor else tonic % 12        # el relativo mayor de un menor está 3 semitonos arriba
    number = (7 * major_tonic + 7) % 12 + 1                         # do mayor = 8B, sol mayor = 9B...
    return f"{number}{'A' if minor else 'B'}"


def parse_camelot(text):
    """(número, letra) de un código como «8A», «08a»... o None si no lo es."""
    match = _CAMELOT.match(str(text or ""))
    if not match:
        return None
    number = int(match.group(1))
    return (number, match.group(2).upper()) if 1 <= number <= 12 else None


def normalize(text):
    """«8a» o «08A» → «8A»; None si no es un código Camelot."""
    parsed = parse_camelot(text)
    return f"{parsed[0]}{parsed[1]}" if parsed else None


def musical_name(code) -> str:
    """Nombre musical de un código («8A» → «Am»), o «» si no es un código."""
    parsed = parse_camelot(code)
    if not parsed:
        return ""
    number, letter = parsed
    return (_MINOR_NAMES if letter == "A" else _MAJOR_NAMES)[number - 1]


def from_text(text):
    """Código Camelot de un tono escrito de cualquier forma común: «8A», «Am», «F#m», «Bb», «C major», «A minor»...
    (así se guarda en las etiquetas de los archivos). None si no se entiende."""
    text = str(text or "").strip()
    if not text:
        return None
    code = normalize(text)
    if code:
        return code
    open_key = _OPEN_KEY.match(text)
    if open_key:                                   # Open Key → Camelot: el número se desplaza 5 y d/m son mayor/menor
        number = int(open_key.group(1))
        if 1 <= number <= 12:
            return f"{(number - 6) % 12 + 1}{'A' if open_key.group(2) in 'mM' else 'B'}"
        return None
    match = _MUSICAL.match(text)
    if not match:
        return None
    note, accidental, rest = match.groups()
    pitch_class = _NOTE_PC[note.upper()] + (1 if accidental in ("#", "♯") else -1 if accidental in ("b", "♭") else 0)
    if rest == "M":                                # «M» mayúscula suelta: mayor
        minor = False
    elif rest.lower() in _MINOR_WORDS:
        minor = True
    elif rest.lower() in _MAJOR_WORDS:
        minor = False
    else:
        return None                                # un modo que no es mayor ni menor («dorian»), «o» (fuera de tono), basura
    return camelot(pitch_class % 12, minor)


def steps(a, b):
    """(pasos por la rueda, ¿misma letra?) entre dos códigos, o None si alguno no es un código."""
    pa, pb = parse_camelot(a), parse_camelot(b)
    if not pa or not pb:
        return None
    diff = abs(pa[0] - pb[0])
    return min(diff, 12 - diff), pa[1] == pb[1]


def score(a, b) -> float:
    """Qué tal suenan mezclados dos tonos: 1,0 iguales; 0,8 un paso por la rueda o relativo mayor/menor; 0,5 un cambio
    de ambiente (diagonal) o dos pasos; 0,0 chocan. Sin tono conocido en alguno: 0,5 (ni a favor ni en contra)."""
    found = steps(a, b)
    if found is None:
        return SCORE_FAIR
    distance, same_letter = found
    if distance == 0 and same_letter:
        return SCORE_EQUAL
    if (distance == 1 and same_letter) or (distance == 0 and not same_letter):
        return SCORE_GOOD
    if (distance == 1 and not same_letter) or (distance == 2 and same_letter):
        return SCORE_FAIR
    return SCORE_BAD


def compatible(a, b) -> bool:
    """¿Mezclan bien en armonía? (iguales, relativos o a un paso por la rueda)."""
    return score(a, b) >= SCORE_GOOD
