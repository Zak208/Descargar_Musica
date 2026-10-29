"""Ecualizador de 3 bandas y cambio de graves (bass swap) del modo DJ (fase 14), como funciones puras sobre arrays de audio.

Formato: arrays de numpy de forma (n, 2) (estéreo), float32, a 44.100 Hz (`mix_types.SAMPLE_RATE`). Una entrada de una sola
dimensión (n,) también vale en `split_bands` y `eq_apply` (devuelven lo mismo, de una dimensión); `render_transition` la
duplica en estéreo. numpy se carga solo cuando hace falta (`key_detect._numpy()`); sin él, las funciones lanzan RuntimeError.

Cómo se separan las bandas (`split_bands`) y por qué:
  Se usa un filtro de fase cero en el dominio de la frecuencia: se hace la FFT de todo el trozo, se multiplica por máscaras
  suaves y se vuelve atrás. Las máscaras son las respuestas en magnitud de un cruce Linkwitz-Riley de 8.º orden (48 dB por
  octava): graves = 1 / (1 + (f / f1)^8), agudos = (f / f2)^8 / (1 + (f / f2)^8), y los medios son todo lo que queda
  (1 menos graves menos agudos). Se eligió el 8.º y no el 4.º porque con 24 dB por octava el kill de graves dejaba pasar
  un bombo de 90 Hz a -36 dB (inaudible casi siempre, pero el objetivo es que no suenen dos bombos); con 48 dB baja a -70 dB
  y los medios quedan planos (±0,01 dB a 1 kHz), a cambio de una respuesta del filtro algo más larga (unos 2 ms, nada).
  Ventajas frente a las alternativas:
    * Reconstrucción perfecta por construcción: graves + medios + agudos = señal, salvo el redondeo de float32 (~1e-7). Con
      filtros en cascada (IIR) la suma solo es plana en magnitud y desfasada; aquí no hay desfase alguno.
    * Fase cero: ninguna banda se retrasa respecto a las otras ni a la señal original, de modo que el bombo (graves) y
      el resto de la mezcla siguen alineados al milisegundo cuando se cambian las ganancias por separado.
    * Cruces suaves: cada banda está a -6 dB en su frecuencia de cruce y las dos suman 0 dB.
    * Sin dependencias (scipy no está en la aplicación) y rápido: 60 s de estéreo se separan en menos de un segundo.
  El filtro no es causal (usa el futuro de la señal), y no importa: aquí se trabaja con trozos ya cargados en memoria, no en
  directo. Para que la FFT circular no meta el final en el principio, el trozo se rellena con silencio por el final antes de
  transformar y se recorta después (el relleno no afecta a la reconstrucción: la suma de las máscaras es 1 en todo el espectro)."""
import math

from services import key_detect
from services.mix_types import KIND_CUT, SAMPLE_RATE

LOW_HZ = 250.0                  # frecuencia de cruce entre graves y medios
HIGH_HZ = 2500.0                # frecuencia de cruce entre medios y agudos
SWAP_STEP_S = 0.04              # lo que dura el paso corto del cambio de graves (40 ms: sin clic y casi sin solapamiento)
CUT_RAMP_S = 0.005              # microrrampa del corte limpio y del final de un trozo que se queda corto
ORDER = 8                       # exponente de las máscaras (Linkwitz-Riley de 8.º orden: 48 dB por octava)
MIN_RAMP_S = 0.002              # un tramo de curva de ganancia no puede ser más corto que esto (si no, haría clic)


def _np():
    np = key_detect._numpy()
    if np is None:
        raise RuntimeError("dj_dsp necesita numpy")
    return np


def _fast_len(n: int) -> int:
    """Menor tamaño >= n cuyos únicos factores primos son 2, 3 y 5 (la FFT de numpy va rápida con ellos)."""
    best = 1 << max(0, (n - 1).bit_length())              # la potencia de dos siguiente siempre vale
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            m = p35
            while m < n:
                m *= 2
            best = min(best, m)
            p35 *= 3
        p5 *= 5
    return best


def _as_2d(x):
    """(array float32 de (n, canales), era_unidimensional). Acepta (n,) y (n, canales)."""
    np = _np()
    arr = np.asarray(x)
    if arr.ndim == 1:
        return arr.astype(np.float32, copy=False).reshape(-1, 1), True
    if arr.ndim != 2:
        raise ValueError("el audio debe ser un array (n,) o (n, canales)")
    return arr.astype(np.float32, copy=False), False


