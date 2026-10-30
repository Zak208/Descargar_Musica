"""Votos del público (fase 31): el servidor HTTP de `services/crowd_server.py`, sin ventana. Arranque y parada, solo escucha en la
IP pedida (y se niega a 0.0.0.0 o a una pública), token incorrecto = 403, cabecera Host falsa, límite de peticiones por IP,
un voto de cada tipo por invitado cada pocos segundos, conteo y umbral de «Pasar» y «Más energía» con invitados distintos,
peticiones enormes o malformadas que no lo tumban, un cliente que no envía nada, muchos clientes a la vez y cierre limpio
sin hilos colgados. Los invitados distintos se simulan con direcciones de bucle local distintas (127.0.0.2, 127.0.0.3...).
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_publico.py"""
import http.client
import json
import os
import socket
import sys
import threading
import time

import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from services import crowd_server  # noqa: E402
from services.crowd_server import ENERGY, LIKE, SKIP, CrowdServer, VoteBox  # noqa: E402


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def request(srv, method, path, body=None, source="127.0.0.1", host=None, headers=None):
    """(código, cabeceras, cuerpo) de una petición al servidor desde la dirección `source`."""
    con = http.client.HTTPConnection(srv.host, srv.port, timeout=5, source_address=(source, 0))
    try:
        hdrs = {"Host": host or f"{srv.host}:{srv.port}"}
        if body is not None:
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        hdrs.update(headers or {})
        con.request(method, path, body=body, headers=hdrs)
        r = con.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        con.close()


def vote(srv, kind, source="127.0.0.1"):
    return request(srv, "POST", f"/{srv.token}/vote", f"v={kind}", source=source)


def raw(srv, data: bytes, read=True, timeout=8.0):
    """Envía bytes tal cual y devuelve lo que conteste (o b"" si cierra)."""
    s = socket.create_connection((srv.host, srv.port), timeout=timeout)
    try:
        try:
            s.sendall(data)
        except OSError:
            return b""
        if not read:
            return b""
        out = b""
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                out += chunk
        except OSError:
            pass
        return out
    finally:
        s.close()


# ---- 1. qué direcciones se admiten -----------------------------------------------------------------------------------------
check("127.0.0.1 y las privadas se admiten", all(crowd_server.is_allowed_host(h) for h in ("127.0.0.1", "192.168.1.20", "10.0.0.5",
                                                                                          "172.16.3.4")))
check("0.0.0.0, públicas, multidifusión, enlace local, IPv6 y nombres NO", not any(crowd_server.is_allowed_host(h) for h in (
    "0.0.0.0", "", "8.8.8.8", "224.0.0.1", "169.254.1.1", "255.255.255.255", "::1", "::", "localhost", "192.168.1.300")))
for bad in ("0.0.0.0", "8.8.8.8", "::"):
    try:
        CrowdServer(host=bad).start()
        check(f"start() en {bad!r} se niega", False)
    except ValueError:
        check(f"start() en {bad!r} se niega (ValueError)", True)
lan = crowd_server.local_ip()
check(f"la IP de la red local es privada o no hay ({lan})", lan is None or (crowd_server.is_allowed_host(lan) and not lan.startswith("127.")))

# ---- 2. el recuento sin red (reloj falso, muchos invitados) -------------------------------------------------------------------
now = [1000.0]
signals = []
box = VoteBox(lambda kind, counts: signals.append((kind, counts["skip"])), clock=lambda: now[0])
check("con 3 conectados hacen falta 2 «pasar» (nunca menos de 2)", [box.touch(f"g{i}") for i in range(3)] and box.needed(SKIP) == 2)
for i in range(3, 20):
    box.touch(f"g{i}")
check("con 20 conectados hacen falta 5 (el 30 % serían 6: vale el tope de 5)", box.needed(SKIP) == 5)
for i in range(4):
    box.vote(f"g{i}", SKIP)
check("4 invitados distintos no llegan al umbral de 5: sin aviso", not signals and box.counts()[SKIP] == 4)
check("el mismo invitado no puede repetir el voto enseguida (espera)", box.vote("g0", SKIP) > 0 and box.counts()[SKIP] == 4)
box.vote("g4", SKIP)
check("el quinto invitado distinto llega al umbral: avisa", signals and signals[-1] == (SKIP, 5))
now[0] += crowd_server.VOTE_COOLDOWN_S + 0.1
box.vote("g0", SKIP)
check("pasado el tiempo de espera puede volver a votar, pero sigue contando como un invitado", box.counts()[SKIP] == 5)
box.reset(SKIP)
check("reset() olvida los «pasar» (el DJ ya saltó)", box.counts()[SKIP] == 0)
now[0] += crowd_server.WINDOW_S + 1
check("pasada la ventana de 60 s los invitados que no dan señales dejan de contar", box.counts()["connected"] == 0)
box.vote("solo", LIKE)
check("«me gusta» siempre avisa (para guardar el voto de la mezcla)", signals[-1][0] == LIKE)
try:
    box.vote("x", "rm -rf")
    check("un voto desconocido se rechaza", False)
except ValueError:
    check("un voto desconocido se rechaza", True)
