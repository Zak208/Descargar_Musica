"""Letras generadas por el sistema: el programa «escucha» la canción descargada y escribe lo que canta.

Usa whisper.cpp (reconocimiento de voz que funciona sin internet y sin cuentas). Como es pesado, no viene dentro del
programa: la primera vez, y solo si el usuario lo acepta, se descarga a app_data/whisper (≈ 68 MB) y se comprueba su
huella SHA-256. Después todo ocurre en el propio equipo.
"""
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile

from services import http
from PySide6.QtCore import QThread, Signal

from config import APP_DATA_DIR
from services import lyrics_store
from services.ffmpeg_service import FFmpegService
from services.lyrics_service import parse_lrc

logger = logging.getLogger(__name__)

WHISPER_DIR = APP_DATA_DIR / "whisper"
CLI_NAME = "whisper-cli.exe"
MODEL_NAME = "ggml-base-q5_1.bin"

# Versión fija y con huella conocida: así siempre se descarga exactamente el mismo programa.
ENGINE_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.9.2/whisper-bin-x64.zip"
ENGINE_SHA256 = "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/" + MODEL_NAME
MODEL_SHA256 = "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898"
DOWNLOAD_MB = 68
HEADERS = {"User-Agent": "DescargadorMusicaApp/2.0"}


def engine_path():
    for p in WHISPER_DIR.rglob(CLI_NAME):
        return p
    return None


def is_ready() -> bool:
    return engine_path() is not None and (WHISPER_DIR / MODEL_NAME).is_file()


def _download(url: str, dest, expected_sha: str, progress, base: float, span: float, cancelled) -> None:
    """Descarga `url` a `dest` (con barra de progreso) y comprueba su SHA-256."""
    tmp = str(dest) + ".part"
    sha = hashlib.sha256()
    with http.get(url, headers=HEADERS, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) or 1
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if cancelled():
                    raise RuntimeError("cancelado")
                f.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                progress(int(base + span * done / total))
    if sha.hexdigest() != expected_sha:
        os.remove(tmp)
        raise RuntimeError("La descarga llegó dañada. Inténtalo de nuevo.")
    os.replace(tmp, dest)


class SetupWorker(QThread):
    """Descarga el reconocedor de voz y su modelo."""
    progress = Signal(int)
    done = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_cancelled = False

    def run(self):
        try:
            WHISPER_DIR.mkdir(parents=True, exist_ok=True)
            cancelled = lambda: self.is_cancelled
            if engine_path() is None:
                zip_path = WHISPER_DIR / "motor.zip"
                _download(ENGINE_URL, zip_path, ENGINE_SHA256, self.progress.emit, 0, 12, cancelled)
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(WHISPER_DIR / "motor")
                os.remove(zip_path)
            if not (WHISPER_DIR / MODEL_NAME).is_file():
                _download(MODEL_URL, WHISPER_DIR / MODEL_NAME, MODEL_SHA256, self.progress.emit, 12, 88, cancelled)
            if engine_path() is None:
                raise RuntimeError("No se encontró el reconocedor de voz dentro de la descarga.")
            self.progress.emit(100)
            self.done.emit()
        except Exception as e:
            logger.warning(f"No se pudo preparar el reconocedor de voz: {e}")
            self.failed.emit(str(e) if str(e) else "No se pudo descargar.")


def clean_generated(lines: list) -> list:
    """Quita lo típico que inventa el reconocedor con la música: repeticiones sin fin y marcas como [Música]."""
    out, prev, repeats = [], None, 0
    for ms, text in lines:
        text = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", text).strip(" ♪*")
        if not text:
            continue
        if text == prev:
            repeats += 1
            if repeats >= 2:      # a la tercera repetición seguida se descarta (suele ser un bucle del reconocedor)
                continue
        else:
            prev, repeats = text, 0
        out.append((ms, text))
    return out


MAX_LINE_CHARS = 34