def _to_stereo(x):
    """El audio como float32 de forma (n, 2) (un array de una dimensión o de un canal se duplica en los dos)."""
    np = _np()
    arr, _ = _as_2d(x)
    if arr.shape[1] == 1:
        arr = np.repeat(arr, 2, axis=1)
    elif arr.shape[1] != 2:
        raise ValueError("el audio debe ser mono o estéreo")
    return arr


def _check_cutoffs(low_hz: float, high_hz: float, sample_rate: int):
    if not 0.0 < low_hz < high_hz < sample_rate / 2.0:
        raise ValueError("hace falta 0 < low_hz < high_hz < sample_rate / 2")


def _spectrum(arr, low_hz: float, sample_rate: int):
    """(FFT de arr (n, canales) rellenado con silencio por el final, tamaño de la FFT, frecuencias de cada punto)."""
    np = _np()
    n = len(arr)
    pad = int(sample_rate * max(0.1, 20.0 / low_hz))      # de sobra para que la respuesta del filtro se apague
    size = _fast_len(n + pad)
    spec = np.fft.rfft(arr.T.astype(np.float64), n=size, axis=1)
    return spec, size, np.fft.rfftfreq(size, 1.0 / sample_rate)


def _low_mask(freqs, low_hz: float):
    return 1.0 / (1.0 + (freqs / low_hz) ** ORDER)


def _high_mask(freqs, high_hz: float):
    r8 = (freqs / high_hz) ** ORDER
    return r8 / (1.0 + r8)


def _lowpass(arr, low_hz: float, sample_rate: int):
    """Solo la banda grave, en float64 y forma (n, canales) (más barata que `split_bands` entera: una FFT y una inversa)."""
    np = _np()
    spec, size, freqs = _spectrum(arr, low_hz, sample_rate)
    low = np.fft.irfft(spec * _low_mask(freqs, low_hz), n=size, axis=1)[:, :len(arr)]
    return low.T


def split_bands(x, low_hz: float = LOW_HZ, high_hz: float = HIGH_HZ, sample_rate: int = SAMPLE_RATE):
    """Separa el audio en tres bandas: graves (hasta `low_hz`), medios y agudos (desde `high_hz`). Devuelve (low, mid, high),
    float32 y de la misma forma que `x`, con low + mid + high == x (error de redondeo de float32, del orden de 1e-7).
    Cada banda está a -6 dB en su cruce, con pendiente de 48 dB por octava; sin retraso entre bandas (fase cero)."""
    np = _np()
    _check_cutoffs(low_hz, high_hz, sample_rate)
    arr, was_1d = _as_2d(x)
    n = len(arr)
    if n == 0:
        empty = arr.copy()
        return empty, arr.copy(), arr.copy()
    spec, size, freqs = _spectrum(arr, low_hz, sample_rate)
    low = np.fft.irfft(spec * _low_mask(freqs, low_hz), n=size, axis=1)[:, :n].T
    high = np.fft.irfft(spec * _high_mask(freqs, high_hz), n=size, axis=1)[:, :n].T
    mid = arr.astype(np.float64) - low - high              # lo que queda: así la suma es exacta
    bands = tuple(b.astype(np.float32) for b in (low, mid, high))
    if was_1d:
        bands = tuple(b[:, 0] for b in bands)
    return bands


