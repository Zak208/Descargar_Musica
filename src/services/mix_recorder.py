"""Grabar el mix del modo DJ (fase 17): renderiza FUERA DE LÍNEA, sin abrir ningún dispositivo de sonido, lo mismo que tocaría el
motor del DJ y lo guarda en un archivo de audio, con la lista de canciones y los instantes de cada una. Sin Qt (aunque el
volumen igualado de `deck_gain` importa `loudness_service`, que sí lo trae).

Fidelidad ante todo: no hay lógica de mezcla propia. Se usa la `EngineSession` REAL sobre un `MixEngine` sin flujo y se saca el
audio con `pull`, que es exactamente lo que hace la llamada de audio. Lo grabado es, muestra a muestra, lo que sonaría.

Cómo se lleva la sesión sin reloj:
  * La interfaz llama a `tick()` cada 50 ms de tiempo real; aquí se llama entre trozo y trozo de 4096 muestras (93 ms de audio).
    El motor saca el audio mucho más deprisa que el tiempo real, así que la preparación de la siguiente canción (hilo de trabajo
    de la sesión: decodificar, medir el volumen, estirar, mezclar) NO puede ir por detrás de lo que se saca. Regla: no se saca
    audio mientras la sesión esté cargando o mientras no tenga lista la transición a la siguiente (si debe haberla); se espera
    con `time.sleep` corto. Así el plan siempre llega con tiempo, como en la reproducción de verdad (que le lleva 45 s de ventaja)
    y nunca sale un «plan tardío» que en directo no habría ocurrido. Si la siguiente no llega nunca (archivo roto, 5 intentos
    fallidos) se deja de esperar: tras 1 s sin nada preparándose, o tras `PREP_TIMEOUT_S` preparándose sin avanzar.
  * El audio va a FFmpeg por una tubería (`-f f32le`), nunca se guarda entero en memoria (una hora estéreo float32 son 1,2 GB).
    Se escribe en `<salida>.part` y solo al terminar bien se renombra: si se cancela o falla, se borra y la salida anterior (si
    había) queda intacta.
  * Solo se escribe el contenido que el motor entregó (`position_frames`): el silencio que rellena un trozo cuando la cola se vacía
    (al final, o si una canción tardó en llegar) no se graba. El instante de salida de cualquier cosa es, por tanto, `muestras
    escritas / 44.100`.
  * Los instantes salen de las notificaciones del motor (`on_segment_start`, exactas a la muestra), no del momento del `tick()`:
    «empieza a dominar B» es el comienzo de su segmento de entrada (la segunda mitad de la mezcla), que es justo lo que
    `tick()` anuncia con `advanced`, y `at_s` de cada transición es el comienzo de la mezcla (primera mitad, o el final de A con
    rampa en un corte).
  * Volumen: lo que sale puede pasar de ±1 (el motor no recorta; lo hace el dispositivo): FFmpeg lo recorta al convertir. El pico
    real se da en `peak` por si la interfaz quiere avisar.

Resultado de `render_session` (dict):
    tracklist    [{"start_s", "path", "title"}] en orden; start_s = segundo de la salida en que domina cada canción
    transitions  [{"at_s", "start_s", "from", "to", "plan"}]; plan = el `TransitionPlan` como dict (None si no se vio)
    duration_s   duración del archivo, out_path (None si se canceló), cancelled, peak, nonfinite (muestras NaN que se pusieron a 0),
    errors       avisos de la sesión (canciones que no se pudieron cargar, que se saltaron), wall_s (lo que tardó en la realidad)

`render_transition_clip` hace lo mismo con una sola pareja de canciones, en memoria y sin FFmpeg para codificar, para escuchar
y puntuar transiciones sueltas."""
import dataclasses
import logging
import math
import os
import subprocess
import tempfile
import time
from typing import NamedTuple

from services.audio_engine import MixEngine
from services.dj_engine import EngineSession
from services.ffmpeg_service import FFmpegService
from services.mix_types import SAMPLE_RATE

log = logging.getLogger(__name__)

