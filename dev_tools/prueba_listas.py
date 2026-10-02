import faulthandler; faulthandler.dump_traceback_later(100, exit=True)
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
app = QApplication([])
from ui.main_window import MainWindow
from services.playlist_service import PlaylistService
from services.artist_service import ArtistService
def pump(s=0.3):
    t=time.time()
    while time.time()-t<s: app.processEvents(); time.sleep(0.02)
def check(l,c): print(("OK   " if c else "FALLO"), l, flush=True)
w = MainWindow(); w.audio_output.setVolume(0); w.show(); pump(0.6)
print("min", w.minimumSize().width(), w.minimumSize().height())
lib = w.library_items()
pid = PlaylistService.create_playlist("Sync"); w.refresh_playlists_sidebar()
PlaylistService.add_track_to_playlist(pid, lib[0])
w.open_list("playlist", pid); pump()
pg = w.page_playlist
c0 = list(pg._cards.values())[0]
side_before = dict((k, v[0]) for k, v in w._side_items.items())
PlaylistService.add_track_to_playlist(pid, lib[1])
w.reload_current_list(); pump()
check("al añadir: la fila existente se conserva", list(pg._cards.values())[0] is c0 and len(pg._cards) == 2)
check("sidebar: items conservados", all(w._side_items[k][0] is v for k, v in side_before.items() if k in w._side_items and k != f"playlist:{pid}"))
PlaylistService.remove_track_from_playlist(pid, str(lib[1]['id']))
w.reload_current_list(); pump()
check("al quitar: solo desaparece una fila", len(pg._cards) == 1 and list(pg._cards.values())[0] is c0)
PlaylistService.rename_playlist(pid, "Renombrada"); w.reload_current_list(); pump()
check("renombrar sin recargar", pg.title_lbl.text() == "Renombrada" and list(pg._cards.values())[0] is c0)
# seguir artista
w.toggle_follow_artist(1126808565, "Bad Bunny", ""); pump(0.5)
check("artista aparece en sidebar", "artist:1126808565" in w._side_items)
w.set_library_filter("artists"); pump()
check("filtro artistas", set(w._side_items) == {"artist:1126808565"})
w.set_library_filter("all"); pump()
w.toggle_follow_artist(1126808565, "Bad Bunny", ""); pump()
check("dejar de seguir", "artist:1126808565" not in w._side_items)
# ventana pequeña (mini) sigue ok
w.play_local_file(lib[0]['local_path']); pump(0.5)
w.toggle_mini_player(); pump(0.5); w.stop_player(); pump(0.4)
check("mini -> stop restaura", not w.is_mini_mode and w.sidebar.isVisible())
PlaylistService.delete_playlist(pid)
print("FIN")
