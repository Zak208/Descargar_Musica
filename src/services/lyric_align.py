"""Sincronizar una letra con la canción: el usuario pega o escribe la letra y el sistema le pone el tiempo a cada línea.

El reconocedor de voz (whisper.cpp) escucha la canción y da cada palabra con su momento; después se «encajan» esas
palabras con las de la letra del usuario (aunque el reconocedor se equivoque en alguna) y cada línea toma el momento
de sus palabras. Es más fiable que generar la letra desde cero, porque el texto ya es el correcto."""
import difflib
import logging
import re
import shutil
import tempfile

from PySide6.QtCore import QThread, Signal

from services.library_search import fold
from services.lyrics_service import parse_lrc

logger = logging.getLogger(__name__)

WORD_MS = 420            # lo que dura una palabra cantada de media (para repartir líneas sin palabras reconocidas)
MIN_GAP_MS = 250         # separación mínima entre líneas seguidas
FUZZY = 0.72             # parecido mínimo para dar por buena una palabra mal reconocida


def norm_word(word: str) -> str:
    return re.sub(r"[^a-z0-9ñ]+", "", fold(word))


def recognized_words(lrc_entries: list) -> list:
    """[(ms, texto)] del reconocedor → [(palabra normalizada, ms)] sin marcas como [Música]."""
    out = []
    for ms, text in lrc_entries:
        text = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", text)
        for token in text.split():
            n = norm_word(token)
            if n:
                out.append((n, ms))
    return out


def _similar(a: str, b: str) -> float:
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def _fuzzy_pairs(rec: list, lyr: list) -> list:
    """Alineación (Needleman-Wunsch) de dos trozos pequeños de palabras permitiendo palabras parecidas.
    Devuelve [(índice en rec, índice en lyr)] de las parejas aceptadas."""
    n, m = len(rec), len(lyr)
    if n == 0 or m == 0 or n * m > 40000:
        return []
    sim = [[_similar(rec[i], lyr[j]) for j in range(m)] for i in range(n)]
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0], back[i][0] = -0.5 * i, 1
    for j in range(1, m + 1):
        score[0][j], back[0][j] = -0.5 * j, 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = sim[i - 1][j - 1]
            diag = score[i - 1][j - 1] + (2 * s if s >= FUZZY else -1.0)
            up, left = score[i - 1][j] - 0.5, score[i][j - 1] - 0.5
            best = max(diag, up, left)
            score[i][j] = best
            back[i][j] = 0 if best == diag else (1 if best == up else 2)
    i, j, pairs = n, m, []
    while i > 0 or j > 0:
        move = back[i][j] if i > 0 and j > 0 else (1 if i > 0 else 2)
        if move == 0:
            if sim[i - 1][j - 1] >= FUZZY:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif move == 1:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def match_words(rec: list, lyr_words: list) -> dict:
    """{índice de palabra de la letra: ms} para las palabras que se han encajado con las del reconocedor."""
    rec_norm = [w for w, _ms in rec]
    sm = difflib.SequenceMatcher(None, rec_norm, lyr_words, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks()]
    found = {}
    prev_i = prev_k = 0
    for i, k, size in blocks:
        # hueco entre dos coincidencias exactas: se intenta con palabras parecidas
        for ri, lk in _fuzzy_pairs(rec_norm[prev_i:i], lyr_words[prev_k:k]):
            found[prev_k + lk] = rec[prev_i + ri][1]
        for t in range(size):
            found[k + t] = rec[i + t][1]
        prev_i, prev_k = i + size, k + size
    return found


def align_lines(rec: list, lines: list) -> list:
    """Momento de inicio (ms) de cada línea de `lines`, a partir de las palabras reconocidas `rec`
    ([(palabra normalizada, ms)]). Las líneas vacías devuelven None."""
    words, line_of, pos_in_line = [], [], []
    for j, line in enumerate(lines):
        count = 0
        for token in line.split():
            n = norm_word(token)
            if n:
                words.append(n)
                line_of.append(j)
                pos_in_line.append(count)
                count += 1
    if not words or not rec:
        return [None] * len(lines)
    matched = match_words(rec, words)

    # inicio estimado de cada línea con las palabras que sí se reconocieron en ella
    starts = [None] * len(lines)
    earliest = {}
    for k, ms in matched.items():
        j = line_of[k]
        if j not in earliest or pos_in_line[k] < earliest[j][0]:
            earliest[j] = (pos_in_line[k], ms)
    for j, (pos, ms) in earliest.items():       # la primera palabra reconocida de la línea manda
        starts[j] = max(0, int(ms - pos * WORD_MS))

    # líneas sin ninguna palabra reconocida: se reparten entre sus vecinas según cuántas palabras tienen
    counts = [sum(1 for lo in line_of if lo == j) for j in range(len(lines))]
    cum = [0]
    for c in counts:
        cum.append(cum[-1] + c)
    known = [j for j, s in enumerate(starts) if s is not None]
    if not known:
        return [None] * len(lines)
    for j in range(len(lines)):
        if starts[j] is not None or counts[j] == 0:
            continue
        before = [p for p in known if p < j]
        after = [n for n in known if n > j]
        if before and after:
            p, n = before[-1], after[0]
            span = max(1, cum[n] - cum[p])
            starts[j] = int(starts[p] + (starts[n] - starts[p]) * (cum[j] - cum[p]) / span)
        elif before:
            starts[j] = int(starts[before[-1]] + (cum[j] - cum[before[-1]]) * WORD_MS)
        else:
            starts[j] = max(0, int(starts[after[0]] - (cum[after[0]] - cum[j]) * WORD_MS))

    # los tiempos nunca retroceden
    last = -MIN_GAP_MS
    for j in range(len(lines)):
        if starts[j] is None:
            continue
        starts[j] = max(starts[j], last + MIN_GAP_MS, 0)
        last = starts[j]
    return starts


class AlignWorker(QThread):
    """Escucha la canción (palabra por palabra) y calcula el tiempo de cada línea de la letra."""
    progress = Signal(int)
    done = Signal(list)           # [ms | None] por línea
    failed = Signal(str)

    def __init__(self, audio_path: str, lines: list, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.lines = lines
        self.is_cancelled = False
        self._proc = None

    def cancel(self):
        self.is_cancelled = True
        if self._proc is not None:
            try:
                self._proc.kill()
            except OSError:
                pass

    def run(self):
        from services import transcribe_service as T
        from services.heavy import heavy_task
        work = tempfile.mkdtemp(prefix="sincro_")
        try:
            with heavy_task("slow"):
                lrc = T.listen(self.audio_path, work, "palabras", self, extra_args=("-ml", "1", "-sow", "-pp"),
                               on_progress=self.progress.emit, limit_s=1800)
            with open(lrc, encoding="utf-8", errors="ignore") as f:
                rec = recognized_words(parse_lrc(f.read()))
            times = align_lines(rec, self.lines)
            if not any(t is not None for t in times):
                self.failed.emit("No se pudo encajar la letra con la canción (¿es la misma canción y el mismo idioma?).")
                return
            self.done.emit(times)
        except T.SpeechError as e:
            if str(e):
                self.failed.emit(str(e))
        except Exception as e:
            logger.warning(f"Error al sincronizar la letra: {e}")
            self.failed.emit(str(e))
        finally:
            shutil.rmtree(work, ignore_errors=True)
