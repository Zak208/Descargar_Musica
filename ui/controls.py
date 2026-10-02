"""Controles propios, pintados a mano y con transiciones breves: interruptor, selector con indicador deslizante,
portada con fundido y zoom, y botón de reproducir/pausa que se transforma. En reposo no gastan nada."""
from PySide6.QtCore import Qt, QSize, QRectF, QPointF, QVariantAnimation, QEasingCurve, Signal, QEvent
from PySide6.QtGui import QPainter, QColor, QPainterPath, QPixmap, QFontMetrics, QPen, QIcon
from PySide6.QtWidgets import QCheckBox, QWidget, QLabel, QFrame, QPushButton, QSizePolicy

from ui import motion
from ui.styles import accent, live_accent


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


class ToggleSwitch(QCheckBox):
    """Casilla con aspecto de interruptor: la perilla se desliza y el fondo pasa de gris al color del tema.
    Es un QCheckBox (misma API: setChecked, isChecked, toggled, setText), así que sustituye a las casillas sin más."""
    TRACK_W, TRACK_H = 42, 22

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._t = 1.0 if self.isChecked() else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(motion.DUR_FAST)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self.toggled.connect(self._start)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(30)

    def hitButton(self, pos):
        """Se puede pulsar en cualquier punto del interruptor (texto, hueco o perilla), no solo donde lo calcula el estilo."""
        return self.rect().contains(pos)

    def setChecked(self, checked):
        super().setChecked(checked)
        self._anim.stop()
        self._t = 1.0 if self.isChecked() else 0.0
        self.update()

    def _start(self, checked: bool):
        self._anim.stop()
        if not motion.enabled() or not self.isVisible():
            self._t = 1.0 if checked else 0.0
            self.update()
            return
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _on_value(self, v):
        self._t = float(v)
        self.update()

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.text()) + self.TRACK_W + 16, max(30, self.TRACK_H + 8))

    def minimumSizeHint(self):
        return QSize(self.TRACK_W + 20, 30)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        track = QRectF(self.width() - self.TRACK_W - 2, (h - self.TRACK_H) / 2, self.TRACK_W, self.TRACK_H)
        off, on = QColor("#5A5A5A"), QColor(accent())
        if not self.isEnabled():
            off, on = QColor("#3A3A3A"), QColor("#4A4A4A")
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(off, on, self._t))
        p.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        d = self.TRACK_H - 6
        x = track.left() + 3 + (self.TRACK_W - d - 6) * self._t
        p.setBrush(QColor("#FFFFFF" if self.isEnabled() else "#9A9A9A"))
        p.drawEllipse(QRectF(x, track.top() + 3, d, d))
        if self.hasFocus() and self.focusPolicy() != Qt.NoFocus:
            ring = QColor(accent())
            p.setBrush(Qt.NoBrush)
            p.setPen(ring)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), self.TRACK_H / 2 + 2, self.TRACK_H / 2 + 2)
        p.setPen(self.palette().windowText().color() if self.isEnabled() else QColor("#777777"))
        text_rect = QRectF(0, 0, track.left() - 12, h)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, self.text())


