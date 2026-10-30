"""Votos del público (fase 31): un servidor HTTP mínimo, solo con la biblioteca estándar, para que los invitados voten desde el
móvil en la misma wifi: 👍 «Me gusta», ⏭ «Pasar» y 🔥 «Más energía». Sin Qt: el DJ recibe los avisos por funciones (que se
llaman en el hilo del servidor; la interfaz las pasa a su hilo con una señal).

Cómo se cuenta (`VoteBox`, sin red, con el reloj inyectable para las pruebas):
  * Un invitado es una dirección IP (en una wifi de casa cada móvil tiene la suya). «Conectados» son los invitados que han
    abierto la página o votado en los últimos `GUEST_TTL_S` (la página da señales de vida cada 15 s).
  * Cada invitado puede votar cada tipo una vez cada `VOTE_COOLDOWN_S`; los votos valen durante `WINDOW_S`.
  * «Pasar» y «Más energía» cuentan invitados distintos (no votos: uno solo no puede forzar nada votando muchas veces). Hace
    falta `needed()` = max(`min_votes`, min(`votes`, techo(`ratio` × conectados))): con 3 conectados, 2; con 20, 5 (los
    valores por defecto: 30 % de los conectados o 5 invitados en 60 s, y nunca menos de 2). Mientras se llegue al umbral,
    cada voto nuevo de ese tipo vuelve a avisar: el DJ decide (no salta si la canción acaba de empezar, por ejemplo) y llama
    a `reset(kind)` cuando lo aplica. «Me gusta» solo se cuenta y se avisa (sirve para guardar el voto de la mezcla).

SEGURIDAD. Esto abre una puerta en la red local y se trata como tal:
  * Apagado por defecto: solo lo enciende el usuario y la interfaz lo apaga al cerrar la fiesta (y al cerrar la aplicación).
  * Escucha solo en UNA dirección IPv4 privada de la red local (192.168.x.x, 10.x.x.x, 172.16-31.x.x) o en la de bucle local
    (127.x, para las pruebas). Nunca en 0.0.0.0 ni en una pública: `start()` lanza ValueError con cualquier otra.
  * Token aleatorio de 32 caracteres (`secrets`) en la ruta: sin él, 403 (comparado en tiempo constante). Se enseña en la
    pantalla de la fiesta (y como QR si está instalada la biblioteca `qrcode`). Quien vea la pantalla puede votar: es la idea.
  * La cabecera Host tiene que ser la dirección del servidor (frena el «DNS rebinding» desde una web maliciosa).
  * Límite por IP: `RATE_MAX` peticiones cada `RATE_WINDOW_S` (si no, 429) y como mucho `MAX_GUESTS` invitados distintos
    (el resto, 503); como mucho `MAX_CONNECTIONS` conexiones a la vez (las demás se cierran sin atender) y `TIMEOUT_S` de
    espera por conexión (un cliente que no envía nada no retiene un hilo).
  * Tamaños acotados: línea de petición y cabeceras con los topes de `http.server` (64 KB, 100 cabeceras), cuerpo de como
    mucho `MAX_BODY` bytes (si no, 413). Solo GET y POST; los demás métodos, 501.
  * No sirve archivos del disco: solo una página fija escrita aquí. Nada de lo que envía el cliente se ejecuta ni se
    refleja en la página: el voto se compara con tres palabras fijas y lo demás se descarta.
  * Cabeceras: `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`,
    `X-Frame-Options: DENY` y una política de contenido que solo permite la propia página. Sin cookies. El nombre del servidor
    no dice la versión de Python. Las respuestas llevan lo mínimo (`{"ok": true}` o cuánto esperar).
  * El registro (`logging`) nunca escribe el token.

LIMITACIONES QUE HAY QUE CONTAR AL USUARIO (la pantalla de la fiesta las avisa):
  * Sin cifrado: es http en la wifi. Cualquiera en esa red que capture el tráfico ve el enlace (y podría votar). En una wifi
    de casa con contraseña es aceptable para votar canciones; en una wifi pública, no lo enciendas.
  * El cortafuegos de Windows preguntará la primera vez si deja que la aplicación (o python.exe) reciba conexiones: hay que
    permitirlo solo en redes PRIVADAS. Si se deniega, los móviles no llegan (no es un fallo de la aplicación).
  * Varios móviles detrás de la misma IP (un repetidor que hace NAT) cuentan como un solo invitado.
  * Quien tenga el enlace puede votar desde cualquier móvil de la wifi; el anti-spam limita, no autentica."""
