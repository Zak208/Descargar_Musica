"""Tiempos de cada palabra de una letra, para que el karaoke vaya al ritmo del cantante.

Una letra sincronizada (como las de internet) solo dice cuándo empieza cada FRASE. Para saber cuándo canta cada PALABRA
hay dos caminos:
  * Estimación (siempre disponible): se reparte el tiempo de la frase según las sílabas de cada palabra y el ritmo medio
    de la propia canción. Es razonable, pero un cantante alarga y acorta palabras, así que no puede ser exacta.
  * Medida con la voz (canciones descargadas): el reconocedor de voz local (whisper.cpp, el mismo de «generar letra»)
    escucha la canción una sola vez, en segundo plano y con prioridad baja, y da el momento de cada palabra; se encajan con
    las de la letra y se guardan. Desde entonces el karaoke sigue la voz de verdad.

Cada palabra se describe como (inicio_ms, fin_ms, car_inicio, car_fin): su momento y su posición dentro del texto de la frase."""
import hashlib
import logging
import os
import re
import subprocess
import tempfile
import time

from PySide6.QtCore import QThread, Signal

from config import APP_DATA_DIR, atomic_write_json
from services.ffmpeg_service import FFmpegService
from services.lyric_align import match_words, norm_word, recognized_words
from services.lyrics_service import parse_lrc

logger = logging.getLogger(__name__)

WORDS_DIR = APP_DATA_DIR / "letras"
VERSION = 1
_TOKEN = re.compile(r"\S+")
_VOWELS = "aeiouyáéíóúüàèìòùâêîôû"
DEFAULT_MS_PER_SYLLABLE = 260
END_GAP_MS = 120          # una frase termina un instante antes de que empiece la siguiente
LAST_WORD_STRETCH = 1.5   # la última palabra de la frase suele alargarse
MIN_WORD_MS = 90
MAX_WORD_MS = 2500


def syllables(word: str) -> int:
    """Sílabas aproximadas de una palabra (grupos de vocales; un diptongo cuenta como una)."""
    groups = re.findall(f"[{_VOWELS}]+", word.lower())
    return max(1, len(groups))


def tokens(text: str) -> list:
    """[(car_inicio, car_fin, texto)] de las palabras de una frase."""
    return [(m.start(), m.end(), m.group()) for m in _TOKEN.finditer(text)]