CHUNK_FRAMES = 4096             # muestras que se sacan del motor entre un tick y el siguiente
POLL_S = 0.005                  # espera corta mientras el hilo de trabajo prepara algo
IDLE_GIVE_UP_S = 1.0            # sin nada preparándose y sin plan durante este tiempo: no hay siguiente, se sigue
PREP_TIMEOUT_S = 180.0          # preparando la siguiente sin ningún avance durante este tiempo: se sigue sin ella
CLIP_TIMEOUT_S = 90.0           # lo máximo que se espera a que la sesión cargue y planifique en render_transition_clip

# extensión -> (formato de contenedor, opciones del códec, ¿usa bitrate?, tipo del archivo en un .cue)
_FORMATS = {
    ".mp3": ("mp3", ["-c:a", "libmp3lame"], True, "MP3"),
    ".wav": ("wav", ["-c:a", "pcm_s16le"], False, "WAVE"),
    ".flac": ("flac", ["-c:a", "flac"], False, "WAVE"),
    ".m4a": ("ipod", ["-c:a", "aac"], True, "WAVE"),
}


class TransitionClip(NamedTuple):
    audio: object               # numpy (n, 2) float32 a 44.100 Hz
    plan: object                # TransitionPlan de la mezcla
    mix_start_s: float          # dentro del clip: donde empieza la mezcla
    mix_end_s: float            # dentro del clip: donde acaba (en un corte, igual que mix_start_s)
    a_from_s: float             # en tiempo de A: de dónde se tomó el principio del clip
    sample_rate: int


def supported_extensions() -> tuple:
    return tuple(_FORMATS)


def _norm(path):
    return os.path.normcase(os.path.normpath(path)) if path else path


def _title(path, info) -> str:
    """Etiqueta de una canción: «artista - título» si la ficha los trae; si no, el nombre del archivo sin extensión."""
    if isinstance(info, dict):
        title = str(info.get("title") or "").strip()
        artist = str(info.get("artist") or "").strip()
        if title:
            return title if not artist or artist.lower() in title.lower() else f"{artist} - {title}"
    return os.path.splitext(os.path.basename(path))[0]


def _info_safe(info_for, path):
    try:
        return info_for(path)
    except Exception as e:
        log.warning("info_for falló con %s: %s", path, e)
        return None


def _ffmpeg_or_raise() -> str:
    ffmpeg = FFmpegService.get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("No se encontró FFmpeg: hace falta para guardar el mix. Instálalo desde los ajustes de la aplicación.")
    return ffmpeg


def _start_encoder(ffmpeg, out_path, part_path, bitrate):
    ext = os.path.splitext(out_path)[1].lower()
    if ext not in _FORMATS:
        raise ValueError(f"Formato de salida no admitido: «{ext}». Usa uno de {', '.join(_FORMATS)}.")
    fmt, codec, uses_bitrate, _ = _FORMATS[ext]
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "2", "-i", "-",
           *codec, *(["-b:a", bitrate] if uses_bitrate else []), "-f", fmt, part_path]
    err = tempfile.TemporaryFile()  # noqa: SIM115  el texto de error de FFmpeg; un archivo y no una tubería: no puede bloquear
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err, creationflags=flags)
    except OSError:
        err.close()
        raise
    return proc, err


def _ffmpeg_error(proc, err) -> str:
    try:
        err.seek(0)
        text = err.read().decode("utf-8", "replace").strip()
    except Exception:
        text = ""
    return text[-400:] or f"código {proc.returncode}"


