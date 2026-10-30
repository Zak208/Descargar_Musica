"""Análisis de cada canción para el modo DJ: tempo (y lo fiable que es), cuánto dura la intro y cuánto el final, el tono
(rueda Camelot, ver `key_detect`), la energía (ver `audio_features`), la rejilla de golpes (ver `beatgrid`), la estructura
(subidas, caídas, parones, partes y voz estimada; ver `structure`) y el género y el artista de las etiquetas.

El tempo, la intro y el final salen de la envolvente que ya se guarda para el visualizador (graves, medios y agudos cada
0,1 s), así que no se vuelve a escuchar el audio si la canción ya sonó alguna vez; el tono, la energía y la rejilla de golpes sí
necesitan decodificar la canción (una sola vez para los cuatro). Se calcula una vez por canción, en segundo plano, y se guarda en el
índice de tu música; solo se repite si el archivo cambia (o si sube VERSION)."""
import logging
import os
from functools import lru_cache

from PySide6.QtCore import QThread, Signal

from services import audio_features, beatgrid, envelope, key_detect, library_db, tempo
from services import structure as structure_mod
from services.mix_types import BeatGrid

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
              "genre": "", "artist": "", "loudness_db": None, "brightness_hz": None, "flux": None,
              "structure": None}                           # JSON de `structure` (None = sin intentar, "" = intentado y sin nada)
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
          "loudness_db", "brightness_hz", "flux", "beat_first_s", "beat_bpm", "beat_downbeat", "beat_conf", "structure")
MIN_GRID_CONFIDENCE = 0.4       # por debajo, la rejilla de golpes no es de fiar: el planificador mezcla sin cuadrar compases


def stored(path: str, mtime: float = None, need_audio: bool = False):
    """Análisis ya guardado (si el archivo no cambió), o None. Con `need_audio`, un análisis al que le falta el tono o las
    medidas de energía (se guardó cuando no se podían calcular: sin numpy o sin FFmpeg, o antes de que existieran) se da
    por no hecho, para volver a intentarlo. Lo mismo con la rejilla y con la estructura (esta, también si es de una versión
    vieja del cálculo)."""
    try:
        mtime = os.path.getmtime(path) if mtime is None else mtime
        with library_db.connect() as con:
            row = con.execute("SELECT * FROM analysis WHERE path=?", (path,)).fetchone()
        if row and abs(row["mtime"] - mtime) < 1 and row["version"] == VERSION:
            if need_audio and (row["tone"] is None or row["loudness_db"] is None or row["beat_conf"] is None
                               or (structure_mod.available() and not _structure_current(row["structure"]))):
                return None
            return {k: row[k] for k in FIELDS}
    except Exception:
        pass
    return None


def _structure_current(text) -> bool:
    """¿Está la estructura guardada hecha y con la versión actual del cálculo? (`""` vale: se intentó y no había nada). Mira solo
    el comienzo del texto (`{"v":N,`, como lo escribe `structure.to_json`) para no leer miles de JSON al arrancar."""
    return text == "" or (isinstance(text, str) and text.startswith(f'{{"v":{structure_mod.VERSION},'))


@lru_cache(maxsize=128)
def _parse_structure(text: str):
    return structure_mod.from_json(text)


def structure_from(result):
    """La estructura de un análisis ya leída ({"energy", "bass", "vocal", "events", "sections"}; ver `structure.analyse`), o
    None si no se calculó, no hay nada (audio corto o en silencio) o es de otra versión. Se guardan en memoria los últimos
    resultados: es el mismo diccionario cada vez, así que quien lo use no debe modificarlo."""
    try:
        text = (result or {}).get("structure")
        if not text or not isinstance(text, str):
            return None
        return _parse_structure(text)
    except Exception:
        return None


def grid_from(result: dict):
    """La rejilla de golpes (`BeatGrid`) de un análisis, o None si no se calculó o no es de fiar."""
    try:
        if (result.get("beat_conf") or 0.0) < MIN_GRID_CONFIDENCE or not result.get("beat_bpm") or result.get("beat_first_s") is None:
            return None
        return BeatGrid(float(result["beat_first_s"]), float(result["beat_bpm"]), 4, int(result.get("beat_downbeat") or 0),
                        float(result["beat_conf"]))
    except (TypeError, ValueError):
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
    _add_beatgrid(samples, result)
    _add_structure(samples, result, previous)


def _add_structure(samples, result: dict, previous: dict = None) -> None:
    """La estructura (fases 18 y 19 ligeras) con las mismas muestras y la rejilla recién calculada. Queda `""` si se intentó y
    no hay nada (audio corto o en silencio) y None si no se pudo intentar (sin numpy). Si el análisis anterior ya la traía (con
    la versión actual y con la rejilla ya hecha entonces) se reutiliza."""
    if not structure_mod.available():
        return
    if previous and previous.get("beat_conf") is not None and previous.get("structure") is not None \
            and _structure_current(previous["structure"]):
        result["structure"] = previous["structure"]
        return
    try:
        found = structure_mod.analyse(samples, grid_from(result))
        result["structure"] = structure_mod.to_json(found) if found.get("energy") else ""
    except Exception as e:                    # fallaría igual cada vez: se apunta como intentado, sin romper el análisis
        logger.warning(f"No se pudo calcular la estructura: {e}")
        result["structure"] = ""


def _add_beatgrid(samples, result: dict) -> None:
    """La rejilla de golpes (fase 11) con las mismas muestras. `beat_conf` queda en 0 si se intentó y no hay pulso claro
    (no se reintenta) y en None si no se pudo intentar (sin numpy)."""
    if not beatgrid.available():
        return
    try:
        grid = beatgrid.compute(samples, result.get("bpm"))
    except Exception as e:                    # fallaría igual cada vez: se apunta como intentado
        logger.warning(f"No se pudo calcular la rejilla de golpes: {e}")
        grid = None
    if grid is None:
        result["beat_conf"] = 0.0
        return
    result.update({"beat_first_s": grid.first_beat_s, "beat_bpm": grid.bpm, "beat_downbeat": grid.downbeat_offset,
                   "beat_conf": grid.confidence})


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