class SegmentedControl(QWidget):
    """Selector de pocas opciones con una píldora que se desliza de una a otra (en vez de saltar)."""
    changed = Signal(str)

    def __init__(self, options, current: str = None, parent=None, height: int = 34):
        super().__init__(parent)
        self._options = list(options)
        self._current = current if current in [k for k, _ in self._options] else self._options[0][0]
        self._x = None
        self._w = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(motion.DUR_BASE)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._hover = -1
        self.setFixedHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def current(self) -> str:
        return self._current

    def set_current(self, key: str, animate: bool = True):
        if key not in [k for k, _ in self._options] or key == self._current:
            return
        old = self._cell(self._current)
        self._current = key
        new = self._cell(key)
        if animate and motion.enabled() and self.isVisible():
            self._anim.stop()
            self._from = (old.left(), old.width())
            self._to = (new.left(), new.width())
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self._x, self._w = new.left(), new.width()
            self.update()

    def _cell(self, key: str) -> QRectF:
        n = len(self._options)
        w = self.width() / max(1, n)
        i = [k for k, _ in self._options].index(key)
        return QRectF(i * w, 0, w, self.height())

    def _on_value(self, v):
        t = float(v)
        self._x = self._from[0] + (self._to[0] - self._from[0]) * t
        self._w = self._from[1] + (self._to[1] - self._from[1]) * t
        self.update()

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(sum(fm.horizontalAdvance(t) + 36 for _, t in self._options), self.height())

    def resizeEvent(self, event):
        cell = self._cell(self._current)
        self._x, self._w = cell.left(), cell.width()
        super().resizeEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(self.rect()), r, r)
        if self._x is None:
            cell = self._cell(self._current)
            self._x, self._w = cell.left(), cell.width()
        pill = QRectF(self._x + 2, 2, self._w - 4, self.height() - 4)
        p.setBrush(QColor(accent()))
        p.drawRoundedRect(pill, r - 2, r - 2)
        for i, (key, text) in enumerate(self._options):
            cell = self._cell(key)
            selected = key == self._current
            p.setPen(QColor("#000000") if selected else QColor("#FFFFFF" if i == self._hover else "#C8C8C8"))
            font = self.font()
            font.setBold(True)
            p.setFont(font)
            p.drawText(cell, Qt.AlignCenter, text)
        if self.hasFocus():
            p.setPen(QColor(accent()))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), r, r)

    def _index_at(self, x: float) -> int:
        return max(0, min(len(self._options) - 1, int(x / max(1.0, self.width() / len(self._options)))))

    def mouseMoveEvent(self, event):
        i = self._index_at(event.position().x())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            key = self._options[self._index_at(event.position().x())][0]
            if key != self._current:
                self.set_current(key)
                self.changed.emit(key)

    def keyPressEvent(self, event):
        keys = [k for k, _ in self._options]
        i = keys.index(self._current)
        if event.key() in (Qt.Key_Right, Qt.Key_Down) and i < len(keys) - 1:
            self.set_current(keys[i + 1])
            self.changed.emit(self._current)
        elif event.key() in (Qt.Key_Left, Qt.Key_Up) and i > 0:
            self.set_current(keys[i - 1])
            self.changed.emit(self._current)
        else:
            super().keyPressEvent(event)


