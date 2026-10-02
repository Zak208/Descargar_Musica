"""Integración con Windows (todo opcional: si algo falla o no es Windows, simplemente no se hace nada):
  · barra de título del color del tema (Windows 11),
  · progreso de las descargas en el icono de la barra de tareas y una marca al terminar,
  · botones anterior / reproducir / siguiente en la miniatura de la barra de tareas,
  · «siempre encima» del reproductor pequeño sin recrear la ventana (sin parpadeo).
Se hace con ctypes, sin dependencias nuevas, y Windows dibuja todo: no cuesta nada de procesador."""
import ctypes
import logging
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QBuffer, QIODevice, Qt
from PySide6.QtWidgets import QApplication

IS_WIN = sys.platform == "win32"

# ------------------------------------------------------------------ barra de título
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def _colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_title_bar(hwnd: int, background: str, text: str = "#FFFFFF") -> bool:
    """Barra de título oscura y del color del fondo del tema (Windows 11; en versiones anteriores no hace nada)."""
    if not IS_WIN or not hwnd:
        return False
    try:
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), 4)
        for attr, color in ((DWMWA_CAPTION_COLOR, background), (DWMWA_BORDER_COLOR, background), (DWMWA_TEXT_COLOR, text)):
            c = ctypes.c_uint(_colorref(color))
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(c), 4)
        corner = ctypes.c_int(2)           # esquinas redondeadas
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), 4)
        return True
    except Exception as e:
        logging.debug(f"Barra de título: {e}")
        return False


# ------------------------------------------------------------- siempre encima
def set_topmost(hwnd: int, on: bool) -> bool:
    """Pone o quita «siempre encima» sin recrear la ventana (cambiar las banderas de Qt la oculta y la vuelve a crear)."""
    if not IS_WIN or not hwnd:
        return False
    try:
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
        ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST if on else HWND_NOTOPMOST),
                                          0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- barra de tareas
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        super().__init__()
        import uuid
        u = uuid.UUID(text)
        self.Data1, self.Data2, self.Data3 = u.time_low, u.time_mid, u.time_hi_version
        raw = u.bytes[8:]
        for i in range(8):
            self.Data4[i] = raw[i]


CLSID_TaskbarList = "56FDF344-FD6D-11D0-958A-006097C9A090"
IID_ITaskbarList3 = "EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF"

TBPF_NOPROGRESS, TBPF_INDETERMINATE, TBPF_NORMAL, TBPF_ERROR, TBPF_PAUSED = 0, 1, 2, 4, 8
THB_ICON, THB_TOOLTIP, THB_FLAGS = 0x2, 0x4, 0x8
THBN_CLICKED = 0x1800
WM_COMMAND = 0x0111


class _ThumbButton(ctypes.Structure):
    _fields_ = [("dwMask", wintypes.DWORD), ("iId", wintypes.UINT), ("iBitmap", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 260), ("dwFlags", wintypes.DWORD)]


def _method(ptr, index, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])


def _icon_from_pixmap(pixmap, size: int = 20):
    """HICON a partir de un QPixmap (se guarda como PNG y Windows lo convierte)."""
    try:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(buf, "PNG")
        data = bytes(buf.data())
        user32 = ctypes.windll.user32
        user32.CreateIconFromResourceEx.restype = wintypes.HICON
        return user32.CreateIconFromResourceEx(data, len(data), True, 0x00030000, size, size, 0)
    except Exception:
        return None


class _ThumbFilter(QAbstractNativeEventFilter):
    def __init__(self, hwnd: int, callback):
        super().__init__()
        self.hwnd = hwnd
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type == b"windows_generic_MSG":
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == WM_COMMAND and msg.hWnd == self.hwnd and ((msg.wParam >> 16) & 0xFFFF) == THBN_CLICKED:
                    self.callback(msg.wParam & 0xFFFF)
                    return True, 0
        except Exception:
            pass
        return False, 0


