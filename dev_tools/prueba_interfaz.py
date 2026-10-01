import faulthandler; faulthandler.dump_traceback_later(170, exit=True)
import os, sys, time, shutil, glob
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication, QPushButton, QLineEdit, QWidget
from PySide6.QtCore import QTimer, QPoint
app = QApplication([])
from ui.main_window import MainWindow
from ui.overlay import InlineDialog
from ui.dialogs import ask_text, ask_confirm
from ui.song_card import SongResultCard
from services.playlist_service import PlaylistService
from config import get_download_dir


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents(); time.sleep(0.02)


def wait(cond, timeout=25):
    t = time.time()
    while time.time() - t < timeout:
        app.processEvents(); time.sleep(0.03)
        if cond():
            return True
    return False


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


w = MainWindow(); w.audio_output.setVolume(0); w.resize(1360, 860); w.show(); pump(1.0)
wait(lambda: w._lib_items is not None, 15)
lib = w.library_items()
check(f"biblioteca en segundo plano ({len(lib)})", len(lib) > 0)

# ---- ventanas internas
def click_in_dialog(text_to_type=None, button_text="Crear"):
    host = w._overlay_host
    dlg = host._stack[-1]
    if text_to_type is not None:
        dlg.findChild(QLineEdit).setText(text_to_type)
    for b in dlg.findChildren(QPushButton):
        if b.text() == button_text:
            b.click(); return
    raise RuntimeError("botón no encontrado: " + button_text)

QTimer.singleShot(400, lambda: click_in_dialog("Lista de prueba", "Crear"))
name, ok = ask_text(w, "Nueva lista", "Ponle un nombre", ok="Crear")
check("ask_text dentro de la ventana", ok and name == "Lista de prueba" and not w._overlay_host.isVisible())
QTimer.singleShot(400, lambda: click_in_dialog(None, "Cancelar"))
check("ask_confirm cancelar", ask_confirm(w, "Eliminar", "¿Seguro?", ok="Eliminar", danger=True) is False)
check("sin ventanas aparte", not any(isinstance(x, InlineDialog) and x.isWindow() for x in QApplication.topLevelWidgets()))

# ---- ajustes y ecualizador como ventanas internas
QTimer.singleShot(400, lambda: w._overlay_host._stack[-1].reject())
w.open_settings(); check("ajustes interno", not w._overlay_host.isVisible())
QTimer.singleShot(400, lambda: w._overlay_host._stack[-1].reject())
w.open_equalizer(); check("ecualizador interno", not w._overlay_host.isVisible())

# ---- panel de descargas
w.downloads.entries[1] = {"title": "Cindy", "artist": "Lérica", "percent": 42, "state": "active", "error": ""}
w.downloads.changed.emit(); w.show_downloads_panel(); pump(0.3)
check("panel de descargas visible", w.downloads_panel.isVisible())
w.downloads_panel.reject(); pump(0.2)
check("panel se cierra", not w.downloads_panel.isVisible())
w.downloads.entries.clear(); w.downloads.changed.emit()

# ---- orden y filas perezosas
w.open_list("downloads"); wait(lambda: len(w.page_playlist._cards) > 0, 10); pump(0.3)
pg = w.page_playlist
order_before = [c.title_label.fullText() for c in pg.tracks_widget.findChildren(SongResultCard)]
pg.set_sort("title", False); pump(0.3)
cards = sorted(pg.tracks_widget.findChildren(SongResultCard), key=lambda c: c.y())
titles = [c.title_label.fullText().lower() for c in cards]
check("orden por título", titles == sorted(titles))
pg.set_sort("duration", True); pump(0.3)
cards = sorted(pg.tracks_widget.findChildren(SongResultCard), key=lambda c: c.y())
durs = [c.item_info.get("duration_secs", 0) for c in cards]
check("orden por duración", durs == sorted(durs, reverse=True))
fake = [{"id": f"f{i}", "title": f"Tema {i:03d}", "uploader": "Fake", "album": "A", "url": "ytsearch1:x", "duration_secs": 100 + i, "duration_str": "1:40", "thumbnail": ""} for i in range(120)]
w.page_playlist.load("mix", 0, "Mix falso", fake); wait(lambda: len(pg._cards) > 0, 5); pump(0.3)
check(f"filas perezosas (creadas {len(pg._cards)} de 120)", len(pg._cards) == 40)
pg._grow(); pump(0.2)
check("al bajar se crean más", len(pg._cards) == 80)
check("duración total en la cabecera", "h" in pg.meta_lbl.text() or "min" in pg.meta_lbl.text())

# ---- vigilancia de la carpeta
src = lib[0]["local_path"]
tmp = os.path.join(str(get_download_dir()), "__prueba_vigilancia.mp3")
shutil.copyfile(src, tmp)
check("aparece al copiar el archivo", wait(lambda: any(i["local_path"] == tmp for i in (w._lib_items or [])), 12))
os.remove(tmp)
check("desaparece al borrarlo", wait(lambda: not any(i["local_path"] == tmp for i in (w._lib_items or [])), 12))

# ---- carruseles con flechas
from ui.home_shelves import make_shelf
box, row = make_shelf("Prueba", 120)
for i in range(30):
    b = QPushButton(f"{i}"); b.setFixedSize(150, 80); row.addWidget(b)
box.resize(600, 200); box.show(); pump(0.3)
bar = box.scroll.horizontalScrollBar()
nexts = [x for x in box.findChildren(QPushButton) if x.objectName() == "ArrowBtn"]
nexts[1].click(); pump(0.5)
check("flecha derecha mueve el carrusel", bar.value() > 0)
nexts[0].click(); pump(0.5)
check("flecha izquierda vuelve", bar.value() == 0)

# ---- búsqueda con filtros y carga de más
w.perform_search("Coldplay")
check("resultados de búsqueda", wait(lambda: len(w._res["tracks"]) > 0, 25))
n0 = len(w._res["tracks"])
w.set_search_filter("albums"); pump(0.3)
check("filtro álbumes pide más", wait(lambda: len(w._res["albums"]) > 12, 25))
w.set_search_filter("tracks"); pump(0.5)
bar = w.scroll_area.verticalScrollBar()
w._maybe_load_more()
check("al llegar al final carga más canciones", wait(lambda: len(w._res["tracks"]) > n0, 25))

# ---- álbum: descargar y crear lista
alb = w._res["albums"][0]
w.open_album_details(alb["id"])
check("álbum cargado", wait(lambda: bool(w.page_album.album_data), 25))
called = []
w.start_batch_download = lambda items: called.append(len(items))
w.download_album_as_list(w.page_album.album_data)
pls = PlaylistService.get_playlists()
created = [pid for pid, d in pls.items() if d["name"] == w.page_album.album_data["name"]]
check("lista creada con el álbum", bool(created) and len(pls[created[0]]["tracks"]) == len(w.page_album.album_data["tracks"]) and called)
for pid in created:
    PlaylistService.delete_playlist(pid)
for pid, d in PlaylistService.get_playlists().items():
    if d["name"] == "Lista de prueba":
        PlaylistService.delete_playlist(pid)
for f in glob.glob(os.path.join("app_data", "covers", "*")):
    if "_tmp_" in f:
        os.remove(f)
print("FIN")