import hmac
import ipaddress
import json
import logging
import math
import secrets
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

log = logging.getLogger(__name__)

LIKE, SKIP, ENERGY = "like", "skip", "energy"
KINDS = (LIKE, SKIP, ENERGY)
WINDOW_S = 60.0                 # los votos valen durante este tiempo
VOTE_COOLDOWN_S = 8.0           # cada invitado, un voto de cada tipo como mucho cada tanto
GUEST_TTL_S = 45.0              # sin señales de vida durante esto, el invitado deja de contar como conectado
SKIP_RATIO, SKIP_VOTES, MIN_VOTES = 0.30, 5, 2
ENERGY_RATIO, ENERGY_VOTES = 0.30, 5
RATE_WINDOW_S, RATE_MAX = 10.0, 20  # peticiones por IP
MAX_GUESTS = 256                # invitados distintos que se recuerdan (memoria acotada)
MAX_CONNECTIONS = 32            # conexiones atendidas a la vez
MAX_BODY = 256                  # bytes de cuerpo de un voto
TIMEOUT_S = 5.0                 # espera máxima por conexión
TOKEN_BYTES = 24                # 32 caracteres en base64 para URL


def is_allowed_host(host) -> bool:
    """¿Se puede escuchar en `host`? Solo una IPv4 concreta privada de la red local o de bucle local."""
    try:
        addr = ipaddress.ip_address(str(host))
    except ValueError:
        return False
    if addr.version != 4 or addr.is_unspecified or addr.is_multicast or addr.is_link_local or addr.is_reserved:
        return False
    if str(addr) == "255.255.255.255":
        return False
    return addr.is_loopback or addr.is_private


def local_ip():
    """La IPv4 privada de este equipo en la red local (la de la wifi), o None si no hay red local. No envía nada: un socket UDP
    «conectado» solo elige por qué interfaz saldría."""
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 1))
            ip = s.getsockname()[0]
        except OSError:
            continue
        finally:
            s.close()
        if is_allowed_host(ip) and not ipaddress.ip_address(ip).is_loopback:
            return ip
    return None