def _percentile(values: list, q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def song_rate(lines: list) -> float:
    """Milisegundos por sílaba de esta canción, a partir de sus frases seguidas (sin pausas largas)."""
    rates = []
    for i in range(len(lines) - 1):
        gap = lines[i + 1][0] - lines[i][0]
        syl = sum(syllables(t) for _s, _e, t in tokens(lines[i][1]))
        if syl >= 3 and 0 < gap <= 7000:
            rates.append(gap / syl)
    if not rates:
        return DEFAULT_MS_PER_SYLLABLE
    return max(150.0, min(520.0, _percentile(rates, 0.25)))


def _line_limit(lines: list, i: int, duration: float) -> float:
    """Hasta cuándo puede durar la frase: algo antes de que empiece la siguiente."""
    start = lines[i][0]
    if i + 1 < len(lines):
        return max(300.0, lines[i + 1][0] - start - END_GAP_MS)
    return duration


def _spread(words: list, start: float, end: float) -> list:
    """Reparte [start, end] entre las palabras de una frase según sus sílabas (la última pesa más)."""
    weights = [syllables(t) * (LAST_WORD_STRETCH if k == len(words) - 1 else 1.0) for k, (_a, _b, t) in enumerate(words)]
    total = sum(weights) or 1.0
    out, t = [], float(start)
    for (c0, c1, _t), w in zip(words, weights):
        span = (end - start) * w / total
        out.append((int(t), int(t + span), c0, c1))
        t += span
    return out


def estimate(lines: list) -> list:
    """Palabras de cada frase con tiempos estimados: lista (una por frase) de [(inicio, fin, c0, c1)]."""
    rate = song_rate(lines)
    result = []
    for i, (start, text) in enumerate(lines):
        words = tokens(text)
        if not words:
            result.append([])
            continue
        duration = sum(syllables(t) for _a, _b, t in words) * rate
        duration = min(duration, _line_limit(lines, i, duration))
        result.append(_spread(words, start, start + max(300.0, duration)))
    return result


def refine(lines: list, rec: list) -> list:
    """Como `estimate`, pero usando los momentos reales que ha dado el reconocedor de voz (`rec` = [(palabra, ms)]).
    Las palabras que se reconocen toman su momento; las demás se reparten entre las vecinas."""
    base = estimate(lines)
    flat, owner = [], []
    for j, (_ms, text) in enumerate(lines):
        for k, (c0, c1, tok) in enumerate(tokens(text)):
            n = norm_word(tok)
            if n:
                flat.append(n)
                owner.append((j, k))
    if not flat or not rec:
        return base
    matched = match_words(rec, flat)
    by_line = {}
    for idx, ms in matched.items():
        j, k = owner[idx]
        by_line.setdefault(j, {})[k] = ms
    out = []
    for j, (start, text) in enumerate(lines):
        words = tokens(text)
        est = base[j]
        found = by_line.get(j)
        if not words or not found:
            out.append(est)
            continue
        n = len(words)
        starts = [None] * n
        for k, ms in found.items():
            starts[k] = float(ms)
        # monotonía: nunca retroceden
        last = None
        for k in range(n):
            if starts[k] is None:
                continue
            if last is not None and starts[k] < last:
                starts[k] = last
            last = starts[k]
        known = [k for k in range(n) if starts[k] is not None]
        line_end = _line_limit(lines, j, est[-1][1] - est[0][0] if est else 1000) + start
        line_end = max(line_end, max(starts[k] for k in known) + 300)
        for k in range(n):                              # palabras sin momento: repartidas por su largo entre las vecinas
            if starts[k] is not None:
                continue
            before = max([p for p in known if p < k], default=None)
            after = min([q for q in known if q > k], default=None)
            lo = starts[before] if before is not None else float(min(start, min(starts[q] for q in known)))
            hi = starts[after] if after is not None else line_end
            lo_i = before if before is not None else 0      # la palabra conocida anterior también ocupa su parte
            hi_i = after if after is not None else n
            chars = [max(1, words[x][1] - words[x][0]) for x in range(lo_i, hi_i)]
            done = sum(chars[: k - lo_i])
            starts[k] = lo + (hi - lo) * done / (sum(chars) or 1)
        spans = []
        for k in range(n):
            begin = starts[k]
            finish = starts[k + 1] if k + 1 < n else min(line_end, begin + MAX_WORD_MS)
            finish = max(begin + MIN_WORD_MS, min(finish, begin + MAX_WORD_MS))
            spans.append((int(begin), int(finish), words[k][0], words[k][1]))
        out.append(spans)
    return out


def fraction_at(spans: list, text_len: int, ms: float) -> float:
    """Parte de la frase ya cantada (0 a 1) en el instante `ms`, siguiendo los tiempos de cada palabra."""
    if not spans or text_len <= 0:
        return 1.0
    if ms <= spans[0][0]:
        return 0.0
    for begin, end, c0, c1 in spans:
        if ms < end:
            inside = (ms - begin) / max(1, end - begin) if ms > begin else 0.0
            return min(1.0, (c0 + inside * (c1 - c0)) / text_len)
    return 1.0


# ------------------------------------------------------------------ guardado
def signature(lines: list) -> str:
    return hashlib.sha1("\n".join(f"{ms}|{text}" for ms, text in lines).encode("utf-8", "ignore")).hexdigest()


def _path(key: str):
    return WORDS_DIR / f"{key}.palabras.json"


def load_spans(key: str, lines: list):
    """Tiempos medidos que ya se guardaron para esta letra (si la letra sigue siendo la misma), o None."""
    try:
        import json
        with open(_path(key), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") == VERSION and data.get("sig") == signature(lines):
            return [[tuple(w) for w in line] for line in data["spans"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save_spans(key: str, lines: list, spans: list) -> None:
    WORDS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(_path(key), {"version": VERSION, "sig": signature(lines), "spans": [[list(w) for w in line] for line in spans]})


# ------------------------------------------------------------ medir con la voz
class WordTimingWorker(QThread):
    """Escucha la canción con el reconocedor de voz y mide cuándo canta cada palabra de la letra."""
    done = Signal(str, list)         # (clave de la letra, tiempos de las palabras)
    failed = Signal(str)

    def __init__(self, audio_path: str, key: str, lines: list, parent=None):
        super().__init__(parent)
        self.audio_path, self.key, self.lines = audio_path, key, list(lines)
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
        self.setPriority(QThread.LowPriority)
        ffmpeg = FFmpegService.get_ffmpeg_path()
        cli = T.engine_path()
        if not ffmpeg or cli is None or not (T.WHISPER_DIR / T.MODEL_NAME).is_file() or not os.path.isfile(self.audio_path):
            self.failed.emit("Falta el reconocedor de voz.")
            return
        work = tempfile.mkdtemp(prefix="palabras_")
        try:
            with heavy_task():
                if self.is_cancelled:
                    return
                wav = os.path.join(work, "audio.wav")
                conv = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", self.audio_path, "-vn", "-ac", "1", "-ar", "16000",
                                       "-c:a", "pcm_s16le", wav], capture_output=True, timeout=300)
                if conv.returncode != 0 or not os.path.isfile(wav) or self.is_cancelled:
                    self.failed.emit("No se pudo leer el audio.")
                    return
                threads = max(1, min(4, (os.cpu_count() or 2) // 2))
                low_priority = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
                cmd = [str(cli), "-m", str(T.WHISPER_DIR / T.MODEL_NAME), "-f", wav, "-olrc", "-of", os.path.join(work, "palabras"),
                       "-l", "auto", "-t", str(threads), "-mc", "0", "-ml", "1", "-sow"]
                self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                              creationflags=low_priority)
                started = time.time()
                while self._proc.poll() is None:
                    time.sleep(0.5)
                    if self.is_cancelled or time.time() - started > 1500:
                        self._proc.kill()
                        return
            lrc = os.path.join(work, "palabras.lrc")
            if self._proc.returncode != 0 or not os.path.isfile(lrc):
                self.failed.emit("El reconocedor no pudo procesar la canción.")
                return
            with open(lrc, encoding="utf-8", errors="ignore") as f:
                rec = recognized_words(parse_lrc(f.read()))
            spans = refine(self.lines, rec)
            save_spans(self.key, self.lines, spans)
            self.done.emit(self.key, spans)
        except Exception as e:
            logger.warning(f"No se pudieron medir las palabras de la letra: {e}")
            self.failed.emit(str(e))
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)
