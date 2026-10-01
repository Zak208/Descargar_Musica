"""Página de inicio estilo Spotify: accesos rápidos, mixes, recientes, novedades y recomendaciones."""

from datetime import datetime

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QScrollArea
)

from ui.home_shelves import make_shelf
from ui.icons import icon


def _section(self, title: str, height: int, subtitle: str = ""):
    box, row = make_shelf(title, height, subtitle)
    box.setVisible(False)
    self.home_layout.addWidget(box)
    return box, row


def build_home_page(self):
    """Construye la página de inicio (se rellena en refresh_home y refresh_recommendations)."""
    self.page_intro = QScrollArea()
    self.page_intro.setWidgetResizable(True)
    self.page_intro.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    content = QWidget()
    content.setObjectName("HomeContent")
    content.setStyleSheet("#HomeContent { background: transparent; }")
    self.home_layout = QVBoxLayout(content)
    self.home_layout.setContentsMargins(0, 0, 8, 24)
    self.home_layout.setSpacing(14)
    self.page_intro.setWidget(content)

    # Saludo según la hora y botón de actualizar recomendaciones
    hour = datetime.now().hour
    greeting = "Buenos días" if hour < 13 else ("Buenas tardes" if hour < 21 else "Buenas noches")
    head = QHBoxLayout()
    head.setContentsMargins(0, 0, 0, 0)
    title = QLabel(greeting)
    title.setObjectName("TitleLabel")
    title.setStyleSheet("font-size: 32px; font-weight: bold; color: #FFFFFF;")
    head.addWidget(title)
    head.addStretch()
    self.home_status_lbl = QLabel("")
    self.home_status_lbl.setObjectName("SectionSubtitle")
    head.addWidget(self.home_status_lbl)
    self.btn_refresh_recs = QPushButton("")
    self.btn_refresh_recs.setObjectName("IconBtn")
    self.btn_refresh_recs.setIcon(icon("refresh.svg", "#B3B3B3"))
    self.btn_refresh_recs.setIconSize(QSize(18, 18))
    self.btn_refresh_recs.setToolTip("Actualizar recomendaciones")
    self.btn_refresh_recs.setCursor(Qt.PointingHandCursor)
    self.btn_refresh_recs.clicked.connect(lambda: self.refresh_recommendations(force=True))
    head.addWidget(self.btn_refresh_recs)
    self.home_layout.addLayout(head)

    # Resumen de tu música
    self.home_stats_lbl = QLabel("")
    self.home_stats_lbl.setObjectName("SectionSubtitle")
    self.home_layout.addWidget(self.home_stats_lbl)

    # Accesos rápidos (tus listas y artistas)
    self.home_quick_box = QWidget()
    self.home_quick_grid = QGridLayout(self.home_quick_box)
    self.home_quick_grid.setContentsMargins(0, 4, 0, 8)
    self.home_quick_grid.setHorizontalSpacing(12)
    self.home_quick_grid.setVerticalSpacing(12)
    self.home_layout.addWidget(self.home_quick_box)

    # Secciones (todas empiezan ocultas)
    self.home_mixes_box, self.home_mixes_row = _section(
        self, "Mixes hechos para ti", 292, "Creados a partir de la música que tienes y de lo que sigues")
    self.home_recents_box, self.home_recents_layout = _section(self, "Añadidas recientemente", 258)
    self.home_releases_box, self.home_releases_row = _section(
        self, "Novedades de los artistas que sigues", 262)
    self.home_because_layout = QVBoxLayout()
    self.home_because_layout.setSpacing(6)
    self.home_layout.addLayout(self.home_because_layout)
    self.home_artists_box, self.home_artists_row = _section(
        self, "Artistas que podrían gustarte", 238, "Parecidos a los que escuchas")
    self.home_tracks_box, self.home_tracks_row = _section(
        self, "Canciones que podrían gustarte", 262, "Nuevas para ti, según tu música")
    self.home_followed_box, self.home_followed_row = _section(self, "Tus artistas", 238)
    self.home_charts_box, self.home_charts_row = _section(self, "Lo más escuchado ahora", 262)
    self.home_genres_box, self.home_genres_row = _section(
        self, "Explorar por géneros", 130, "Las canciones más escuchadas de cada género")

    # Guía rápida (solo mientras no hay música descargada)
    self.home_howto_box = QWidget()
    howto = QHBoxLayout(self.home_howto_box)
    howto.setContentsMargins(0, 12, 0, 0)
    howto.setSpacing(16)
    for num, head_text, body in (
        ("1", "Busca", "Escribe en la barra de arriba una canción, un artista o pega un enlace."),
        ("2", "Escucha", "Pulsa el botón de reproducir para oír un adelanto antes de descargar."),
        ("3", "Descarga", "Pulsa «Descargar» y tendrás la canción en tu música."),
    ):
        card = QFrame()
        card.setObjectName("CoverCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(4)
        h = QLabel(f"{num}. {head_text}")
        h.setObjectName("CoverTitle")
        h.setStyleSheet("font-size: 16px;")
        b = QLabel(body)
        b.setObjectName("CoverSub")
        b.setWordWrap(True)
        cl.addWidget(h)
        cl.addWidget(b)
        howto.addWidget(card, stretch=1)
    self.home_layout.addWidget(self.home_howto_box)
    self.home_layout.addStretch(1)

    self.stacked_widget.addWidget(self.page_intro)
