"""Las páginas de la ventana principal, en el orden en que están dentro del `QStackedWidget`.
Úsalas en vez de números sueltos: `self.switch_to_page(Page.RESULTS)`. Son enteros (IntEnum), así que valen donde se
esperaba un índice."""
from enum import IntEnum


class Page(IntEnum):
    HOME = 0
    RESULTS = 1
    ARTIST = 2
    ALBUM = 3
    LIST = 4        # una lista (favoritos, playlist, cola, lo más escuchado...)
    LIBRARY = 5     # tu música descargada