class CoverLabel(QLabel):
    """Portada que aparece con un fundido (desde el color de relleno o desde la anterior) y, si se quiere, crece un
    poco al pasar el ratón. Se pinta a mano: no usa efectos gráficos, que son caros en cuadrículas con decenas de portadas."""

    def __init__(self, radius: int = 8, zoom_on_hover: bool = False, placeholder: str = "#2A2A2A", parent=None):
        super().__init__(parent)
        self.radius = radius
        self._zoom_on_hover = zoom_on_hover
        self._placeholder = QColor(placeholder)
        self._old = None
        self._fade = 1.0
        self._zoom = 1.0
        self._dim = 0.0
        self._dim_target = 0.0
        self._dim_anim = QVariantAnimation(self)
        self._dim_anim.setDuration(motion.DUR_BASE)
        self._dim_anim.valueChanged.connect(self._on_dim)
        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.setDuration(motion.DUR_BASE)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.valueChanged.connect(self._on_fade)
        self._zoom_anim = QVariantAnimation(self)
        self._zoom_anim.setDuration(motion.DUR_FAST + 20)
        self._zoom_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._zoom_anim.valueChanged.connect(self._on_zoom)
        if zoom_on_hover:
            self.setAttribute(Qt.WA_Hover, True)
            self.installEventFilter(self)

    # -- contenido
    def setPixmap(self, pix):
        previous = self.pixmap()
        super().setPixmap(pix)
        if pix is None or pix.isNull():
            self._old = None
            self._fade = 1.0
            self.update()
            return
        if motion.enabled() and motion.visible_ok(self):
            self._old = previous if (previous is not None and not previous.isNull()) else None
            self._fade = 0.0
            self._fade_anim.stop()
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
        else:
            self._old = None
            self._fade = 1.0
        self.update()

    def clear(self):
        super().clear()
        self._old = None
        self._fade = 1.0

    def _on_fade(self, v):
        self._fade = float(v)
        if self._fade >= 1.0:
            self._old = None
        self.update()

    def _on_zoom(self, v):
        self._zoom = float(v)
        self.update()

    def set_dim(self, dim: bool):
        """Atenúa la portada (canción en pausa)."""
        target = 1.0 if dim else 0.0
        if target == self._dim_target:
            return
        self._dim_target = target
        if motion.enabled() and self.isVisible():
            self._dim_anim.stop()
            self._dim_anim.setStartValue(self._dim)
            self._dim_anim.setEndValue(target)
            self._dim_anim.start()
        else:
            self._dim = target
            self.update()

    def _on_dim(self, v):
        self._dim = float(v)
        self.update()

    def eventFilter(self, obj, event):
        if obj is self and self._zoom_on_hover and motion.enabled():
            if event.type() == QEvent.Enter:
                self._zoom_to(1.05)
            elif event.type() == QEvent.Leave:
                self._zoom_to(1.0)
        return False

    def zoom_hover(self, on: bool):
        """La portada crece un poco (o vuelve) cuando el ratón está sobre su tarjeta."""
        if not motion.enabled():
            self._zoom = 1.0
            return
        self._zoom_to(1.05 if on else 1.0)

    def _zoom_to(self, value: float):
        self._zoom_anim.stop()
        self._zoom_anim.setStartValue(self._zoom)
        self._zoom_anim.setEndValue(value)
        self._zoom_anim.start()

    # -- dibujo
    def paintEvent(self, event):
        QFrame.paintEvent(self, event)
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, self.radius, self.radius)
        p.setClipPath(clip)
        if self._zoom != 1.0:
            p.translate(rect.center())
            p.scale(self._zoom, self._zoom)
            p.translate(-rect.center())
        src = QRectF(pix.rect())
        if self._fade < 1.0:
            if self._old is not None:
                p.drawPixmap(rect, self._old, QRectF(self._old.rect()))
            else:
                p.fillRect(rect, self._placeholder)
            p.setOpacity(self._fade)
        p.drawPixmap(rect, pix, src)
        if self._dim > 0.001:
            p.setOpacity(1.0)
            p.fillRect(rect, QColor(0, 0, 0, int(120 * self._dim)))


class PlayPauseButton(QPushButton):
    """El botón grande de reproducir/pausa: al cambiar de estado, un icono se mezcla con el otro (140 ms).
    Se usa con `set_state(True/False)`; el resto del programa lo trata como un QPushButton."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._pix = {}
        self._playing = False
        self._t = 1.0
        self._prev = None
        self._ring = None            # progreso 0..1 que se dibuja como un arco alrededor del botón (modo mini)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)

    def set_state(self, playing: bool):
        if playing == self._playing:
            return
        self._prev = self._playing
        self._playing = playing
        if motion.enabled() and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self._t = 1.0
            self.update()

    def _on_value(self, v):
        self._t = float(v)
        self.update()

    def set_ring(self, progress):
        """Arco de progreso alrededor del botón (None lo quita)."""
        if progress is None:
            if self._ring is not None:
                self._ring = None
                self.update()
            return
        progress = max(0.0, min(1.0, progress))
        if self._ring is None or abs(progress - self._ring) > 0.002:
            self._ring = progress
            self.update()

    def _icon_pix(self, playing: bool, size: int) -> QPixmap:
        from ui.icons import icon
        key = (playing, size)
        pix = self._pix.get(key)
        if pix is None:
            pix = icon("pause_black.svg" if playing else "play_black.svg").pixmap(QSize(size, size))
            self._pix[key] = pix
        return pix

    def paintEvent(self, event):
        # el fondo redondo y los estados (hover, pulsado) los pinta la hoja de estilos; aquí solo el icono
        super().paintEvent(event)
        size = self.iconSize().width() or 20
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        cx, cy = self.width() / 2, self.height() / 2
        if self._t < 1.0 and self._prev is not None:
            p.setOpacity(1.0 - self._t)
            self._draw_icon(p, self._icon_pix(self._prev, size), cx, cy, size, 1.0 - 0.15 * self._t)
        p.setOpacity(self._t if self._t < 1.0 else 1.0)
        self._draw_icon(p, self._icon_pix(self._playing, size), cx, cy, size, 0.85 + 0.15 * self._t)
        if self._ring is not None:
            p.setOpacity(1.0)
            p.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(live_accent()), 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
            p.drawArc(r, 90 * 16, int(-360 * 16 * self._ring))

    def _draw_icon(self, p, pix, cx, cy, size, scale):
        d = size * scale
        p.drawPixmap(QRectF(cx - d / 2, cy - d / 2, d, d), pix, QRectF(pix.rect()))


class DotButton(QPushButton):
    """Botón de control con un puntito de color debajo cuando está activo (aleatorio, repetir): se distingue por la
    forma y no solo por el color."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._active = False

    def set_active(self, active: bool):
        if active != self._active:
            self._active = bool(active)
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._active:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(accent()))
            p.drawEllipse(QPointF(self.width() / 2, self.height() - 4), 2.2, 2.2)


