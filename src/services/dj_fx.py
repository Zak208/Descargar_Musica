"""Efectos del modo DJ (fase 20): eco, eco al tempo, filtro con barrido, reverberación, subida de ruido (riser), repetición
(stutter) y utilidades de ganancia, como funciones puras sobre arrays de audio.

Formato: igual que `dj_dsp`: numpy, float32, 44.100 Hz (`mix_types.SAMPLE_RATE`). Todas las funciones aceptan (n,), (n, 1)
o (n, 2) y devuelven SIEMPRE estéreo (m, 2) float32, una copia nueva (nunca modifican la entrada). Una entrada vacía da una
salida vacía (o solo la cola pedida, en silencio). Todo está vectorizado con numpy (sin bucles de Python por muestra): 30 s de
estéreo se procesan en bastante menos de 1 s (medido en `pruebas/prueba_efectos.py`).

Longitud de la salida:
  * Sin cola (filter_sweep, stutter, gain_ramp, limit_peak): la misma que la entrada.
  * Con cola (echo, echo_beats, reverb_tail): len(entrada) + round(tail_s * sample_rate). Lo que sobresale es la cola del
    efecto, que sigue sonando cuando la entrada ya ha acabado; sus últimos 50 ms bajan a cero con una rampa (si se recorta
    antes de apagarse del todo no hace clic). Mientras dura la entrada, la salida es la entrada seca más el efecto: el
    efecto empieza en silencio (el eco no suena hasta el primer retardo y la reverberación hasta su pre-retardo), así que el
    primer fotograma de la salida es el de la entrada y no hay salto con lo que suena antes.
  * Si la entrada no termina en silencio, la cola empieza con un salto de la señal seca a cero: bájala antes con `gain_ramp`.

Ganancia segura: los efectos «de cola» (echo, echo_beats, reverb_tail, riser) nunca pasan de ±0,99 (`CEILING`): si la suma
seca más efecto se pasa, `limit_peak` baja la ganancia solo alrededor de los picos, con una curva suave (sin clic). Si no se
pasa, no se toca nada (la salida es exactamente seca + efecto). `filter_sweep` solo se limita si tiene resonancia (la
resonancia sube el nivel cerca del corte); sin ella el filtro solo quita, no añade.

Cómo funciona el filtro con barrido (`filter_sweep`): por bloques de 2048 muestras con ventana de Hann y solape del 50 % (la
suma de las ventanas es exactamente 1, así que sin filtro se reconstruye la señal). Cada bloque se lleva a la frecuencia con
una FFT de 8192 puntos (el relleno de ceros deja sitio a la respuesta del filtro sin que se dé la vuelta), se multiplica por
la respuesta en magnitud de un Butterworth (24 dB por octava por defecto, fase cero) con su propia frecuencia de corte y se
vuelve atrás sumando los bloques solapados. El corte avanza en escala logarítmica, un paso cada 1024 muestras (23 ms), y el
solape funde un paso con el siguiente: no se oyen escalones. El filtro no es causal (usa el futuro) y trata lo que hay antes
y después del audio como silencio; en el primer y el último bloque el resultado es el de un audio que empieza o acaba ahí.

Límites: los retardos van de 1 ms a 10 s, la realimentación de 0 a 0,95, las colas automáticas no pasan de 10 s. No hay
efectos en tiempo real: todo se calcula sobre trozos ya cargados (como el resto del motor híbrido, ver docs/MOTOR_DJ.md)."""
import math

from services import dj_dsp
from services.mix_types import SAMPLE_RATE

CEILING = 0.99                  # pico máximo de la salida de los efectos «de cola»
TAIL_FADE_S = 0.05              # rampa de bajada al final de una cola
STUTTER_RAMP_S = 0.002          # rampas de cada repetición del stutter
MIN_DELAY_S, MAX_DELAY_S = 0.001, 10.0
MAX_FEEDBACK = 0.95
MAX_TAIL_S = 10.0
FRAME = 2048                    # bloque del filtro con barrido (y su FFT, 4 veces más larga)
FFT_PAD = 4
FILTER_ORDER = 4                # Butterworth de 4.º orden: 24 dB por octava (pendiente suave, no pared de ladrillo)
RES_WIDTH_OCT = 0.3             # anchura (desviación, en octavas) del pico de resonancia
LIMIT_BLOCK = 256               # bloque del limitador (5,8 ms)
LIMIT_SPREAD = 4                # el limitador empieza a bajar 4 bloques (23 ms) antes del pico y sube 4 después
REVERB_PREDELAY_S = 0.02
REVERB_LOW_CUT_HZ = 150.0       # la reverberación no lleva graves (emborronan el bombo)
REVERB_HIGH_CUT_HZ = 6000.0     # ni agudos fuertes (suena más natural y menos metálica)
_CHUNK = 64                     # bloques del filtro que se transforman a la vez (memoria acotada: unos 8 MB)


def _np():
    return dj_dsp._np()


def _stereo(audio):
    """La entrada como float32 (n, 2): mono se duplica. Puede ser la misma memoria que la entrada (no escribir en ella)."""
    return dj_dsp._to_stereo(audio)