small = VoteBox(clock=lambda: now[0], max_guests=4)
check("memoria acotada: un invitado de más no cabe", all(small.touch(f"h{i}") for i in range(4)) and not small.touch("h99"))

# ---- 3. el servidor de verdad en 127.0.0.1 --------------------------------------------------------------------------------------
threads_before = {t.ident for t in threading.enumerate()}
got = []
srv = CrowdServer(host="127.0.0.1", on_signal=lambda kind, counts: got.append((kind, dict(counts))), rate_max=1000)
srv.start()
check(f"arranca en 127.0.0.1 con un puerto libre ({srv.port})", srv.running and srv.port > 0 and srv.url.startswith("http://127.0.0.1:"))
check("el token es largo y aleatorio (32 caracteres)", len(srv.token) >= 32 and srv.token != CrowdServer(host="127.0.0.1").token)
code, headers, body = request(srv, "GET", f"/{srv.token}/")
check("con el token, la página del móvil (200, html)", code == 200 and b"Me gusta" in body and "text/html" in headers.get("Content-Type", ""))
check("cabeceras seguras: nosniff, no-store, sin cookies, sin versión de Python",
      headers.get("X-Content-Type-Options") == "nosniff" and "no-store" in headers.get("Cache-Control", "")
      and "Set-Cookie" not in headers and "Python" not in headers.get("Server", "")
      and "frame-ancestors 'none'" in headers.get("Content-Security-Policy", ""))
check("token incorrecto = 403", request(srv, "GET", "/" + "x" * 32 + "/")[0] == 403)
check("sin token = 403", request(srv, "GET", "/")[0] == 403)
check("token casi igual (una letra cambiada) = 403", request(srv, "GET", "/" + srv.token[:-1] + ("A" if srv.token[-1] != "A" else "B") + "/")[0] == 403)
check("cabecera Host falsa (DNS rebinding) = 400", request(srv, "GET", f"/{srv.token}/", host="malo.example:80")[0] == 400)
check("no sirve archivos del disco: ../ y rutas raras = 404", request(srv, "GET", f"/{srv.token}/../../config.py")[0] == 404
      and request(srv, "GET", f"/{srv.token}/C:/Windows/win.ini")[0] == 404)
check("métodos que no son GET ni POST = 501", request(srv, "DELETE", f"/{srv.token}/")[0] == 501
      and request(srv, "PUT", f"/{srv.token}/vote", "v=like")[0] == 501)
code, _h, body = vote(srv, LIKE)
check("votar «me gusta» = 200 con datos mínimos", code == 200 and json.loads(body) == {"ok": True})
code, _h, body = vote(srv, LIKE)
check("repetirlo enseguida = 429 con los segundos que faltan", code == 429 and json.loads(body).get("wait", 0) > 0)
check("un voto inventado = 400 y no se cuenta", vote(srv, "borrar")[0] == 400 and srv.counts()[LIKE] == 1)
check("cuerpo demasiado grande = 413", request(srv, "POST", f"/{srv.token}/vote", "v=like&" + "a" * 5000)[0] == 413)
check("sin Content-Length = 411", raw(srv, f"POST /{srv.token}/vote HTTP/1.0\r\nHost: {srv.host}:{srv.port}\r\n\r\n".encode()).split(b" ")[1:2] == [b"411"])

# Umbral de «pasar» con invitados distintos (direcciones 127.0.0.x distintas)
multi = True
try:                                                       # en algunos Windows solo 127.0.0.1 sirve como origen
    socket.create_connection((srv.host, srv.port), timeout=1.5, source_address=("127.0.0.2", 0)).close()
except OSError:
    multi = False
if multi:
    for i in range(2, 6):                                  # 4 invitados conectados + el 127.0.0.1 = 5: hacen falta 2
        request(srv, "GET", f"/{srv.token}/ping", source=f"127.0.0.{i}")
    check(f"5 conectados: hacen falta {srv.counts()['skip_needed']} «pasar»", srv.counts()["skip_needed"] == 2)
    vote(srv, SKIP, source="127.0.0.2")
    check("un solo «pasar» no avisa", not any(k == SKIP for k, _c in got))
    vote(srv, SKIP, source="127.0.0.2")
    check("el mismo invitado otra vez tampoco (sigue siendo uno)", not any(k == SKIP for k, _c in got))
    vote(srv, SKIP, source="127.0.0.3")
    check("el segundo invitado distinto llega al umbral: avisa al DJ", any(k == SKIP and c[SKIP] == 2 for k, c in got))
    vote(srv, ENERGY, source="127.0.0.4")
    vote(srv, ENERGY, source="127.0.0.5")
    check("dos «más energía» de invitados distintos también avisan", any(k == ENERGY for k, _c in got))
else:
    check("este equipo no deja usar 127.0.0.2 como origen: el umbral se prueba solo sin red (arriba)", True)

# Solo escucha en la IP pedida
other = "127.0.0.2"
try:
    socket.create_connection((other, srv.port), timeout=1).close()
    check(f"no escucha en {other} (solo en 127.0.0.1)", False)
