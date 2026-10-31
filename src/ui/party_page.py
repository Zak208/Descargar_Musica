"""Modo fiesta (fase 30): pantalla para llevar la sesión DJ de lejos, con botones muy grandes y letra que se lee a metros.

Colores de la casa: fondo negro, texto blanco, gris #555555 y amarillo #F8C700 para lo importante. Todo se maneja también con
el teclado (lo atiende `PartyMixin.party_key`, la página no se queda con las teclas): espacio = pausa o seguir, → = siguiente,
↑ = más energía, ↓ = menos energía, V = votos del público, E = eventos, Esc = salir de la fiesta. Los botones no cogen el foco
(así el espacio no «pulsa» el último botón tocado). La página solo enseña y avisa con señales; la lógica está en
ui/party_mixin.py."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QListWidget, QAbstractItemView, QFrame, QSizePolicy
)

from ui.widgets import ElidedLabel

YELLOW, GREY, BLACK, WHITE = "#F8C700", "#555555", "#000000", "#FFFFFF"
EVENTS_SHOWN = 200

_STYLE = """
#PartyPage {{ background: {BLACK}; border-radius: 12px; }}
#PartyPage QLabel {{ color: {WHITE}; background: transparent; }}
#PartyPage QLabel#PartyCaption {{ color: #BBBBBB; font-size: 15px; font-weight: 800; letter-spacing: 2px; }}
#PartyPage QLabel#PartyTitle {{ font-size: {title}px; font-weight: 900; }}
#PartyPage QLabel#PartyArtist {{ font-size: 24px; color: #DDDDDD; }}
#PartyPage QLabel#PartyNext {{ font-size: 24px; font-weight: 700; }}
#PartyPage QLabel#PartyEnergy {{ font-size: 24px; font-weight: 800; }}
#PartyPage QLabel#PartyHint {{ color: #BBBBBB; font-size: 14px; }}
#PartyPage QLabel#PartyWarn {{ color: {YELLOW}; font-size: 14px; }}
#PartyPage QLabel#PartyUrl {{ font-size: 26px; font-weight: 800; color: {YELLOW}; }}
#PartyPage QLabel#PartyCounts {{ font-size: 22px; font-weight: 700; }}
#PartyPage QLabel#StatusOk {{ background: {GREY}; color: {WHITE}; font-size: 18px; font-weight: 900; padding: 6px 14px;
                              border-radius: 18px; }}
#PartyPage QLabel#StatusBad {{ background: {YELLOW}; color: {BLACK}; font-size: 18px; font-weight: 900; padding: 6px 14px;
                               border-radius: 18px; }}
#PartyPage QPushButton {{ font-size: {big}px; font-weight: 900; border-radius: 20px; padding: 18px 12px; min-height: 96px;
                          background: {GREY}; color: {WHITE}; border: 3px solid {GREY}; }}
#PartyPage QPushButton:hover {{ border-color: {WHITE}; }}
#PartyPage QPushButton:pressed {{ background: {WHITE}; color: {BLACK}; }}
#PartyPage QPushButton:disabled {{ background: #222222; color: #777777; border-color: #222222; }}
#PartyPage QPushButton#PartyMain {{ background: {YELLOW}; color: {BLACK}; border-color: {YELLOW}; }}
#PartyPage QPushButton#PartyMain:pressed {{ background: {WHITE}; }}
#PartyPage QPushButton#PartySmall {{ font-size: 14px; font-weight: 800; min-height: 0; min-width: 0; padding: 6px 12px; border-radius: 14px;
                                     background: {BLACK}; border: 2px solid {GREY}; }}