class GlowCover(QWidget):
    """Portada con una luz de su mismo color detrás (la portada reducida, muy borrosa y desplazada un poco hacia
    abajo). Se genera una vez por canción y no se anima: cuesta cero y da profundidad."""
    PAD = 16

    def __init__(self, size: int, radius: int = 12, parent=None):
        super().__init__(parent)
        self.cover = CoverLabel(radius=radius, parent=self)
        self.cover.setFixedSize(size, size)
        self.cover.move(self.PAD, self.PAD - 4)
        self.setFixedSize(size + 2 * self.PAD, size + self.PAD * 2 - 2)
        self._glow = None

    def set_glow(self, pix):
        from ui.ambient import blurred
        self._glow = blurred(pix, 10) if pix is not None and not pix.isNull() else None
        self.update()

    def paintEvent(self, _event):
        if self._glow is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(0.42)
        r = QRectF(self.cover.geometry()).adjusted(-10, 2, 10, 20)
        p.drawPixmap(r, self._glow, QRectF(self._glow.rect()))


class TabStrip(QWidget):
    """Pestañas (Todas / Descargadas / Sin descargar): la píldora blanca se desliza de una a otra. Los botones son
    QPushButton comprobables (`buttons[clave]`), así que el resto del código los usa igual que antes."""
    HEIGHT = 34

    def __init__(self, options, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        self.buttons = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.pill = QWidget(self)
        self.pill.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.pill.setStyleSheet("background-color: #FFFFFF; border-radius: 17px;")
        self.pill.hide()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(motion.DUR_BASE - 20)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._from = self._to = None
        for key, label in options:
            b = QPushButton(label)
            b.setObjectName("TabBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton#TabBtn { background-color: transparent; }"
                            "QPushButton#TabBtn:checked { background-color: transparent; color: #000000; }")
            b.toggled.connect(lambda on, btn=b: on and self._move_to(btn, animate=True))
            b.installEventFilter(self)
            lay.addWidget(b)
            self.buttons[key] = b
        lay.addStretch()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show) and isinstance(obj, QPushButton) and obj.isChecked():
            self._move_to(obj, animate=False)
        return False

    def _checked(self):
        return next((b for b in self.buttons.values() if b.isChecked()), None)

    def _move_to(self, btn, animate: bool):
        target = btn.geometry()
        if not target.isValid() or target.width() < 4:
            return
        if not self.pill.isVisible() or not animate or not motion.enabled() or not self.isVisible():
            self._anim.stop()
            self.pill.setGeometry(target)
            self.pill.show()
            self.pill.lower()
            self._to = target
            return
        self._anim.stop()
        self._from = self.pill.geometry()
        self._to = target
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_value(self, v):
        t = float(v)
        a, b = self._from, self._to
        lerp = lambda p, q: int(p + (q - p) * t)
        self.pill.setGeometry(lerp(a.x(), b.x()), lerp(a.y(), b.y()), lerp(a.width(), b.width()), lerp(a.height(), b.height()))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#242424"))
        for b in self.buttons.values():
            if b.isVisible():
                p.drawRoundedRect(QRectF(b.geometry()), 17, 17)


