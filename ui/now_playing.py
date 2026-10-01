"""Panel lateral derecho «En reproducción» (como el de Spotify): portada, acciones, letra, artista y siguiente canción."""
import os

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget
)

from services.artist_service import ArtistService
from services.lyrics_service import LyricsWorker
from services.playlist_service import PlaylistService
from services.recommendation_service import ArtistInfoWorker
from ui.formatting import split_artists
from ui.icons import icon
from ui.save_popup import save_icon
from ui.imageloader import ImageLoaderThread, LocalCoverLoader
from ui.perf import eco
from ui.styles import accent
from ui.widgets import ElidedLabel

PANEL_WIDTH = 330
COVER = 286


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


LINE_IDLE = "color: #D2D2D2; font-size: 19px; font-weight: 700; background: transparent;"
LINE_ACTIVE = "color: #FFFFFF; font-size: 19px; font-weight: 800; background: transparent;"


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
    """Letra de la canción dentro del panel (las sincronizadas avanzan solas)."""

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
        self._lines = []      # [(ms, QLabel)]
        self._active = -1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("Letra")
        title.setStyleSheet("color: #FFFFFF; font-size: 15px; font-weight: 800; background: transparent;")
        head.addWidget(title)
        head.addStretch()
        self.btn_full = QPushButton("Ver completa")
        self.btn_full.setObjectName("LinkBtn")
        self.btn_full.setStyleSheet("color: #FFFFFF; background: transparent; border: none; font-weight: 700;")
        self.btn_full.setCursor(Qt.PointingHandCursor)
        self.btn_full.clicked.connect(self.window_ref.open_lyrics)
        head.addWidget(self.btn_full)
        lay.addLayout(head)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #E6E6E6; background: transparent; font-size: 14px;")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

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

    def set_color(self, color):
        """Fondo de la tarjeta: el tono que sale de mezclar los colores de la portada."""
        self.setStyleSheet(f"QFrame#LyricsCard {{ background-color: {color.name()}; border-radius: 14px; }}")

    def load(self, title: str, artist: str, key: str):
        if key == self._key:
            return
        self._key = key
        self._clear()
        self.status.setText("Buscando la letra...")
        self.status.setVisible(True)
        self.scroll.setVisible(False)
        if self._worker is not None:
            try:
                self._worker.lyrics_ready.disconnect()
                self._worker.lyrics_error.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._worker = LyricsWorker(title, artist)
        self._worker.lyrics_ready.connect(lambda data, k=key: self._on_ready(data, k))
        self._worker.lyrics_error.connect(lambda msg, k=key: self._on_error(msg, k))
        self._worker.start()

    def _clear(self):
        self._lines = []
        self._active = -1
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
                item.widget().deleteLater()

    def _on_error(self, msg: str, key: str):
        if key == self._key:
            self.status.setText("No hemos encontrado la letra de esta canción.")

    def _on_ready(self, data: dict, key: str):
        if key != self._key:
            return
        self._clear()
        synced = data.get("is_synced") and data.get("synced_lines")
        lines = [(ms, text) for ms, text in data["synced_lines"]] if synced else \
                [(0, t.strip()) for t in data.get("plain_text", "").splitlines() if t.strip()]
        for ms, text in lines:
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(LINE_IDLE)
            self.body.addWidget(lbl)
            if synced:
                self._lines.append((ms, lbl))
        self._plain = bool(lines) and not synced
        self.scroll.verticalScrollBar().setValue(0)
        self.status.setVisible(not lines)
        if not lines:
            self.status.setText("No hemos encontrado la letra de esta canción.")
        self.scroll.setVisible(bool(lines))

    def update_position(self, ms: int):
        if self._plain:     # letra sin tiempos: baja poco a poco según lo que lleva la canción
            dur = self.window_ref.player.duration()
            if dur > 0:
                bar = self.scroll.verticalScrollBar()
                self._scroll_to(int(bar.maximum() * min(1.0, ms / dur)))
            return
        if not self._lines:
            return
        new = -1
        for i, (t, _lbl) in enumerate(self._lines):
            if ms >= t:
                new = i
            else:
                break
        if new == self._active or new < 0:
            return
        if 0 <= self._active < len(self._lines):
            self._lines[self._active][1].setStyleSheet(LINE_IDLE)
        self._active = new
        lbl = self._lines[new][1]
        lbl.setStyleSheet(LINE_ACTIVE)
        QTimer.singleShot(0, lambda l=lbl: self._center(l))

    def _center(self, lbl):
        try:
            self._scroll_to(max(0, lbl.y() + lbl.height() // 2 - self.scroll.viewport().height() // 2))
        except RuntimeError:
            pass

    def _scroll_to(self, value: int):
        bar = self.scroll.verticalScrollBar()
        if eco():
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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 12)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(18, 0, 10, 8)
        self.heading = QLabel("En reproducción")
        self.heading.setObjectName("PanelTitle")
        head.addWidget(self.heading)
        head.addStretch()
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
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
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

        self.cover = QLabel()
        self.cover.setFixedSize(COVER, COVER)
        self.cover.setStyleSheet("background-color: #2A2A2A; border-radius: 12px;")
        main_lay.addWidget(self.cover, alignment=Qt.AlignHCenter)

        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 22px; font-weight: 800; background: transparent;")
        main_lay.addWidget(self.title)
        self.artist = ClickableLabel("")
        self.artist.setCursor(Qt.PointingHandCursor)
        self.artist.setObjectName("PanelArtistLink")
        self.artist.setWordWrap(True)
        self.artist.clicked.connect(self._open_artist)
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
        self.artist_fans = QLabel("")
        self.artist_fans.setObjectName("SectionSubtitle")
        inner_a.addWidget(self.artist_fans)
        self.artist_bio = QLabel("")
        self.artist_bio.setWordWrap(True)
        self.artist_bio.setStyleSheet("font-size: 13px; color: #D0D0D0; background: transparent;")
        inner_a.addWidget(self.artist_bio)
        row = QHBoxLayout()
        self.btn_follow = QPushButton("Seguir")
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
        nh.addWidget(btn_queue)
        nl.addLayout(nh)
        nrow = QHBoxLayout()
        nrow.setSpacing(10)
        self.next_cover = QLabel()
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
        color = cover_color(pix)
        if color is not None:
            self.lyrics.set_color(color)
            top = QColor(color)
            top.setHslF(top.hslHueF(), top.hslSaturationF(), 0.26)
            self.setStyleSheet(
                "QFrame#SidePanel { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                f"stop:0 {top.name()}, stop:0.5 #121212, stop:1 #121212); border-radius: 14px; }}")

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
        fans = data.get("fans", 0)
        self.artist_fans.setText(f"{fans:,} seguidores".replace(",", ".") if fans else "")
        self.artist_bio.setText(data.get("bio") or "No hay información disponible de este artista.")
        if data.get("picture"):
            loader = ImageLoaderThread(data["picture"], False, (PANEL_WIDTH - 36, 170), 0)
            loader.image_loaded.connect(lambda pix: self._safe_set(self.artist_photo, pix))
            self._artist_loader = loader
            loader.start()

    def refresh_next(self):
        """Siguiente canción: primero la cola que has añadido, luego la siguiente de la lista."""
        w = self.window_ref
        nxt = (w.playback_queue[0] if w.playback_queue else None)
        if nxt is None:
            upcoming = w.upcoming_tracks(1)
            nxt = upcoming[0] if upcoming else None
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