#PartyPage QPushButton#PartySmall:checked {{ background: {YELLOW}; color: {BLACK}; border-color: {YELLOW}; }}
#PartyPage QListWidget {{ background: {BLACK}; color: #DDDDDD; border: 1px solid {GREY}; border-radius: 8px; font-size: 14px; }}
#PartyPage QFrame#PartyLine {{ background: {GREY}; max-height: 2px; min-height: 2px; border: none; }}
"""


WIDE_W = 1000                  # desde este ancho de página, letra grande; por debajo, más pequeña (para que nada se corte)


def _style(wide: bool) -> str:
    return _STYLE.format(big=30 if wide else 20, title=44 if wide else 30, YELLOW=YELLOW, GREY=GREY, BLACK=BLACK, WHITE=WHITE)


def _big(text: str, hint: str, main: bool = False) -> QPushButton:
    btn = QPushButton(f"{text}\n{hint}")
    btn.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # en una ventana estrecha encoge (y la letra baja)
    btn.setMinimumWidth(120)
    if main:
        btn.setObjectName("PartyMain")
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def _small(text: str, checkable: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("PartySmall")
    btn.setCheckable(checkable)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def _label(name: str, text: str = "", elide: bool = False, wrap: bool = False):
    lbl = ElidedLabel(text) if elide else QLabel(text)
    lbl.setObjectName(name)
    if wrap:
        lbl.setWordWrap(True)
    return lbl


class PartyPage(QWidget):
    next_requested = Signal()
    energy_requested = Signal(int)          # +1 más energía, -1 menos
    pause_requested = Signal()
    exit_requested = Signal()
    start_requested = Signal()
    crowd_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PartyPage")
        self.setProperty("noRetheme", True)            # los colores de la fiesta no cambian con el tema de la aplicación
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._wide = False
        self.setStyleSheet(_style(self._wide))
        self.setFocusPolicy(Qt.StrongFocus)            # las teclas llegan aquí (y suben a la ventana, que las atiende)
        main = QVBoxLayout(self)
        main.setContentsMargins(24, 18, 24, 18)
        main.setSpacing(12)

        head = QHBoxLayout()
        cap = _label("PartyCaption", "MODO FIESTA")
        cap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)        # en una ventana estrecha se recorta él, no los botones
        head.addWidget(cap, 1)
        self.status = _label("StatusOk", "Todo bien")
        head.addWidget(self.status)
        self.btn_exit = _small("Salir (Esc)")
        self.btn_exit.setToolTip("Salir del modo fiesta (la música sigue)")
        self.btn_exit.clicked.connect(self.exit_requested.emit)
        head.addWidget(self.btn_exit)
        main.addLayout(head)

        # --- sin sesión ---
        self.empty = QWidget()
        empty_lay = QVBoxLayout(self.empty)
        empty_lay.setContentsMargins(0, 30, 0, 30)
        msg = _label("PartyNext", "No hay ninguna sesión DJ sonando.", wrap=True)
        msg.setAlignment(Qt.AlignCenter)
        empty_lay.addWidget(msg)
        self.btn_start = _big("▶ Empezar la fiesta", "con la carpeta del DJ", main=True)
        self.btn_start.clicked.connect(self.start_requested.emit)
        empty_lay.addWidget(self.btn_start)
        main.addWidget(self.empty)

        # --- con sesión ---
        self.session = QWidget()
        sess = QVBoxLayout(self.session)
        sess.setContentsMargins(0, 0, 0, 0)
        sess.setSpacing(8)
        sess.addWidget(_label("PartyCaption", "SUENA AHORA"))
        self.now_title = _label("PartyTitle", elide=True)
        sess.addWidget(self.now_title)
        self.now_artist = _label("PartyArtist", elide=True)
        sess.addWidget(self.now_artist)
        row = QHBoxLayout()
        self.energy = _label("PartyEnergy", elide=True)
        row.addWidget(self.energy, 1)
        self.play_state = _label("PartyEnergy")
        row.addWidget(self.play_state)
        sess.addLayout(row)
        line = QFrame()
        line.setObjectName("PartyLine")
        sess.addWidget(line)
        nxt_row = QHBoxLayout()
        nxt_row.addWidget(_label("PartyCaption", "DESPUÉS"))
        self.next_title = _label("PartyNext", elide=True)
        nxt_row.addWidget(self.next_title, 1)
        sess.addLayout(nxt_row)
        self.after = _label("PartyHint", elide=True)
        sess.addWidget(self.after)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.btn_next = _big("⏭ Siguiente", "(tecla →)", main=True)
        self.btn_next.clicked.connect(self.next_requested.emit)
        self.btn_pause = _big("⏯ Pausa", "(espacio)")
        self.btn_pause.clicked.connect(self.pause_requested.emit)
        self.btn_up = _big("▲ Más energía", "(tecla ↑)")
        self.btn_up.clicked.connect(lambda: self.energy_requested.emit(1))
        self.btn_down = _big("▼ Menos energía", "(tecla ↓)")
        self.btn_down.clicked.connect(lambda: self.energy_requested.emit(-1))
        grid.addWidget(self.btn_next, 0, 0)
        grid.addWidget(self.btn_pause, 0, 1)
        grid.addWidget(self.btn_up, 1, 0)
        grid.addWidget(self.btn_down, 1, 1)
        sess.addLayout(grid)
        main.addWidget(self.session, 1)

        # --- votos del público ---
        crowd_row = QHBoxLayout()
        self.btn_crowd = _small("Votos del público (V)", checkable=True)
        self.btn_crowd.toggled.connect(self.crowd_toggled.emit)
        crowd_row.addWidget(self.btn_crowd)
        self.crowd_counts = _label("PartyCounts", elide=True)
        crowd_row.addWidget(self.crowd_counts, 1)
        main.addLayout(crowd_row)
        self.crowd_box = QWidget()
        crowd_lay = QHBoxLayout(self.crowd_box)
        crowd_lay.setContentsMargins(0, 0, 0, 0)
        self.qr = QLabel()
        self.qr.hide()
        crowd_lay.addWidget(self.qr)
        texts = QVBoxLayout()
        hint_row = QHBoxLayout()
        hint_row.addWidget(_label("PartyHint", "Los invitados abren en el móvil, con la misma wifi:", wrap=True), 1)
        self.btn_copy = _small("Copiar enlace")
        self.btn_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._url))
        hint_row.addWidget(self.btn_copy)
        texts.addLayout(hint_row)
        self._url = ""
        self.crowd_url = _label("PartyUrl", wrap=True)      # con cortes posibles tras «/» y «:» (un enlace no tiene espacios)
        self.crowd_url.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        texts.addWidget(self.crowd_url)
        self.crowd_warn = _label("PartyWarn", wrap=True)
        texts.addWidget(self.crowd_warn)
        crowd_lay.addLayout(texts, 1)
        self.crowd_box.hide()
        main.addWidget(self.crowd_box)

        # --- eventos (lo que ha hecho el vigilante) ---
        ev_row = QHBoxLayout()
        self.btn_events = _small("Eventos ▸ (E)")
        self.btn_events.clicked.connect(self.toggle_events)
        ev_row.addWidget(self.btn_events)
        self.last_event = _label("PartyHint", elide=True)
        ev_row.addWidget(self.last_event, 1)
        main.addLayout(ev_row)
        self.events = QListWidget()
        self.events.setSelectionMode(QAbstractItemView.NoSelection)
        self.events.setFocusPolicy(Qt.NoFocus)
        self.events.setMaximumHeight(160)
        self.events.hide()
        main.addWidget(self.events)
        self.session.hide()

    # ------------------------------------------------------------------ estado
    def set_session(self, active: bool, now: dict = None, nxt: dict = None, after: list = (), energy_text: str = "",
                    playing: bool = True):
        self.empty.setVisible(not active)
        self.session.setVisible(active)
        if not active:
            return
        now = now or {}
        self._set(self.now_title, now.get("title", ""))
        self._set(self.now_artist, now.get("uploader", ""))
        self._set(self.energy, energy_text)
        self._set(self.play_state, "" if playing else "⏸ EN PAUSA")
        self._set(self.btn_pause, "⏯ Pausa\n(espacio)" if playing else "▶ Seguir\n(espacio)")
        self._set(self.next_title, nxt.get("title", "") if nxt else "Nada más: es la última")
        later = " · ".join(t.get("title", "") for t in list(after)[:3])
        self._set(self.after, f"Luego: {later}" if later else "")
        self.btn_next.setEnabled(bool(nxt))

    @staticmethod
    def _set(widget, text: str):
        if widget.text() != text:
            widget.setText(text)

    def set_status(self, ok: bool, text: str):
        """«Todo bien» (gris) o «Recuperándose» (amarillo, se ve desde lejos)."""
        name = "StatusOk" if ok else "StatusBad"
        if self.status.objectName() != name:
            self.status.setObjectName(name)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        self._set(self.status, text)

    def add_event(self, text: str):
        self.events.insertItem(0, text)
        while self.events.count() > EVENTS_SHOWN:
            self.events.takeItem(self.events.count() - 1)
        self._set(self.last_event, text)

    def toggle_events(self):
        show = not self.events.isVisible()
        self.events.setVisible(show)
        self._set(self.btn_events, "Eventos ▾ (E)" if show else "Eventos ▸ (E)")

    def set_crowd(self, on: bool, url: str = "", counts: str = "", warning: str = "", qr_pixmap=None):
        if self.btn_crowd.isChecked() != on:
            self.btn_crowd.blockSignals(True)
            self.btn_crowd.setChecked(on)
            self.btn_crowd.blockSignals(False)
        self.crowd_box.setVisible(on)
        self._url = url
        self._set(self.crowd_url, url.replace("/", "/​").replace(":", ":​"))
        self._set(self.crowd_counts, counts if on else "apagados")
        self._set(self.crowd_warn, warning)
        if qr_pixmap is not None:
            self.qr.setPixmap(qr_pixmap)
        pix = self.qr.pixmap()
        self.qr.setVisible(on and pix is not None and not pix.isNull())

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus(Qt.OtherFocusReason)          # las teclas de la fiesta funcionan nada más entrar

    def resizeEvent(self, event):
        super().resizeEvent(event)
        wide = self.width() >= WIDE_W
        if wide != self._wide:
            self._wide = wide
            self.setStyleSheet(_style(wide))
