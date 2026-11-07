"""Pruebas automáticas para el visualizador superior de formas de onda duales,
medidor de fase, beatmatching ('Juntar beats') y explorador integrado estilo VirtualDJ.
"""
import sys
import os

# Asegurar path de importación
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QMouseEvent

# Instancia global de Qt para pruebas
_app = QApplication.instance() or QApplication(sys.argv)

from ui.dj_components import (
    DjMasterWaveformDisplay, DjRunningWaveformView, DjPhaseMeter,
    DjOverviewWaveform, DjVirtualBrowser
)
from ui.dj_page import DjPage


def test_overview_waveform():
    print("--- 1. Probando DjOverviewWaveform ---")
    ow = DjOverviewWaveform(color="#00D2FF")
    ow.resize(400, 14)
    ow.setProgress(30000, 180000, 15000)

    assert ow._pos_ms == 30000, "Posición incorrecta en overview"
    assert ow._dur_ms == 180000, "Duración incorrecta en overview"
    assert ow._cue_ms == 15000, "Cue incorrecto en overview"

    # Simular clic para salto de posición
    clicked_ms = []
    ow.seekRequested.connect(clicked_ms.append)
    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(200, 7), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    ow.mousePressEvent(event)

    assert len(clicked_ms) == 1, "No se emitió seekRequested en overview"
    # El clic a mitad de ancho (200 de 400 px) debe dar aprox la mitad de la duración (90000 ms)
    assert abs(clicked_ms[0] - 90000) < 1000, f"Salto impreciso: {clicked_ms[0]}"
    print("[OK] Overview Waveform calcula posición, cue y responde a clic de salto.")


def test_phase_meter():
    print("--- 2. Probando DjPhaseMeter (Medidor de Fase / Beats alineados) ---")
    pm = DjPhaseMeter()
    pm.resize(300, 22)

    # 1. Beats desfasados en +80 ms
    pm.setPhaseOffset(80.0, 500.0)
    assert not pm._is_aligned, "Debería indicar desalineado con +80 ms"

    # 2. Beats alineados (<= 20 ms)
    pm.setPhaseOffset(5.0, 500.0)
    assert pm._is_aligned, "Debería indicar alineado con 5 ms"

    aligned_signal = []
    pm.alignRequested.connect(lambda: aligned_signal.append(True))
    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(150, 11), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    pm.mousePressEvent(event)
    assert len(aligned_signal) == 1, "Clic en PhaseMeter debe emitir alignRequested"
    print("[OK] Phase Meter calcula alineación de bombos y emite solicitud de junta.")


def test_running_waveform_view():
    print("--- 3. Probando DjRunningWaveformView (Ondas Duales en Movimiento) ---")
    rw = DjRunningWaveformView()
    rw.resize(600, 110)
    rw.setPlaybackState(
        pos_a=45000, dur_a=200000, bpm_a=128.0, playing_a=True,
        pos_b=30000, dur_b=180000, bpm_b=126.0, playing_b=True
    )
    assert rw._pos_a == 45000
    assert rw._pos_b == 30000
    assert rw._bpm_a == 128.0

    # Arrastre con ratón sobre Deck B (mitad inferior) para empujar/juntar la onda
    nudged = []
    rw.nudgeRequested.connect(lambda deck, delta: nudged.append((deck, delta)))

    # Presionar en y=80 (Deck B) y arrastrar hacia la izquierda
    press_ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(300, 80), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    rw.mousePressEvent(press_ev)
    assert rw._drag_active and rw._drag_deck == "B", "Arrastre de Deck B no detectado"

    move_ev = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(280, 80), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    rw.mouseMoveEvent(move_ev)
    assert len(nudged) >= 1, "Mover el ratón debe emitir nudgeRequested"
    assert nudged[0][0] == "B", "El nudge debe ser sobre Deck B"

    rel_ev = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(280, 80), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    rw.mouseReleaseEvent(rel_ev)
    assert not rw._drag_active, "Release debe desactivar arrastre"
    print("[OK] Running Waveform muestra pistas duales y responde a arrastre con ratón.")


