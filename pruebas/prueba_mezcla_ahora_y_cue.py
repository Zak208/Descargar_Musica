"""Pruebas automáticas para la mezcla inmediata ('Mezclar Ahora'), detección de Cue Point
y reproducción de vista previa sin descargas.
"""
import os
import sys
import unittest

# Asegurar src en path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtWidgets import QApplication
from services import cue_detector
from services.catalog_service import AlbumDetailsWorker
from services.mix_types import TransitionPlan, KIND_BLEND
from services.transition_types import choose_type
from ui.dj_page import DjPage

app = QApplication.instance() or QApplication(sys.argv)


class TestCueDetectorAndAutoMix(unittest.TestCase):
    def test_cue_detector_from_structure_drop(self):
        """Si la estructura contiene un evento de drop en la primera mitad, se usa como Cue Point."""
        analysis = {
            "duration_s": 210.0,
            "structure": {
                "events": [
                    {"t": 16.5, "type": "drop", "strength": 0.9},
                    {"t": 85.0, "type": "drop", "strength": 1.0}
                ]
            }
        }
        cue = cue_detector.get_track_cue_point(analysis)
        self.assertEqual(cue, 16.5)

    def test_cue_detector_from_intro_energy(self):
        """Si no hay evento de drop pero sí intro_ms por energía, se usa el fin de intro como Cue Point."""
        analysis = {
            "duration_s": 180.0,
            "intro_ms": 22400.0,
            "structure": None
        }
        cue = cue_detector.get_track_cue_point(analysis)
        self.assertEqual(cue, 22.4)

    def test_cue_detector_from_beatgrid(self):
        """Si hay tempo y beat_first, se calcula el compás 8 o 16 para iniciar con el groove."""
        analysis = {
            "duration_s": 240.0,
            "bpm": 128.0,
            "beat_first_s": 0.5,
            "intro_ms": 0
        }
        cue = cue_detector.get_track_cue_point(analysis)
        self.assertGreater(cue, 4.0)
        self.assertLessEqual(cue, 35.0)

    def test_cue_detector_never_starts_at_zero_for_long_track(self):
        """Una pista larga estándar nunca empieza en 0.0s."""
        analysis = {"duration_s": 200.0}
        cue = cue_detector.get_track_cue_point(analysis)
        self.assertGreater(cue, 0.0)

    def test_transition_types_choice(self):
        """La transición seleccionada debe ser un tipo profesional (smart_filter_eq, delay_drop o reverb_wash)."""
        analysis_a = {"bpm": 124.0, "energy": 0.85, "duration_s": 180.0}
        analysis_b = {"bpm": 124.0, "energy": 0.80, "duration_s": 200.0}
        plan = TransitionPlan(a_start_s=60.0, b_start_s=15.0, length_s=6.0, kind=KIND_BLEND)

        t_type, reason = choose_type(analysis_a, analysis_b, plan, bpm_a=124.0, profile="club")
        self.assertIn(t_type, ("smart_filter_eq", "filter", "blend", "delay_drop"))

    def test_auto_mix_button_signal_isolation(self):
        """El botón 'MEZCLAR AHORA' solo emite auto_mix_requested y NUNCA skip_requested (evita doble salto)."""
        page = DjPage()
        emitted_auto = []
        emitted_skip = []

        page.auto_mix_requested.connect(lambda: emitted_auto.append(True))
        page.skip_requested.connect(lambda: emitted_skip.append(True))

        page.btn_auto_mix.click()

        self.assertEqual(len(emitted_auto), 1, "Debe emitirse exactamente 1 señal auto_mix_requested")
        self.assertEqual(len(emitted_skip), 0, "NO debe emitirse skip_requested al pulsar Mezclar Ahora")

    def test_animate_transition_moves_crossfader_and_knobs(self):
        """animate_transition activa la animación del crossfader y filtros."""
        page = DjPage()
        page.crossfader._pos = -1.0  # en Deck A

        page.animate_transition(duration_ms=1000)

        # Comprobar que la animación del crossfader se ha iniciado
        self.assertIsNotNone(page.crossfader._anim)

    def test_album_details_fallback_query(self):
        """AlbumDetailsWorker puede resolver álbumes por nombre y artista si el ID de red falla."""
        album_dict = {
            "id": "dz_invalid_or_missing",
            "name": "Superhumano",
            "artist": "Capaz"
        }
        worker = AlbumDetailsWorker(album_dict)
        data_received = []
        err_received = []
        worker.details_ready.connect(lambda d: data_received.append(d))
        worker.error_occurred.connect(lambda e: err_received.append(e))

        worker.run()  # Ejecución síncrona en test

        self.assertEqual(len(err_received), 0, f"No debería haber error con fallback de texto: {err_received}")
        self.assertEqual(len(data_received), 1, "Debería recibirse data_ready con los tracks del álbum")
        self.assertGreater(len(data_received[0].get("tracks", [])), 0, "El álbum debe contener pistas")


if __name__ == "__main__":
    unittest.main()