def band_gains(n: int, points, sample_rate: int = SAMPLE_RATE):
    """Curva de ganancia de `n` muestras a partir de puntos (tiempo_s, ganancia), para automatizar una banda en el tiempo.
    Entre dos puntos la curva es un paso suave (3t² - 2t³: sin escalón y sin pico de pendiente al empezar ni al acabar);
    antes del primero vale lo del primero y después del último, lo del último. Los puntos se ordenan por tiempo, y dos
    puntos casi juntos se separan al menos 2 ms (un salto instantáneo haría clic). Devuelve float32 de forma (n,).
    Ejemplo: band_gains(n, [(0, 1.0), (7.98, 1.0), (8.02, 0.0)]) mantiene la ganancia en 1 y la baja a 0 en 40 ms."""
    np = _np()
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    pts = sorted((float(t), float(g)) for t, g in points)
    if not pts:
        return np.ones(n, dtype=np.float32)
    times, gains = [pts[0][0]], [pts[0][1]]
    for t, g in pts[1:]:
        times.append(max(t, times[-1] + MIN_RAMP_S))
        gains.append(g)
    times = np.asarray(times)
    gains = np.asarray(gains)
    t = np.arange(n, dtype=np.float64) / sample_rate
    if len(times) == 1:
        return np.full(n, gains[0], dtype=np.float32)
    seg = np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 2)
    u = np.clip((t - times[seg]) / (times[seg + 1] - times[seg]), 0.0, 1.0)
    s = u * u * (3.0 - 2.0 * u)
    return (gains[seg] + (gains[seg + 1] - gains[seg]) * s).astype(np.float32)


def eq_apply(x, low_gain=1.0, mid_gain=1.0, high_gain=1.0, low_hz: float = LOW_HZ, high_hz: float = HIGH_HZ,
             sample_rate: int = SAMPLE_RATE):
    """Ecualizador de 3 bandas: cada banda se multiplica por su ganancia (1.0 = igual, 0.0 = silenciada). Las ganancias
    pueden ser números (ecualizador estático) o arrays de una dimensión de n muestras (como los de `band_gains`).
    Con las tres a 1.0 devuelve la señal sin cambios. Devuelve float32 de la misma forma que `x`."""
    np = _np()
    arr, was_1d = _as_2d(x)
    if all(np.all(np.asarray(g) == 1.0) for g in (low_gain, mid_gain, high_gain)):
        return arr[:, 0].copy() if was_1d else arr.copy()
    low, mid, high = split_bands(arr, low_hz, high_hz, sample_rate)
    out = np.zeros(arr.shape, dtype=np.float64)
    for band, gain in ((low, low_gain), (mid, mid_gain), (high, high_gain)):
        g = np.asarray(gain, dtype=np.float64)
        out += band * (g.reshape(-1, 1) if g.ndim == 1 else g)
    out = out.astype(np.float32)
    return out[:, 0] if was_1d else out


def kill_low(x, low_hz: float = LOW_HZ, sample_rate: int = SAMPLE_RATE):
    """El audio sin los graves (el clásico «kill» del ecualizador de un DJ): medios y agudos intactos."""
    return eq_apply(x, low_gain=0.0, low_hz=low_hz, sample_rate=sample_rate)


def _fit(x, n: int):
    """Los primeros `n` fotogramas de x (n, 2). Si x es más corto, se rellena con silencio y los últimos 5 ms de lo que había
    se bajan a cero con una rampa (para no hacer clic). Devuelve float32 de forma (n, 2); copia, nunca la misma memoria."""
    np = _np()
    out = np.zeros((n, 2), dtype=np.float32)
    have = min(len(x), n)
    out[:have] = x[:have]
    if have < n and have > 0:
        r = min(int(CUT_RAMP_S * SAMPLE_RATE), have)
        out[have - r:have] *= _ramp(r, down=True)[:, None]
    return out


def _ramp(r: int, down: bool):
    """Rampa de coseno elevado de r muestras: de 1 a 0 (o de 0 a 1); acaba exactamente en 0 (o empieza en 0)."""
    np = _np()
    if r <= 0:
        return np.zeros(0, dtype=np.float32)
    if r == 1:
        return np.zeros(1, dtype=np.float32) if down else np.ones(1, dtype=np.float32)
    up = 0.5 - 0.5 * np.cos(np.linspace(0.0, math.pi, r))
    return (1.0 - up if down else up).astype(np.float32)


def _clean_cut(a, b):
    """Corte limpio: A entera con sus últimos 5 ms bajando a cero y B entera con sus primeros 5 ms subiendo desde cero."""
    np = _np()
    a = a.copy()
    b = b.copy()
    ra = min(int(CUT_RAMP_S * SAMPLE_RATE), len(a))
    rb = min(int(CUT_RAMP_S * SAMPLE_RATE), len(b))
    if ra:
        a[len(a) - ra:] *= _ramp(ra, down=True)[:, None]
    if rb:
        b[:rb] *= _ramp(rb, down=False)[:, None]
    return np.concatenate([a, b], axis=0)