except OSError:
    check(f"no escucha en {other} (solo en 127.0.0.1)", True)
if lan:
    try:
        socket.create_connection((lan, srv.port), timeout=1).close()
        check(f"no escucha en la IP de la red local {lan} (solo en la pedida)", False)
    except OSError:
        check(f"no escucha en la IP de la red local {lan} (solo en la pedida)", True)

# Peticiones malformadas o enormes
t0 = time.monotonic()
answers = [
    raw(srv, b"GET /" + b"a" * 70000 + b" HTTP/1.0\r\n\r\n"),                                 # línea de petición enorme
    raw(srv, b"\x00\xff\xfe garbage \r\n\r\n"),                                               # basura binaria
    raw(srv, b"GET / HTTP/1.0\r\n" + b"X-A: b\r\n" * 150 + b"\r\n"),                          # demasiadas cabeceras
    raw(srv, f"POST /{srv.token}/vote HTTP/1.0\r\nHost: {srv.host}:{srv.port}\r\nContent-Length: 999999999\r\n\r\n".encode()),
    raw(srv, f"POST /{srv.token}/vote HTTP/1.0\r\nHost: {srv.host}:{srv.port}\r\nContent-Length: -5\r\n\r\n".encode()),
    raw(srv, f"POST /{srv.token}/vote HTTP/1.0\r\nHost: {srv.host}:{srv.port}\r\nContent-Length: 4\r\n\r\nv=\xff".encode("latin-1")),
    raw(srv, b"GET /%00%2e%2e/" + srv.token.encode() + b"/ HTTP/1.0\r\n\r\n"),
]
check("ninguna petición malformada tumba el servidor (todas reciben respuesta o cierre)", all(isinstance(a, bytes) for a in answers))
check("la línea enorme se rechaza (414) y la basura con un error (sin cabeceras: no es HTTP)", b" 414 " in answers[0][:20]
      and answers[1] == b'{"ok": false}')
check("demasiadas cabeceras: error (431)", b" 431 " in answers[2][:20])
check("Content-Length enorme o negativo: 413 sin esperar el cuerpo", b" 413 " in answers[3][:20] and b" 413 " in answers[4][:20])
check("sigue atendiendo después", request(srv, "GET", f"/{srv.token}/ping")[0] == 200)
slow = socket.create_connection((srv.host, srv.port), timeout=10)        # un cliente que no envía nada
t_slow = time.monotonic()
try:
    left = slow.recv(100)
except OSError:
    left = b""
slow.close()
waited = time.monotonic() - t_slow
check(f"un cliente que no envía nada se corta solo a los {waited:.1f} s (máximo {crowd_server.TIMEOUT_S:.0f} s)",
      waited <= crowd_server.TIMEOUT_S + 2)

# Muchos clientes a la vez
results = []
lock = threading.Lock()


def client(n):
    ok = 0
    for _ in range(5):
        try:
            if request(srv, "GET", f"/{srv.token}/ping")[0] == 200:
                ok += 1
        except OSError:
            pass
    with lock:
        results.append(ok)


t0 = time.monotonic()
workers = [threading.Thread(target=client, args=(i,)) for i in range(60)]
for t in workers:
    t.start()
for t in workers:
    t.join(30)
total_ok = sum(results)
elapsed = time.monotonic() - t0
check(f"60 clientes a la vez × 5 peticiones: {total_ok} de 300 atendidas en {elapsed:.1f} s (el resto se corta por el tope de "
      f"{crowd_server.MAX_CONNECTIONS} conexiones)", total_ok >= 150 and len(results) == 60)
check("y sigue atendiendo después", request(srv, "GET", f"/{srv.token}/ping")[0] == 200)
srv.stop()

# Límite de peticiones por IP (servidor con su límite normal)
srv2 = CrowdServer(host="127.0.0.1")
srv2.start()
codes = [request(srv2, "GET", f"/{srv2.token}/ping")[0] for _ in range(crowd_server.RATE_MAX + 10)]
check(f"límite por IP: de {len(codes)} peticiones seguidas, {codes.count(200)} atendidas y {codes.count(429)} con 429",
      codes.count(200) == crowd_server.RATE_MAX and codes.count(429) == 10)
check("también cuentan las de token incorrecto (no se puede adivinar a fuerza de intentos)", request(srv2, "GET", "/nada/")[0] == 429)
if multi:
    check("otra IP no se ve afectada", request(srv2, "GET", f"/{srv2.token}/ping", source="127.0.0.9")[0] == 200)
url = srv2.url
port = srv2.port
srv2.stop()
check("al parar ya no escucha", not srv2.running and srv2.url == "")
try:
    socket.create_connection(("127.0.0.1", port), timeout=1).close()
    check("el puerto queda cerrado", False)
except OSError:
    check("el puerto queda cerrado", True)
srv2.stop()                                         # parar dos veces no falla
check("parar dos veces no falla", True)
time.sleep(0.3)
left = [t for t in threading.enumerate() if t.ident not in threads_before and t.is_alive()]
check(f"cierre limpio: sin hilos colgados ({[t.name for t in left]})", not left)
print("FIN")