def _split_text(text: str, max_chars: int) -> list:
    """Parte una frase larga en trozos de longitud parecida, cortando por comas o espacios (nunca dejando una palabra suelta)."""
    if len(text) <= max_chars + 8:      # hasta ~42 letras cabe bien en dos renglones: no se toca
        return [text]
    parts = -(-len(text) // max_chars)        # trozos necesarios (redondeo hacia arriba)
    target = len(text) / parts
    out, start = [], 0
    for i in range(1, parts):
        ideal = int(round(target * i))
        # primero una coma/punto cercano, si no el espacio más próximo al punto ideal
        window = [m for m in range(max(start + 8, ideal - 9), min(len(text) - 6, ideal + 9)) if text[m - 1] in ",.;:!?"]
        spaces = [m for m in range(max(start + 4, ideal - 12), min(len(text) - 3, ideal + 12)) if text[m] == " "]
        cut = min(window, key=lambda m: abs(m - ideal)) if window else             (min(spaces, key=lambda m: abs(m - ideal)) if spaces else ideal)
        out.append(text[start:cut].strip())
        start = cut
    out.append(text[start:].strip())
    return [t for t in out if t]


def split_long_lines(lines: list, max_chars: int = MAX_LINE_CHARS) -> list:
    """Las frases largas se dividen en varias más cortas, repartiendo el tiempo según su longitud."""
    out = []
    for i, (ms, text) in enumerate(lines):
        pieces = _split_text(text, max_chars)
        if len(pieces) == 1:
            out.append((ms, text))
            continue
        next_ms = lines[i + 1][0] if i + 1 < len(lines) else ms + 8000
        span = min(max(next_ms - ms, 1500), max(2500, int(len(text) * 90)))   # lo que se tarda en cantarla (aprox.)
        total = sum(len(p) for p in pieces)
        done = 0
        for piece in pieces:
            out.append((ms + int(span * done / total), piece))
            done += len(piece)
    return out


class TranscribeWorker(QThread):
    """Escucha un archivo de audio y guarda la letra generada (con tiempos) en el almacén de letras."""
    progress = Signal(int)       # 0-100 mientras el reconocedor escucha
    done = Signal(str, dict)     # clave, letra
    failed = Signal(str, str)    # clave, motivo

    def __init__(self, audio_path: str, key: str, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.key = key
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
        from services.heavy import heavy_task
        with heavy_task("slow"):
            self._transcribe()

    def _transcribe(self):
        ffmpeg = FFmpegService.get_ffmpeg_path()
        cli = engine_path()
        if not ffmpeg or cli is None or not (WHISPER_DIR / MODEL_NAME).is_file():
            self.failed.emit(self.key, "Falta el reconocedor de voz.")
            return
        work = tempfile.mkdtemp(prefix="letra_")
        try:
            wav = os.path.join(work, "audio.wav")
            conv = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", self.audio_path, "-vn", "-ac", "1", "-ar", "16000",
                                   "-c:a", "pcm_s16le", wav], capture_output=True, timeout=300)
            if conv.returncode != 0 or not os.path.isfile(wav):
                self.failed.emit(self.key, "No se pudo leer el audio.")
                return
            threads = max(1, min(4, (os.cpu_count() or 2) // 2))
            low_priority = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            cmd = [str(cli), "-m", str(WHISPER_DIR / MODEL_NAME), "-f", wav, "-olrc", "-of", os.path.join(work, "letra"),
                   "-l", "auto", "-t", str(threads), "-mc", "0", "-pp"]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                          errors="ignore", creationflags=low_priority)
            started = time.time()
            for raw in self._proc.stderr:        # el reconocedor avisa de su avance: «progress = 35%»
                m = re.search(r"progress\s*=\s*(\d+)%", raw)
                if m:
                    self.progress.emit(int(m.group(1)))
                if time.time() - started > 1500:
                    self._proc.kill()
                    self.failed.emit(self.key, "Tardó demasiado.")
                    return
            self._proc.wait()
            if self.is_cancelled:
                return
            lrc = os.path.join(work, "letra.lrc")
            if self._proc.returncode != 0 or not os.path.isfile(lrc):
                self.failed.emit(self.key, "El reconocedor no pudo procesar la canción.")
                return
            with open(lrc, encoding="utf-8", errors="ignore") as f:
                lines = split_long_lines(clean_generated(parse_lrc(f.read())))
            if not lines:
                self.failed.emit(self.key, "No se entendió ninguna palabra (puede ser una canción instrumental).")
                return
            text = "\n".join(f"{lyrics_store.format_ms(ms)} {t}" for ms, t in lines)
            data = lyrics_store.save(self.key, text, "auto")
            self.done.emit(self.key, data)
        except Exception as e:
            logger.warning(f"Error al generar la letra: {e}")
            self.failed.emit(self.key, str(e))
        finally:
            shutil.rmtree(work, ignore_errors=True)