class Taskbar:
    """Progreso, marca y botones de la miniatura en la barra de tareas de Windows."""

    PREV, PLAY, NEXT = 101, 102, 103

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.ptr = None
        self.ok = False
        self._filter = None
        self._icons = {}
        self._on_button = None
        if not IS_WIN or not hwnd:
            return
        try:
            ole32 = ctypes.windll.ole32
            ole32.CoInitialize(None)
            ptr = ctypes.c_void_p()
            clsid, iid = _GUID(CLSID_TaskbarList), _GUID(IID_ITaskbarList3)
            hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr))
            if hr != 0 or not ptr.value:
                return
            self.ptr = ptr
            _method(ptr, 3)(ptr)               # HrInit
            self.ok = True
        except Exception as e:
            logging.debug(f"Barra de tareas: {e}")

    # -- progreso
    def set_progress(self, percent):
        """Avance de las descargas (0 a 100) o None para quitarlo."""
        if not self.ok:
            return
        try:
            if percent is None:
                _method(self.ptr, 10, wintypes.HWND, ctypes.c_int)(self.ptr, self.hwnd, TBPF_NOPROGRESS)
                return
            _method(self.ptr, 10, wintypes.HWND, ctypes.c_int)(self.ptr, self.hwnd, TBPF_NORMAL)
            _method(self.ptr, 9, wintypes.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong)(
                self.ptr, self.hwnd, int(max(0, min(100, percent))), 100)
        except Exception:
            pass

    def set_state(self, state: int):
        if not self.ok:
            return
        try:
            _method(self.ptr, 10, wintypes.HWND, ctypes.c_int)(self.ptr, self.hwnd, state)
        except Exception:
            pass

    def set_overlay(self, pixmap, description: str = ""):
        """Marca pequeña sobre el icono (por ejemplo ✓ al terminar); `None` la quita."""
        if not self.ok:
            return
        try:
            hicon = _icon_from_pixmap(pixmap, 16) if pixmap is not None else None
            _method(self.ptr, 18, wintypes.HWND, wintypes.HICON, wintypes.LPCWSTR)(self.ptr, self.hwnd, hicon, description)
        except Exception:
            pass

    # -- botones de la miniatura
    def add_thumb_buttons(self, pixmaps: dict, callback):
        """`pixmaps` = {PREV: ..., PLAY: ..., NEXT: ...}; `callback(id)` se llama al pulsar uno."""
        if not self.ok:
            return
        try:
            buttons = (_ThumbButton * 3)()
            tips = {self.PREV: "Anterior", self.PLAY: "Reproducir / pausa", self.NEXT: "Siguiente"}
            for i, bid in enumerate((self.PREV, self.PLAY, self.NEXT)):
                icon = _icon_from_pixmap(pixmaps[bid])
                self._icons[bid] = icon
                b = buttons[i]
                b.dwMask = THB_ICON | THB_TOOLTIP | THB_FLAGS
                b.iId = bid
                b.hIcon = icon
                b.szTip = tips[bid]
                b.dwFlags = 0
            _method(self.ptr, 15, wintypes.HWND, wintypes.UINT, ctypes.c_void_p)(self.ptr, self.hwnd, 3, ctypes.addressof(buttons))
            self._on_button = callback
            self._filter = _ThumbFilter(self.hwnd, callback)
            QApplication.instance().installNativeEventFilter(self._filter)
        except Exception as e:
            logging.debug(f"Botones de la miniatura: {e}")

    def update_play_icon(self, pixmap):
        """Cambia el icono del botón central (reproducir ⇄ pausa)."""
        if not self.ok or self._filter is None:
            return
        try:
            icon = _icon_from_pixmap(pixmap)
            self._icons[self.PLAY] = icon
            b = _ThumbButton()
            b.dwMask = THB_ICON
            b.iId = self.PLAY
            b.hIcon = icon
            _method(self.ptr, 16, wintypes.HWND, wintypes.UINT, ctypes.c_void_p)(self.ptr, self.hwnd, 1, ctypes.addressof(b))
        except Exception:
            pass

    def shutdown(self):
        if self._filter is not None:
            try:
                QApplication.instance().removeNativeEventFilter(self._filter)
            except Exception:
                pass
            self._filter = None
        self.ok = False
