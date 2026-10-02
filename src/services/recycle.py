"""Enviar archivos a la papelera de reciclaje de Windows (se pueden recuperar), en vez de borrarlos para siempre."""
import ctypes
import os
import sys
from ctypes import wintypes

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000     # si no cabe en la papelera, avisa en vez de borrarlo para siempre


class _SHFILEOPSTRUCT(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def move_to_recycle_bin(path: str) -> bool:
    """True si el archivo quedó en la papelera. Fuera de Windows (o si falla) no borra nada y devuelve False."""
    if sys.platform != "win32" or not os.path.exists(path):
        return False
    op = _SHFILEOPSTRUCT()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"          # la lista termina con un doble carácter nulo
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except Exception:
        return False
    return result == 0 and not op.fAnyOperationsAborted and not os.path.exists(path)


def open_recycle_bin() -> None:
    try:
        os.startfile("shell:RecycleBinFolder")
    except Exception:
        pass