class FollowButton(QPushButton):
    """«Seguir» / «Siguiendo»: al seguir, un relleno del color del tema entra desde la izquierda (150 ms)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(motion.DUR_FAST + 30)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self.toggled.connect(self._start)

    def setChecked(self, checked):
        was = self.isChecked()
        super().setChecked(checked)
        if bool(checked) == was:
            self._t = 1.0 if checked else 0.0
            self.update()

    def _start(self, checked: bool):
        self._anim.stop()
        if not motion.enabled() or not self.isVisible():
            self._t = 1.0 if checked else 0.0
            self.update()
            return
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _on_value(self, v):
        self._t = float(v)
        self.update()

    def paintEvent(self, event):
        if self._t > 0.01:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            clip = QPainterPath()
            r = self.height() / 2
            clip.addRoundedRect(QRectF(self.rect()), r, r)
            p.setClipPath(clip)
            c = QColor(accent())
            c.setAlphaF(0.16)
            p.fillRect(QRectF(0, 0, self.width() * self._t, self.height()), c)
            p.end()
        super().paintEvent(event)


class SpinIconButton(QPushButton):
    """Botón de icono que gira mientras algo se está actualizando (12 fotogramas ya dibujados, 10 por segundo)."""

    def __init__(self, icon_name: str, color: str = "#B3B3B3", size: int = 18, parent=None):
        super().__init__("", parent)
        from ui.icons import icon as _icon
        self._pix = _icon(icon_name, color).pixmap(size * 2, size * 2)
        self._pix.setDevicePixelRatio(2.0)
        self._size = size
        self._icon = _icon(icon_name, color)
        self.setIcon(self._icon)
        self.setIconSize(QSize(size, size))
        self._token = None
        self._i = 0

    def start_spin(self):
        if self._token is None and motion.enabled():
            from ui.anim_clock import clock
            self.setIcon(QIcon())              # el icono quieto se quita: lo dibuja el fotograma que gira
            self._token = clock().subscribe(self._tick, 10)

    def stop_spin(self):
        if self._token is not None:
            from ui.anim_clock import clock
            clock().unsubscribe(self._token)
            self._token = None
            self.setIcon(self._icon)
            self.update()

    def _tick(self, _dt):
        self._i = (self._i + 1) % 12
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._token is None:
            return
        from ui import frames
        strip = frames.rotated_frames(self._pix, 12, tag=f"spin{self._size}{self._pix.cacheKey()}")
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF((self.width() - self._size) / 2, (self.height() - self._size) / 2, self._size, self._size)
        p.drawPixmap(rect, strip[self._i % 12], QRectF(strip[self._i % 12].rect()))


class ProgressDots(QWidget):
    """Puntitos de los pasos de un asistente: el actual se alarga (de 6 a 18 px) y los demás quedan pequeños."""

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self._count = count
        self._index = 0
        self._shown = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(motion.DUR_BASE)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self.setFixedHeight(10)
        self.setFixedWidth(count * 16 + 24)

    def set_index(self, index: int):
        if index == self._index:
            return
        self._index = index
        if not motion.enabled() or not self.isVisible():
            self._shown = float(index)
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._shown)
        self._anim.setEndValue(float(index))
        self._anim.start()

    def _on_value(self, v):
        self._shown = float(v)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        x = 0.0
        for i in range(self._count):
            k = max(0.0, 1.0 - abs(i - self._shown))              # cuánto de «actual» tiene este punto
            w = 6 + 12 * k
            c = QColor(accent()) if k > 0.5 else QColor(255, 255, 255, 70)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(x, 2, w, 6), 3, 3)
            x += w + 6