class _Recorder:
    """Lleva la sesión sin reloj y apunta lo que pasa. `emit(array)` recibe cada trozo de contenido real."""

    def __init__(self, paths, info_for, bars, session_kw):
        self.paths = list(paths)
        self.info_for = info_for
        self.engine = MixEngine()
        self.engine.on_segment_start = self._on_segment
        self.session = EngineSession(self.engine, info_for, self._next_after, bars=bars, **session_kw)
        self.idx = 0                    # posición, en `paths`, de la canción que suena
        self.events = []                # (rol, muestra de la salida, id de pista) de los segmentos que han empezado
        self.written = 0                # muestras de contenido ya escritas
        self.peak = 0.0
        self.nonfinite = 0
        self.errors = []
        self.tracklist = []
        self.transitions = []
        self.last_plan = None

    # ---- lo que la sesión pregunta y el motor avisa
    def _next_after(self, path):
        key = _norm(path)
        for k in range(self.idx, len(self.paths)):
            if _norm(self.paths[k]) == key:
                return self.paths[k + 1] if k + 1 < len(self.paths) else None
        return None

    def _on_segment(self, label, seg_id, start_frame):
        role = getattr(label, "role", None)
        if role in ("x1", "entry"):
            self.events.append((role, int(start_frame), getattr(label, "track_id", None)))

    def _advance_idx(self, path):
        key = _norm(path)
        for k in range(self.idx + 1, len(self.paths)):
            if _norm(self.paths[k]) == key:
                for skipped in self.paths[self.idx + 1:k]:      # las que la sesión no pudo cargar y saltó
                    self.errors.append(f"se saltó una canción que no se pudo cargar: {skipped}")
                self.idx = k
                return
        self.idx += 1

    # ---- avance
    def _add_track(self, start_s, path):
        self.tracklist.append({"start_s": start_s, "path": path, "title": _title(path, _info_safe(self.info_for, path))})

    def _note_advance(self, st):
        entry = next((e for e in reversed(self.events) if e[0] == "entry"), None)
        mix = next((e for e in reversed(self.events) if e[0] == "x1" and (entry is None or e[1] <= entry[1])), None)
        self.events.clear()
        start = (entry[1] if entry is not None else self.written) / SAMPLE_RATE
        prev = self.tracklist[-1]["path"] if self.tracklist else None
        self._advance_idx(st["advanced"])
        self._add_track(start, st["advanced"])
        self.transitions.append({"at_s": (mix[1] if mix is not None else (entry[1] if entry is not None else self.written)) / SAMPLE_RATE,
                                 "start_s": start, "from": prev, "to": st["advanced"],
                                 "plan": dataclasses.asdict(self.last_plan) if self.last_plan is not None else None})
        self.last_plan = None

    def run(self, emit, cancel=None, progress=None) -> bool:
        """Saca audio hasta que acabe la última canción. False si se canceló."""
        sess, eng = self.session, self.engine
        sess.play(self.paths[0])
        started = False
        idle_since = prep_since = time.monotonic()
        last_next, last_report = None, 0.0
        while True:
            if cancel is not None and cancel():
                return False
            st = sess.tick()
            if st["error"]:
                self.errors.append(st["error"])
            if st["plan"] is not None:
                self.last_plan = st["plan"]
            if st["advanced"]:
                self._note_advance(st)
                prep_since = idle_since = time.monotonic()
            if st["ended"]:
                return True
            if st["state"] == "loading":
                time.sleep(POLL_S)
                continue
            if st["state"] == "stopped":                # la primera no se pudo cargar (después de `ended` ya no se llega aquí)
                raise RuntimeError(st["error"] or (self.errors[-1] if self.errors else "no se pudo cargar la primera canción"))
            if not started:
                started = True
                self._add_track(0.0, self.paths[0])
                prep_since = idle_since = time.monotonic()
            if self._must_wait(st, last_next, idle_since, prep_since):
                if st["next_path"] != last_next:
                    last_next, prep_since = st["next_path"], time.monotonic()
                if st["next_path"] is not None:
                    idle_since = time.monotonic()
                time.sleep(POLL_S)
                continue
            before = eng.position_frames
            chunk = eng.pull(CHUNK_FRAMES)
            n = eng.position_frames - before
            if n > 0:
                emit(self._clean(chunk[:n]))
                self.written += n
            now = time.monotonic()
            if progress is not None and now - last_report > 0.25:
                last_report = now
                progress(self.idx, len(self.paths), self.written / SAMPLE_RATE)

    def _must_wait(self, st, last_next, idle_since, prep_since) -> bool:
        """¿Hay que esperar a que el hilo de trabajo tenga lista la transición a la siguiente antes de sacar más audio?"""
        if self.idx >= len(self.paths) - 1 or st["plan"] is not None:
            return False
        now = time.monotonic()
        if st["next_path"] is None:                     # nadie la está preparando: puede ser el instante entre dos pasos, o que no haya
            return now - idle_since < IDLE_GIVE_UP_S
        return now - prep_since < PREP_TIMEOUT_S

    def _clean(self, block):
        import numpy as np
        peak = float(np.abs(block).max())
        if not math.isfinite(peak):
            bad = ~np.isfinite(block)
            self.nonfinite += int(bad.sum())
            block = np.nan_to_num(block, nan=0.0, posinf=1.0, neginf=-1.0)
            peak = float(np.abs(block).max())
        self.peak = max(self.peak, peak)
        return block


