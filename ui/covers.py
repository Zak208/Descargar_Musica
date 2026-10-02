"""Portadas de las listas: degradado con icono, o la imagen que haya elegido el usuario (playlists)."""
import os

import requests
from services import http
from PySide6.QtCore import Qt, QThread, Signal, QRectF
from PySide6.QtGui import QPixmap, QPainter, QLinearGradient, QColor, QPainterPath, QImage, QFont

from config import COVERS_DIR
from services.playlist_service import PlaylistService
from ui.icons import icon
from ui.styles import accent

TILE_COLORS = {
    "favorites": ("#5B2BE0", "#C73E8E"),
    "playlist": ("#2B5BE0", "#3EC7C7"),
}
MIX_COLORS = [
    ("#E8115B", "#8D67AB"), ("#1E3264", "#4F8EF7"), ("#148A08", "#B6F23C"),
    ("#BA5D07", "#F5C542"), ("#7358FF", "#E13300"), ("#0D73EC", "#19D3C5"),
    ("#8D1F7A", "#F065C3"), ("#0F6B5C", "#7BE0B3"),
]
GENRE_COLORS = ["#E8115B", "#1E3264", "#148A08", "#BA5D07", "#7358FF", "#0D73EC", "#8D67AB", "#B02897",
                "#E13300", "#477D95", "#503750", "#608108", "#A56752", "#2D46B9"]
TILE_ICONS = {"favorites": "heart_filled.svg", "downloads": "download.svg", "playlist": "playlist.svg"}


def tile_colors(kind: str) -> tuple:
    """Colores de la portada de cada tipo de lista; 'Mis descargas' sigue el color de la aplicación."""
    if kind == "downloads":
        return QColor(accent()).darker(170).name(), accent()
    return TILE_COLORS.get(kind, TILE_COLORS["playlist"])


def _rounded(pix: QPixmap, size: int, radius: int) -> QPixmap:
    dpr = 2
    px = size * dpr
    scaled = pix.scaled(px, px, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    scaled = scaled.copy((scaled.width() - px) // 2, (scaled.height() - px) // 2, px, px)
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, px, px, radius * dpr, radius * dpr)
    p.setClipPath(path)
    p.drawPixmap(0, 0, scaled)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def cover_tile(icon_name: str, c1: str, c2: str, size: int = 140, radius: int = 12) -> QPixmap:
    """Cuadrado con degradado y un icono blanco en el centro."""
    dpr = 2
    px = size * dpr
    pix = QPixmap(px, px)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, px, px)
    grad.setColorAt(0, QColor(c1))
    grad.setColorAt(1, QColor(c2))
    path = QPainterPath()
    path.addRoundedRect(0, 0, px, px, radius * dpr, radius * dpr)
    p.fillPath(path, grad)
    glyph = icon(icon_name, "#FFFFFF", 128).pixmap(px // 2, px // 2)
    p.drawPixmap((px - glyph.width()) // 2, (px - glyph.height()) // 2, glyph)
    p.end()
    pix.setDevicePixelRatio(dpr)
    return pix


def genre_cover(label: str, color_index: int, size: int = 140, radius: int = 12) -> QPixmap:
    """Portada de un género: color propio y su nombre (Pop, Rap...) en grande."""
    base = QColor(GENRE_COLORS[color_index % len(GENRE_COLORS)])
    dpr = 2
    px = size * dpr
    pix = QPixmap(px, px)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, px, px)
    grad.setColorAt(0, base)
    grad.setColorAt(1, base.darker(160))
    path = QPainterPath()
    path.addRoundedRect(0, 0, px, px, radius * dpr, radius * dpr)
    p.fillPath(path, grad)
    p.setPen(QColor("#FFFFFF"))
    font = QFont("Poppins")
    font.setBold(True)
    font.setPixelSize(int(px * (0.2 if len(label) <= 8 else 0.14)))
    p.setFont(font)
    p.drawText(QRectF(px * 0.08, px * 0.08, px * 0.84, px * 0.84), Qt.AlignCenter | Qt.TextWordWrap, label)
    p.end()
    pix.setDevicePixelRatio(dpr)
    return pix


SMART_ICONS = {"week": "clock.svg", "untagged": "tag.svg", "long": "timer.svg", "top": "volume.svg",
               "never": "music.svg", "rediscover": "refresh.svg"}


_PLACEHOLDERS: dict = {}


def placeholder_cover(text: str, size: int = 48, radius: int = 6) -> QPixmap:
    """Portada de relleno mientras llega la real (o si no tiene): un degradado suave según el título con su inicial.
    Es siempre la misma para la misma canción y se guarda en memoria."""
    text = text or ""
    letter = next((c for c in text if c.isalnum()), "♪").upper()
    idx = sum(ord(c) for c in text) % len(MIX_COLORS)
    key = (letter, idx, size, radius)
    cached = _PLACEHOLDERS.get(key)
    if cached is not None:
        return cached
    c1, c2 = MIX_COLORS[idx]
    dpr = 2
    px = size * dpr
    pix = QPixmap(px, px)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, px, px)
    grad.setColorAt(0, QColor(c1).darker(190))
    grad.setColorAt(1, QColor(c2).darker(230))
    path = QPainterPath()
    path.addRoundedRect(0, 0, px, px, radius * dpr, radius * dpr)
    p.fillPath(path, grad)
    p.setPen(QColor(255, 255, 255, 215))
    font = QFont("Poppins")
    font.setBold(True)
    font.setPixelSize(int(px * 0.46))
    p.setFont(font)
    p.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, letter)
    p.end()
    pix.setDevicePixelRatio(dpr)
    if len(_PLACEHOLDERS) > 300:
        _PLACEHOLDERS.clear()
    _PLACEHOLDERS[key] = pix
    return pix