class VoteBox:
    """El recuento (ver la explicación del módulo). Seguro entre hilos. `on_signal(kind, counts)` se llama (fuera del candado)
    cuando un voto de «pasar» o «más energía» llega al umbral, y con cada «me gusta»."""

    def __init__(self, on_signal=None, clock=time.monotonic, window_s=WINDOW_S, cooldown_s=VOTE_COOLDOWN_S,
                 guest_ttl_s=GUEST_TTL_S, skip_ratio=SKIP_RATIO, skip_votes=SKIP_VOTES, energy_ratio=ENERGY_RATIO,
                 energy_votes=ENERGY_VOTES, min_votes=MIN_VOTES, max_guests=MAX_GUESTS):
        self._on_signal = on_signal
        self._clock = clock
        self.window_s, self.cooldown_s, self.guest_ttl_s = float(window_s), float(cooldown_s), float(guest_ttl_s)
        self.skip_ratio, self.skip_votes = float(skip_ratio), int(skip_votes)
        self.energy_ratio, self.energy_votes = float(energy_ratio), int(energy_votes)
        self.min_votes = max(1, int(min_votes))
        self.max_guests = int(max_guests)
        self._lock = threading.Lock()
        self._seen = {}                          # invitado -> último instante en que dio señales de vida
        self._last_vote = {}                     # (invitado, tipo) -> instante de su último voto
        self._votes = {k: deque() for k in KINDS}    # tipo -> [(instante, invitado)]
        self.totals = dict.fromkeys(KINDS, 0)    # votos aceptados desde el arranque (para el usuario)

    def _prune(self, now):
        for q in self._votes.values():
            while q and now - q[0][0] > self.window_s:
                q.popleft()
        if len(self._seen) > self.max_guests // 2:
            for guest in [g for g, t in self._seen.items() if now - t > self.guest_ttl_s]:
                del self._seen[guest]
        if len(self._last_vote) > self.max_guests * len(KINDS):
            for key in [k for k, t in self._last_vote.items() if now - t > self.cooldown_s]:
                del self._last_vote[key]

    def touch(self, guest) -> bool:
        """El invitado da señales de vida. False si ya hay demasiados invitados distintos y este es nuevo."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            if guest not in self._seen and len(self._seen) >= self.max_guests:
                return False
            self._seen[guest] = now
            return True

    def _connected(self, now) -> int:
        return sum(1 for t in self._seen.values() if now - t <= self.guest_ttl_s)

    def _voters(self, kind) -> int:
        return len({g for _t, g in self._votes[kind]})

    def needed(self, kind=SKIP, connected=None) -> int:
        with self._lock:
            now = self._clock()
            return self._needed(kind, self._connected(now) if connected is None else connected)

    def _needed(self, kind, connected) -> int:
        ratio, votes = (self.skip_ratio, self.skip_votes) if kind == SKIP else (self.energy_ratio, self.energy_votes)
        return max(self.min_votes, min(votes, math.ceil(ratio * max(0, connected))))

    def vote(self, guest, kind) -> float:
        """Apunta un voto. Devuelve 0 si se aceptó, o los segundos que le faltan a ese invitado para poder repetirlo.
        ValueError si `kind` no es uno de `KINDS` o el invitado no cabe (demasiados distintos)."""
        if kind not in KINDS:
            raise ValueError("voto desconocido")
        signal = None
        with self._lock:
            now = self._clock()
            self._prune(now)
            if guest not in self._seen and len(self._seen) >= self.max_guests:
                raise ValueError("demasiados invitados")
            self._seen[guest] = now
            last = self._last_vote.get((guest, kind))
            if last is not None and now - last < self.cooldown_s:
                return self.cooldown_s - (now - last)
            self._last_vote[(guest, kind)] = now
            self._votes[kind].append((now, guest))
            self.totals[kind] += 1
            if kind == LIKE or self._voters(kind) >= self._needed(kind, self._connected(now)):
                signal = (kind, self._counts_locked(now))
        if signal is not None and self._on_signal is not None:
            try:
                self._on_signal(*signal)
            except Exception:
                log.exception("fallo al avisar al DJ de un voto del público")
        return 0.0

    def reset(self, kind=None):
        """Olvida los votos de ese tipo (o de todos): el DJ ya lo aplicó, o cambió la canción."""
        with self._lock:
            for k in (KINDS if kind is None else (kind,)):
                self._votes[k].clear()
                for key in [key for key in self._last_vote if key[1] == k]:
                    del self._last_vote[key]

    def counts(self) -> dict:
        """{«connected», «like», «skip», «energy» (invitados distintos en la ventana), «skip_needed», «energy_needed», «totals»}."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            return self._counts_locked(now)

    def _counts_locked(self, now) -> dict:
        connected = self._connected(now)
        return {"connected": connected, LIKE: self._voters(LIKE), SKIP: self._voters(SKIP), ENERGY: self._voters(ENERGY),
                "skip_needed": self._needed(SKIP, connected), "energy_needed": self._needed(ENERGY, connected),
                "totals": dict(self.totals)}


class _RateLimiter:
    """Peticiones por IP en una ventana deslizante (memoria acotada a `max_ips`)."""

    def __init__(self, max_requests=RATE_MAX, window_s=RATE_WINDOW_S, clock=time.monotonic, max_ips=MAX_GUESTS * 4):
        self.max_requests, self.window_s, self._clock, self.max_ips = int(max_requests), float(window_s), clock, int(max_ips)
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, ip) -> bool:
        with self._lock:
            now = self._clock()
            hits = self._hits.get(ip)
            if hits is None:
                if len(self._hits) >= self.max_ips:
                    for key in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window_s]:
                        del self._hits[key]
                    if len(self._hits) >= self.max_ips:
                        return False
                hits = self._hits[ip] = deque()
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True


