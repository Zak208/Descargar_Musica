"""Pruebas del modo sin conexión: banner, tarjetas oscurecidas, Inicio local, búsqueda local, descargas pendientes,
letras guardadas y listas locales. Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_sin_conexion.py"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication([])
from services import library_search, local_mixes, lyrics_store, network_service, pending_downloads
from services.lyrics_service import LyricsWorker
from services.playlist_service import PlaylistService


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


check("errores de red reconocidos", network_service.is_network_error("getaddrinfo failed")
      and network_service.is_network_error("HTTPSConnectionPool: Max retries exceeded") and not network_service.is_network_error("HTTP 404"))

from ui.main_window import MainWindow
from ui.track_row import TrackRow
from ui.song_card import SongResultCard

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(2.5)
items = w.library_items()
check("hay música local para probar", len(items) >= 3)

# ---- búsqueda local y mixes (no necesitan red)
found = library_search.search_items(items, "QUEVEDO")
check("búsqueda local ignora mayúsculas", found and all("quevedo" in (i["title"] + i["uploader"] + i.get("album", "")).lower() for i in found))
check("búsqueda local ignora acentos", library_search.fold("Canción Ñandú") == "cancion nandu")
mixes = local_mixes.build_local_mixes(items)
check("mixes locales generados", len(mixes) >= 1 and all(m["tracks"] for m in mixes))

# ---- una lista con una canción descargada y otra que no
pid = PlaylistService.create_playlist("Mezcla")
PlaylistService.add_track_to_playlist(pid, items[0])
remote = {"id": "yt-remota-1", "title": "Tema solo en internet", "uploader": "Alguien", "album": "", "url": "ytsearch1:x",
          "duration_secs": 200, "duration_str": "3:20", "thumbnail": ""}
PlaylistService.add_track_to_playlist(pid, remote)
w.open_list("playlist", pid)
pump(1.0)
rows = {r.item_info["title"]: r for r in w.page_playlist.tracks_widget.findChildren(TrackRow)}
check("online: las dos filas se pueden usar", all(r.isEnabled() for r in rows.values()))

# ---- se pierde la conexión
w.network.set_forced_offline(True)
pump(0.8)
check("sin conexión: aparece el aviso", w.offline_banner.isVisible() and "sin conexión" in w.offline_banner.text.text().lower())
check("sin conexión: la búsqueda pasa a tu música", "música descargada" in w.topbar.search.placeholderText())
check("sin conexión: la lista pasa a mostrar solo lo descargado", w.page_playlist.tab == "downloaded"
      and "disponibles sin conexión" in w.page_playlist.meta_lbl.text())
rows = {r.item_info["title"]: r for r in w.page_playlist.tracks_widget.findChildren(TrackRow)}
check("sin conexión: la descargada sigue normal y la otra no se muestra", rows[items[0]["title"]].isEnabled()
      and "Tema solo en internet" not in rows)
w.page_playlist.set_tab("all")
pump(0.4)
rows = {r.item_info["title"]: r for r in w.page_playlist.tracks_widget.findChildren(TrackRow)}
check("sin conexión: en «Todas» la no descargada sale oscurecida y sin poder usarse",
      not rows["Tema solo en internet"].isEnabled() and rows["Tema solo en internet"]._veil.isVisible())
check("offline_blocks distingue descargada y no descargada", w.offline_blocks(remote) and not w.offline_blocks(items[0]))
w.play_list([remote, items[0]], 0)
pump(1.5)
check("sin conexión: reproducir salta a la primera descargada",
      w.current_item_info and w.current_item_info.get("local_path") == items[0]["local_path"])
w.player.stop()

# ---- Inicio sin conexión
w.switch_to_page(0)
w.refresh_home()
pump(0.5)
check("Inicio: aviso grande sin conexión", w.home_offline_box.isVisible())
check("Inicio: mixes de tu música visibles", w.home_local_mixes_box.isVisible())
check("Inicio: lo que necesita internet está oculto", not w.home_mixes_box.isVisible() and not w.home_charts_box.isVisible()
      and not w.home_genres_box.isVisible())

# ---- búsqueda local
w.perform_search("quevedo")
pump(0.5)
cards = w.results_container.findChildren(SongResultCard)
check("búsqueda sin conexión: resultados locales", len(cards) >= 1 and "Sin conexión" in w.status_label.text())
check("búsqueda sin conexión: todos son descargados", all(c.item_info.get("local_path") for c in cards))

# ---- artista y álbum locales
w.open_artist_by_name({"name": "Quevedo"})
pump(0.8)
check("artista sin conexión: lista con tus canciones de él", w._current_list == ("artist_local", "Quevedo")
      and len(w.page_playlist.items) >= 1)

# ---- descargas pendientes
pending_downloads.clear()
w._reload_pending_keys()
w.quick_download(dict(remote))
check("descarga sin conexión: queda pendiente", pending_downloads.count() == 1 and w.is_pending(remote))
w.start_batch_download([dict(remote, id="yt-remota-2", title="Otra remota", url="ytsearch1:y")])
check("lote sin conexión: se añade a pendientes", pending_downloads.count() == 2)
started = []
w.start_batch_download_real = w.start_batch_download
w.network.set_forced_offline(False)
pump(0.8)
w.start_batch_download = lambda items, from_pending=False: started.append((len(items), from_pending))
w.resume_pending_downloads()
check("al volver internet se retoman las pendientes", started == [(2, True)])
check("al volver internet desaparece el aviso", not w.offline_banner.isVisible())
rows = w.page_playlist.tracks_widget.findChildren(TrackRow)
check("vuelven a poder usarse las filas", all(r.isEnabled() for r in rows))
pending_downloads.clear()

# ---- letras sin conexión
key = lyrics_store.key_for("Cancion de prueba", "Artista X")
lyrics_store.save_online(key, {"is_synced": True, "synced_lines": [(1000, "uno"), (2000, "dos")], "plain_text": "uno\ndos"})
got = []
w.network.set_forced_offline(True)
pump(0.3)
worker = LyricsWorker("Cancion de prueba", "Artista X", key)
worker.lyrics_ready.connect(got.append)
worker.start()
worker.wait(5000)
pump(0.3)
check("letra guardada: sale sin conexión", got and got[0]["is_synced"] and got[0]["synced_lines"][0] == (1000, "uno"))
errs = []
worker2 = LyricsWorker("Sin letra guardada", "Nadie", lyrics_store.key_for("Sin letra guardada", "Nadie"))
worker2.lyrics_error.connect(errs.append)
worker2.start()
worker2.wait(5000)
pump(0.3)
check("sin letra y sin conexión: mensaje claro", errs and "Sin conexión" in errs[0])

w.network.set_forced_offline(False)
PlaylistService.delete_playlist(pid)
print("FIN")
