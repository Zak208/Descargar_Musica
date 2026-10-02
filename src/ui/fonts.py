"""Carga de la tipografía de la aplicación (Poppins, licencia SIL OFL, incluida en assets/fonts)."""
from PySide6.QtGui import QFontDatabase, QFont

from config import BASE_DIR

FONT_FAMILY = "Poppins"
_FILES = ("Poppins-Regular.ttf", "Poppins-Medium.ttf", "Poppins-SemiBold.ttf", "Poppins-Bold.ttf")


def load_app_fonts(app=None) -> bool:
    """Registra las fuentes incluidas y las aplica como tipografía predeterminada. Devuelve True si cargaron."""
    loaded = 0
    for name in _FILES:
        path = BASE_DIR / "assets" / "fonts" / name
        if path.exists() and QFontDatabase.addApplicationFont(str(path)) >= 0:
            loaded += 1
    if loaded and app is not None:
        font = QFont(FONT_FAMILY)
        font.setPixelSize(13)
        app.setFont(font)
    return bool(loaded)
