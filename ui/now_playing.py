"""Panel lateral derecho «En reproducción» (como el de Spotify): portada, acciones, letra, artista y siguiente canción."""
import os

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QPropertyAnimation, QEasingCurve, QRectF, QVariantAnimation
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QLinearGradient
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget, QProgressBar
)

from services.artist_service import ArtistService
from services.lyrics_service import LyricsWorker
from services.playlist_service import PlaylistService
from services.recommendation_service import ArtistInfoWorker
from ui.controls import CoverLabel, FollowButton, GlowCover
from ui.scrolling import polish_scroll_area
from ui.formatting import split_artists
from ui.icons import icon
from ui.save_popup import save_icon
from ui.imageloader import ImageLoaderThread, LocalCoverLoader
from ui.lyric_line import LyricLine
from ui.lyric_follow import LyricsFollower
from ui import motion
from ui.anim_clock import clock
from ui.styles import accent
from ui.textfx import CountLabel, DotsLabel, grow_underline
from ui.widgets import ElidedLabel

PANEL_WIDTH = 330
COVER = 286


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


def cover_color(pix):
    """Mezcla todos los colores de la portada (más peso a los vivos) y devuelve un tono medio con el que el texto claro se lee bien."""
    if pix is None or pix.isNull():
        return None
    img = pix.toImage().scaled(24, 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB32)
    r = g = b = wsum = 0.0
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            weight = 0.15 + c.hsvSaturationF() * c.valueF()
            r += c.red() * weight
            g += c.green() * weight
            b += c.blue() * weight
            wsum += weight
    if not wsum:
        return None
    mixed = QColor(int(r / wsum), int(g / wsum), int(b / wsum))
    return QColor.fromHslF(max(mixed.hslHueF(), 0.0), min(max(mixed.hslSaturationF(), 0.38), 0.62), 0.40)


class AutoScrollArea(QScrollArea):
    """Zona de letra: se mueve sola con la canción; la rueda del ratón no la desplaza (sigue moviendo el panel)."""

    def wheelEvent(self, ev):
        ev.ignore()


