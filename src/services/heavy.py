"""Tareas pesadas (generar letras, copias del ecualizador, leer la biblioteca, analizar volumen...) de una en una por carril:
así un ordenador modesto nunca tiene varias trabajando a la vez.

Hay dos carriles para que algo lento no bloquee lo rápido:
  * "short" (por defecto): leer la biblioteca, copias del ecualizador, medir volumen... (segundos)
  * "slow": escuchar una canción con el reconocedor de voz (minutos): letras y tiempos de las palabras."""
import threading
from contextlib import contextmanager

_slots = {"short": threading.Semaphore(1), "slow": threading.Semaphore(1)}


@contextmanager
def heavy_task(lane: str = "short"):
    with _slots.get(lane, _slots["short"]):
        yield
