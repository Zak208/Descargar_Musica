"""Carga de imágenes (portadas y fotos) con un único grupo de hilos y caché en memoria y en disco.

Antes cada portada abría su propio hilo y se volvía a descargar cada vez. Ahora:
  * como mucho 3 imágenes se procesan a la vez,
  * las ya vistas salen de una caché en memoria (límite de entradas) o del disco (límite de tamaño).
"""
import hashlib
import threading
from collections import OrderedDict

from services import http
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, QTimer, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QPainterPath

from config import APP_DATA_DIR
from ui.perf import image_scale, eco

CACHE_DIR = APP_DATA_DIR / "img_cache"
DISK_LIMIT_MB = 60
MEMORY_ENTRIES = 90
MEMORY_BYTES_ECO = 20 * 1024 * 1024       # tope de memoria para imágenes ya vistas (modo ahorro)
MEMORY_BYTES = 48 * 1024 * 1024
_memory_bytes = 0

_pool = QThreadPool()
_pool.setMaxThreadCount(3)

_memory: "OrderedDict[tuple, QPixmap]" = OrderedDict()
_lock = threading.Lock()


def _memory_get(key):
    pix = _memory.get(key)
    if pix is not None:
        _memory.move_to_end(key)
    return pix


def _pix_bytes(pix) -> int:
    return pix.width() * pix.height() * 4


def _memory_put(key, pix):
    """Guarda la imagen en memoria; se descartan las más antiguas al pasar de cierto número o de cierto peso."""
    global _memory_bytes
    old = _memory.pop(key, None)
    if old is not None:
        _memory_bytes -= _pix_bytes(old)
    _memory[key] = pix
    _memory_bytes += _pix_bytes(pix)
    budget = MEMORY_BYTES_ECO if eco() else MEMORY_BYTES
    while _memory and (len(_memory) > MEMORY_ENTRIES or _memory_bytes > budget):
        _k, dropped = _memory.popitem(last=False)
        _memory_bytes -= _pix_bytes(dropped)


def clear_memory_cache():
    global _memory_bytes
    with _lock:
        _memory.clear()
        _memory_bytes = 0


def prune_disk_cache():
    """Borra las imágenes más antiguas si la caché de disco supera su límite."""
    try:
        if not CACHE_DIR.exists():
            return
        files = [(f.stat().st_mtime, f.stat().st_size, f) for f in CACHE_DIR.iterdir() if f.is_file()]
        total = sum(s for _, s, _ in files)
        limit = DISK_LIMIT_MB * 1024 * 1024
        for _mtime, size, f in sorted(files, key=lambda x: x[0]):
            if total <= limit:
                break
            try:
                f.unlink()
                total -= size
            except OSError:
                pass
    except Exception:
        pass


def _shape(image: QImage, w: int, h: int, scale: int, circular: bool, radius: int) -> QImage:
    """Recorta al centro, escala y redondea la imagen (se hace en el hilo de trabajo)."""
    pw, ph = w * scale, h * scale
    scaled = image.scaled(pw, ph, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    scaled = scaled.copy((scaled.width() - pw) // 2, (scaled.height() - ph) // 2, pw, ph)
    out = QImage(pw, ph, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    if circular:
        path.addEllipse(QRectF(0, 0, pw, ph))
    else:
        path.addRoundedRect(QRectF(0, 0, pw, ph), radius * scale, radius * scale)
    p.setClipPath(path)
    p.drawImage(0, 0, scaled)
    p.end()
    out.setDevicePixelRatio(scale)
    return out


class _Signals(QObject):
    done = Signal(object)


class _Task(QRunnable):
    def __init__(self, source: str, kind: str, w: int, h: int, scale: int, circular: bool, radius: int, signals):
        super().__init__()
        self.source, self.kind = source, kind
        self.w, self.h, self.scale, self.circular, self.radius = w, h, scale, circular, radius
        self.signals = signals

    def _load_bytes(self) -> bytes | None:
        if self.kind == "file":
            from services.metadata_service import MetadataService
            return MetadataService.read_metadata(self.source).get("cover_data")
        name = hashlib.md5(self.source.encode("utf-8")).hexdigest()
        cached = CACHE_DIR / name
        try:
            if cached.exists():
                cached.touch()
                return cached.read_bytes()
        except OSError:
            pass
        from services import network_service
        if not network_service.is_online():
            return None          # sin conexión no se espera a que caduque cada petición: las imágenes ya vistas salen de la caché
        r = http.get(self.source, timeout=7)
        if r.status_code != 200:
            return None
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(r.content)
        except OSError:
            pass
        return r.content

    def run(self):
        result = None
        try:
            data = self._load_bytes()
            if data:
                img = QImage()
                if img.loadFromData(data):
                    result = _shape(img, self.w, self.h, self.scale, self.circular, self.radius)
        except Exception:
            result = None
        try:
            self.signals.done.emit(result)
        except RuntimeError:
            pass          # la tarjeta que pidió la imagen ya se cerró: no hace falta avisar a nadie


class _BaseLoader(QObject):
    """Pide una imagen y avisa con `image_loaded(QPixmap)` cuando esté lista."""
    image_loaded = Signal(QPixmap)
    kind = "url"

    def __init__(self, source: str, is_circular: bool = False, size: tuple = (120, 120), radius: int = 8):
        super().__init__()
        self.source = source
        self.is_circular = is_circular
        self.size = size
        self.radius = radius
        self.is_cancelled = False
        self._signals = None

    def start(self):
        if not self.source or self.is_cancelled:
            return
        scale = image_scale()
        w, h = self.size
        key = (self.source, w, h, scale, self.is_circular, self.radius)
        with _lock:
            cached = _memory_get(key)
        if cached is not None:
            QTimer.singleShot(0, lambda p=cached: self._emit(p))
            return
        self._signals = _Signals()
        self._signals.done.connect(lambda img, k=key: self._on_done(img, k))
        _pool.start(_Task(self.source, self.kind, w, h, scale, self.is_circular, self.radius, self._signals))

    def _on_done(self, image, key):
        if image is None:
            return
        pix = QPixmap.fromImage(image)
        with _lock:
            _memory_put(key, pix)
        self._emit(pix)

    def _emit(self, pix: QPixmap):
        if not self.is_cancelled:
            try:
                self.image_loaded.emit(pix)
            except RuntimeError:
                pass


class ImageLoaderThread(_BaseLoader):
    """Imagen desde internet (con caché en memoria y disco)."""
    kind = "url"


class LocalCoverLoader(_BaseLoader):
    """Carátula incrustada en un archivo de audio."""
    kind = "file"


def shutdown():
    """Al cerrar: cancela lo pendiente y espera a que terminen los hilos de imágenes."""
    _pool.clear()
    _pool.waitForDone(1500)
