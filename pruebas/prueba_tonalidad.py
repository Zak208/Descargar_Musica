"""Tono de las canciones (rueda Camelot): la rueda y la compatibilidad, la detección con audio sintético en los 24 tonos
(también desafinado y con ruido), las etiquetas de los archivos, el guardado en el índice y la actualización de una base
de datos de la versión anterior. Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_tonalidad.py"""
import os
import sqlite3
import sys
import tempfile
import time
import wave

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import numpy as np
from PySide6.QtWidgets import QApplication

app = QApplication([])


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


from services import camelot, key_detect, library_db, track_analysis
from services.ffmpeg_service import FFmpegService

# ------------------------------------------------------------------ la rueda
check("do mayor es 8B y la menor es 8A", camelot.camelot(0, False) == "8B" and camelot.camelot(9, True) == "8A")
check("sol mayor 9B, mi menor 9A, si bemol mayor 6B", camelot.camelot(7, False) == "9B" and camelot.camelot(4, True) == "9A"
      and camelot.camelot(10, False) == "6B")
check("fa sostenido menor 11A, la bemol menor 1A, si mayor 1B", camelot.camelot(6, True) == "11A" and camelot.camelot(8, True) == "1A"
      and camelot.camelot(11, False) == "1B")
check("los 24 códigos son distintos", len({camelot.camelot(t, m) for t in range(12) for m in (False, True)}) == 24)
check("un menor y su relativo mayor comparten número", all(
    camelot.camelot(t, True)[:-1] == camelot.camelot((t + 3) % 12, False)[:-1] for t in range(12)))
for text, code in (("Am", "8A"), ("F#m", "11A"), ("Bb", "6B"), ("C major", "8B"), ("A minor", "8A"), ("8a", "8A"), ("08B", "8B"),
                   ("Dbm", "12A"), ("Ebm", "2A"), ("Gm", "6A"), ("Fmaj", "7B"), ("C♯m", "12A"), ("B", "1B"), ("E♭", "5B")):
    check(f"se entiende «{text}» como {code}", camelot.from_text(text) == code)
check("lo que no es un tono no se entiende («o», vacío, None, 13A, H, Cdim)", all(
    camelot.from_text(t) is None for t in ("o", "", None, "13A", "H", "Cdim", "xyz")))
check("un modo que no es mayor ni menor no se interpreta mal («D dorian», «D mixolydian», «Cm.»)", all(
    camelot.from_text(t) is None for t in ("D dorian", "D mixolydian", "Cm.", "Cmaj7x")))
for text, code in (("1d", "8B"), ("1m", "8A"), ("6m", "1A"), ("12d", "7B"), ("10m", "5A"), ("04D", "11B")):
    check(f"Open Key de Traktor: «{text}» es {code}", camelot.from_text(text) == code)
check("Open Key fuera de rango no se entiende", camelot.from_text("13d") is None and camelot.from_text("0m") is None)
check("Open Key y Camelot dan la vuelta a los 24 tonos", all(
    camelot.from_text(f"{(int(c[:-1]) + 4) % 12 + 1}{'m' if c[-1] == 'A' else 'd'}") == c
    for c in (f"{n}{l}" for n in range(1, 13) for l in "AB")))
check("nombre musical de un código", camelot.musical_name("8A") == "Am" and camelot.musical_name("8B") == "C"
      and camelot.musical_name("1A") == "A♭m" and camelot.musical_name("11A") == "F♯m" and camelot.musical_name("x") == "")
check("compatibilidad: iguales 1,0", camelot.score("8A", "8A") == 1.0)
check("compatibilidad: relativo y un paso por la rueda, 0,8 (también dando la vuelta de 12 a 1)", all(
    camelot.score(a, b) == 0.8 for a, b in (("8A", "8B"), ("8A", "9A"), ("8A", "7A"), ("12A", "1A"), ("1B", "12B"))))
