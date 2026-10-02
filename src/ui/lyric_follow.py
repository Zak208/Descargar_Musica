"""Seguimiento de una letra sincronizada: decide qué frase suena, cuánto lleva cantada, cuándo empezar a desplazar
(un poco antes, para que llegue al centro justo cuando suena) y cuándo hay una pausa instrumental. Lo comparten el panel
«En reproducción» y la ventana de letras."""
from bisect import bisect_right

from PySide6.QtCore import QEasingCurve, QPropertyAnimation

from services import word_timing
from ui import motion
from ui.lyric_line import GapDots

LEAD_MS = 220            # el desplazamiento empieza esto antes de que suene la frase
GAP_MIN_MS = 5000        # pausas más largas que esto enseñan los puntos
MS_PER_CHAR = 80         # lo que se tarda, más o menos, en cantar cada letra (para el barrido y las pausas)


def estimated_length(text: str) -> int:
    return max(1200, len(text) * MS_PER_CHAR)


class LyricsFollower:
    def __init__(self, scroll_area):
        self.scroll = scroll_area
        self.lines = []                 # [(ms, LyricLine)]
        self.times = []
        self.spans = []                 # por frase: [(inicio, fin, car_inicio, car_fin)] de cada palabra
        self.active = -1
        self._pre = -1
        self._anim = QPropertyAnimation(scroll_area.verticalScrollBar(), b"value", scroll_area)
        curve = QEasingCurve(QEasingCurve.OutBack)
        curve.setOvershoot(0.7)          # un ligerísimo rebote al llegar
        self._anim.setEasingCurve(curve)
        self.dots = GapDots(scroll_area.viewport())

    # ------------------------------------------------------------------ datos
    def set_lines(self, lines: list):
        self.lines = list(lines)
        self.times = [ms for ms, _ in self.lines]
        self.active = -1
        self._pre = -1
        self.dots.hide()
        self._anim.stop()
        self.spans = word_timing.estimate([(ms, lbl.text()) for ms, lbl in self.lines]) if self.lines else []

    def set_spans(self, spans: list) -> bool:
        """Cambia los tiempos estimados de cada palabra por otros (medidos con la voz). Solo si encajan con las frases."""
        if len(spans) != len(self.lines):
            return False
        self.spans = list(spans)
        return True

    def clear(self):
        self.set_lines([])

    # --------------------------------------------------------------- posición
    def update(self, ms: int):
        n = len(self.lines)
        if not n:
            return
        new = bisect_right(self.times, ms) - 1           # -1 antes de la primera frase
        if new != self.active:
            old = self.active
            self.active = new
            self._restyle(old, new)
            self._pre = -1
            if new >= 0:
                self.center(self.lines[new][1])
        if new >= 0:
            label = self.lines[new][1]
            label.set_fill(word_timing.fraction_at(self.spans[new], len(label.text()), ms))
        nxt = new + 1
        if nxt < n:
            remaining = self.times[nxt] - ms
            if 0 < remaining <= LEAD_MS and self._pre != nxt:
                self._pre = nxt                             # se empieza a desplazar antes de que suene
                self.center(self.lines[nxt][1])
        self._update_gap(ms, new)

    def _restyle(self, old: int, new: int):
        n = len(self.lines)
        lo = 0 if old < 0 else max(0, min(old, new))
        hi = min(n - 1, max(old, new) + 4)
        for i in range(lo, hi + 1):
            if i < new:
                self.lines[i][1].set_state("past")
            elif i == new:
                self.lines[i][1].set_state("active")
            else:
                self.lines[i][1].set_state("idle", i - new)
        if new < 0:                                         # antes de la primera frase: las de abajo van apagadas
            for i in range(0, min(n, 4)):
                self.lines[i][1].set_state("idle", i + 1)

    # ------------------------------------------------------------ pausas
    def _update_gap(self, ms: int, active: int):
        n = len(self.lines)
        if active < 0:
            start, end = 0, self.times[0]
        elif active + 1 < n:
            words = self.spans[active] if active < len(self.spans) else []
            start = words[-1][1] if words else self.times[active] + estimated_length(self.lines[active][1].text())
            end = self.times[active + 1]
        else:
            self.dots.hide()
            return
        if end - start >= GAP_MIN_MS and ms >= start:
            self.dots.set_progress((ms - start) / (end - start))
            if not self.dots.isVisible():
                self.dots.move(14, 10)
                self.dots.show()
                self.dots.raise_()
        elif self.dots.isVisible():
            self.dots.hide()

    # --------------------------------------------------------------- scroll
    def center(self, label):
        try:
            bar = self.scroll.verticalScrollBar()
            target = max(0, label.y() + label.height() // 2 - self.scroll.viewport().height() // 2)
            if not motion.enabled() or not self.scroll.isVisible():
                self._anim.stop()
                bar.setValue(target)
                return
            self._anim.stop()
            self._anim.setDuration(380)
            self._anim.setStartValue(bar.value())
            self._anim.setEndValue(target)
            self._anim.start()
        except RuntimeError:
            pass

    def recenter(self):
        if 0 <= self.active < len(self.lines):
            self.center(self.lines[self.active][1])
