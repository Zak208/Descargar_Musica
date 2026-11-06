"""Validación integral de la Fase 4:
1. StreamingProxy (puerto dinámico, HTTP Range 206, cabeceras, singleton, start/stop).
2. Autoplay inteligente (_try_autoplay, candidatos Deezer / biblioteca local, flags).
3. Persistencia de configuración (chk_autoplay en settings).
"""
import http.server
import os
import sys
import threading
import time
import urllib.request

# Ajustar PYTHONPATH
sys.path.insert(0, os.path.abspath("src"))
sys.path.insert(0, os.path.abspath("pruebas"))


def test_streaming_proxy_lifecycle_and_range():
    print("[TEST 1/4] Comprobando ciclo de vida y peticiones de StreamingProxy...")
    from services.streaming_proxy import StreamingProxy

    proxy = StreamingProxy.get_instance()
    assert proxy is not None
    assert StreamingProxy.get_instance() is proxy, "StreamingProxy debe ser un Singleton"

    # Iniciar servidor proxy
    proxy.start()
    port = proxy.port
    assert port is not None and port > 0, f"Puerto no asignado: {port}"
    print(f"  -> StreamingProxy escuchando en puerto {port}")

    # Montar un servidor de prueba upstream que sirva un archivo simulado de 100 KB
    sample_data = b"X" * (100 * 1024)

    class MockAudioHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            range_header = self.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                parts = range_header.replace("bytes=", "").split("-")
                start = int(parts[0]) if parts[0] else 0
                end = int(parts[1]) if parts[1] else len(sample_data) - 1
                end = min(end, len(sample_data) - 1)
                chunk = sample_data[start : end + 1]

                self.send_response(206)
                self.send_header("Content-Type", "audio/mp4")
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(sample_data)}")
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(chunk)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "audio/mp4")
                self.send_header("Content-Length", str(len(sample_data)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                self.wfile.write(sample_data)

    upstream_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockAudioHandler)
    upstream_port = upstream_server.server_address[1]
    upstream_thread = threading.Thread(target=upstream_server.serve_forever, daemon=True)
    upstream_thread.start()

    try:
        mock_audio_url = f"http://127.0.0.1:{upstream_port}/test_song.m4a"
        proxied_url = proxy.get_stream_url(mock_audio_url)
        assert f"127.0.0.1:{port}" in proxied_url, f"URL proxificada inesperada: {proxied_url}"
        print(f"  -> URL Proxificada: {proxied_url}")

        # Petición completa al proxy
        req = urllib.request.Request(proxied_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200, f"Status code no es 200: {resp.status}"
            data = resp.read()
            assert len(data) == len(sample_data), f"Longitud de datos recibidos errónea: {len(data)}"
        print("  -> Descarga completa a través de StreamingProxy verificada OK (100 KB)")

        # Petición Range al proxy (HTTP 206)
        range_req = urllib.request.Request(proxied_url, headers={"Range": "bytes=1024-2047"})
        with urllib.request.urlopen(range_req, timeout=5) as resp:
            assert resp.status == 206, f"Se esperaba 206 Partial Content, recibido {resp.status}"
            content_range = resp.headers.get("Content-Range")
            assert "bytes 1024-2047/102400" in content_range, f"Cabecera Content-Range errónea: {content_range}"
            range_data = resp.read()
            assert len(range_data) == 1024, f"Longitud de bytes de rango inesperada: {len(range_data)}"
        print("  -> Petición HTTP Range 206 a través de StreamingProxy verificada OK (1024 bytes)")

    finally:
        upstream_server.shutdown()
        upstream_server.server_close()
        proxy.stop()
        assert proxy.port is None, "El puerto del proxy debe restablecerse a None tras stop()"
        print("  -> StreamingProxy detenido limpiamente")


def test_autoplay_fallback_and_queue():
    print("[TEST 2/4] Comprobando lógica de Autoplay inteligente en PlaybackMixin...")
    from ui.playback_mixin import PlaybackMixin

    class MockPlayer:
        def __init__(self):
            self.state = 0

        def playbackState(self):
            return self.state

        def play(self):
            self.state = 1

        def stop(self):
            self.state = 0

    class MockStatus:
        def __init__(self):
            self.text = ""

        def setText(self, t):
            self.text = t

    class DummyWindow(PlaybackMixin):
        def __init__(self):
            self.init_playback_state()
            self.player = MockPlayer()
            self.player_status = MockStatus()
            self.current_item_info = {
                "title": "Bohemian Rhapsody",
                "uploader": "Queen",
                "artist": "Queen",
                "duration_secs": 354,
                "url": "local.mp3"
            }
            self.playback_queue = []
            self.is_shuffle_enabled = lambda: False
            self._lib_items = [
                {"title": "Radio Ga Ga", "uploader": "Queen", "duration_secs": 343, "local_path": "c:/music/q1.mp3"},
                {"title": "Under Pressure", "uploader": "Queen", "duration_secs": 248, "local_path": "c:/music/q2.mp3"},
                {"title": "Another One Bites the Dust", "uploader": "Queen", "duration_secs": 215, "local_path": "c:/music/q3.mp3"},
            ]
            self.played_entries = []
            self.notifications = []

        def notify(self, msg):
            self.notifications.append(msg)

        def _play_entry(self, entry, crossfade_ms=0):
            self.played_entries.append(entry)

        def _same_track(self, a, b):
            return a.get("title") == b.get("title")

    win = DummyWindow()

    # Probar _try_autoplay cuando no hay siguientes en la lista
    res = win._try_autoplay(xf=0)
    assert res is True, "Autoplay debió encontrar candidatos"
    assert len(win.played_entries) == 1, "Debió reproducir el primer tema de autoplay"
    nxt = win.played_entries[0]
    assert nxt.get("is_autoplay") is True, "El tema reproducido debe tener is_autoplay=True"
    print(f"  -> Autoplay seleccionó: {nxt.get('title')} por {nxt.get('uploader')}")
    print(f"  -> Cola de reproducción llenada con {len(win.playback_queue)} canciones adicionales")
    assert len(win.playback_queue) > 0, "Debió encolar canciones adicionales"
    print(f"  -> Notificación emitida: {win.notifications[-1] if win.notifications else 'N/A'}")


def test_settings_autoplay_flag():
    print("[TEST 3/4] Comprobando integración de autoplay_enabled en settings...")
    from config import load_settings, update_settings

    orig = load_settings().get("autoplay_enabled", True)
    try:
        update_settings(autoplay_enabled=False)
        assert load_settings().get("autoplay_enabled") is False, "autoplay_enabled no se guardó como False"
        update_settings(autoplay_enabled=True)
        assert load_settings().get("autoplay_enabled") is True, "autoplay_enabled no se guardó como True"
        print("  -> Persistencia de autoplay_enabled correcta")
    finally:
        update_settings(autoplay_enabled=orig)


def test_main_window_proxy_integration():
    print("[TEST 4/4] Comprobando integración de StreamingProxy en MainWindow...")
    from services.streaming_proxy import StreamingProxy

    proxy = StreamingProxy.get_instance()
    sample_remote = "https://rr3---sn-4g5ednks.googlevideo.com/videoplayback?expire=12345&id=abcdef"
    proxied = proxy.get_stream_url(sample_remote)

    assert proxied.startswith("http://127.0.0.1:"), f"URL no redirige a proxy local: {proxied}"
    assert "url=https%3A%2F%2Frr3---sn-4g5ednks" in proxied, f"URL destino no codificada adecuadamente: {proxied}"
    proxy.stop()
    print("  -> get_stream_url genera endpoints loopback válidos y sanitizados")


if __name__ == "__main__":
    test_streaming_proxy_lifecycle_and_range()
    test_autoplay_fallback_and_queue()
    test_settings_autoplay_flag()
    test_main_window_proxy_integration()
    print("\nTODOS LOS TESTS DE FASE 4 PASARON SATISFACTORIAMENTE (4/4)")