check("compatibilidad: diagonal y dos pasos, 0,5", camelot.score("8A", "9B") == 0.5 and camelot.score("8A", "10A") == 0.5)
check("compatibilidad: lejos, 0,0", camelot.score("8A", "2A") == 0.0 and camelot.score("8A", "3B") == 0.0)
check("sin tono conocido no se castiga: 0,5", camelot.score("8A", None) == 0.5 and camelot.score("", "8A") == 0.5)
check("compatible() solo con 0,8 o más", camelot.compatible("8A", "9A") and not camelot.compatible("8A", "10A"))

# ------------------------------------------------------------------ audio sintético en los 24 tonos
SR = key_detect.SAMPLE_RATE


def hz(midi):
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def chord(root_midi, minor, seconds, detune_cents=0.0):
    """Un acorde con 5 armónicos por nota y un bajo con la tónica."""
    t = np.arange(int(seconds * SR)) / SR
    sig = np.zeros_like(t)
    for interval in (0, 3 if minor else 4, 7):
        f0 = hz(root_midi + interval + detune_cents / 100.0)
        for k in range(1, 6):
            if f0 * k < 2000:
                sig += np.sin(2 * np.pi * f0 * k * t) / k
    bass = hz(root_midi - 12 + detune_cents / 100.0)
    sig += np.sin(2 * np.pi * bass * t) + 0.5 * np.sin(2 * np.pi * 2 * bass * t)
    return sig * np.minimum(1.0, np.minimum(t, seconds - t) * 20)


def song(tonic, minor, detune_cents=0.0, noise=0.0, seconds_per_chord=8.0, seed=1):
    """I-IV-V-I (mayor) o i-iv-V-i (menor) en el tono pedido."""
    base = 48 + tonic
    steps = ((0, minor), (5, minor), (7, False), (0, minor))
    audio = np.concatenate([chord(base + root, is_minor, seconds_per_chord, detune_cents) for root, is_minor in steps])
    audio = audio / np.max(np.abs(audio)) * 0.5
    if noise:
        audio = audio + np.random.default_rng(seed).normal(0.0, noise, len(audio))
    return audio.astype(np.float32)


exact = within = 0
failures = []
for tonic in range(12):
    for minor in (False, True):
        found = key_detect.detect_from_samples(song(tonic, minor))["tone"]
        want = camelot.camelot(tonic, minor)
        exact += found == want
        within += bool(found) and camelot.compatible(found, want)
        if found != want:
            failures.append(f"{want}→{found or '-'}")
check(f"los 24 tonos sintéticos: {exact} de 24 exactos ({', '.join(failures) or 'sin fallos'})", exact >= 23)
check("y los 24 al menos compatibles con el verdadero", within == 24)

desafinado = [(t, m) for t in (0, 3, 6, 9) for m in (False, True)]
good = sum(key_detect.detect_from_samples(song(t, m, detune_cents=c))["tone"] == camelot.camelot(t, m)
           for t, m in desafinado for c in (-35.0, 30.0))
check(f"desafinados 35 centésimas abajo y 30 arriba: {good} de {2 * len(desafinado)}", good >= 2 * len(desafinado) - 1)
midi_, peso_ = key_detect._peaks(song(0, False, detune_cents=30.0))
check("la afinación estimada es la verdadera (+0,30 semitonos)", abs(key_detect.pitch_class_profile(midi_, peso_)[1] - 0.30) < 0.08)
midi_, peso_ = key_detect._peaks(song(0, False))
check("y en una canción afinada sale cero", abs(key_detect.pitch_class_profile(midi_, peso_)[1]) < 0.05)
noisy = sum(key_detect.detect_from_samples(song(t, m, noise=0.08))["tone"] == camelot.camelot(t, m) for t, m in desafinado)
check(f"con ruido blanco fuerte: {noisy} de {len(desafinado)}", noisy >= len(desafinado) - 1)

check("silencio: sin tono", key_detect.detect_from_samples(np.zeros(SR * 40, dtype=np.float32))["tone"] == "")
check("menos de 20 s: sin tono", key_detect.detect_from_samples(song(0, False, seconds_per_chord=3.0))["tone"] == "")
check("sin audio: sin tono", key_detect.detect_from_samples(None)["tone"] == "")
rumor = key_detect.detect_from_samples(np.random.default_rng(3).normal(0, 0.1, SR * 40).astype(np.float32))
check(f"solo ruido: sin tono o con poca confianza (da «{rumor['tone']}», {rumor['tone_conf']})",
      rumor["tone"] == "" or rumor["tone_conf"] < key_detect.CONFIDENT)
