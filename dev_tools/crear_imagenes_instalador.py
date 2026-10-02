"""Genera las imágenes del instalador (installer/*.bmp) con la identidad de la aplicación. Se ejecuta una vez:
    python dev_tools/crear_imagenes_instalador.py
El asistente de Inno Setup usa BMP: una imagen grande a la izquierda y una pequeña arriba a la derecha (en dos tamaños,
para pantallas normales y de mucha resolución)."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

from ui.icons import icon

app = QGuiApplication([])
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "installer")


def big(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    grad = QLinearGradient(0, 0, w * 0.4, h)
    grad.setColorAt(0, QColor("#1ED760"))
    grad.setColorAt(1, QColor("#0B3D1E"))
    p.fillRect(0, 0, w, h, grad)
    k = w / 164
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 28))
    p.drawEllipse(QPointF(w * 0.9, h * 0.12), 70 * k, 70 * k)
    p.drawEllipse(QPointF(w * 0.05, h * 0.82), 90 * k, 90 * k)
    size = int(96 * k)
    pix = icon("music.svg", "#FFFFFF", max(64, size)).pixmap(size, size)
    p.drawPixmap(int((w - size) / 2), int(h * 0.2), pix)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 1)
    f.setPixelSize(int(17 * k))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(8 * k, h * 0.2 + size + 14 * k, w - 16 * k, 60 * k), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
               "Descargador\nde Música")
    f.setPixelSize(int(10 * k))
    f.setBold(False)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 210))
    p.drawText(QRectF(8 * k, h - 52 * k, w - 16 * k, 40 * k), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
               "Gratis y de código abierto\nTus datos se quedan en tu equipo")
    p.end()
    return img


def small(side: int) -> QImage:
    img = QImage(side, side, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, side, side)
    grad.setColorAt(0, QColor("#1ED760"))
    grad.setColorAt(1, QColor("#128A3E"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(side * 0.04, side * 0.04, side * 0.92, side * 0.92), side * 0.2, side * 0.2)
    p.fillPath(path, grad)
    n = int(side * 0.58)
    p.drawPixmap((side - n) // 2, (side - n) // 2, icon("music.svg", "#FFFFFF", max(64, n)).pixmap(n, n))
    p.end()
    return img


big(164, 314).save(os.path.join(OUT, "imagen_grande.bmp"), "BMP")
big(328, 628).save(os.path.join(OUT, "imagen_grande_2x.bmp"), "BMP")
small(55).save(os.path.join(OUT, "imagen_pequena.bmp"), "BMP")
small(110).save(os.path.join(OUT, "imagen_pequena_2x.bmp"), "BMP")
print("Imágenes escritas en", OUT)
