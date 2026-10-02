"""Arrastrar y soltar: canciones sobre una lista de la barra lateral, y enlaces o archivos de audio sobre la ventana."""
import json
import os
import shutil

from PySide6.QtCore import Qt, QMimeData, QByteArray, QPoint
from PySide6.QtGui import QDrag, QPixmap

from services.library_service import AUDIO_EXTS
from services.spotify_service import is_spotify_url
from services.youtube_service import is_youtube_url

TRACK_MIME = "application/x-descargador-track"


def _clean(info: dict) -> dict:
    return {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool, type(None)))}


def start_track_drag(widget, infos, source=None) -> None:
    """Empieza a arrastrar una o varias canciones (la fila se ve semitransparente bajo el ratón).
    `source` = (tipo, id) de la lista de la que salen, para poder reordenar dentro de una playlist."""
    infos = [infos] if isinstance(infos, dict) else list(infos)
    mime = QMimeData()
    payload = {"tracks": [_clean(i) for i in infos], "source": list(source) if source else None}
    mime.setData(TRACK_MIME, QByteArray(json.dumps(payload).encode("utf-8")))
    drag = QDrag(widget)
    drag.setMimeData(mime)
    pix = widget.grab()
    if pix.width() > 360:
        pix = pix.scaledToWidth(360, Qt.SmoothTransformation)
    ghost = QPixmap(pix.size())
    ghost.fill(Qt.transparent)
    from PySide6.QtGui import QPainter
    p = QPainter(ghost)
    p.setOpacity(0.7)
    p.drawPixmap(0, 0, pix)
    p.setOpacity(1.0)
    p.setRenderHint(QPainter.Antialiasing)
    from PySide6.QtGui import QColor, QPen
    from ui.styles import accent
    p.setPen(QPen(QColor(accent()), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(1, 1, ghost.width() - 2, ghost.height() - 2, 8, 8)
    if len(infos) > 1:                      # insignia redonda con el número de canciones que se arrastran
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(accent()))
        p.drawEllipse(ghost.width() - 30, 6, 24, 24)
        p.setPen(QColor("#000000"))
        font = p.font()
        font.setBold(True)
        p.setFont(font)
        p.drawText(ghost.width() - 30, 6, 24, 24, Qt.AlignCenter, str(min(len(infos), 99)))
    p.end()
    drag.setPixmap(ghost)
    drag.setHotSpot(QPoint(24, ghost.height() // 2))
    drag.exec(Qt.CopyAction)


def read_drop(mime) -> dict | None:
    """{'tracks': [...], 'source': [tipo, id] | None} de lo que se está arrastrando, o None."""
    if mime.hasFormat(TRACK_MIME):
        try:
            data = json.loads(bytes(mime.data(TRACK_MIME)).decode("utf-8"))
            return data if isinstance(data, dict) and data.get("tracks") else None
        except (ValueError, UnicodeDecodeError):
            return None
    return None


def read_dropped_tracks(mime) -> list:
    data = read_drop(mime)
    return data["tracks"] if data else []


def read_dropped_track(mime) -> dict | None:
    tracks = read_dropped_tracks(mime)
    return tracks[0] if tracks else None


def _dropped_links_and_files(mime) -> tuple:
    """(enlace de YouTube/Spotify o None, [archivos de audio])"""
    link = None
    files = []
    for url in mime.urls() if mime.hasUrls() else []:
        if url.isLocalFile():
            path = url.toLocalFile()
            if os.path.isfile(path) and path.lower().endswith(AUDIO_EXTS):
                files.append(path)
            elif os.path.isdir(path):
                for root, _dirs, names in os.walk(path):
                    files.extend(os.path.join(root, n) for n in names if n.lower().endswith(AUDIO_EXTS))
        else:
            text = url.toString()
            if is_youtube_url(text) or is_spotify_url(text):
                link = link or text
    if mime.hasText() and not link:
        text = mime.text().strip()
        if text and len(text) < 400 and (is_youtube_url(text) or is_spotify_url(text)):
            link = text
    return link, files[:300]


def can_accept_window_drop(mime) -> bool:
    if mime.hasFormat(TRACK_MIME):
        return False
    link, files = _dropped_links_and_files(mime)
    return bool(link or files)


def handle_window_drop(window, mime) -> bool:
    """Un enlace se busca/descarga; archivos de audio se ofrecen para añadirlos a tu música."""
    link, files = _dropped_links_and_files(mime)
    if link:
        window.topbar.set_text(link, silent=True)
        window.perform_search(link)
        return True
    if files:
        window.import_audio_files(files)
        return True
    return False


def unique_target(folder: str, name: str) -> str:
    stem, ext = os.path.splitext(name)
    target = os.path.join(folder, name)
    n = 2
    while os.path.exists(target):
        target = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return target


def copy_into(folder: str, files: list) -> list:
    """Copia los archivos a la carpeta de música (sin pisar los que ya existen). Devuelve las rutas nuevas."""
    os.makedirs(folder, exist_ok=True)
    copied = []
    for src in files:
        try:
            if os.path.normcase(os.path.dirname(os.path.abspath(src))) == os.path.normcase(os.path.abspath(folder)):
                continue            # ya está en tu música
            dst = unique_target(folder, os.path.basename(src))
            shutil.copy2(src, dst)
            copied.append(dst)
        except OSError:
            continue
    return copied
