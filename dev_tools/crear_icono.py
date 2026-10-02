"""Genera el icono de la aplicación (assets/app.ico) a partir del icono de la nota musical. Se ejecuta una vez:
    python dev_tools/crear_icono.py
Un .ico es una cabecera con varios tamaños; cada uno va comprimido como PNG (lo entiende Windows desde Vista)."""
import os
import struct
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

from ui.icons import icon

app = QGuiApplication([])
SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "app.ico")


def render(size: int) -> bytes:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#1ED760"))
    grad.setColorAt(1, QColor("#128A3E"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    p.fillPath(path, grad)
    note = int(size * 0.62)
    pix = icon("music.svg", "#FFFFFF", max(64, note)).pixmap(note, note)
    p.drawPixmap((size - note) // 2, (size - note) // 2, pix)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


images = [render(s) for s in SIZES]
header = struct.pack("<HHH", 0, 1, len(images))
offset = 6 + 16 * len(images)
entries, blobs = b"", b""
for s, png in zip(SIZES, images):
    entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(png), offset)
    blobs += png
    offset += len(png)
with open(OUT, "wb") as f:
    f.write(header + entries + blobs)
print("Icono escrito:", OUT, os.path.getsize(OUT), "bytes")
