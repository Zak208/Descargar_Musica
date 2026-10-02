"""Peticiones web compartidas: una sola sesión con conexiones que se reutilizan.

Cada `requests.get(...)` suelto abre una conexión nueva y vuelve a cargar los certificados de seguridad
(≈ 170 ms de CPU por petición en Windows). Con una sesión compartida las conexiones se reutilizan y el coste baja
más de 10 veces: es lo que más ayuda a que la aplicación no sobrecargue un ordenador modesto al arrancar.
"""
import ssl
import threading
from http.cookiejar import DefaultCookiePolicy

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_lock = threading.Lock()
_session: requests.Session | None = None
_context: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    """Contexto de seguridad que se crea UNA sola vez (certificados de Windows + los de certifi)."""
    global _context
    if _context is None:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except Exception:
            pass
        _context = ctx
    return _context


class _SharedContextAdapter(HTTPAdapter):
    """Todas las conexiones usan el mismo contexto de seguridad (si no, cada conexión nueva volvía a leer
    los certificados: ≈ 160 ms de CPU)."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = _ssl_context()
        super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

    def cert_verify(self, conn, url, verify, cert):
        if url.lower().startswith("https") and verify is True:
            conn.cert_reqs = "CERT_REQUIRED"
            conn.ca_certs = None
            conn.ca_cert_dir = None
        else:
            super().cert_verify(conn, url, verify, cert)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
        if verify is True:
            pool_kwargs["ssl_context"] = _ssl_context()
        return host_params, pool_kwargs


def session() -> requests.Session:
    global _session
    if _session is None:
        with _lock:
            if _session is None:
                s = requests.Session()
                retry = Retry(total=2, connect=2, read=1, status=0, backoff_factor=0.15, allowed_methods=("GET", "HEAD"))
                adapter = _SharedContextAdapter(pool_connections=24, pool_maxsize=24, max_retries=retry)
                s.mount("https://", adapter)
                s.mount("http://", adapter)
                s.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))     # no se guardan cookies
                _session = s
    return _session


def get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 8)
    return session().get(url, **kwargs)


def head(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 8)
    return session().head(url, **kwargs)


def warm_up() -> None:
    """Prepara la sesión y los certificados en segundo plano (así la primera petición no espera)."""
    threading.Thread(target=session, name="http-warmup", daemon=True).start()