_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vota la música</title>
<style>
body{margin:0;background:#000;color:#fff;font-family:system-ui,sans-serif;text-align:center}
h1{font-size:26px;margin:22px 12px 6px}
p{color:#bbb;margin:4px 12px 18px;font-size:15px}
button{display:block;width:calc(100% - 32px);margin:14px 16px;padding:26px 8px;font-size:30px;font-weight:800;border:0;border-radius:18px;
background:#555555;color:#fff}
button.main{background:#F8C700;color:#000}
#msg{min-height:30px;font-size:20px;color:#F8C700;margin:10px}
</style></head><body>
<h1>¿Qué te parece lo que suena?</h1>
<p>Tu voto se cuenta junto al de los demás invitados.</p>
<button class="main" data-v="like">👍 Me gusta</button>
<button data-v="skip">⏭ Pasar</button>
<button data-v="energy">🔥 Más energía</button>
<div id="msg"></div>
<script>
var msg=document.getElementById("msg");
function say(t){msg.textContent=t;}
document.querySelectorAll("button").forEach(function(b){b.addEventListener("click",function(){
fetch("vote",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"v="+b.dataset.v,cache:"no-store"})
.then(function(r){return r.json();}).then(function(d){
say(d.ok?"¡Gracias! Voto contado.":(d.wait?"Espera "+Math.ceil(d.wait)+" s para repetir ese voto.":"No se pudo votar ahora."));})
.catch(function(){say("Sin conexión con el DJ.");});});});
function ping(){fetch("ping",{cache:"no-store"}).catch(function(){});}
setInterval(ping,15000);
</script></body></html>"""

_SECURITY_HEADERS = (("X-Content-Type-Options", "nosniff"), ("Cache-Control", "no-store"), ("Pragma", "no-cache"),
                     ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
                     ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                                 "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"))


class _Handler(BaseHTTPRequestHandler):
    server_version = "fiesta"
    sys_version = ""
    protocol_version = "HTTP/1.0"           # una petición por conexión: nada de conexiones abiertas a la espera
    timeout = TIMEOUT_S

    def version_string(self):
        return self.server_version

    def log_message(self, fmt, *args):      # nunca con la ruta (lleva el token)
        log.debug("público %s: %s", self.client_address[0], getattr(self, "command", "?"))

    def log_request(self, code="-", size="-"):
        log.debug("público %s %s -> %s", self.client_address[0], getattr(self, "command", "?"), code)

    def send_error(self, code, message=None, explain=None):
        """Las respuestas de error de `http.server` también salen sin detalles y con las cabeceras seguras."""
        try:
            self._send(code, {"ok": False})
        except OSError:
            pass

    def _send(self, code, payload, content_type="application/json; charset=utf-8"):
        body = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        for name, value in _SECURITY_HEADERS:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _route(self):
        """La parte de la ruta tras el token ("", "vote", "ping"), o None si la petición no vale (y ya se respondió)."""
        srv = self.server.owner
        ip = self.client_address[0]
        if not srv.limiter.allow(ip):
            self._send(429, {"ok": False})
            return None
        if self.headers.get("Host", "") not in srv.hosts:
            self._send(400, {"ok": False})
            return None
        path = self.path.split("?", 1)[0]
        parts = path.split("/")
        if len(parts) < 3 or parts[0] != "" or not hmac.compare_digest(parts[1].encode("utf-8", "replace"), srv.token.encode()):
            self._send(403, {"ok": False})
            return None
        rest = "/".join(parts[2:])
        if not srv.box.touch(ip):
            self._send(503, {"ok": False})
            return None
        return rest

    def do_GET(self):
        rest = self._route()
        if rest is None:
            return
        if rest == "":
            self._send(200, _PAGE, "text/html; charset=utf-8")
        elif rest == "ping":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"ok": False})

    def do_POST(self):
        rest = self._route()
        if rest is None:
            return
        if rest != "vote":
            self._send(404, {"ok": False})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send(411, {"ok": False})
            return
        if length < 0 or length > MAX_BODY:
            self._send(413, {"ok": False})
            return
        raw = self.rfile.read(length)
        try:
            kind = parse_qs(raw.decode("ascii"), max_num_fields=4).get("v", [""])[0]
        except (UnicodeDecodeError, ValueError):
            kind = ""
        if kind not in KINDS:
            self._send(400, {"ok": False})
            return
        try:
            wait = self.server.owner.box.vote(self.client_address[0], kind)
        except ValueError:
            self._send(503, {"ok": False})
            return
        if wait > 0:
            self._send(429, {"ok": False, "wait": round(wait, 1)})
        else:
            self._send(200, {"ok": True})


class _Server(ThreadingHTTPServer):
    daemon_threads = False                  # se esperan al cerrar (cada una dura como mucho TIMEOUT_S, y se les cierra el socket)
    block_on_close = True
    allow_reuse_address = False             # en Windows dejaría a otro programa robar el puerto
    request_queue_size = 16

    def __init__(self, addr, owner):
        self.owner = owner
        self._slots = threading.BoundedSemaphore(owner.max_connections)
        self._open = set()
        self._open_lock = threading.Lock()
        super().__init__(addr, _Handler)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):          # Windows: nadie más puede escuchar en el mismo puerto
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):     # demasiadas a la vez: se cierra sin atender
            self.shutdown_request(request)
            return
        with self._open_lock:
            self._open.add(request)
        try:
            super().process_request(request, client_address)
        except Exception:
            self._forget(request)
            self._slots.release()
            self.shutdown_request(request)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._forget(request)
            self._slots.release()

    def shutdown_request(self, request):
        """Cierre «con espera»: primero se avisa de que ya no se envía nada más y se tira lo que el cliente aún mandaba (como
        mucho 64 KB y 1 s). Si se cerrara con datos sin leer (un cuerpo que se rechazó sin leerlo), Windows corta la conexión
        y el móvil no llega a ver la respuesta."""
        try:
            request.shutdown(socket.SHUT_WR)
            deadline = time.monotonic() + 1.0
            drained = 0
            while drained < 65536 and time.monotonic() < deadline:
                request.settimeout(max(0.05, deadline - time.monotonic()))
                chunk = request.recv(8192)
                if not chunk:
                    break
                drained += len(chunk)
        except OSError:
            pass
        self.close_request(request)

    def handle_error(self, request, client_address):
        log.debug("público: petición fallida de %s", client_address[0] if client_address else "?")

    def _forget(self, request):
        with self._open_lock:
            self._open.discard(request)

    def close_open(self):
        """Corta las conexiones que siguen abiertas (para que sus hilos acaben ya al cerrar)."""
        with self._open_lock:
            sockets = list(self._open)
        for s in sockets:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class CrowdServer:
    """El servidor de votos. `host`: la IP en la que escuchar (ver `is_allowed_host`; por defecto, `local_ip()`); `port`: 0 =
    uno libre. `on_signal(kind, counts)`: ver `VoteBox` (se llama en un hilo del servidor). `**box_kw`: umbrales de `VoteBox`."""

    def __init__(self, host=None, port=0, on_signal=None, token=None, rate_max=RATE_MAX, rate_window_s=RATE_WINDOW_S,
                 max_connections=MAX_CONNECTIONS, clock=time.monotonic, **box_kw):
        self.host = host
        self.port = int(port)
        self.token = token or secrets.token_urlsafe(TOKEN_BYTES)
        self.max_connections = int(max_connections)
        self.box = VoteBox(on_signal, clock=clock, **box_kw)
        self.limiter = _RateLimiter(rate_max, rate_window_s, clock)
        self.hosts = set()
        self._server = None
        self._thread = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/{self.token}/" if self.running else ""

    def start(self):
        """Empieza a escuchar. ValueError si la dirección no es una privada concreta; OSError si no se puede abrir el puerto.
        Si ya estaba en marcha, no hace nada."""
        if self._server is not None:
            return
        host = self.host or local_ip()
        if not host or not is_allowed_host(host):
            raise ValueError("solo se puede escuchar en una dirección privada de la red local (no hay red local o no es privada)")
        server = _Server((host, self.port), self)
        self.host, self.port = server.server_address[0], server.server_address[1]
        self.hosts = {f"{self.host}:{self.port}"}
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, name="crowd-server",
                                        daemon=True)
        self._thread.start()
        log.info("votos del público: escuchando en %s:%s", self.host, self.port)

    def stop(self):
        """Deja de escuchar, corta las conexiones abiertas y espera a sus hilos. Se puede llamar aunque no esté en marcha."""
        server, thread = self._server, self._thread
        self._server = self._thread = None
        if server is None:
            return
        try:
            server.shutdown()
        finally:
            server.close_open()
            server.server_close()               # espera a los hilos de las peticiones (ya sin socket, acaban enseguida)
            if thread is not None:
                thread.join(timeout=2.0)
        log.info("votos del público: apagado")

    def counts(self) -> dict:
        return self.box.counts()

    def reset(self, kind=None):
        self.box.reset(kind)
