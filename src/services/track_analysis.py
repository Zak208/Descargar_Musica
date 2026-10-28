"""Análisis de cada canción para el modo DJ: tempo (y lo fiable que es), cuánto dura la intro y cuánto el final, el tono
(rueda Camelot, ver `key_detect`), la energía (ver `audio_features`), y el género y el artista de las etiquetas.

El tempo, la intro y el final salen de la envolvente que ya se guarda para el visualizador (graves, medios y agudos cada
0,1 s), así que no se vuelve a escuchar el audio si la canción ya sonó alguna vez; el tono y la energía sí necesitan
decodificar la canción (una sola vez para los dos). Se calcula una vez por canción, en segundo plano, y se guarda en el
índice de tu música; solo se repite si el archivo cambia (o si sube VERSION)."""
import logging
import os

from PySide6.QtCore import QThread, Signal

from services import audio_features, envelope, key_detect, library_db, tempo

logger = logging.getLogger(__name__)

VERSION = 2                     # súbela si cambia el cálculo del tempo, la intro o el final (el tono pendiente se reintenta solo)
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
    """{bpm (o None), confidence, intro_ms, outro_ms, duration_ms} a partir de la envolvente (el resto de campos del
    análisis se rellenan en `analyze`). Con el género de la canción, el tempo se lleva a la ventana habitual de ese género.
    La envolvente está normalizada canción a canción, así que no sirve para medir la energía: eso lo hace `audio_features`."""
    result = {"bpm": None, "confidence": 0.0, "energy": None, "intro_ms": 0, "outro_ms": 0, "duration_ms": 0,
              "tone": None, "tone_conf": 0.0,              # None = todavía no se ha intentado sacar el tono / medir el audio
              "genre": "", "artist": "", "loudness_db": None, "brightness_hz": None, "flux": None}
    if not data:
        return result
    energy = _smoothed_energy(data)
    n = len(energy)
    result["duration_ms"] = n * envelope.STEP_MS
    result["bpm"], result["confidence"] = tempo.estimate_bpm_with_confidence(data)
    result["bpm"] = tempo.fold_for_genre(result["bpm"], genre)
    core = sorted(energy[int(n * 0.15):int(n * 0.85)] or energy)
    body = core[len(core) // 2] if core else 0.0
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


FIELDS = ("bpm", "confidence", "energy", "intro_ms", "outro_ms", "duration_ms", "tone", "tone_conf", "genre", "artist",
          "loudness_db", "brightness_hz", "flux")


def stored(path: str, mtime: float = None, need_audio: bool = False):
    """Análisis ya guardado (si el archivo no cambió), o None. Con `need_audio`, un análisis al que le falta el tono o las
    medidas de energía (se guardó cuando no se podían calcular: sin numpy o sin FFmpeg, o antes de que existieran) se da
    por no hecho, para volver a intentarlo."""
    try:
        mtime = os.path.getmtime(path) if mtime is None else mtime
        with library_db.connect() as con:
            row = con.execute("SELECT * FROM analysis WHERE path=?", (path,)).fetchone()
        if row and abs(row["mtime"] - mtime) < 1 and row["version"] == VERSION:
            if need_audio and (row["tone"] is None or row["loudness_db"] is None):
                return None
            return {k: row[k] for k in FIELDS}
    except Exception:
        pass
    return None


def save(path: str, result: dict) -> None:
    try:
        with library_db.connect() as con:
            con.execute(f"INSERT INTO analysis(path, mtime, version, {', '.join(FIELDS)}) "
                        f"VALUES (?, ?, ?, {', '.join('?' for _ in FIELDS)}) ON CONFLICT(path) DO UPDATE SET "
                        f"mtime=excluded.mtime, version=excluded.version, {', '.join(f'{k}=excluded.{k}' for k in FIELDS)}",
                        (path, os.path.getmtime(path), VERSION, *(result.get(k) for k in FIELDS)))
    except Exception as e:
        logger.warning(f"No se pudo guardar el análisis: {e}")


def analyze(path: str, previous: dict = None):
    """Analiza una canción (usando la envolvente guardada si existe) y guarda el resultado. None si no se pudo. `previous`:
    un análisis anterior válido pero incompleto (de antes de que existieran las medidas de energía): si ya trae el tono, no
    se vuelve a calcular (es lo más caro)."""
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
    tags = read_basic_tags(path)
    result = analyze_envelope(data, tags.get("genre", ""))
    result["genre"], result["artist"] = tags.get("genre", ""), tags.get("artist", "")
    _add_audio_analysis(path, result, previous)
    save(path, result)
    return result


def _add_audio_analysis(path: str, result: dict, previous: dict = None) -> None:
    """El tono y las medidas de energía, con una sola decodificación del audio. Si no se puede decodificar (sin numpy,
    sin FFmpeg, archivo ilegible) quedan sin intentar (None) y se vuelve a probar más adelante."""
    tagged = key_detect.tag_key(path)
    kept = ({"tone": previous["tone"], "tone_conf": previous.get("tone_conf") or 0.0}
            if previous and previous.get("tone") is not None else None)           # el tono que ya se había calculado
    samples = key_detect.decode(path)
    if samples is None:
        if tagged:
            result.update({"tone": tagged, "tone_conf": 1.0})
        elif kept:
            result.update(kept)
        return
    try:
        if tagged:
            result.update({"tone": tagged, "tone_conf": 1.0})
        else:
            result.update(kept or key_detect.detect_from_samples(samples))
        features = audio_features.compute(samples)
    except Exception as e:                    # no se vuelve a probar con este archivo: fallaría igual cada vez
        logger.warning(f"No se pudo analizar el audio de {path}: {e}")
        features = None
    if features is None:                      # silencio, menos de 20 s o un fallo: se intentó y no hay nada que medir
        features = {"loudness_db": audio_features.NOT_MEASURED, "brightness_hz": 0.0, "flux": 0.0}
    result.update(features)
    result["energy"] = audio_features.energy_score(features)


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
        pending, partials = [], {}
        need_audio = key_detect.available()
        for path in self.paths:
            if self.isInterruptionRequested():
                return
            if not os.path.isfile(path):
                continue
            known = stored(path, need_audio=need_audio)
            if known is not None:
                self.result.emit(path, known)
            else:
                partial = stored(path)                 # un análisis válido pero de antes de las medidas de energía: se enseña ya
                if partial is not None:
                    self.result.emit(path, partial)
                partials[path] = partial
                pending.append(path)
        total = len(pending)
        self.progress.emit(0, total)
        for done, path in enumerate(pending, 1):
            if self.isInterruptionRequested():
                return
            with heavy_task():                # de una en una: entre canción y canción pueden pasar otras tareas
                found = analyze(path, partials.get(path))
            if found is not None:
                self.result.emit(path, found)
            self.progress.emit(done, total)
            self.msleep(PAUSE_MS)              # cede el turno: si no, el visualizador o el tempo del fundido esperarían horas