check("la confianza de un tono claro es alta", key_detect.detect_from_samples(song(2, True))["tone_conf"] > 0.8)
seno = (0.5 * np.sin(2 * np.pi * 440.0 * np.arange(SR * 30) / SR)).astype(np.float32)
bajo = (0.5 * np.sin(2 * np.pi * 82.41 * np.arange(SR * 30) / SR)).astype(np.float32)
for nombre, sola in (("un tono puro de 440 Hz", seno), ("un bajo solo", bajo)):
    r = key_detect.detect_from_samples(sola)
    check(f"{nombre}: con menos de 4 notas la confianza queda por debajo del umbral (se vería con «?»; da {r['tone_conf']})",
          r["tone_conf"] < key_detect.CONFIDENT)
tranquila = (song(7, False) * 0.004).astype(np.float32)                                   # un master muy bajo (pico de 0,002)
check("un master muy bajo no se descarta: la puerta de silencio es relativa", key_detect.detect_from_samples(tranquila)["tone"] == "9B")
mitad_silencio = np.concatenate([np.zeros(SR * 40, dtype=np.float32), song(0, False)])
check("silencio al principio y música después: sale el tono de la música", key_detect.detect_from_samples(mitad_silencio)["tone"] == "8B")
check("best_key rechaza un perfil plano", key_detect.best_key(np.ones(12)) is None and key_detect.best_key(None) is None)
import subprocess
cargado = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from services import key_detect, track_analysis; "
                          "print('numpy' in sys.modules)", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")],
                         capture_output=True, text=True, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}).stdout.strip()
check("importar los módulos del tono no carga numpy (se carga al usarlo; así no se nota al abrir la aplicación)", cargado == "False")

# ------------------------------------------------------------------ archivos de verdad (FFmpeg) y etiquetas
carpeta = tempfile.mkdtemp(prefix="tonalidad_")


def write_wav(path, audio, rate=22050):
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)


if not key_detect.available():
    check("hay numpy y FFmpeg para probar con archivos (no: se salta esta parte)", True)
else:
    ruta = os.path.join(carpeta, "do_mayor.wav")
    write_wav(ruta, np.repeat(song(0, False), 2), 22050)               # mismo tono a 22.050 Hz (FFmpeg lo baja a 11.025)
    t0 = time.time()
    found = key_detect.detect(ruta)
    check(f"un archivo de verdad pasa por FFmpeg: do mayor = 8B ({found}, {time.time() - t0:.1f} s)", found and found["tone"] == "8B")
    check("y con confianza alta", found["tone_conf"] > 0.8)
    check("un archivo que no existe: None (se reintentará)", key_detect.detect(os.path.join(carpeta, "no_existe.wav")) is None)

    from mutagen.id3 import TKEY
    from mutagen.wave import WAVE
    etiquetada = os.path.join(carpeta, "etiquetada.wav")
    write_wav(etiquetada, song(0, False), 11025)                         # suena a do mayor (8B)
    audio = WAVE(etiquetada)
    audio.add_tags()
    audio.tags.add(TKEY(encoding=3, text=["Am"]))
    audio.save()
    check("la etiqueta del archivo manda: dice «Am» y se usa (8A, confianza 1,0)", key_detect.tag_key(etiquetada) == "8A"
          and key_detect.detect(etiquetada) == {"tone": "8A", "tone_conf": 1.0})
    audio = WAVE(etiquetada)
    audio.tags.delall("TKEY")
    audio.tags.add(TKEY(encoding=3, text=["11B"]))
    audio.save()
    check("la etiqueta puede estar ya en Camelot", key_detect.tag_key(etiquetada) == "11B")
    audio = WAVE(etiquetada)
    audio.tags.delall("TKEY")
    audio.tags.add(TKEY(encoding=3, text=["o"]))
    audio.save()
    check("una etiqueta que no es un tono («o») se ignora y se calcula", key_detect.tag_key(etiquetada) is None
          and key_detect.detect(etiquetada)["tone"] == "8B")
    check("sin etiquetas, ninguna", key_detect.tag_key(ruta) is None and key_detect.tag_key(os.path.join(carpeta, "nada.wav")) is None)

    # el análisis completo guarda el tono y lo devuelve del índice
    analizada = os.path.join(carpeta, "analizada.wav")
    write_wav(analizada, np.tile(song(7, True, seconds_per_chord=8.0), 2), 11025)     # 64 s en sol menor = 6A
    result = track_analysis.analyze(analizada)
    check(f"analyze() incluye el tono (sol menor = 6A; da {result and result.get('tone')})", result is not None
          and result["tone"] == "6A" and result["tone_conf"] > 0.8)
    again = track_analysis.stored(analizada, need_tone=True)
    check("se lee del índice con el tono", again is not None and again["tone"] == "6A")

