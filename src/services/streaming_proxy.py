"""Proxy HTTP local de streaming para previsualizaciones de audio.
Escucha en 127.0.0.1 en un puerto dinámico asignado por el sistema operativo.
Soporta peticiones HTTP Range (bytes=X-Y) con HTTP 206 Partial Content y realiza
reintentos automáticos si YouTube corta la conexión upstream a mitad de canción.
"""
import http.client
import http.server
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CHUNK_SIZE = 64 * 1024  # 64 KB


class _ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Silenciar logs HTTP habituales
        pass

    def do_HEAD(self):
        self._handle_request(send_body=False)

    def do_GET(self):
        self._handle_request(send_body=True)

    def _handle_request(self, send_body: bool = True):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        remote_url = qs.get("url", [None])[0]

        if not remote_url:
            self.send_error(400, "Parámetro 'url' requerido")
            return

        range_header = self.headers.get("Range")
        req_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Connection": "keep-alive",
        }
        if range_header:
            req_headers["Range"] = range_header

        # Intentar conectar con el origen remoto con reintento automático
        upstream_resp = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(remote_url, headers=req_headers)
                upstream_resp = urllib.request.urlopen(req, timeout=8)
                break
            except urllib.error.HTTPError as e:
                if e.code in (416,):
                    self.send_error(416, "Requested Range Not Satisfiable")
                    return
                if attempt == 2:
                    self.send_error(e.code, f"Error upstream: {e.reason}")
                    return
            except Exception as e:
                if attempt == 2:
                    self.send_error(502, f"Error de conexión upstream: {e}")
                    return

        if not upstream_resp:
            self.send_error(504, "Tiempo de espera agotado")
            return

        status_code = upstream_resp.status
        content_type = upstream_resp.headers.get("Content-Type", "audio/mp4")
        content_length = upstream_resp.headers.get("Content-Length")
        content_range = upstream_resp.headers.get("Content-Range")

        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        if content_range:
            self.send_header("Content-Range", content_range)
        if content_length:
            self.send_header("Content-Length", content_length)
        self.end_headers()

        if not send_body:
            upstream_resp.close()
            return

        # Streaming de datos por chunks con autorecuperación
        bytes_sent = 0
        try:
            while True:
                chunk = upstream_resp.read(CHUNK_SIZE)
                if not chunk:
                    break
                self.wfile.write(chunk)
                bytes_sent += len(chunk)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass  # El reproductor cerró el stream o hizo seek
        except Exception as e:
            logger.debug(f"Streaming interrumpido tras {bytes_sent} bytes: {e}")
        finally:
            upstream_resp.close()


class StreamingProxy:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._server = None
        self._thread = None
        self._port = None
        self._running = False

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = StreamingProxy()
            return cls._instance

    @property
    def port(self) -> int | None:
        return self._port

    def start(self):
        with self._lock:
            if self._running:
                return
            try:
                self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ProxyHandler)
                self._port = self._server.server_address[1]
                self._running = True
                self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="StreamingProxyThread")
                self._thread.start()
                logger.info(f"StreamingProxy iniciado en http://127.0.0.1:{self._port}")
            except Exception as e:
                logger.error(f"No se pudo iniciar StreamingProxy: {e}")
                self._running = False

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._server:
                try:
                    self._server.shutdown()
                    self._server.server_close()
                except Exception:
                    pass
                self._server = None
            self._port = None

    def get_stream_url(self, remote_url: str) -> str:
        """Devuelve una URL proxificada por 127.0.0.1 si el servidor está activo, o la remota si no."""
        if not self._running or not self._port:
            self.start()
        if self._running and self._port:
            encoded = urllib.parse.quote(remote_url, safe="")
            return f"http://127.0.0.1:{self._port}/stream?url={encoded}"
        return remote_url
