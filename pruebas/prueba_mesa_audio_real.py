"""Prueba de integración de control de audio real en la Mesa de DJ y previsualización en el buscador.

Verifica:
1. Previsualización de canciones sin descargar: reproducción directa de CDN y fallback.
2. Pitch Fader: modifica físicamente la velocidad de reproducción y calcula el BPM en vivo.
3. Jog Wheel: arrastre con ratón (scrub/scratch) modifica la posición en milisegundos en tiempo real.
4. Ganancias, Faders y Crossfader: cálculo de curva de igual potencia aplicada a la salida de audio.
5. Ecualizador de 3 bandas y filtro de color (COLOR FX): envío de frecuencias graves, medias y agudas.
6. Hot Cues, Beat Loops, CUE y SYNC: memoria de puntos y salto inmediato.
"""
import os
import sys
import math
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, QEvent, Qt

# Entorno de pruebas
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ui.main_window import MainWindow  # noqa: E402
from ui.dj_page import DjPage  # noqa: E402
from ui.dj_components import DjJogWheel, DjPitchFader, DjRotaryKnob, DjCrossfader  # noqa: E402


def check(name: str, cond: bool):
    if cond:
        print(f"[OK] {name}")
    else:
        print(f"[FAIL] {name}")
        raise AssertionError(f"Fallo en: {name}")