# ------------------------------------------------------------------ guardado en el índice
fake = os.path.join(carpeta, "guardada.mp3")
with open(fake, "wb") as fh:
    fh.write(b"x")
base = {"bpm": 120.0, "confidence": 2.0, "energy": 0.5, "intro_ms": 1000, "outro_ms": 2000, "duration_ms": 180000}
track_analysis.save(fake, dict(base, tone=None, tone_conf=0.0))
check("sin tono intentado: se da por hecho si no se pide el tono", track_analysis.stored(fake)["tone"] is None)
check("y por no hecho si se puede calcular el tono (para reintentar)", track_analysis.stored(fake, need_tone=True) is None)
track_analysis.save(fake, dict(base, tone="", tone_conf=0.0))
check("tono «» (se intentó y no hay armonía clara): no se reintenta", track_analysis.stored(fake, need_tone=True)["tone"] == "")
track_analysis.save(fake, dict(base, tone="8A", tone_conf=0.71))
check("ida y vuelta del tono y su confianza", track_analysis.stored(fake, need_tone=True)["tone"] == "8A"
      and track_analysis.stored(fake)["tone_conf"] == 0.71)
check("el resultado del análisis lleva los dos campos nuevos", {"tone", "tone_conf"} <= set(track_analysis.analyze_envelope(b"")))

# ------------------------------------------------------------------ una base de datos de la versión anterior se actualiza
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(str(library_db.DB_FILE) + suffix)
    except OSError:
        pass
library_db._ready = False
vieja = os.path.join(carpeta, "vieja.mp3")
with open(vieja, "wb") as fh:
    fh.write(b"x")
viejo = sqlite3.connect(str(library_db.DB_FILE))
viejo.executescript("""
CREATE TABLE analysis (path TEXT PRIMARY KEY, mtime REAL NOT NULL, version INTEGER NOT NULL, bpm REAL,
    confidence REAL DEFAULT 0, energy REAL DEFAULT 0, intro_ms INTEGER DEFAULT 0, outro_ms INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0);
PRAGMA user_version=1;
""")
viejo.execute("INSERT INTO analysis(path, mtime, version, bpm) VALUES (?, ?, ?, 128.0)",
              (vieja, os.path.getmtime(vieja), track_analysis.VERSION))
viejo.commit()
viejo.close()
with library_db.connect() as con:
    columnas = {row[1] for row in con.execute("PRAGMA table_info(analysis)")}
    fila = con.execute("SELECT bpm, tone, tone_conf FROM analysis WHERE path=?", (vieja,)).fetchone()
check("una base de la versión anterior gana las columnas del tono", {"tone", "tone_conf"} <= columnas)
check("y no pierde lo que tenía (BPM 128, tono sin intentar)", fila["bpm"] == 128.0 and fila["tone"] is None)
check("una fila válida de la versión anterior sigue valiendo (no se reanaliza todo al actualizar)",
      track_analysis.stored(vieja) is not None and track_analysis.stored(vieja)["bpm"] == 128.0)
check("y solo se vuelve a analizar si se puede calcular el tono", track_analysis.stored(vieja, need_tone=True) is None)
library_db._ready = False
with library_db.connect() as con:
    check("repetirlo no da error (columnas ya creadas)", len({row[1] for row in con.execute("PRAGMA table_info(analysis)")}) == len(columnas))

print("FIN")
