"""Cargador de audio del motor de mezcla del modo DJ (fase 12): una canción (o un trozo) como matriz de numpy, estéreo,
float32, a 44.100 Hz (`mix_types.SAMPLE_RATE`), y opcionalmente con el tempo cambiado sin cambiar el tono.

Cómo funciona: una sola llamada a FFmpeg decodifica, pasa a estéreo y a 44.100 Hz, estira con el filtro `rubberband`
(librubberband, la misma biblioteca que usan los programas de DJ y de audio profesional) y entrega las muestras en bruto
(`-f f32le`) por la tubería. Sin ventanas de consola (el parche global de Popen ya las oculta) y sin leer nada de la entrada.

Correspondencia de tiempos (medida con un click track, ver pruebas/prueba_pcm.py):
  * El audio devuelto empieza en `start_s` del original (la búsqueda `-ss` se hace antes de `-i`, que en FFmpeg es exacta
    al muestreo: decodifica un poco antes y descarta lo que sobra).
  * Un instante `t_original` (segundos desde el principio de la canción) cae en el instante
        (t_original - start_s) / tempo_ratio
    del resultado. Con `tempo_ratio` 1,08 (la canción va un 8 % más deprisa) todo ocurre antes y el resultado dura
    un 8 % menos. `duration_s` también se mide en el original: el resultado dura `duration_s / tempo_ratio`.
  * El filtro apenas desfasa: rubberband en FFmpeg compensa su propio retardo interno; queda un error constante (sin
    deriva) de unos 1 a 5 ms entre el golpe esperado y el real, y la búsqueda con `-ss` no añade nada (con archivo
    wav y mp3 sale lo mismo).

Opciones de rubberband (`RUBBERBAND_OPTIONS`) pensadas para música con percusión y cambios pequeños de tempo (de 0,92 a 1,08):
  * transients=crisp   mantiene nítidos los ataques (bombo, caja, hi-hat); `smooth` los emborrona, `mixed` queda a medias.
  * detector=percussive  la detección de golpes optimizada para percusión (en las pruebas no se midió diferencia con
                       `compound`; se deja por intención).
  * phase=independent  lo que más importa para percusión: con `laminar` (la opción por omisión de rubberband) un golpe
                       seco de 6 ms salía con el pico al 75 % y repartido en 10 a 15 ms; con `independent` sale al 96 a
                       103 % y en 2,3 ms. En canciones reales (factor de cresta de tramos de 20 ms, más cerca del original
                       es mejor) también queda igual o más cerca que `laminar`. El precio teórico es algo de «fase de
                       lata» en tonos sostenidos y voces; la pureza de un tono de 1 kHz medida es la misma (97,6 a 98 %),
                       pero el oído lo juzga el usuario.
  * window=standard    equilibrio entre graves limpios y ataques; `short` afina los golpes pero ensucia (95 % de pureza).
  * channels=together  procesa izquierda y derecha a la vez, para que la imagen estéreo no se corra al estirar.
  * pitch=1 (por omisión): el tono no cambia.
Mediciones de velocidad (con la máquina cargada): una canción de 2 min 10 s estirada tarda 2 a 3 s (unas 50 veces el tiempo
real); el estiramiento no desvía los golpes con el paso del tiempo (error constante de 1 a 5 ms, sin deriva en 60 s).

Límites: `tempo_ratio` de 0,5 a 2,0 (fuera de ahí devuelve None; quien llama decide si hace un corte limpio), y como mucho
8 minutos de resultado (unos 170 MB), para no comerse la memoria con una mezcla larguísima: lo que sobra se descarta.
Si no hay FFmpeg, o no tiene el filtro rubberband y hace falta estirar, devuelve None. numpy es opcional y se carga cuando
hace falta, como en `key_detect`."""
import logging
import subprocess

from services.ffmpeg_service import FFmpegService
from services.mix_types import SAMPLE_RATE

logger = logging.getLogger(__name__)

CHANNELS = 2
MAX_SECONDS = 480                      # 8 minutos de resultado como máximo (44,1 kHz estéreo float32: unos 170 MB)
MIN_RATIO, MAX_RATIO = 0.5, 2.0        # fuera de este margen el estiramiento suena a máquina: no se hace
RUBBERBAND_OPTIONS = "transients=crisp:detector=percussive:phase=independent:window=standard:channels=together"

_numpy_module = None
_numpy_checked = False
_rubberband_cache = None               # None = sin mirar todavía