def render_session(paths, info_for, out_path, bars=16, progress=None, cancel=None, max_tracks=None, bitrate="192k", **session_kw):
    """Graba en `out_path` (mp3, wav, flac o m4a según la extensión) lo que tocaría el modo DJ con esas canciones, en ese orden.

    `info_for(path)`: la ficha de cada canción para el planificador (la misma función que se da a `EngineSession`).
    `progress(indice, total, segundos_de_salida)`: si se da, se llama unas 4 veces por segundo (índice 0 de la canción que suena).
    `cancel()`: si devuelve True se para, se cierra FFmpeg y se borra el archivo a medias (devuelve `cancelled` True).
    `max_tracks`: solo las N primeras. `session_kw`: más parámetros de `EngineSession` (`loader`, `lufs_stored`, `lufs_measure`).
    Lanza RuntimeError (sin FFmpeg, no se pudo cargar la primera canción, FFmpeg falló) o ValueError (formato o lista vacía).
    Ver el resultado en la explicación del módulo. Se debe llamar desde un hilo que no sea el de la interfaz: tarda."""
    paths = [p for p in paths if p]
    if max_tracks is not None:
        paths = paths[:max(0, int(max_tracks))]
    if not paths:
        raise ValueError("No hay canciones que grabar.")
    out_path = os.fspath(out_path)
    ffmpeg = _ffmpeg_or_raise()
    part = out_path + ".part"
    t0 = time.monotonic()
    rec = _Recorder(paths, info_for, bars, session_kw)
    proc, err = _start_encoder(ffmpeg, out_path, part, bitrate)
    done = False

    def emit(block):
        try:
            proc.stdin.write(block.tobytes())
        except (BrokenPipeError, OSError, ValueError):
            proc.wait()
            raise RuntimeError("FFmpeg se detuvo al guardar el mix: " + _ffmpeg_error(proc, err)) from None

    try:
        finished = rec.run(emit, cancel, progress)
        if finished:
            try:
                proc.stdin.close()
            except OSError:
                pass
            if proc.wait(timeout=300) != 0:
                raise RuntimeError("FFmpeg no pudo guardar el mix: " + _ffmpeg_error(proc, err))
            os.replace(part, out_path)
            done = True
        return {"tracklist": rec.tracklist, "transitions": rec.transitions, "duration_s": rec.written / SAMPLE_RATE,
                "out_path": out_path if done else None, "cancelled": not finished, "peak": rec.peak, "nonfinite": rec.nonfinite,
                "errors": rec.errors, "wall_s": time.monotonic() - t0}
    finally:
        rec.session.stop(wait=True)
        if not done:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        try:
            proc.stdin.close()
        except Exception:
            pass
        err.close()
        if not done:
            try:
                os.remove(part)
            except OSError:
                pass