class LyricsBox(QFrame):
    """Letra de la canción dentro del panel: avanza sola, se oscurece lo ya leído y se puede pulsar una frase para saltar a ella.
    Si no hay letra, permite generarla con el sistema (canciones descargadas) o escribirla uno mismo."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.setObjectName("LyricsCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.window_ref = window
        self._anim = None
        self._plain = False
        self.set_color(QColor("#3D5A4A"))
        self._worker = None
        self._key = None
        self._info_key = None
        self._lines = []      # [(ms, LyricLine)]
        self.data = None      # última letra mostrada (para poder editarla)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("Letra")
        title.setStyleSheet("color: #FFFFFF; font-size: 15px; font-weight: 800; background: transparent;")
        head.addWidget(title)
        head.addStretch()
        link_css = "color: #FFFFFF; background: transparent; border: none; font-weight: 700;"
        self.btn_edit = QPushButton("Editar")
        self.btn_edit.setObjectName("LinkBtn")
        self.btn_edit.setStyleSheet(link_css)
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.setToolTip("Corrige la letra o escribe la tuya")
        self.btn_edit.clicked.connect(lambda: self.window_ref.edit_lyrics())
        grow_underline(self.btn_edit, "#FFFFFF")
        head.addWidget(self.btn_edit)
        self.btn_full = QPushButton("Ver completa")
        self.btn_full.setObjectName("LinkBtn")
        self.btn_full.setStyleSheet(link_css)
        self.btn_full.setCursor(Qt.PointingHandCursor)
        self.btn_full.clicked.connect(self.window_ref.open_lyrics)
        grow_underline(self.btn_full, "#FFFFFF")
        head.addWidget(self.btn_full)
        lay.addLayout(head)

        self.badge = QLabel("")
        self.badge.setWordWrap(True)
        self.badge.setStyleSheet("color: #FFFFFF; background: rgba(0, 0, 0, 0.28); border-radius: 8px; "
                                 "font-size: 12px; font-weight: 600; padding: 5px 9px;")
        self.badge.setVisible(False)
        lay.addWidget(self.badge)

        self.status = DotsLabel("")
        self.status.setStyleSheet("color: #E6E6E6; background: transparent; font-size: 14px;")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet("QProgressBar { background: rgba(0,0,0,0.3); border: none; border-radius: 3px; }"
                                    "QProgressBar::chunk { background: #FFFFFF; border-radius: 3px; }")
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.actions = QWidget()
        self.actions.setStyleSheet("background: transparent;")
        act = QVBoxLayout(self.actions)
        act.setContentsMargins(0, 0, 0, 0)
        act.setSpacing(6)
        pill = ("QPushButton { color: #FFFFFF; background: rgba(0,0,0,0.30); border: 1px solid rgba(255,255,255,0.35); "
                "border-radius: 16px; padding: 8px 12px; font-weight: 700; font-size: 13px; }"
                "QPushButton:hover { background: rgba(0,0,0,0.45); border-color: #FFFFFF; }")
        self.btn_generate = QPushButton("Generar con el sistema")
        self.btn_generate.setStyleSheet(pill)
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.setToolTip("El programa escucha la canción y escribe lo que canta (solo canciones descargadas)")
        self.btn_generate.clicked.connect(lambda: self.window_ref.generate_lyrics())
        act.addWidget(self.btn_generate)
        self.btn_write = QPushButton("Escribir la letra yo")
        self.btn_write.setStyleSheet(pill)
        self.btn_write.setCursor(Qt.PointingHandCursor)
        self.btn_write.clicked.connect(lambda: self.window_ref.edit_lyrics())
        act.addWidget(self.btn_write)
        self.actions.setVisible(False)
        lay.addWidget(self.actions)

        self.scroll = AutoScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(320)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 4, 4, 4)
        self.body.setSpacing(12)
        self.body.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(inner)
        lay.addWidget(self.scroll)
        self.follower = LyricsFollower(self.scroll)
        self._show_idle_buttons(False)

    def set_color(self, color):
        """Fondo de la tarjeta: el tono que sale de mezclar los colores de la portada."""
        self.setStyleSheet(f"QFrame#LyricsCard {{ background-color: {color.name()}; border-radius: 14px; }}")

    # ------------------------------------------------------------- carga
    def load(self, title: str, artist: str, key: str):
        if key == self._key:
            return
        self._key = key
        self._clear()
        self.data = None
        self._show_idle_buttons(False)
        self.badge.setVisible(False)
        self.progress.setVisible(False)
        self.status.animate("Buscando la letra")
        self.status.setVisible(True)
        self.scroll.setVisible(False)
        if self._worker is not None:
            try:
                self._worker.lyrics_ready.disconnect()
                self._worker.lyrics_error.disconnect()
            except (RuntimeError, TypeError):
                pass
        info = self.window_ref.current_item_info or {}
        self._worker = LyricsWorker(title, artist, self.window_ref.lyrics_key(), info.get("local_path") or "")
        self._worker.lyrics_ready.connect(lambda data, k=key: self._on_ready(data, k))
        self._worker.lyrics_error.connect(lambda msg, k=key: self._on_error(msg, k))
        self._worker.start()

    def reload(self):
        """Vuelve a pedir la letra de la canción actual (tras editarla o generarla)."""
        info = self.window_ref.current_item_info
        if info:
            self._key = None
            self.load(info.get("title", ""), info.get("uploader", ""), self._current_key())

    def _current_key(self):
        from ui.playback_mixin import track_key
        return track_key(self.window_ref.current_item_info)

    def set_busy(self, text: str, percent: int = -1):
        """Muestra un mensaje de trabajo (descargando el reconocedor, escuchando la canción…)."""
        self.status.setText(text)
        self.status.setVisible(True)
        self.actions.setVisible(False)
        self.progress.setVisible(percent != -1)
        if percent == -2:
            self.progress.setRange(0, 0)         # barra que se mueve sola: se sabe que trabaja aunque no haya porcentaje
        elif percent >= 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)

    def _show_idle_buttons(self, show: bool):
        self.actions.setVisible(show)
        if show:
            info = self.window_ref.current_item_info or {}
            local = info.get("local_path")
            self.btn_generate.setVisible(bool(local and os.path.isfile(local)))

    def _clear(self):
        self._lines = []
        self.follower.clear()
        while self.body.count():
            widget = self.body.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _on_error(self, msg: str, key: str):
        if key != self._key:
            return
        self.progress.setVisible(False)
        info = self.window_ref.current_item_info or {}
        local = info.get("local_path")
        has_file = bool(local and os.path.isfile(local))
        note = getattr(self.window_ref, "_lyrics_note", "")
        self.window_ref._lyrics_note = ""
        self.status.setText((note + " " if note else "") + "No hemos encontrado la letra de esta canción."
                            + ("" if has_file else " Descárgala para que el sistema pueda generarla, o escríbela tú."))
        self._show_idle_buttons(True)
        self.btn_edit.setVisible(False)

    def _on_ready(self, data: dict, key: str):
        if key != self._key:
            return
        self._clear()
        self.data = data
        self.progress.setVisible(False)
        self._show_idle_buttons(False)
        self.btn_edit.setVisible(True)
        source = data.get("source")
        self.badge.setText({"auto": "Letra generada por el sistema: puede tener errores. Pulsa «Editar» para corregirla.",
                            "user": "Letra escrita por ti."}.get(source, ""))
        self.badge.setVisible(source in ("auto", "user"))
        synced = data.get("is_synced") and data.get("synced_lines")
        lines = [(ms, text) for ms, text in data["synced_lines"]] if synced else \
                [(0, t.strip()) for t in data.get("plain_text", "").splitlines() if t.strip()]
        for ms, text in lines:
            lbl = LyricLine(ms, text, self._seek if synced else None, size=19)
            self.body.addWidget(lbl)
            if synced:
                self._lines.append((ms, lbl))
        self._plain = bool(lines) and not synced
        self.follower.set_lines(self._lines)
        if synced:
            self.window_ref.ensure_word_timing(self.follower)
        for delay in (0, 80, 300):             # comprueba que las frases tienen altura (ver _ensure_layout)
            QTimer.singleShot(delay, self._ensure_layout)
        self.scroll.verticalScrollBar().setValue(0)
        self.status.setVisible(not lines)
        if not lines:
            self.status.setText("No hemos encontrado la letra de esta canción.")
        self.scroll.setVisible(bool(lines))
        if self.window_ref.player.position() and self._lines:
            self.update_position(self.window_ref.player.position())

    def _ensure_layout(self):
        """Si las frases se midieron cuando la zona aún estaba oculta o estrecha, quedaban con altura 0 y la letra no se
        veía (pasaba al cambiar de canción). Si es así, se vuelven a colocar."""
        try:
            if self._lines and self._lines[0][1].height() < 4:
                self.body.invalidate()
                self.body.activate()
                self.scroll.widget().adjustSize()
                self.follower.recenter()
        except RuntimeError:
            pass

    def _seek(self, ms: int):
        self.window_ref.player.setPosition(ms)

    # ---------------------------------------------------------- seguimiento
    def update_position(self, ms: int):
        if self._plain:     # letra sin tiempos: baja poco a poco según lo que lleva la canción
            dur = self.window_ref.player.duration()
            if dur > 0:
                bar = self.scroll.verticalScrollBar()
                self._scroll_to(int(bar.maximum() * min(1.0, ms / dur)))
            return
        if not self._lines:
            return
        self.follower.update(ms)

    def _scroll_to(self, value: int):
        bar = self.scroll.verticalScrollBar()
        if not motion.enabled():
            bar.setValue(value)
            return
        if self._anim is None:
            self._anim = QPropertyAnimation(bar, b"value", self)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.stop()
        self._anim.setDuration(350)
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(value)
        self._anim.start()


class NowPlayingPanel(QFrame):
    close_requested = Signal()
    full_requested = Signal()

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setFixedWidth(PANEL_WIDTH)
        self.window_ref = window
        self._info = None
        self._key = None
        self._artist_name = None
        self._cover_loader = None
        self._artist_loader = None
        self._artist_worker = None
        self._bg_color = None
        self._bg_old = None
        self._bg_t = 1.0
        self._breath = 0.0
        self._breath_token = None
        self._bg_anim = QVariantAnimation(self)
        self._bg_anim.setDuration(400)
        self._bg_anim.valueChanged.connect(self._bg_value)
        window.playing_changed.connect(self._breath_sync)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 12)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(18, 0, 10, 8)
        self.heading = QLabel("En reproducción")
        self.heading.setObjectName("PanelTitle")
        head.addWidget(self.heading)
        head.addStretch()
        btn_full = QPushButton("")
        btn_full.setObjectName("IconBtn")
        btn_full.setIcon(icon("fullscreen.svg", "#B3B3B3"))
        btn_full.setIconSize(QSize(16, 16))
        btn_full.setToolTip("Pantalla completa")
        btn_full.setProperty("shortcut", "F11")
        btn_full.setCursor(Qt.PointingHandCursor)
        btn_full.clicked.connect(self.full_requested.emit)
        head.addWidget(btn_full)
        btn_close = QPushButton("")
        btn_close.setObjectName("IconBtn")
        btn_close.setIcon(icon("x.svg", "#B3B3B3"))
        btn_close.setIconSize(QSize(16, 16))
        btn_close.setToolTip("Cerrar")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.close_requested.emit)
        head.addWidget(btn_close)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        polish_scroll_area(scroll)
        inner = QWidget()
        inner.setObjectName("PanelInner")
        inner.setStyleSheet("#PanelInner { background: transparent; }")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(18, 4, 18, 18)
        self.body.setSpacing(14)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        # ---- canción actual
        self.empty = QLabel("No hay nada sonando.\nElige una canción y aquí verás su portada, su letra\ny la información del artista.")
        self.empty.setObjectName("SectionSubtitle")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("padding: 40px 6px;")
        self.body.addWidget(self.empty)

        self.main_box = QWidget()
        main_lay = QVBoxLayout(self.main_box)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(10)

        self.cover_box = GlowCover(COVER, 12)         # portada con una luz de su color detrás
        self.cover = self.cover_box.cover
        self.cover.setStyleSheet("background-color: #2A2A2A; border-radius: 12px;")
        main_lay.addWidget(self.cover_box, alignment=Qt.AlignHCenter)

        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 22px; font-weight: 800; background: transparent;")
        main_lay.addWidget(self.title)
        self.artist = ClickableLabel("")
        self.artist.setCursor(Qt.PointingHandCursor)
        self.artist.setObjectName("PanelArtistLink")
        self.artist.setWordWrap(True)
        self.artist.clicked.connect(self._open_artist)
        grow_underline(self.artist)
        main_lay.addWidget(self.artist)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.btn_like = QPushButton("")
        self.btn_like.setObjectName("IconBtn")
        self.btn_like.setIconSize(QSize(22, 22))
        self.btn_like.setToolTip("Guardar en una lista")
        self.btn_like.setCursor(Qt.PointingHandCursor)
        self.btn_like.clicked.connect(self._toggle_like)
        actions.addWidget(self.btn_like)
        actions.addStretch()
        main_lay.addLayout(actions)
        self.body.addWidget(self.main_box)

        # ---- letra
        self.lyrics = LyricsBox(window)
        self.body.addWidget(self.lyrics)

        # ---- sobre el artista
        self.artist_card = QFrame()
        self.artist_card.setObjectName("PanelCard")
        al = QVBoxLayout(self.artist_card)
        al.setContentsMargins(0, 0, 0, 14)
        al.setSpacing(8)
        self.artist_photo = QLabel()
        self.artist_photo.setFixedHeight(170)
        self.artist_photo.setAlignment(Qt.AlignCenter)
        self.artist_photo.setStyleSheet("background-color: #2A2A2A; border-top-left-radius: 12px; border-top-right-radius: 12px;")
        al.addWidget(self.artist_photo)
        inner_a = QVBoxLayout()
        inner_a.setContentsMargins(16, 4, 16, 0)
        inner_a.setSpacing(6)
        heading = QLabel("Sobre el artista")
        heading.setObjectName("PanelHeading")
        inner_a.addWidget(heading)
        self.artist_name = QLabel("")
        self.artist_name.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent;")
        inner_a.addWidget(self.artist_name)
        self.artist_fans = CountLabel("")
        self.artist_fans.setObjectName("SectionSubtitle")
        inner_a.addWidget(self.artist_fans)
        self.artist_bio = QLabel("")
        self.artist_bio.setWordWrap(True)
        self.artist_bio.setStyleSheet("font-size: 13px; color: #D0D0D0; background: transparent;")
        inner_a.addWidget(self.artist_bio)
        row = QHBoxLayout()
        self.btn_follow = FollowButton("Seguir")
        self.btn_follow.setObjectName("FollowBtn")
        self.btn_follow.setCheckable(True)
        self.btn_follow.setCursor(Qt.PointingHandCursor)
        self.btn_follow.clicked.connect(self._toggle_follow)
        row.addWidget(self.btn_follow)
        self.btn_profile = QPushButton("Ver perfil")
        self.btn_profile.setCursor(Qt.PointingHandCursor)
        self.btn_profile.clicked.connect(self._open_artist)
        row.addWidget(self.btn_profile)
        row.addStretch()
        inner_a.addLayout(row)
        al.addLayout(inner_a)
        self.body.addWidget(self.artist_card)

        # ---- a continuación
        self.next_card = QFrame()
        self.next_card.setObjectName("PanelCard")
        nl = QVBoxLayout(self.next_card)
        nl.setContentsMargins(16, 14, 16, 14)
        nl.setSpacing(8)
        nh = QHBoxLayout()
        nt = QLabel("A continuación")
        nt.setObjectName("PanelHeading")
        nh.addWidget(nt)
        nh.addStretch()
        btn_queue = QPushButton("Abrir cola")
        btn_queue.setObjectName("LinkBtn")
        btn_queue.setCursor(Qt.PointingHandCursor)
        btn_queue.clicked.connect(self.window_ref.open_queue_dialog)
        grow_underline(btn_queue, "#FFFFFF")
        nh.addWidget(btn_queue)
        nl.addLayout(nh)
        nrow = QHBoxLayout()
        nrow.setSpacing(10)
        self.next_cover = CoverLabel(radius=6)
        self.next_cover.setFixedSize(48, 48)
        self.next_cover.setStyleSheet("background-color: #2A2A2A; border-radius: 6px;")
        nrow.addWidget(self.next_cover)
        ntexts = QVBoxLayout()
        ntexts.setSpacing(1)
        self.next_title = ElidedLabel("")
        self.next_title.setObjectName("SongTitle")
        self.next_title.setStyleSheet("font-size: 13px; background: transparent;")
        self.next_artist = ElidedLabel("")
        self.next_artist.setObjectName("ArtistName")
        self.next_artist.setStyleSheet("font-size: 12px; background: transparent;")
        ntexts.addWidget(self.next_title)
        ntexts.addWidget(self.next_artist)
        nrow.addLayout(ntexts, stretch=1)
        nl.addLayout(nrow)
        self.next_empty = QLabel("No hay más canciones en cola.")
        self.next_empty.setObjectName("SectionSubtitle")
        nl.addWidget(self.next_empty)
        self._next_loader = None
        self.body.addWidget(self.next_card)
        self.body.addStretch()

        self.show_empty()

    # ------------------------------------------------------------------ estado
    def show_empty(self):
        self._info = None
        self._key = None
        self.empty.setVisible(True)
        for w in (self.main_box, self.lyrics, self.artist_card, self.next_card):
            w.setVisible(False)

    def set_track(self, info):
        """Muestra la canción que suena. Solo se pide la letra / información si es una canción distinta."""
        if not info:
            self.show_empty()
            return
        from ui.playback_mixin import track_key
        key = track_key(info)
        for w in (self.main_box, self.lyrics, self.artist_card, self.next_card):
            w.setVisible(True)
        self.empty.setVisible(False)
        self._info = info
        self.title.setText(info.get("title", ""))
        self.artist.setText(info.get("uploader", ""))
        self._refresh_like()
        if key != self._key:
            self._key = key
            self._load_cover(info)
            self.lyrics.load(info.get("title", ""), info.get("uploader", ""), key)
            main_artist = (split_artists(info.get("uploader", "")) or [""])[0]
            if main_artist != self._artist_name:
                self._artist_name = main_artist
                self._load_artist(main_artist)
            else:
                self._refresh_follow()
        self.refresh_next()

    def _load_cover(self, info):
        url, local = info.get("thumbnail"), info.get("local_path")
        if url:
            loader = ImageLoaderThread(url, False, (COVER, COVER), 12)
        elif local and os.path.isfile(local):
            loader = LocalCoverLoader(local, False, (COVER, COVER), 12)
        else:
            self.cover.clear()
            return
        loader.image_loaded.connect(self._cover_ready)
        self._cover_loader = loader
        loader.start()

    def _cover_ready(self, pix):
        self._safe_set(self.cover, pix)
        self.cover_box.set_glow(pix)
        color = cover_color(pix)
        if color is not None:
            self.lyrics.set_color(color)
            top = QColor(color)
            top.setHslF(top.hslHueF(), top.hslSaturationF(), 0.26)
            self._set_bg(top)

    # ---- fondo con el color de la portada: se mezcla al cambiar de canción y, en «Completas», respira despacio
    def _set_bg(self, color: QColor):
        if self._bg_color is not None and color == self._bg_color:
            return
        self._bg_old = self._bg_color
        self._bg_color = QColor(color)
        if motion.enabled() and self.isVisible() and self._bg_old is not None:
            self._bg_t = 0.0
            self._bg_anim.stop()
            self._bg_anim.setStartValue(0.0)
            self._bg_anim.setEndValue(1.0)
            self._bg_anim.start()
        else:
            self._bg_t = 1.0
            self.update()

    def _bg_value(self, v):
        self._bg_t = float(v)
        self.update()

    def _breath_sync(self, *_):
        want = motion.full() and self.isVisible() and self._bg_color is not None and self.window_ref.is_playing_now()
        if want and self._breath_token is None:
            self._breath_token = clock().subscribe(self._breath_tick, 6)
        elif not want and self._breath_token is not None:
            clock().unsubscribe(self._breath_token)
            self._breath_token = None

    def _breath_tick(self, dt):
        self._breath = (self._breath + dt / 9000.0) % 1.0
        self.update()

    def showEvent(self, event):
        self._breath_sync()
        super().showEvent(event)

    def hideEvent(self, event):
        self._breath_sync()
        super().hideEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._bg_color is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 14, 14)
        p.setClipPath(clip)
        for color, alpha in ((self._bg_old, 1.0 - self._bg_t), (self._bg_color, self._bg_t)):
            if color is None or alpha <= 0.002:
                continue
            c = QColor(color)
            if self._breath_token is not None:
                import math
                c.setHslF(c.hslHueF(), c.hslSaturationF(), max(0.0, min(1.0, c.lightnessF() + 0.025 * math.sin(self._breath * 6.283))))
            top = QColor(c)
            bottom = QColor(c)
            bottom.setAlpha(0)
            grad = QLinearGradient(0, 0, 0, self.height() * 0.5)
            grad.setColorAt(0.0, top)
            grad.setColorAt(1.0, bottom)
            p.setOpacity(alpha)
            p.fillRect(QRectF(0, 0, self.width(), self.height() * 0.5), grad)

    @staticmethod
    def _safe_set(label, pix):
        try:
            label.setPixmap(pix)
        except RuntimeError:
            pass

    def _load_artist(self, name: str):
        self.artist_name.setText(name)
        self.artist_fans.setText("")
        self.artist_bio.setText("Buscando información...")
        self.artist_photo.clear()
        self._refresh_follow()
        if not name:
            self.artist_card.setVisible(False)
            return
        self._artist_worker = ArtistInfoWorker(name)
        self._artist_worker.ready.connect(lambda data, n=name: self._on_artist_info(data, n))
        self._artist_worker.start()

    def _on_artist_info(self, data: dict, name: str):
        if name != self._artist_name:
            return
        fans = int(data.get("fans", 0) or 0)
        if fans:
            self.artist_fans.count_to(fans, lambda v: f"{v:,} seguidores".replace(",", "."), key=name)
        else:
            self.artist_fans.setText("")
        self.artist_bio.setText(data.get("bio") or "No hay información disponible de este artista.")
        if data.get("picture"):
            loader = ImageLoaderThread(data["picture"], False, (PANEL_WIDTH - 36, 170), 0)
            loader.image_loaded.connect(lambda pix: self._safe_set(self.artist_photo, pix))
            self._artist_loader = loader
            loader.start()

    def refresh_next(self):
        """Siguiente canción: primero la cola que has añadido, luego la siguiente de la lista."""
        nxt = self.window_ref.peek_next()      # exactamente lo que sonará (también con el aleatorio)
        if not nxt:
            self.next_title.setText("")
            self.next_artist.setText("")
            self.next_cover.clear()
            self.next_cover.setVisible(False)
            self.next_empty.setVisible(True)
            return
        self.next_empty.setVisible(False)
        self.next_cover.setVisible(True)
        self.next_title.setText(nxt.get("title", ""))
        self.next_artist.setText(nxt.get("uploader", ""))
        url, local = nxt.get("thumbnail"), nxt.get("local_path")
        if url:
            loader = ImageLoaderThread(url, False, (48, 48), 6)
        elif local and os.path.isfile(local):
            loader = LocalCoverLoader(local, False, (48, 48), 6)
        else:
            self.next_cover.clear()
            return
        loader.image_loaded.connect(lambda pix: self._safe_set(self.next_cover, pix))
        self._next_loader = loader
        loader.start()

    def update_position(self, ms: int):
        self.lyrics.update_position(ms)

    # ---------------------------------------------------------------- acciones
    def _refresh_like(self):
        if not self._info:
            return
        self.btn_like.setIcon(save_icon(bool(PlaylistService.lists_containing(self._info))))

    def refresh_like(self):
        self._refresh_like()

    def _toggle_like(self):
        if self._info:
            self.window_ref.save_button_clicked(dict(self._info), self.btn_like)
            self._refresh_like()

    def _open_artist(self):
        if self._artist_name:
            self.window_ref.open_artist_by_name({"name": self._artist_name})

    def _refresh_follow(self):
        followed = next((a for a in ArtistService.get_followed() if a["name"].lower() == (self._artist_name or "").lower()), None)
        self.btn_follow.setChecked(bool(followed))
        self.btn_follow.setText("Siguiendo" if followed else "Seguir")

    def _toggle_follow(self):
        name = self._artist_name
        if not name:
            return
        followed = next((a for a in ArtistService.get_followed() if a["name"].lower() == name.lower()), None)
        if followed:
            self.window_ref.toggle_follow_artist(followed["id"], followed["name"], followed.get("avatar", ""))
            self._refresh_follow()
        else:
            # se necesita el identificador del artista: se localiza y se sigue
            self.window_ref.follow_artist_by_name(name, on_done=self._refresh_follow)
