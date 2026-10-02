"""Tareas pesadas (generar letras, copias del ecualizador, leer la biblioteca, analizar volumen...) de una en una:
así un ordenador modesto nunca tiene varias trabajando a la vez."""
import threading
from contextlib import contextmanager

_slot = threading.Semaphore(1)


@contextmanager
def heavy_task():
    with _slot:
        yield