def _fade_out(x, n_fade: int):
    """Baja a cero, con una rampa de coseno, los últimos `n_fade` fotogramas de x (en el sitio)."""
    n_fade = min(int(n_fade), len(x))
    if n_fade > 0:
        x[len(x) - n_fade:] *= dj_dsp._ramp(n_fade, down=True)[:, None]


def _check_sr(sample_rate):
    if not isinstance(sample_rate, (int, float)) or sample_rate <= 0:
        raise ValueError("sample_rate debe ser positivo")


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} debe ser un número")
    return float(value)


# ------------------------------------------------------------------ ganancia

def limit_peak(audio, ceiling: float = CEILING):
    """Limitador de seguridad: la misma señal, pero sin pasar de ±`ceiling` en ningún canal. Si ya no se pasa, devuelve una
    copia exacta. Si se pasa, multiplica por una curva de ganancia que baja solo alrededor de cada pico (empieza a bajar
    unos 23 ms antes y vuelve a 1 unos 23 ms después, con tramos lineales de 5,8 ms: sin clics), garantizando que en cada
    muestra la ganancia es la que hace falta o menos. Devuelve float32 (n, 2). No es un compresor: no sube nada."""
    np = _np()
    x = _stereo(audio)
    n = len(x)
    ceiling = max(1e-6, float(ceiling))
    peak = np.max(np.abs(x), axis=1) if n else np.zeros(0, np.float32)
    if n == 0 or float(np.max(peak)) <= ceiling:
        return x.copy()
    nb = -(-n // LIMIT_BLOCK)
    padded = np.zeros(nb * LIMIT_BLOCK, dtype=np.float64)
    padded[:n] = peak
    need = np.minimum(1.0, ceiling / np.maximum(padded.reshape(nb, LIMIT_BLOCK).max(axis=1), 1e-12))
    # mínimo entre vecinos: entre dos centros de bloque la interpolación no pasa de lo que necesitan los dos bloques
    k = LIMIT_SPREAD
    wide = np.concatenate([np.ones(k), need, np.ones(k)])
    smooth = np.lib.stride_tricks.sliding_window_view(wide, 2 * k + 1).min(axis=1)
    centers = np.arange(nb) * LIMIT_BLOCK + LIMIT_BLOCK / 2.0
    gain = np.interp(np.arange(n, dtype=np.float64), centers, smooth)
    out = x.astype(np.float64) * gain[:, None]
    return np.clip(out, -ceiling, ceiling).astype(np.float32)


def gain_ramp(audio, start_gain: float, end_gain: float):
    """El audio multiplicado por una ganancia que va en línea recta de `start_gain` (primer fotograma) a `end_gain` (último).
    Sirve para bajar a cero el final de un trozo antes de darle cola a un efecto, o para un fundido sencillo. Devuelve
    float32 (n, 2) de la misma longitud. Con un solo fotograma se usa `start_gain`."""
    np = _np()
    x = _stereo(audio)
    n = len(x)
    if n == 0:
        return x.copy()
    g = np.linspace(float(start_gain), float(end_gain), n) if n > 1 else np.array([float(start_gain)])
    return (x.astype(np.float64) * g[:, None]).astype(np.float32)


def crossfade_equal_power(a, b):
    """Fundido cruzado de potencia constante de `a` (sale con coseno) a `b` (entra con seno), a lo largo de la más larga de
    las dos (la más corta se rellena con silencio). Mismo fundido que los medios y agudos de `dj_dsp.render_transition`:
    en el primer fotograma suena `a` y en el último `b`. Devuelve float32 (max(len(a), len(b)), 2)."""
    np = _np()
    a, b = _stereo(a), _stereo(b)
    n = max(len(a), len(b))
    out = np.zeros((n, 2), dtype=np.float64)
    if n == 0:
        return out.astype(np.float32)
    angle = (np.arange(n, dtype=np.float64) + 0.5) / n * (math.pi / 2.0)
    out[:len(a)] += a * np.cos(angle[:len(a)])[:, None]
    out[:len(b)] += b * np.sin(angle[:len(b)])[:, None]
    return out.astype(np.float32)


# ------------------------------------------------------------------ eco

def _echo_wet(x, d: int, feedback: float, total: int):
    """Solo el eco (sin la señal seca) de x (n, canales) float64, de `total` fotogramas: wet[t] = suma de k >= 1 de
    feedback^(k-1) * x[t - k*d]. Por bloques de d muestras (cada bloque es el anterior realimentado más la entrada
    retrasada): un bucle por repetición del eco, no por muestra; cuando la entrada se acaba, el resto es una potencia."""
    np = _np()
    ch = x.shape[1]
    m = -(-total // d)
    xb = np.zeros((m * d, ch), dtype=np.float64)
    have = min(len(x), m * d)
    xb[:have] = x[:have]
    xb = xb.reshape(m, d, ch)
    y = np.zeros_like(xb)
    last_in = min(m - 1, -(-len(x) // d))           # a partir de este bloque ya no entra nada
    for k in range(1, last_in + 1):
        y[k] = xb[k - 1] + feedback * y[k - 1]
    if last_in + 1 < m:
        powers = feedback ** np.arange(1, m - last_in, dtype=np.float64)
        y[last_in + 1:] = y[last_in][None] * powers[:, None, None]
    return y.reshape(m * d, ch)[:total]


def echo_tail_s(delay_s: float, feedback: float, floor_db: float = -60.0) -> float:
    """Segundos que tarda un eco en caer por debajo de `floor_db` respecto a la primera repetición (con un máximo de 10 s).
    Sin realimentación, un solo retardo."""
    delay_s = min(max(float(delay_s), MIN_DELAY_S), MAX_DELAY_S)
    feedback = min(max(float(feedback), 0.0), MAX_FEEDBACK)
    if feedback <= 0.0:
        return min(delay_s, MAX_TAIL_S)
    repeats = math.ceil(math.log(10.0 ** (float(floor_db) / 20.0)) / math.log(feedback)) + 1
    return min(repeats * delay_s, MAX_TAIL_S)


def echo(audio, delay_s: float, feedback: float, mix: float, tail_s: float = 0.0, sample_rate: int = SAMPLE_RATE):
    """Eco con realimentación: salida = seca + mix * (repeticiones), donde la repetición k (k = 1, 2...) llega `k * delay_s`
    después y suena a feedback^(k-1). La primera repetición suena a `mix` del original.

    Parámetros: delay_s de 1 ms a 10 s (se redondea a la muestra), feedback de 0 a 0,95 y mix de 0 a 1 (fuera de rango se
    recortan); tail_s >= 0: segundos de cola tras el final de la entrada (0 = misma longitud, el eco se corta al acabar).
    Devuelve float32 (n + round(tail_s * sample_rate), 2), con ganancia segura (nunca pasa de ±0,99) y los últimos 50 ms de la
    cola bajando a cero. Los primeros `delay_s` de la salida son la entrada sin tocar."""
    np = _np()
    _check_sr(sample_rate)
    delay_s = min(max(_finite(delay_s, "delay_s"), MIN_DELAY_S), MAX_DELAY_S)
    feedback = min(max(_finite(feedback, "feedback"), 0.0), MAX_FEEDBACK)
    mix = min(max(_finite(mix, "mix"), 0.0), 1.0)
    x = _stereo(audio)
    n = len(x)
    tail_n = max(0, int(round(max(0.0, _finite(tail_s, "tail_s")) * sample_rate)))
    total = n + tail_n
    out = np.zeros((total, 2), dtype=np.float64)
    if total == 0:
        return out.astype(np.float32)
    out[:n] = x
    if n and mix > 0.0:
        d = max(1, int(round(delay_s * sample_rate)))
        out += mix * _echo_wet(x.astype(np.float64), d, feedback, total)
    if tail_n:
        _fade_out(out[n:], min(tail_n, int(TAIL_FADE_S * sample_rate)))
    return limit_peak(out)


def echo_beats(audio, bpm: float, beats: float = 0.75, feedback: float = 0.45, mix: float = 0.5, tail_s: float = None,
               sample_rate: int = SAMPLE_RATE):
    """Eco al tempo: como `echo` con un retardo de `beats` golpes a `bpm` (0,75 por defecto: tres semicorcheas, el eco
    «con puntillo» habitual de los DJ, que cae entre los golpes y no los tapa). Con tail_s None, la cola dura lo que el eco
    tarda en caer 60 dB (`echo_tail_s`, como mucho 10 s): con 128 BPM y los valores por defecto, unos 3,9 s. Devuelve
    float32 (n + cola, 2), con ganancia segura. ValueError si el BPM o los golpes no son positivos."""
    bpm = _finite(bpm, "bpm")
    beats = _finite(beats, "beats")
    if bpm <= 0 or beats <= 0:
        raise ValueError("bpm y beats deben ser positivos")
    delay = beats * 60.0 / bpm
    if tail_s is None:
        tail_s = echo_tail_s(delay, feedback)
    return echo(audio, delay, feedback, mix, tail_s, sample_rate)


# ------------------------------------------------------------------ filtro con barrido

def _stft_filter(x, masks_for, sample_rate):
    """Filtra x (n, canales) por bloques solapados con una máscara de magnitud distinta en cada bloque. `masks_for(centros, freqs)`
    recibe los centros de los bloques (en muestras de x, pueden caer fuera) y las frecuencias de la FFT, y devuelve (bloques,
    puntos) con la ganancia de cada punto. Devuelve float64 (n, canales). Con máscaras de 1 reconstruye x (error ~1e-15)."""
    np = _np()
    n, ch = x.shape
    size, hop, fft_n = FRAME, FRAME // 2, FRAME * FFT_PAD
    off = (fft_n - size) // 2                        # el bloque va centrado: la respuesta del filtro cabe a los dos lados
    frames_n = -(-n // hop) + 1
    padded = np.zeros(((frames_n - 1) * hop + size, ch), dtype=np.float64)
    padded[hop:hop + n] = x
    window = 0.5 - 0.5 * np.cos(2.0 * math.pi * np.arange(size) / size)     # Hann periódica: con solape del 50 % suma 1
    frames = np.lib.stride_tricks.sliding_window_view(padded, size, axis=0)[::hop]   # (bloques, canales, size), sin copia
    freqs = np.fft.rfftfreq(fft_n, 1.0 / sample_rate)
    centers = np.arange(frames_n, dtype=np.float64) * hop            # centro de cada bloque, en muestras de x
    parts = fft_n // hop
    acc = np.zeros((frames_n + parts, ch, hop), dtype=np.float64)
    for s in range(0, frames_n, _CHUNK):
        block = frames[s:s + _CHUNK] * window
        k = len(block)
        spec = np.fft.rfft(block, n=fft_n, axis=-1) * masks_for(centers[s:s + k], freqs)[:, None, :]
        y = np.roll(np.fft.irfft(spec, n=fft_n, axis=-1), off, axis=-1).reshape(k, ch, parts, hop)
        for j in range(parts):
            acc[s + j:s + j + k] += y[:, :, j, :]
    out = acc.transpose(1, 0, 2).reshape(ch, -1).T
    return out[hop + off:hop + off + n]


def _cutoffs(centers, n, start_hz, end_hz, start_at, end_at):
    """Frecuencia de corte de cada bloque: de start_hz a end_hz en escala logarítmica entre las fracciones start_at y end_at
    del audio (antes, start_hz; después, end_hz)."""
    np = _np()
    u = np.clip(centers / max(n - 1, 1), 0.0, 1.0)
    span = max(end_at - start_at, 1e-9)
    p = np.clip((u - start_at) / span, 0.0, 1.0)
    return start_hz * (end_hz / start_hz) ** p


def _sweep_masks(kind, start_hz, end_hz, resonance, order, n, start_at, end_at):
    np = _np()

    def masks_for(centers, freqs):
        fc = _cutoffs(centers, n, start_hz, end_hz, start_at, end_at)[:, None]
        f = np.maximum(freqs, 1e-3)[None, :]
        if kind == "bp":                                            # campana de 1 octava (riser): sin realimentar
            return np.exp(-0.5 * (np.log2(f / fc) / 0.5) ** 2) * np.sqrt(start_hz / fc)
        r = (f / fc) ** order
        mask = 1.0 / np.sqrt(1.0 + r * r) if kind == "lp" else r / np.sqrt(1.0 + r * r)
        if resonance > 0.0:
            mask = mask * (1.0 + resonance * np.exp(-0.5 * (np.log2(f / fc) / RES_WIDTH_OCT) ** 2))
        return mask
    return masks_for


def filter_sweep(audio, kind: str, start_hz: float, end_hz: float, resonance: float = 0.0, sample_rate: int = SAMPLE_RATE,
                 order: int = FILTER_ORDER, start_at: float = 0.0, end_at: float = 1.0):
    """Filtro paso alto (`kind` «hp») o paso bajo («lp») cuya frecuencia de corte barre de `start_hz` a `end_hz` en escala
    logarítmica a lo largo del audio (un hp que sube de 20 Hz a 2 kHz va quitando graves y luego cuerpo; un lp que sube de
    300 Hz a 20 kHz va «abriendo» una canción apagada).

    Respuesta en magnitud de un Butterworth de orden `order` (4 = 24 dB por octava), fase cero, -3 dB en el corte.
    `resonance` de 0 a 1 añade un pico de hasta +6 dB alrededor del corte (en ese caso la salida pasa por la ganancia segura).
    `start_at` y `end_at` (fracciones de 0 a 1 de la duración) dicen cuándo empieza y acaba el barrido: antes el corte está
    quieto en start_hz y después en end_hz (por ejemplo, end_at=0,8 para que el filtro esté del todo abierto en el último 20 %).
    Las frecuencias deben estar entre 0 y sample_rate / 2 (ValueError si no). Devuelve float32 (n, 2), misma longitud.
    Por bloques de 2048 muestras con solape (ver el docstring del módulo): el corte cambia cada 23 ms, sin escalones."""
    np = _np()
    _check_sr(sample_rate)
    if kind not in ("hp", "lp"):
        raise ValueError("kind debe ser «hp» (paso alto) o «lp» (paso bajo)")
    start_hz, end_hz = _finite(start_hz, "start_hz"), _finite(end_hz, "end_hz")
    if not (0.0 < start_hz < sample_rate / 2.0 and 0.0 < end_hz < sample_rate / 2.0):
        raise ValueError("las frecuencias del barrido deben estar entre 0 y sample_rate / 2")
    resonance = min(max(_finite(resonance, "resonance"), 0.0), 1.0)
    order = max(1, int(order))
    start_at = min(max(_finite(start_at, "start_at"), 0.0), 1.0)
    end_at = min(max(_finite(end_at, "end_at"), start_at), 1.0)
    x = _stereo(audio)
    n = len(x)
    if n == 0:
        return x.copy()
    out = _stft_filter(x.astype(np.float64), _sweep_masks(kind, start_hz, end_hz, resonance, order, n, start_at, end_at),
                       sample_rate)
    return limit_peak(out) if resonance > 0.0 else out.astype(np.float32)


# ------------------------------------------------------------------ reverberación

def _impulse(decay_s: float, length_n: int, sample_rate: int, seed: int):
    """Respuesta de impulso sintética (length_n, 2): ruido distinto en cada canal (da anchura) con caída exponencial de 60 dB
    en `decay_s`, un pre-retardo de 20 ms en silencio, sin graves ni agudos fuertes, y energía 1 en cada canal."""
    np = _np()
    rng = np.random.default_rng(seed)
    pre = min(int(REVERB_PREDELAY_S * sample_rate), length_n)
    body = length_n - pre
    ir = np.zeros((length_n, 2), dtype=np.float64)
    if body <= 0:
        return ir
    t = np.arange(body, dtype=np.float64) / sample_rate
    noise = rng.standard_normal((body, 2)) * np.exp(-6.9078 * t / decay_s)[:, None]
    spec = np.fft.rfft(noise, axis=0)
    f = np.maximum(np.fft.rfftfreq(body, 1.0 / sample_rate), 1e-3)[:, None]
    lo = (f / REVERB_LOW_CUT_HZ) ** 2
    hi = (f / REVERB_HIGH_CUT_HZ) ** 2
    shaped = np.fft.irfft(spec * (lo / np.sqrt(1.0 + lo * lo)) / np.sqrt(1.0 + hi * hi), n=body, axis=0)
    shaped[:min(32, body)] *= np.linspace(0.0, 1.0, min(32, body))[:, None]      # sin escalón al empezar
    energy = np.sqrt(np.sum(shaped * shaped, axis=0))
    ir[pre:] = shaped / np.maximum(energy, 1e-12)
    return ir


def reverb_tail(audio, decay_s: float = 1.5, mix: float = 0.3, tail_s: float = None, sample_rate: int = SAMPLE_RATE,
                seed: int = 0):
    """Reverberación: salida = seca + mix * (audio convolucionado con una respuesta de impulso sintética), por FFT.

    La respuesta es ruido (distinto en cada canal, para que suene ancha) que cae 60 dB en `decay_s` segundos (0,1 a 10 s),
    con un pre-retardo de 20 ms y sin graves (por debajo de 150 Hz) ni agudos fuertes (por encima de 6 kHz); tiene energía 1,
    así que con un ruido a la entrada la reverberación suena más o menos igual de fuerte que el original. Con la misma
    `seed` sale siempre igual. tail_s None = decay_s (lo que tarda en apagarse). Devuelve float32 (n + cola, 2) con ganancia
    segura; los primeros 20 ms son la entrada sin tocar y los últimos 50 ms de la cola bajan a cero."""
    np = _np()
    _check_sr(sample_rate)
    decay_s = min(max(_finite(decay_s, "decay_s"), 0.1), 10.0)
    mix = min(max(_finite(mix, "mix"), 0.0), 1.0)
    if tail_s is None:
        tail_s = decay_s
    x = _stereo(audio)
    n = len(x)
    tail_n = max(0, int(round(min(max(0.0, _finite(tail_s, "tail_s")), MAX_TAIL_S) * sample_rate)))
    total = n + tail_n
    out = np.zeros((total, 2), dtype=np.float64)
    if total == 0:
        return out.astype(np.float32)
    out[:n] = x
    if n and mix > 0.0:
        ir = _impulse(decay_s, int(round((decay_s + REVERB_PREDELAY_S) * sample_rate)), sample_rate, seed)
        size = dj_dsp._fast_len(n + len(ir))
        wet = np.fft.irfft(np.fft.rfft(x.astype(np.float64), n=size, axis=0) * np.fft.rfft(ir, n=size, axis=0), n=size, axis=0)
        out += mix * wet[:total]
    if tail_n:
        _fade_out(out[n:], min(tail_n, int(TAIL_FADE_S * sample_rate)))
    return limit_peak(out)


# ------------------------------------------------------------------ subida (riser)

def riser(length_s: float, start_hz: float = 300.0, end_hz: float = 6000.0, level: float = 0.4, sample_rate: int = SAMPLE_RATE,
          seed: int = 0):
    """Subida de ruido para preparar una entrada: ruido (distinto en cada canal) filtrado con una campana de una octava cuyo
    centro sube de `start_hz` a `end_hz` en escala logarítmica, con un volumen que crece como el cuadrado del tiempo (empieza
    en silencio y llega a `level`, de 0 a 1, en el pico, cerca del final). Los últimos 5 ms bajan a cero (para que el corte al
    llegar al golpe no haga clic). Devuelve float32 (round(length_s * sample_rate), 2); vacío si length_s <= 0."""
    np = _np()
    _check_sr(sample_rate)
    start_hz, end_hz = _finite(start_hz, "start_hz"), _finite(end_hz, "end_hz")
    if not (0.0 < start_hz < sample_rate / 2.0 and 0.0 < end_hz < sample_rate / 2.0):
        raise ValueError("las frecuencias del riser deben estar entre 0 y sample_rate / 2")
    level = min(max(_finite(level, "level"), 0.0), 1.0)
    n = max(0, int(round(_finite(length_s, "length_s") * sample_rate)))
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32)
    noise = np.random.default_rng(seed).standard_normal((n, 2))
    y = _stft_filter(noise, _sweep_masks("bp", start_hz, end_hz, 0.0, 1, n, 0.0, 1.0), sample_rate)
    u = np.arange(n, dtype=np.float64) / n
    y *= (u * u)[:, None]
    _fade_out(y, int(dj_dsp.CUT_RAMP_S * sample_rate))
    peak = float(np.max(np.abs(y)))
    if peak > 0.0:
        y *= level / peak
    return y.astype(np.float32)


# ------------------------------------------------------------------ repetición (stutter)

def stutter(audio, bpm: float, division: int = 16, repeats: int = 4, sample_rate: int = SAMPLE_RATE):
    """Repetición rítmica («beat roll»): el trozo inicial de una figura (`division` 4 = un golpe, 8 = medio golpe, 16 = un
    cuarto de golpe, como las figuras musicales con el golpe en negra) se repite `repeats` veces seguidas y luego el audio
    sigue donde iría si no se hubiera repetido nada (como el modo «slip» de los platos: la canción no pierde su sitio).

    Cada unión lleva una rampa de bajada de 2 ms y una de subida de 2 ms (sin clic). La primera repetición empieza sin rampa
    (es la continuación de lo que sonaba). Devuelve float32 (n, 2), la misma longitud; las repeticiones que no caben se
    descartan. Con repeats <= 1 o un trozo de menos de 8 ms, devuelve una copia sin cambios."""
    np = _np()
    _check_sr(sample_rate)
    bpm = _finite(bpm, "bpm")
    if bpm <= 0 or not isinstance(division, (int, float)) or division <= 0:
        raise ValueError("bpm y division deben ser positivos")
    x = _stereo(audio)
    n = len(x)
    piece = int(round(60.0 / bpm * 4.0 / float(division) * sample_rate))
    ramp = int(round(STUTTER_RAMP_S * sample_rate))
    reps = min(int(repeats), n // piece) if piece > 0 else 0
    if reps <= 1 or piece < 4 * ramp:
        return x.copy()
    idx = np.arange(n)
    idx[:reps * piece] %= piece
    out = x[idx].astype(np.float64)
    gain = np.ones(n, dtype=np.float64)
    bounds = np.arange(1, reps + 1) * piece                 # cada vuelta al principio del trozo, y la vuelta a la canción
    down = bounds[:, None] - ramp + np.arange(ramp)[None, :]
    gain[down.ravel()] *= np.tile(dj_dsp._ramp(ramp, down=True), len(bounds))
    up_idx = bounds[:, None] + np.arange(ramp)[None, :]
    keep = up_idx < n
    gain[up_idx[keep]] *= np.tile(dj_dsp._ramp(ramp, down=False), len(bounds))[keep.ravel()]
    return (out * gain[:, None]).astype(np.float32)


# ------------------------------------------------------------------ efectos avanzados DJ

def tempo_delay(audio, bpm: float, beats: float = 0.75, feedback: float = 0.5, mix: float = 0.5,
                ping_pong: bool = True, ducking: float = 0.0, tail_s: float = None,
                sample_rate: int = SAMPLE_RATE):
    """Tempo Delay rítmico estéreo sincronizado a compás (1/2, 3/4, 1T).

    Parámetros:
      bpm: tempo en pulsos por minuto (debe ser positivo).
      beats: figura rítmica (0.5 = 1/2 compás, 0.75 = 3/4 con puntillo, 1.0 = 1 pulso).
      feedback: realimentación de 0 a 0.95.
      mix: balance efecto de 0 a 1.
      ping_pong: si True, los ecos rebotan alternando entre el canal izquierdo y derecho.
      ducking: atenuación de 0 a 1 de las repeticiones mientras la señal seca tiene volumen alto,
               haciendo que los ecos florezcan en los huecos y pausas sin saturar la mezcla.
      tail_s: segundos de cola tras el final (None = automático hasta -60 dB)."""
    np = _np()
    _check_sr(sample_rate)
    bpm = _finite(bpm, "bpm")
    beats = _finite(beats, "beats")
    if bpm <= 0 or beats <= 0:
        raise ValueError("bpm y beats deben ser positivos")
    feedback = min(max(_finite(feedback, "feedback"), 0.0), MAX_FEEDBACK)
    mix = min(max(_finite(mix, "mix"), 0.0), 1.0)
    ducking = min(max(_finite(ducking, "ducking"), 0.0), 1.0)

    delay_s = beats * 60.0 / bpm
    if tail_s is None:
        tail_s = echo_tail_s(delay_s, feedback)
    tail_s = min(max(0.0, _finite(tail_s, "tail_s")), MAX_TAIL_S)

    x = _stereo(audio)
    n = len(x)
    tail_n = max(0, int(round(tail_s * sample_rate)))
    total = n + tail_n
    out = np.zeros((total, 2), dtype=np.float64)
    if total == 0:
        return out.astype(np.float32)
    out[:n] = x

    if n and mix > 0.0:
        d = max(1, int(round(delay_s * sample_rate)))
        ch = 2
        m = -(-total // d)
        xb = np.zeros((m * d, ch), dtype=np.float64)
        have = min(n, m * d)
        xb[:have] = x[:have]
        xb = xb.reshape(m, d, ch)
        y = np.zeros_like(xb)
        last_in = min(m - 1, -(-n // d))

        if not ping_pong:
            for k in range(1, last_in + 1):
                y[k] = xb[k - 1] + feedback * y[k - 1]
            if last_in + 1 < m:
                powers = feedback ** np.arange(1, m - last_in, dtype=np.float64)
                y[last_in + 1:] = y[last_in][None] * powers[:, None, None]
        else:
            # Ping-Pong: rebote alterno entre canales I y D
            for k in range(1, m):
                in_k = xb[k - 1] if k - 1 <= last_in else np.zeros((d, 2), dtype=np.float64)
                if k == 1:
                    # Inyección inicial estéreo hacia canal izquierdo
                    in_mono = 0.5 * (in_k[:, 0] + in_k[:, 1])
                    y[1, :, 0] = in_mono
                    y[1, :, 1] = 0.0
                else:
                    y[k, :, 0] = in_k[:, 0] + feedback * y[k - 1, :, 1]
                    y[k, :, 1] = in_k[:, 1] + feedback * y[k - 1, :, 0]

        wet = y.reshape(m * d, ch)[:total]

        # Ducking envolvente
        if ducking > 0.0 and n > 0:
            amp = np.max(np.abs(x), axis=1)
            win = max(1, min(int(0.05 * sample_rate), n))
            smoothed = np.convolve(amp, np.ones(win, dtype=np.float64) / win, mode="same")
            peak_lvl = float(np.percentile(smoothed, 90)) if len(smoothed) else 1.0
            norm_env = np.clip(smoothed / max(peak_lvl, 1e-4), 0.0, 1.0)
            duck_mult = np.ones(total, dtype=np.float64)
            duck_mult[:n] = 1.0 - (ducking * norm_env)
            wet = wet * duck_mult[:, None]

        out += mix * wet

    if tail_n:
        _fade_out(out[n:], min(tail_n, int(TAIL_FADE_S * sample_rate)))
    return limit_peak(out)


def dub_tape_echo(audio, bpm: float = None, delay_s: float = None, beats: float = 0.75,
                  feedback: float = 0.55, mix: float = 0.5, low_cut_hz: float = 250.0,
                  high_cut_hz: float = 5000.0, saturation: float = 0.3, freeze: bool = False,
                  freeze_at_s: float = None, tail_s: float = None,
                  sample_rate: int = SAMPLE_RATE):
    """Dub / Tape Echo profesional con corte de graves/agudos, saturación tipo cinta (tanh)
    y soporte para Echo Freeze (congelación infinita).

    freeze: si es True, bloquea el bucle de realimentación en 0.995 y corta la entrada para crear
            una cama ambiental sostenida.
    freeze_at_s: instante en segundos a partir del cual se congela la señal."""
    np = _np()
    _check_sr(sample_rate)
    if delay_s is None:
        bpm = _finite(bpm if bpm and bpm > 0 else 120.0, "bpm")
        beats = _finite(beats, "beats")
        delay_s = beats * 60.0 / bpm
    else:
        delay_s = _finite(delay_s, "delay_s")
    delay_s = min(max(delay_s, MIN_DELAY_S), MAX_DELAY_S)

    if freeze:
        feedback = 0.99
        if tail_s is None:
            tail_s = 6.0
    else:
        feedback = min(max(_finite(feedback, "feedback"), 0.0), MAX_FEEDBACK)

    mix = min(max(_finite(mix, "mix"), 0.0), 1.0)
    saturation = min(max(_finite(saturation, "saturation"), 0.0), 2.0)
    x = _stereo(audio).copy()
    n = len(x)

    if freeze_at_s is not None and 0.0 <= freeze_at_s < n / sample_rate:
        freeze_idx = int(round(freeze_at_s * sample_rate))
        x[freeze_idx:] = 0.0

    if tail_s is None:
        tail_s = echo_tail_s(delay_s, feedback)
    tail_s = min(max(0.0, _finite(tail_s, "tail_s")), MAX_TAIL_S)

    tail_n = max(0, int(round(tail_s * sample_rate)))
    total = n + tail_n
    out = np.zeros((total, 2), dtype=np.float64)
    if total == 0:
        return out.astype(np.float32)
    out[:n] = x

    if n and mix > 0.0:
        d = max(1, int(round(delay_s * sample_rate)))
        ch = 2
        m = -(-total // d)
        xb = np.zeros((m * d, ch), dtype=np.float64)
        have = min(n, m * d)
        xb[:have] = x[:have]
        xb = xb.reshape(m, d, ch)
        y = np.zeros_like(xb)
        last_in = min(m - 1, -(-n // d))

        for k in range(1, m):
            in_tap = xb[k - 1] if k - 1 <= last_in else np.zeros((d, ch), dtype=np.float64)
            prev = y[k - 1]
            # Saturación analógica de cinta
            if saturation > 0.0:
                prev = np.tanh(prev * (1.0 + saturation)) / (1.0 + saturation)
            y[k] = in_tap + feedback * prev

        wet = y.reshape(m * d, ch)[:total]
        # Corte de graves en la cola
        if low_cut_hz > 20.0 and len(wet) > 0:
            wet = dj_dsp.kill_low(wet, sample_rate=sample_rate).astype(np.float64)

        out += mix * wet

    if tail_n:
        _fade_out(out[n:], min(tail_n, int(TAIL_FADE_S * sample_rate)))
    return limit_peak(out)


def washout_reverb(audio, decay_s: float = 3.5, mix_start: float = 0.0, mix_end: float = 0.85,
                   hpf_start_hz: float = 20.0, hpf_end_hz: float = 1800.0, tail_s: float = None,
                   sample_rate: int = SAMPLE_RATE, seed: int = 42):
    """Space / Washout Reverb con cola envolvente:
    Aplica barrido ascendente de filtro paso alto (HPF) y rampa creciente de reverberación
    para crear salidas etéreas sin colisión ni cortes secos.

    mix_start: nivel inicial de reverb (por defecto 0.0).
    mix_end: nivel de reverb al final del audio seco (por defecto 0.85).
    hpf_start_hz a hpf_end_hz: rango de frecuencia del barrido de paso alto."""
    np = _np()
    _check_sr(sample_rate)
    decay_s = min(max(_finite(decay_s, "decay_s"), 0.1), 10.0)
    mix_start = min(max(_finite(mix_start, "mix_start"), 0.0), 1.0)
    mix_end = min(max(_finite(mix_end, "mix_end"), 0.0), 1.0)
    if tail_s is None:
        tail_s = decay_s
    tail_s = min(max(0.0, _finite(tail_s, "tail_s")), MAX_TAIL_S)

    x = _stereo(audio)
    n = len(x)
    tail_n = max(0, int(round(tail_s * sample_rate)))
    total = n + tail_n
    if total == 0:
        return np.zeros((0, 2), dtype=np.float32)

    # Filtrado paso alto progresivo
    if n > 0 and hpf_end_hz > hpf_start_hz:
        x_filtered = filter_sweep(x, "hp", hpf_start_hz, min(hpf_end_hz, sample_rate / 2.0 * 0.95),
                                  sample_rate=sample_rate)
    else:
        x_filtered = x

    ir_len = max(int(round((decay_s + REVERB_PREDELAY_S) * sample_rate)), tail_n)
    ir = _impulse(decay_s, ir_len, sample_rate, seed)
    size = dj_dsp._fast_len(n + ir_len)
    raw_wet = np.fft.irfft(np.fft.rfft(x_filtered.astype(np.float64), n=size, axis=0)
                           * np.fft.rfft(ir, n=size, axis=0), n=size, axis=0)
    wet = np.zeros((total, 2), dtype=np.float64)
    take = min(total, len(raw_wet))
    wet[:take] = raw_wet[:take]

    # Envolvente de mezcla: de mix_start a mix_end durante n, y mix_end durante la cola
    mix_env = np.ones(total, dtype=np.float64) * mix_end
    if n > 0:
        mix_env[:n] = np.linspace(mix_start, mix_end, n)

    out = np.zeros((total, 2), dtype=np.float64)
    out[:n] = x
    out += wet * mix_env[:, None]

    if tail_n:
        _fade_out(out[n:], min(tail_n, int(TAIL_FADE_S * sample_rate)))
    return limit_peak(out)


def space_reverb(audio, decay_s: float = 2.5, mix: float = 0.4, tail_s: float = None,
                 sample_rate: int = SAMPLE_RATE, seed: int = 42):
    """Reverberación espacial de sala amplia para uso interactivo en el rack de efectos."""
    return reverb_tail(audio, decay_s=decay_s, mix=mix, tail_s=tail_s, sample_rate=sample_rate, seed=seed)



def vinyl_brake(audio, duration_s: float = 1.0, curve: float = 2.0, sample_rate: int = SAMPLE_RATE):
    """Efecto de parada de motor de vinilo (turntable vinyl brake).

    Desacelera la reproducción desde velocidad 1.0 a 0.0 a lo largo de duration_s,
    con caída de pitch y tiempo realista, simulando la inercia del plato giratorio al apagarse.
    Técnica clásica de DJ para transiciones en Hip-Hop, Trap y Boom Bap.

    audio: entrada (n, 2) o compatible.
    duration_s: duración del frenado en segundos (0.2 a 4.0 s).
    curve: exponente de la curva de frenado (2.0 = inercia cuadrática analógica clásica).
    sample_rate: frecuencia de muestreo.
    Devuelve (n, 2) float32 estéreo con el frenado en el tramo final o en todo el audio.
    """
    np = _np()
    x = _stereo(audio)
    n = len(x)
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32)

    dur = max(0.1, float(duration_s))
    brake_len = min(n, max(1, int(round(dur * sample_rate))))
    pre_len = n - brake_len

    out = np.zeros((n, 2), dtype=np.float32)
    if pre_len > 0:
        out[:pre_len] = x[:pre_len]

    u = np.arange(brake_len, dtype=np.float64)
    v = np.maximum(0.0, 1.0 - (u / float(brake_len))) ** max(0.5, float(curve))
    src_pos = pre_len + np.cumsum(v)
    src_pos = np.clip(src_pos, 0, n - 1)

    idx = src_pos.astype(np.int64)
    idx = np.clip(idx, 0, max(0, n - 2))
    frac = (src_pos - idx)[:, None]

    if n >= 2:
        brake_audio = (1.0 - frac) * x[idx] + frac * x[np.minimum(idx + 1, n - 1)]
    else:
        brake_audio = x[idx]

    fade_len = min(brake_len, max(1, int(0.02 * sample_rate)))
    brake_audio[-fade_len:] *= np.linspace(1.0, 0.0, fade_len)[:, None]

    out[pre_len:] = brake_audio.astype(np.float32)
    return limit_peak(out)