def _numpy():
    """numpy, cargado la primera vez que se pide (tarda un poco y no hace falta si nadie usa el modo DJ), o None."""
    global _numpy_module, _numpy_checked
    if not _numpy_checked:
        _numpy_checked = True
        try:
            import numpy
            _numpy_module = numpy
        except ImportError:                # depende de cómo esté instalado
            _numpy_module = None
    return _numpy_module


def rubberband_available() -> bool:
    """¿Esta compilación de FFmpeg trae el filtro `rubberband`? Se pregunta una sola vez (`ffmpeg -filters`)."""
    global _rubberband_cache
    if _rubberband_cache is None:
        _rubberband_cache = False
        ffmpeg = FFmpegService.get_ffmpeg_path()
        if ffmpeg:
            try:
                out = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-filters"], capture_output=True, timeout=30).stdout
                _rubberband_cache = any(line.split()[1:2] == [b"rubberband"] for line in out.splitlines())
            except Exception as e:
                logger.warning(f"No se pudo comprobar si FFmpeg trae rubberband: {e}")
    return _rubberband_cache


def _command(ffmpeg: str, path: str, tempo_ratio: float, start_s: float, duration_s, options: str) -> list[str]:
    stretch = abs(tempo_ratio - 1.0) > 1e-9
    # Tope de memoria: como mucho MAX_SECONDS de resultado, que son MAX_SECONDS * ratio segundos del original
    source_s = MAX_SECONDS * tempo_ratio if duration_s is None else min(duration_s, MAX_SECONDS * tempo_ratio)
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error"]
    if start_s > 0:
        cmd += ["-ss", f"{start_s:.6f}"]                  # antes de -i: búsqueda exacta, el resultado empieza justo en start_s
    cmd += ["-t", f"{source_s:.6f}", "-i", path, "-vn", "-sn", "-dn"]
    # El formato final (estéreo, 44,1 kHz) se fija ANTES de estirar: rubberband trabaja ya con el audio definitivo
    chain = f"aformat=sample_rates={SAMPLE_RATE}:channel_layouts=stereo"
    if stretch:
        chain += f",rubberband=tempo={tempo_ratio:.9f}:{options}"
    cmd += ["-af", chain, "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]
    return cmd


def load(path: str, tempo_ratio: float = 1.0, start_s: float = 0.0, duration_s: float | None = None,
         timeout: int = 300, options: str = RUBBERBAND_OPTIONS):
    """Audio estéreo float32 a 44.100 Hz, forma (n, 2) con valores de -1 a 1 (pueden pasar un poco de 1 en mp3), o None.

    `tempo_ratio`: factor de velocidad sin cambiar el tono (1,08 = un 8 % más deprisa; el resultado dura 1/1,08).
    `start_s`: desde dónde, en segundos del original. `duration_s`: cuánto, en segundos del original (None = hasta el final,
    con el tope de 8 minutos de resultado). Correspondencia: t_original -> (t_original - start_s) / tempo_ratio.
    Devuelve None si: la razón está fuera de 0,5 a 2,0 o no es un número, hay que estirar y no hay rubberband, no hay numpy o
    FFmpeg, el archivo no existe o no se puede leer, o no queda audio en ese tramo. Nunca lanza excepciones."""
    try:
        tempo_ratio = float(tempo_ratio)
        start_s = max(0.0, float(start_s or 0.0))
        duration_s = None if duration_s is None else float(duration_s)
    except (TypeError, ValueError):
        return None
    if not (MIN_RATIO <= tempo_ratio <= MAX_RATIO):              # también descarta NaN
        return None
    if duration_s is not None and not duration_s > 0:
        return None
    np = _numpy()
    ffmpeg = FFmpegService.get_ffmpeg_path()
    if np is None or not ffmpeg:
        return None
    if abs(tempo_ratio - 1.0) > 1e-9 and not rubberband_available():
        return None
    try:
        out = subprocess.run(_command(ffmpeg, path, tempo_ratio, start_s, duration_s, options),
                             capture_output=True, timeout=timeout).stdout
    except Exception as e:
        logger.warning(f"No se pudo cargar {path} para el motor de mezcla: {e}")
        return None
    out = out[:len(out) // (4 * CHANNELS) * (4 * CHANNELS)]
    if not out:
        return None
    samples = np.frombuffer(out, dtype="<f4").reshape(-1, CHANNELS).astype(np.float32)    # copia: se puede modificar
    del out
    if not np.isfinite(samples).all():                           # un archivo roto no debe contaminar la mezcla con NaN
        np.nan_to_num(samples, copy=False, nan=0.0, posinf=1.0, neginf=-1.0)
    return samples
