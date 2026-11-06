"""Servicio de presencia enriquecida para Discord (Discord Rich Presence / RPC).
Conecta directamente a través de las tuberías locales de Windows (\\.\\pipe\\discord-ipc-0 a 9)
o notifica a Vencord CustomRPC de forma no bloqueante y en segundo plano.
"""
import json
import logging
import os
import struct
import sys
import threading
import time
import uuid

from config import get_discord_rpc_enabled, get_discord_client_id

logger = logging.getLogger(__name__)

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4


class DiscordRPCService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._pipe = None
        self._connected = False
        self._running = False
        self._thread = None
        self._queue = []
        self._cond = threading.Condition()
        self._current_activity = None
        self._client_id = get_discord_client_id()
        self._last_connect_try = 0

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = DiscordRPCService()
            return cls._instance

    def start(self):
        if not get_discord_rpc_enabled():
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DiscordRPCThread")
        self._thread.start()

    def stop(self):
        self._running = False
        with self._cond:
            self._cond.notify_all()
        self._disconnect()

    def update_presence(self, info: dict, position_s: int = 0, is_playing: bool = True):
        if not get_discord_rpc_enabled() or not info:
            self.clear_presence()
            return
        if not self._running:
            self.start()

        with self._cond:
            self._queue = [(info, position_s, is_playing)]
            self._cond.notify_all()

    def clear_presence(self):
        with self._cond:
            self._queue = [None]
            self._cond.notify_all()

    # ------------------------------------------------------------- conexión IPC
    def _find_pipe(self):
        for i in range(10):
            pipe_path = f"\\\\.\\pipe\\discord-ipc-{i}" if sys.platform == "win32" else f"/tmp/discord-ipc-{i}"
            if os.path.exists(pipe_path):
                return pipe_path
        return None

    def _connect(self):
        now = time.time()
        if now - self._last_connect_try < 4.0:
            return False
        self._last_connect_try = now
        pipe_path = self._find_pipe()
        if not pipe_path:
            return False
        try:
            self._client_id = get_discord_client_id()
            if sys.platform == "win32":
                self._pipe = open(pipe_path, "r+b", buffering=0)  # noqa: SIM115
            else:
                import socket
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(pipe_path)
                self._pipe = s

            # Enviar apretón de manos (Handshake)
            payload = json.dumps({"v": 1, "client_id": self._client_id}).encode("utf-8")
            self._send_frame(OP_HANDSHAKE, payload)

            op, resp = self._read_frame()
            if op == OP_FRAME and resp.get("cmd") == "DISPATCH" and resp.get("evt") == "READY":
                self._connected = True
                logger.info("Discord Rich Presence conectado correctamente.")
                return True
            else:
                self._disconnect()
                return False
        except Exception:
            self._disconnect()
            return False

    def _disconnect(self):
        self._connected = False
        if self._pipe:
            try:
                self._pipe.close()
            except Exception:
                pass
            self._pipe = None

    def _send_frame(self, opcode: int, data_bytes: bytes):
        if not self._pipe:
            return
        header = struct.pack("<II", opcode, len(data_bytes))
        if hasattr(self._pipe, "write"):
            self._pipe.write(header + data_bytes)
        else:
            self._pipe.sendall(header + data_bytes)

    def _read_frame(self):
        if not self._pipe:
            return None, {}
        try:
            if hasattr(self._pipe, "read"):
                header = self._pipe.read(8)
            else:
                header = self._pipe.recv(8)
            if len(header) < 8:
                return None, {}
            op, length = struct.unpack("<II", header)
            if hasattr(self._pipe, "read"):
                data = self._pipe.read(length)
            else:
                data = self._pipe.recv(length)
            return op, json.loads(data.decode("utf-8"))
        except Exception:
            return None, {}

    # ----------------------------------------------------------- bucle de envío
    def _run_loop(self):
        while self._running:
            item = None
            with self._cond:
                while self._running and not self._queue:
                    self._cond.wait(timeout=2.0)
                if not self._running:
                    break
                if self._queue:
                    item = self._queue.pop(0)

            if not get_discord_rpc_enabled():
                self._send_clear()
                continue

            if item is None:
                self._send_clear()
            else:
                info, position_s, is_playing = item
                self._send_activity(info, position_s, is_playing)

    def _send_clear(self):
        if not self._connected:
            return
        try:
            msg = {
                "cmd": "SET_ACTIVITY",
                "args": {
                    "pid": os.getpid(),
                    "activity": None
                },
                "nonce": str(uuid.uuid4())
            }
            self._send_frame(OP_FRAME, json.dumps(msg).encode("utf-8"))
        except Exception:
            self._disconnect()

    def _send_activity(self, info: dict, position_s: int, is_playing: bool):
        if not self._connected:
            if not self._connect():
                # Si Discord nativo no está disponible, intentar enviar a Vencord CustomRPC local
                self._send_vencord_customrpc(info, position_s, is_playing)
                return

        title = str(info.get("title") or "Música").strip()[:128]
        artist = str(info.get("uploader") or info.get("artist") or "Artista").strip()[:128]
        album = str(info.get("album") or "Descargador de Música").strip()[:128]
        duration_s = int(info.get("duration_secs", 0) or 0)
        thumb = info.get("thumbnail") or ""
        cover_image = thumb if (thumb.startswith("http://") or thumb.startswith("https://")) else "music_icon"

        activity = {
            "type": 2,  # Listening
            "details": title,
            "state": f"por {artist}",
            "assets": {
                "large_image": cover_image,
                "large_text": album,
                "small_image": "play" if is_playing else "pause",
                "small_text": "Reproduciendo" if is_playing else "En pausa"
            }
        }

        if is_playing:
            now = int(time.time())
            start_ts = now - max(0, int(position_s))
            timestamps = {"start": start_ts}
            if duration_s > 0:
                timestamps["end"] = start_ts + duration_s
            activity["timestamps"] = timestamps

        url = info.get("webpage_url") or info.get("url")
        if url and isinstance(url, str) and url.startswith("http"):
            activity["buttons"] = [{"label": "Escuchar en YouTube", "url": url[:512]}]

        msg = {
            "cmd": "SET_ACTIVITY",
            "args": {
                "pid": os.getpid(),
                "activity": activity
            },
            "nonce": str(uuid.uuid4())
        }
        try:
            self._send_frame(OP_FRAME, json.dumps(msg).encode("utf-8"))
        except Exception:
            self._disconnect()

    def _send_vencord_customrpc(self, info: dict, position_s: int, is_playing: bool):
        """Soporte complementario para el plugin OpenRPC / CustomRPC de Vencord."""
        try:
            from services import http
            vencord_payload = {
                "details": str(info.get("title") or "Música"),
                "state": str(info.get("uploader") or info.get("artist") or "Artista"),
                "largeImageKey": info.get("thumbnail") or "",
                "largeImageText": str(info.get("album") or "Descargador de Música"),
                "smallImageKey": "play" if is_playing else "pause"
            }
            # Probar puertos comunes de CustomRPC en Vencord
            for port in (1337, 3020):
                try:
                    http.post(f"http://127.0.0.1:{port}/setActivity", json=vencord_payload, timeout=0.3)
                    break
                except Exception:
                    pass
        except Exception:
            pass
