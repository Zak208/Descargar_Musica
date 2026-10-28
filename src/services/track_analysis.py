"""Análisis de cada canción para el modo DJ: tempo (y lo fiable que es), energía, cuánto dura la intro y cuánto el final.

Sale de la envolvente que ya se guarda para el visualizador (graves, medios y agudos cada 0,1 s), así que no se vuelve a
escuchar el audio si la canción ya sonó alguna vez. Se calcula una vez por canción, en segundo plano, y se guarda en el
índice de tu música; solo se repite si el archivo cambia (o si sube VERSION)."""
import logging
import os

from PySide6.QtCore import QThread, Signal

from services import envelope, library_db, tempo

logger = logging.getLogger(__name__)

VERSION = 2                     # 2: el tempo se lleva a la ventana de su género (tempo.fold_for_genre)
SMOOTH_FRAMES = 20              # 2 s: la energía se suaviza para que un golpe suelto no cuente como «empieza la canción»
BODY_SHARE = 0.6                # la intro termina cuando la energía llega al 60 % de la del cuerpo de la canción
PAUSE_MS = 150                  # respiro entre canción y canción para las demás tareas pesadas
MAX_INTRO_SHARE = 0.5           # una intro o un final de más de la mitad de la canción no son creíbles: se da 0


def _smoothed_energy(data: bytes) -> list:
    """Energía de graves y medios en cada instante (0..255), suavizada."""
    n = len(data) // envelope.BANDS
    raw = [(data[i * envelope.BANDS] + data[i * envelope.BANDS + 1]) / 2 for i in range(n)]
    out, total = [], 0.0
    for i, v in enumerate(raw):
        total += v
        if i >= SMOOTH_FRAMES:
            total -= raw[i - SMOOTH_FRAMES]
        out.append(total / min(i + 1, SMOOTH_FRAMES))
    return out


def analyze_envelope(data: bytes, genre: str = "") -> dict:
    """{bpm (o None), confidence, energy (0..1), intro_ms, outro_ms, duration_ms} a partir de la envolvente. Con el
    género de la canción, el tempo se lleva a la ventana habitual de ese género."""
    result = {"bpm": None, "confidence": 0.0, "energy": 0.0, "intro_ms": 0, "outro_ms": 0, "duration_ms": 0}
    if not data:
        return result
    energy = _smoothed_energy(data)
    n = len(energy)
    result["duration_ms"] = n * envelope.STEP_MS
    result["bpm"], result["confidence"] = tempo.estimate_bpm_with_confidence(data)
    result["bpm"] = tempo.fold_for_genre(result["bpm"], genre)
    core = sorted(energy[int(n * 0.15):int(n * 0.85)] or energy)
    body = core[len(core) // 2] if core else 0.0
    result["energy"] = round(body / 255.0, 3)
    if body <= 0:
        return result
    threshold = body * BODY_SHARE
    # la media de los últimos 2 s va retrasada medio intervalo: se corrige para que intro y final caigan en su sitio
    lag = SMOOTH_FRAMES // 2
    first = max(0, next((i for i, v in enumerate(energy) if v >= threshold), 0) - lag)
    last = max(first, next((i for i in range(n - 1, -1, -1) if energy[i] >= threshold), n - 1) - lag)
    if first <= n * MAX_INTRO_SHARE:
        result["intro_ms"] = first * envelope.STEP_MS
    if n - 1 - last <= n * MAX_INTRO_SHARE:
        result["outro_ms"] = (n - 1 - last) * envelope.STEP_MS
    return result


def stored(path: str, mtime: float = None):
    """Análisis ya guardado (si el archivo no cambió), o None."""
    try:
        mtime = os.path.getmtime(path) if mtime is None else mtime
        with library_db.connect() as con:
            row = con.execute("SELECT * FROM analysis WHERE path=?", (path,)).fetchone()
        if row and abs(row["mtime"] - mtime) < 1 and row["version"] == VERSION:
            return {k: row[k] for k in ("bpm", "confidence", "energy", "intro_ms", "outro_ms", "duration_ms")}
    except Exception:
        pass
    return None


def save(path: str, result: dict) -> None:
    try:
        with library_db.connect() as con:
            con.execute("INSERT INTO analysis(path, mtime, version, bpm, confidence, energy, intro_ms, outro_ms, duration_ms) "
                        "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, "
                        "version=excluded.version, bpm=excluded.bpm, confidence=excluded.confidence, "
                        "energy=excluded.energy, intro_ms=excluded.intro_ms, outro_ms=excluded.outro_ms, "
                        "duration_ms=excluded.duration_ms",
                        (path, os.path.getmtime(path), VERSION, result["bpm"], result["confidence"], result["energy"],
                         result["intro_ms"], result["outro_ms"], result["duration_ms"]))
    except Exception as e:
        logger.warning(f"No se pudo guardar el análisis: {e}")


def analyze(path: str):
    """Analiza una canción (usando la envolvente guardada si existe) y guarda el resultado. None si no se pudo."""
    from services.ffmpeg_service import FFmpegService
    data = envelope.stored(path)
    if data is None:
        if not FFmpegService.get_ffmpeg_path():
            return None                       # sin FFmpeg no se puede: se intentará cuando esté
        data = envelope.compute(path)
        if data:
            envelope.save(path, data)
    if not data:
        return None                           # no se pudo leer (archivo a medias, error de FFmpeg...): se reintentará
    from services.library_service import read_basic_tags
    result = analyze_envelope(data, read_basic_tags(path).get("genre", ""))
    save(path, result)
    return result


class AnalysisWorker(QThread):
    """Analiza una lista de canciones de una en una, en segundo plano y con prioridad baja. Primero entrega lo que ya
    estaba guardado (es instantáneo) y luego calcula lo que falta, avisando del progreso."""
    result = Signal(str, dict)                # (ruta, análisis)
    progress = Signal(int, int)               # (hechas, total)

    def __init__(self, paths: list, parent=None):
        super().__init__(parent)
        self.paths = list(paths)

    def cancel(self):
        """Al cerrar el programa (o al cambiar de carpeta): para después de la canción que esté analizando."""
        self.requestInterruption()

    def run(self):
        from services.heavy import heavy_task
        self.setPriority(QThread.LowPriority)
        pending = []
        for path in self.paths:
            if self.isInterruptionRequested():
                return
            known = stored(path) if os.path.isfile(path) else None
            if known is not None:
                self.result.emit(path, known)
            elif os.path.isfile(path):
                pending.append(path)
        total = len(pending)
        self.progress.emit(0, total)
        for done, path in enumerate(pending, 1):
            if self.isInterruptionRequested():
                return
            with heavy_task():                # de una en una: entre canción y canción pueden pasar otras tareas
                found = analyze(path)
            if found is not None:
                self.result.emit(path, found)
            self.progress.emit(done, total)
            self.msleep(PAUSE_MS)              # cede el turno: si no, el visualizador o el tempo del fundido esperarían horas