def mosaic_cover(tracks: list, size: int = 140, radius: int = 12):
    """Mosaico 2×2 con las portadas de las primeras canciones de una lista, usando solo las que ya están en la caché de
    disco (no descarga nada). Devuelve None si no hay suficientes."""
    import hashlib
    from ui.imageloader import CACHE_DIR
    images = []
    for t in tracks[:12]:
        url = t.get("thumbnail")
        if not url:
            continue
        f = CACHE_DIR / hashlib.md5(url.encode("utf-8")).hexdigest()
        try:
            if f.exists():
                img = QImage()
                if img.loadFromData(f.read_bytes()):
                    images.append(img)
        except OSError:
            continue
        if len(images) == 4:
            break
    if len(images) < 2:
        return None
    dpr = 2
    px = size * dpr
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(0, 0, px, px, radius * dpr, radius * dpr)
    p.setClipPath(path)
    half = px // 2
    for i in range(4):
        img = images[i % len(images)]
        tile = QPixmap.fromImage(img).scaled(half, half, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        p.drawPixmap((i % 2) * half, (i // 2) * half, tile, (tile.width() - half) // 2, (tile.height() - half) // 2, half, half)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def list_cover_pixmap(kind: str, list_id, size: int = 48, radius: int = 8, label: str = "") -> QPixmap:
    """Portada de una lista: imagen elegida (playlists), nombre del género o degradado con icono."""
    if kind == "localmix":
        return mix_cover(int(list_id or 0), size, radius)
    if kind in ("smart", "artist_local", "album_local"):
        idx = sum(ord(ch) for ch in str(list_id)) % len(MIX_COLORS)
        c1, c2 = MIX_COLORS[idx]
        icon_name = SMART_ICONS.get(str(list_id), "album.svg" if kind == "album_local" else "user.svg" if kind == "artist_local" else "music.svg")
        return cover_tile(icon_name, c1, c2, size, radius)
    if kind == "genre":
        return genre_cover(label, int(list_id or 0), size, radius)
    if kind == "artist":
        return artist_avatar_pixmap(list_id, size)
    if kind == "mix":
        return mix_cover(int(list_id or 0), size, radius)
    if kind == "playlist" and list_id:
        path = PlaylistService.get_cover_path(list_id)
        if path:
            img = QPixmap(path)
            if not img.isNull():
                return _rounded(img, size, radius)
        mosaic = mosaic_cover(PlaylistService.get_playlists().get(list_id, {}).get("tracks", []), size, radius)
        if mosaic is not None:
            return mosaic
    c1, c2 = tile_colors(kind)
    return cover_tile(TILE_ICONS.get(kind, "playlist.svg"), c1, c2, size, radius)


def import_cover(playlist_id: str, src_path: str) -> bool:
    """Guarda como portada de la playlist la imagen elegida (recortada a cuadrado y reducida)."""
    img = QImage(src_path)
    if img.isNull():
        return False
    side = min(img.width(), img.height())
    img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
    img = img.scaled(600, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    # nombre nuevo cada vez, así la interfaz no usa una copia antigua en caché
    name = f"{playlist_id}_{int.from_bytes(os.urandom(3), 'big'):x}.jpg"
    if not img.save(str(COVERS_DIR / name), "JPG", 90):
        return False
    old = PlaylistService.get_playlists().get(playlist_id, {}).get("cover")
    PlaylistService.set_cover_filename(playlist_id, name)
    if old and old != name:
        try:
            (COVERS_DIR / old).unlink()
        except OSError:
            pass
    return True


# ---------------------------------------------------------------------------
# Artistas (avatar redondo) y mixes
# ---------------------------------------------------------------------------
def _circle(pix: QPixmap, size: int) -> QPixmap:
    dpr = 2
    px = size * dpr
    scaled = pix.scaled(px, px, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    scaled = scaled.copy((scaled.width() - px) // 2, (scaled.height() - px) // 2, px, px)
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, px, px))
    p.setClipPath(path)
    p.drawPixmap(0, 0, scaled)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def artist_avatar_path(artist_id) -> str:
    return str(COVERS_DIR / f"artist_{artist_id}.jpg")


def artist_avatar_pixmap(artist_id, size: int = 48) -> QPixmap:
    """Foto redonda del artista (si ya se descargó) o un círculo con un icono de persona."""
    path = artist_avatar_path(artist_id)
    if os.path.exists(path):
        img = QPixmap(path)
        if not img.isNull():
            return _circle(img, size)
    dpr = 2
    px = size * dpr
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, px, px)
    grad.setColorAt(0, QColor("#3A3A3A"))
    grad.setColorAt(1, QColor("#1F1F1F"))
    p.setBrush(grad)
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, px, px)
    glyph = icon("user.svg", "#B3B3B3", 128).pixmap(px // 2, px // 2)
    p.drawPixmap((px - glyph.width()) // 2, (px - glyph.height()) // 2, glyph)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def mix_cover(index: int, size: int = 140, radius: int = 12) -> QPixmap:
    """Portada de un 'Mix': degradado de color con su número."""
    c1, c2 = MIX_COLORS[index % len(MIX_COLORS)]
    dpr = 2
    px = size * dpr
    pix = QPixmap(px, px)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, px, px)
    grad.setColorAt(0, QColor(c1))
    grad.setColorAt(1, QColor(c2))
    path = QPainterPath()
    path.addRoundedRect(0, 0, px, px, radius * dpr, radius * dpr)
    p.fillPath(path, grad)
    p.setPen(QColor("#FFFFFF"))
    font = QFont("Poppins")
    font.setPixelSize(int(px * 0.15))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(px * 0.1, px * 0.62, px * 0.8, px * 0.25), Qt.AlignLeft | Qt.AlignVCenter, "Mix")
    font.setPixelSize(int(px * 0.30))
    p.setFont(font)
    p.drawText(QRectF(px * 0.1, px * 0.18, px * 0.8, px * 0.45), Qt.AlignLeft | Qt.AlignVCenter, str(index + 1))
    p.end()
    pix.setDevicePixelRatio(dpr)
    return pix


class AvatarDownloader(QThread):
    """Descarga y guarda la foto de un artista para poder mostrarla siempre en la barra lateral."""
    done = Signal(str)

    def __init__(self, artist_id, url: str, parent=None):
        super().__init__(parent)
        self.artist_id = artist_id
        self.url = url

    def run(self):
        if not self.url:
            return
        try:
            r = http.get(self.url, timeout=8)
            if r.status_code != 200:
                return
            img = QImage()
            if not img.loadFromData(r.content):
                return
            img = img.scaled(400, 400, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            COVERS_DIR.mkdir(parents=True, exist_ok=True)
            if img.save(artist_avatar_path(self.artist_id), "JPG", 90):
                self.done.emit(str(self.artist_id))
        except Exception:
            pass


class PlaylistCoverFromUrl(QThread):
    """Usa una imagen de internet (por ejemplo la portada de un álbum) como imagen de una playlist."""
    done = Signal(str)

    def __init__(self, playlist_id: str, url: str, parent=None):
        super().__init__(parent)
        self.playlist_id = playlist_id
        self.url = url

    def run(self):
        if not self.url:
            return
        try:
            r = http.get(self.url, timeout=8)
            if r.status_code != 200:
                return
            tmp = COVERS_DIR / f"_tmp_{self.playlist_id}"
            COVERS_DIR.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(r.content)
            ok = import_cover(self.playlist_id, str(tmp))
            try:
                tmp.unlink()
            except OSError:
                pass
            if ok:
                self.done.emit(self.playlist_id)
        except Exception:
            pass