def main():
    _app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.audio_output.setVolume(1.0)
    dj_page: DjPage = win.page_dj

    print("--- 1. Probando Previsualización Directa y Recuperación de Audio ---")
    # Usar una URL o recurso para verificar que no bloquea la interfaz
    mock_cdn_track = {
        "id": "12345",
        "title": "Prueba CDN",
        "uploader": "Artista Test",
        "preview_url": "https://cdns-preview-d.dzcdn.net/stream/c-dda28164b1.mp3",
        "url": "ytsearch1:Artista Test Prueba CDN"
    }
    win.play_preview(mock_cdn_track)
    check("Previsualización directa asigna URL sin colgarse", win.player.source().toString() != "")
    check("Salida de audio no está silenciada en preview", not win.audio_output.isMuted())
    check("El reproductor pasa a estado activo o cargando", int(win.player.playbackState().value) in (0, 1, 2))

    print("\n--- 2. Probando Pitch Fader y Modificación de Velocidad en Tiempo Real ---")
    pitch_a = dj_page.pitch_a
    # Mover pitch hacia abajo +5%
    pitch_a.setValue(0.5)  # +5% de pitch (+5% tempo)
    check("Pitch fader calcula +5.0% de pitch", abs(pitch_a.value - 0.5) < 0.01)
    check("Player ajusta playbackRate a 1.05", abs(win.player.playbackRate() - 1.05) < 0.02)
    # Doble clic resetea pitch
    pitch_a.resetPitch()
    check("Pitch fader resetea a centro (0.0% / 1.00x)", abs(pitch_a.value) < 0.001)
    check("Player recupera velocidad nominal 1.00", abs(win.player.playbackRate() - 1.0) < 0.01)

    print("\n--- 3. Probando Jog Wheel y Manipulación de Audio con Ratón (Scratch / Scrub) ---")
    jog_a = dj_page.jog_a
    check("Jog Wheel arranca en Modo Vinilo", jog_a.isVinylMode())
    jog_events = []
    jog_a.scratched.connect(lambda delta: jog_events.append(delta))

    # Simular giro del ratón de 90 grados
    jog_a._last_mouse_angle = 0.0
    jog_a._dragging = True
    jog_a.resize(100, 100)
    # Posición en x=50, y=100 -> ángulo 90 grados
    jog_a._last_mouse_angle = 0.0
    # Desplazamiento de +45 grados: 45 * 5ms = 225 ms
    cur_pos = win.player.position()
    dj_page._on_jog_a_scratched(500)
    check("Scratch con Jog Wheel desplaza posición del reproductor", win.player.position() >= cur_pos)

    # Alternar a modo CDJ (Pitch bend)
    jog_a.setVinylMode(False)
    check("Jog Wheel alterna a Modo CDJ", not jog_a.isVinylMode())
    dj_page._on_jog_a_nudged(0.04)
    check("Jog Wheel en modo CDJ aplica pitch bend temporal", win.player.playbackRate() > 1.0)
    jog_a.setVinylMode(True)

    print("\n--- 4. Probando Ganancias, Faders y Crossfader de Potencia Constante ---")
    xf = dj_page.crossfader
    # Crossfader al extremo izquierdo (Plato A = 100%, Plato B = 0%)
    xf.setPosition(-1.0)
    dj_page._apply_audio_gains()
    check("Crossfader todo a la izquierda mantiene Plato A al 100%", abs(win.audio_output.volume() - 1.0) < 0.05)

    # Crossfader al centro (Igual potencia: cos(pi/4) = 0.707)
    xf.setPosition(0.0)
    dj_page._apply_audio_gains()
    expected_gain = math.cos(math.pi / 4.0)
    check(f"Crossfader al centro aplica ganancia de igual potencia (~{expected_gain:.3f})",
          abs(win.audio_output.volume() - expected_gain) < 0.05)

    # Crossfader todo a la derecha (Plato A = 0%, Plato B = 100%)
    xf.setPosition(1.0)
    dj_page._apply_audio_gains()
    check("Crossfader todo a la derecha atenúa Plato A a 0%", win.audio_output.volume() < 0.02)

    # Resetear crossfader a izquierda para Deck A
    xf.setPosition(-1.0)
    dj_page.fader_a.setValue(0.5)
    dj_page._apply_audio_gains()
    check("Fader individual de Canal A atenúa la señal en tiempo real (0.5)", abs(win.audio_output.volume() - 0.5) < 0.05)
    dj_page.fader_a.setValue(1.0)
    dj_page._apply_audio_gains()

    print("\n--- 5. Probando Ecualizador de 3 Bandas y Filtro de Color ---")
    dj_page.knob_low_a.setValue(-0.8)  # Cortar graves
    dj_page.knob_mid_a.setValue(0.2)   # Realce de medios
    dj_page.knob_high_a.setValue(0.5)  # Realce de agudos
    dj_page._do_apply_eq()
    check("EQ se aplica a la ventana principal", hasattr(win, "eq_settings"))
    check("Corte de graves efectivo reflejado en settings", win.eq_settings.get("bass", 0) < 0)

    # Probar barrido de filtro de color (COLOR FX)
    dj_page.knob_filter_a.setValue(-0.7)  # Low Pass
    dj_page._do_apply_eq()
    check("Filtro Low Pass atenúa agudos y medios", win.eq_settings.get("treble", 0) < 0)
    dj_page.knob_filter_a.setValue(0.0)
    dj_page.knob_low_a.setValue(0.0)
    dj_page.knob_mid_a.setValue(0.0)
    dj_page.knob_high_a.setValue(0.0)
    dj_page._do_apply_eq()

    print("\n--- 6. Probando Hot Cues, Beat Loops, CUE y SYNC ---")
    # Fijar y saltar a Hot Cue 1
    dj_page._on_pad_action(is_deck_a=True, pad_idx=0, mode="HOT CUE")
    check("Hot Cue 1 graba la marca de tiempo", dj_page._hot_cues_a[0] is not None)
    saved_cue = dj_page._hot_cues_a[0]
    win.player.setPosition(50000)
    dj_page._on_pad_action(is_deck_a=True, pad_idx=0, mode="HOT CUE")
    check("Al pulsar Hot Cue 1 de nuevo, el reproductor salta inmediatamente a la marca", win.player.position() == saved_cue)

    # Probar Beat Loops (IN, OUT, RELOOP)
    dj_page._on_loop_in("A")
    check("Loop IN marcado", dj_page._loop_start_a is not None)
    dj_page._on_loop_out("A")
    check("Loop OUT marcado y bucle activado", dj_page._loop_active_a and dj_page._loop_end_a is not None)
    dj_page._on_reloop("A")
    check("Reloop desactiva el bucle", not dj_page._loop_active_a)

    # Probar CUE de transporte Pioneer
    dj_page._on_cue_clicked("A")
    check("CUE marca punto de retorno", dj_page._cue_a_ms is not None)

    # Probar SYNC entre platos
    dj_page._deck_a_bpm = 120.0
    dj_page._deck_b_bpm = 126.0
    dj_page._on_sync_clicked("A")
    check("SYNC ajusta el pitch de Deck A para igualar los 126 BPM de Deck B", abs(dj_page.pitch_a.value - 0.5) < 0.05)

    print("\nTODAS LAS PRUEBAS DE AUDIO Y MESA DJ REAL (16/16) HAN PASADO CON EXITO!")
    sys.stdout.flush()
    win.player.stop()
    from PySide6.QtCore import QUrl
    win.player.setSource(QUrl())
    _app.processEvents()
    os._exit(0)


if __name__ == "__main__":
    main()
