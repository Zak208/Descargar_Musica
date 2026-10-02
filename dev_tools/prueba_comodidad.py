"""Pruebas de comodidad: deshacer, papelera, arrastrar y soltar, teclado en las listas, pegar enlaces, alto contraste.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_comodidad.py"""
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QMimeData, QUrl, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton

app = QApplication([])
from services import recycle
from services.playlist_service import PlaylistService
from ui import dragdrop


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


def key(k):
    return QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)


from ui.main_window import MainWindow
from ui.track_row import TrackRow

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(2.5)
items = w.library_items()

# ---- papelera de reciclaje
tmp = os.path.join(tempfile.mkdtemp(), "prueba_papelera.txt")
open(tmp, "w").write("hola")
check("papelera: el archivo se envía y desaparece", recycle.move_to_recycle_bin(tmp) and not os.path.exists(tmp))
check("papelera: un archivo inexistente no falla", recycle.move_to_recycle_bin(tmp) is False)

# ---- aviso con botón y deshacer
called = []
w.toast.show_message("Aviso con botón", action=("Deshacer", lambda: called.append(1)))
pump(0.5)
check("aviso: el botón se ve y es pulsable", w.toast.action_btn.isVisible()
      and not w.toast.testAttribute(Qt.WA_TransparentForMouseEvents))
w.toast.action_btn.click()
check("aviso: el botón ejecuta la acción", called == [1])
w.toast.show_message("Aviso normal")
check("aviso sin botón deja pasar el ratón", w.toast.testAttribute(Qt.WA_TransparentForMouseEvents) and not w.toast.action_btn.isVisible())

# quitar de una lista y deshacer
pid = PlaylistService.create_playlist("Con deshacer")
for it in items[:3]:
    PlaylistService.add_track_to_playlist(pid, it)
w.open_list("playlist", pid)
pump(1.0)
ids_before = [t["id"] for t in PlaylistService.get_playlists()[pid]["tracks"]]
page = w.page_playlist
second = [r for r in page._ordered_rows() if r.item_info["id"] == ids_before[1]][0]
page._remove_track(second.item_info)
pump(0.5)
check("quitar de la lista: ya no está", len(PlaylistService.get_playlists()[pid]["tracks"]) == 2)
w.perform_undo()
pump(0.5)
check("deshacer: vuelve a su sitio", [t["id"] for t in PlaylistService.get_playlists()[pid]["tracks"]] == ids_before)

# teclado en la lista
rows = page._ordered_rows()
check("teclado: ↓ marca la primera fila", page.handle_key(key(Qt.Key_Down)) and w._selected_row is rows[0])
page.handle_key(key(Qt.Key_Down))
check("teclado: ↓ pasa a la siguiente", w._selected_row is rows[1])
page.handle_key(key(Qt.Key_Up))
check("teclado: ↑ vuelve a la anterior", w._selected_row is rows[0])
page.handle_key(key(Qt.Key_Down))
page.handle_key(key(Qt.Key_Delete))
pump(0.4)
check("teclado: Supr quita la fila marcada de la lista", len(PlaylistService.get_playlists()[pid]["tracks"]) == 2)
w.perform_undo()
pump(0.4)
page.handle_key(key(Qt.Key_Down))
played = []
w.play_local_file = lambda p, **kw: played.append(p)
page.handle_key(key(Qt.Key_Return))
check("teclado: Intro reproduce la fila marcada", len(played) == 1)

# eliminar una lista y deshacer
snap = PlaylistService.get_playlists()[pid]["name"]
w.delete_playlist(pid)
pump(0.4)
check("eliminar lista: desaparece al momento (sin preguntar)", pid not in PlaylistService.get_playlists())
w.perform_undo()
pump(0.4)
check("deshacer: la lista vuelve entera", PlaylistService.get_playlists().get(pid, {}).get("name") == snap
      and len(PlaylistService.get_playlists()[pid]["tracks"]) == 3)

# favoritos: quitar y deshacer
info = dict(items[0])
if not PlaylistService.is_favorite(info["id"], info["title"]):
    PlaylistService.toggle_favorite(info)
w.toggle_info_favorite(info)
check("favorita: se quita", not PlaylistService.is_favorite(info["id"], info["title"]))
w.perform_undo()
check("favorita: deshacer la devuelve", PlaylistService.is_favorite(info["id"], info["title"]))

# ---- arrastrar y soltar
mime = QMimeData()
check("soltar: una canción arrastrada se reconoce", dragdrop.read_dropped_track(mime) is None)
from PySide6.QtCore import QByteArray
import json
mime.setData(dragdrop.TRACK_MIME, QByteArray(json.dumps({"tracks": [{"id": "x", "title": "Tema"}], "source": None}).encode()))
check("soltar: se lee la canción", dragdrop.read_dropped_track(mime) == {"id": "x", "title": "Tema"})
check("soltar en la ventana: una canción interna no se acepta como enlace", not dragdrop.can_accept_window_drop(mime))
m2 = QMimeData()
m2.setUrls([QUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ")])
check("soltar en la ventana: un enlace de YouTube se acepta", dragdrop.can_accept_window_drop(m2))
m3 = QMimeData()
m3.setUrls([QUrl("https://example.com/algo")])
check("soltar en la ventana: un enlace cualquiera no", not dragdrop.can_accept_window_drop(m3))
m4 = QMimeData()
m4.setUrls([QUrl.fromLocalFile(items[0]["local_path"])])
check("soltar en la ventana: un archivo de audio se acepta", dragdrop.can_accept_window_drop(m4))
dest = tempfile.mkdtemp()
copied = dragdrop.copy_into(dest, [items[0]["local_path"], items[0]["local_path"]])
check("importar: se copia sin pisar", len(copied) == 2 and copied[0] != copied[1] and all(os.path.isfile(c) for c in copied))
check("importar: no copia lo que ya está en la carpeta", dragdrop.copy_into(dest, copied) == [])
# soltar una canción sobre una lista de la barra lateral
w.on_track_dropped("playlist", pid, dict(items[4]))
check("soltar sobre una lista: se añade", PlaylistService.track_index(pid, items[4]["id"]) >= 0)
PlaylistService.delete_playlist(pid)

# ---- pegar enlace
searched = []
w.perform_search = lambda q: searched.append(q)
app.clipboard().setText("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
w.paste_link_from_clipboard()
check("Ctrl+V: un enlace se busca", searched and "youtube" in searched[0])
app.clipboard().setText("hola que tal")
searched.clear()
w.paste_link_from_clipboard()
check("Ctrl+V: texto cualquiera solo avisa", not searched)

# ---- accesibilidad
icon_only = [b for b in w.findChildren(QPushButton) if not b.text().strip() and b.toolTip()]
check("lectores de pantalla: los botones con icono tienen nombre", icon_only and all(b.accessibleName() for b in icon_only))
base = w.styleSheet()
w.set_high_contrast(True)
check("alto contraste: aclara los grises de los textos", "#B3B3B3" in base and "#B3B3B3" not in w.styleSheet())
w.set_high_contrast(False)
check("alto contraste: se puede quitar", "#B3B3B3" in w.styleSheet())
sd = w.settings_dialog
sd.scale_combo.setCurrentIndex(2)
from config import load_settings
check("tamaño de la aplicación: se guarda y pide reiniciar", abs(load_settings()["ui_scale"] - 1.3) < 0.01 and not sd.btn_restart.isHidden())
sd.scale_combo.setCurrentIndex(0)
print("FIN")