def render_transition(a, b, plan, sample_rate: int = SAMPLE_RATE):
    """Mezcla el trozo de A con el de B durante `plan.length_s` con cambio de graves. Devuelve float32 de forma (n, 2).

    Qué se espera de las entradas:
      a  audio de A desde `plan.a_start_s` (el primer fotograma de `a` es ese instante); puede ser más largo que la mezcla
         (solo se usa lo que cabe) o más corto.
      b  audio de B ya estirado de tempo y empezando justo donde entra (su primer fotograma es el primero de la mezcla).
      Mono (n,) o de un canal se duplica en estéreo. El audio no se recorta ni se normaliza: la suma puede pasar de 1.0
      (que lo controle quien reproduzca o grabe).

    Qué devuelve:
      Mezcla (kind distinto de "cut" y length_s > 0): exactamente round(length_s * sample_rate) fotogramas. Si `a` o `b` tienen
      menos fotogramas que eso, se rellenan con silencio al final, con los últimos 5 ms de lo que había bajando a cero
      (nunca falla ni hace clic); si son más largos, lo que sobra se ignora. Un trozo vacío cuenta como silencio.
      Corte (kind == "cut" o length_s <= 0): len(a) + len(b) fotogramas, es decir, A entera (su trozo termina donde se
      corta) y B entera, una detrás de otra, con los últimos 5 ms de A y los primeros 5 ms de B en rampa para evitar clics.

    Cómo se mezcla:
      * Medios y agudos: fundido de potencia constante en toda la mezcla (A con cos, B con sen, de 0 a 90 grados).
        Con dos señales sin relación entre sí la potencia total se mantiene; si las dos fueran idénticas subiría 3 dB
        (es inevitable con cualquier fundido de potencia constante).
      * Graves (por debajo de 250 Hz): A los lleva entera hasta `plan.bass_swap_at` y B no los lleva hasta entonces; en ese
        instante los graves se pasan de una a otra con un paso corto y suave de 40 ms centrado en él (de A a B, con
        ganancias complementarias que suman 1). Como es una mezcla lineal de las dos, la amplitud de los graves nunca
        supera la mayor de las dos, y solo hay graves de las dos canciones a la vez durante ese paso. El momento del cambio
        se limita para que el paso quepa entero dentro de la mezcla.
    Como cada banda se mueve por separado y la separación es de fase cero y con reconstrucción perfecta, en el primer
    fotograma la salida es `a` y en el último, `b` (hasta ~1e-6, el fundido empieza y acaba en 0 y 1), sin saltos con lo que va
    antes ni después."""
    np = _np()
    a = _to_stereo(a)
    b = _to_stereo(b)
    length = int(round(float(plan.length_s) * sample_rate))
    if plan.kind == KIND_CUT or length <= 0:
        return _clean_cut(a, b)

    a = _fit(a, length)
    b = _fit(b, length)
    # Fundido de potencia constante (para medios y agudos), de 0 a 90 grados a lo largo de toda la mezcla
    angle = (np.arange(length, dtype=np.float64) + 0.5) / length * (math.pi / 2.0)
    fade_a, fade_b = np.cos(angle), np.sin(angle)
    # Cambio de graves: A baja de 1 a 0 y B sube de 0 a 1 en un paso suave centrado en el instante del cambio
    step = min(SWAP_STEP_S, length / sample_rate)
    swap = min(max(float(plan.bass_swap_at), step / 2.0), length / sample_rate - step / 2.0)
    bass_b = band_gains(length, [(swap - step / 2.0, 0.0), (swap + step / 2.0, 1.0)], sample_rate).astype(np.float64)
    bass_a = 1.0 - bass_b
    # salida = fade * (A completa) + (ganancia de graves - fade) * (graves de A), y lo mismo con B; equivale a ponerle a cada
    # banda su ganancia (graves con la suya y medios y agudos con el fundido), pero con una sola banda que separar
    out = (fade_a[:, None] * a + fade_b[:, None] * b
           + (bass_a - fade_a)[:, None] * _lowpass(a, LOW_HZ, sample_rate)
           + (bass_b - fade_b)[:, None] * _lowpass(b, LOW_HZ, sample_rate))
    return out.astype(np.float32)