def test_master_waveform_display():
    print("--- 4. Probando DjMasterWaveformDisplay (Contenedor Superior VirtualDJ) ---")
    mwd = DjMasterWaveformDisplay()
    mwd.resize(800, 160)

    mwd.updateDecks(
        title_a="Canción A (Club Mix)", bpm_a=128.0, pos_a=10000, dur_a=180000, playing_a=True,
        title_b="Canción B (Remix)", bpm_b=128.0, pos_b=10050, dur_b=210000, playing_b=False
    )
    assert "Canción A" in mwd.lbl_title_a.text()
    assert "Canción B" in mwd.lbl_title_b.text()
    assert "128.0 BPM" in mwd.lbl_bpm_a.text()

    juntar_called = []
    mwd.juntarBeatsRequested.connect(lambda: juntar_called.append(True))
    mwd.btn_juntar.click()
    assert len(juntar_called) == 1, "Botón 'JUNTAR BEATS' debe emitir señal"
    print("[OK] DjMasterWaveformDisplay actualiza metadatos y gestiona botón 'JUNTAR BEATS'.")


def test_virtual_browser():
    print("--- 5. Probando DjVirtualBrowser (Explorador Inferior VirtualDJ) ---")
    browser = DjVirtualBrowser()
    browser.resize(700, 200)

    test_tracks = [
        {"title": "Track One", "uploader": "Artist 1", "album": "Album 1", "duration_str": "3:20", "bpm": 128.0, "local_path": "/p1.mp3"},
        {"title": "Track Two", "uploader": "Artist 2", "album": "Album 2", "duration_str": "4:05", "bpm": 124.0, "local_path": "/p2.mp3"},
        {"title": "Bomba", "uploader": "Latin Star", "album": "Hits", "duration_str": "2:50", "bpm": 95.0, "local_path": "/p3.mp3"},
    ]
    browser.setTracks(test_tracks)
    assert browser.table.rowCount() == 3, "Debe tener 3 filas en la tabla"

    # Filtrar búsqueda
    browser.search_input.setText("bomba")
    assert browser.table.rowCount() == 1, "El filtro de búsqueda debe dejar solo 1 fila"

    browser.search_input.clear()
    assert browser.table.rowCount() == 3

    # Probar carga en Deck A y Deck B
    loaded = []
    browser.loadDeckRequested.connect(lambda deck, item: loaded.append((deck, item["title"])))

    # Clic en botón "LOAD A" de fila 0
    btn_a = browser.table.cellWidget(0, 5)
    btn_a.click()
    assert len(loaded) == 1 and loaded[0] == ("A", "Track One"), f"Carga en A falló: {loaded}"

    # Clic en botón "LOAD B" de fila 1
    btn_b = browser.table.cellWidget(1, 6)
    btn_b.click()
    assert len(loaded) == 2 and loaded[1] == ("B", "Track Two"), f"Carga en B falló: {loaded}"

    print("[OK] VirtualBrowser busca canciones y carga en Deck A y Deck B correctamente.")


def test_dj_page_integration():
    print("--- 6. Probando Integración en DjPage Completa ---")
    page = DjPage()
    assert hasattr(page, "waveform_display"), "DjPage debe contener waveform_display"
    assert hasattr(page, "virtual_browser"), "DjPage debe contener virtual_browser"

    # Comprobar juntar beats
    page._deck_a_bpm = 128.0
    page._deck_b_bpm = 125.0
    page._deck_a_sim_pos = 10250  # 128 BPM -> beat_ms = 468.75 ms
    page._deck_b_sim_pos = 10100

    page._on_juntar_beats()
    # Deck B debe igualar el BPM a 128.0
    assert page._deck_b_bpm == 128.0, f"BPM B no se sincronizó: {page._deck_b_bpm}"

    # Comprobar actualización visual periódica
    page._on_anim_frame()
    print("[OK] DjPage integra formas de onda duales superiores y navegador inferior estilo VirtualDJ.")


if __name__ == "__main__":
    test_overview_waveform()
    test_phase_meter()
    test_running_waveform_view()
    test_master_waveform_display()
    test_virtual_browser()
    test_dj_page_integration()
    print("\nTODAS LAS PRUEBAS DE FORMAS DE ONDA Y VIRTUALDJ (6/6) HAN PASADO CON ÉXITO!")