# ---- listados --------------------------------------------------------------------------------------------------------------
def _mmss(seconds) -> str:
    total = int(max(0.0, seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def write_tracklist(result, path_txt):
    """Escribe el listado de canciones con su minuto de entrada (minutos:segundos; pasada la hora, los minutos siguen contando)."""
    lines = [f"{k:02d}. {_mmss(t['start_s'])}  {t['title']}" for k, t in enumerate(result["tracklist"], 1)]
    with open(path_txt, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def _cue_time(seconds) -> str:
    frames = int(max(0.0, seconds) * 75 + 1e-6)          # un archivo .cue cuenta en 75 fotogramas por segundo
    return f"{frames // 4500:02d}:{frames // 75 % 60:02d}:{frames % 75:02d}"


def write_cue(result, path_cue):
    """Escribe un .cue estándar (una pista por canción, INDEX 01 en minutos:segundos:fotogramas) del archivo de audio grabado."""
    out = result.get("out_path") or ""
    kind = _FORMATS.get(os.path.splitext(out)[1].lower(), (None, None, None, "WAVE"))[3]

    def clean(text):
        return str(text).replace('"', "'")

    lines = [f'FILE "{clean(os.path.basename(out))}" {kind}']
    for k, t in enumerate(result["tracklist"], 1):
        lines += [f"  TRACK {k:02d} AUDIO", f'    TITLE "{clean(t["title"])}"', f"    INDEX 01 {_cue_time(t['start_s'])}"]
    with open(path_cue, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


# ---- una transición suelta -------------------------------------------------------------------------------------------------
def render_transition_clip(a_path, b_path, info_a, info_b, context_s=12.0, bars=16, **session_kw) -> TransitionClip:
    """`context_s` segundos de A antes de empezar la mezcla, la mezcla entera y `context_s` segundos de B después, con el mismo
    código que el motor (una `EngineSession` con solo esas dos canciones, `seek` al punto de partida y `pull`).

    Si A no tiene `context_s` segundos antes de la mezcla, el clip empieza en su principio (`a_from_s` dice de dónde empieza);
    si B no tiene tanto después, el clip acaba donde acaba B. `info_a` e `info_b`: las fichas de las dos canciones. Con la
    misma ruta dos veces la ficha de B se pierde (se da la de A): usa dos archivos distintos. Tarda lo que decodificar,
    medir el volumen de B y estirar el tramo (2 a 4 s con canciones de 3 min); llamar desde un hilo que no sea el de la interfaz.
    Lanza RuntimeError si no se pudo cargar alguna o preparar la mezcla."""
    import numpy as np
    infos = {_norm(a_path): info_a, _norm(b_path): info_b}
    eng = MixEngine()
    sess = EngineSession(eng, lambda p: infos.get(_norm(p), {}), lambda p: b_path if _norm(p) == _norm(a_path) else None,
                         bars=bars, **session_kw)
    try:
        sess.play(a_path)
        t0 = idle_since = time.monotonic()
        plan, errors = None, []
        while plan is None:
            st = sess.tick()
            if st["error"]:
                errors.append(st["error"])
            plan = st["plan"]
            if plan is not None:
                break
            now = time.monotonic()
            if st["state"] == "stopped":
                raise RuntimeError(errors[-1] if errors else "no se pudo cargar la primera canción")
            if st["state"] == "loading" or st["next_path"] is not None:
                idle_since = now
            if now - t0 > CLIP_TIMEOUT_S or (errors and now - idle_since > IDLE_GIVE_UP_S):
                raise RuntimeError(errors[-1] if errors else "la mezcla no se preparó a tiempo")
            time.sleep(POLL_S)
        s0 = max(0.0, plan.a_start_s - context_s)
        sess.seek(s0)
        mix_start = plan.a_start_s - s0
        mix_end = mix_start + (plan.length_s if plan.kind != "cut" else 0.0)
        total = round((mix_end + context_s) * SAMPLE_RATE)
        parts, got = [], 0
        while got < total:
            before = eng.position_frames
            chunk = eng.pull(min(CHUNK_FRAMES * 16, total - got))
            n = eng.position_frames - before
            if n <= 0:
                break
            parts.append(chunk[:n])
            got += n
        audio = np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)
        return TransitionClip(audio, plan, mix_start, mix_end, s0, SAMPLE_RATE)
    finally:
        sess.stop(wait=True)
