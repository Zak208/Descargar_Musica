"""Pruebas de la biblioteca: repetidas, mejorar etiquetas, listas automáticas, estadísticas, selección múltiple y reordenar.
Se ejecuta desde la carpeta del proyecto:  python pruebas/prueba_biblioteca.py"""
import glob
import os
import shutil
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

app = QApplication([])
from services import duplicates, library_db, library_service, local_mixes, tag_fixer
from services.metadata_service import MetadataService
from services.playlist_service import PlaylistService


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


songs = glob.glob(os.path.expanduser("~/Music/Canciones_YouTube/*.mp3"))[:3]
tmp = tempfile.mkdtemp(prefix="bib_")
a1 = os.path.join(tmp, "Quevedo - Tema (Official Video).mp3")
a2 = os.path.join(tmp, "Quevedo - Tema.mp3")
other = os.path.join(tmp, "Otra cosa.mp3")
shutil.copy(songs[0], a1)
shutil.copy(songs[0], a2)
shutil.copy(songs[1], other)
for path, title in ((a1, "Tema (Official Video)"), (a2, "Tema"), (other, "Otra cosa")):
    MetadataService.embed_metadata(path, title, "Quevedo", "")
items = library_service.load_items_sync(tmp)

# ---- repetidas
groups = duplicates.find_duplicates(items)
check("repetidas: encuentra el par y no la otra canción", len(groups) == 1 and len(groups[0]) == 2
      and {os.path.basename(e["item"]["local_path"]) for e in groups[0]} ==
      {"Quevedo - Tema (Official Video).mp3", "Quevedo - Tema.mp3"})
check("repetidas: una se conserva y otra se propone quitar", sum(1 for e in groups[0] if e["keep"]) == 1)
check("título normalizado ignora «(Official Video)»",
      duplicates.normalize_title("Tema (Official Video)") == duplicates.normalize_title("TEMA"))
check("artista principal ignora colaboraciones",
      duplicates.primary_artist("Bizarrap & Quevedo") == duplicates.primary_artist("Bizarrap"))

# ---- mejorar etiquetas
poor = {"title": "tema raro", "uploader": "Música local", "album": "",
        "local_path": os.path.join(tmp, "Daft Punk - Get Lucky.mp3")}
check("etiquetas: detecta las pobres", tag_fixer.needs_fixing(poor) and not tag_fixer.needs_fixing(
    {"uploader": "Daft Punk", "album": "RAM", "title": "x", "local_path": "a.mp3"}))
check("etiquetas: deduce artista y título del nombre del archivo", tag_fixer.guess_query(poor) == ("Daft Punk", "Get Lucky"))
fake = [{"trackName": "Get Lucky", "artistName": "Daft Punk", "collectionName": "Random Access Memories",
         "artworkUrl100": "https://x/100x100bb.jpg", "releaseDate": "2013-05-17T07:00:00Z", "primaryGenreName": "Electronic"},
        {"trackName": "Otra", "artistName": "Otro", "collectionName": "Z"}]
match, score = tag_fixer.best_match("Daft Punk", "Get Lucky", fake)
check("etiquetas: elige la ficha correcta", match["collectionName"] == "Random Access Memories" and score > 0.9)
check("etiquetas: rechaza fichas que no se parecen", tag_fixer.best_match("Daft Punk", "Get Lucky", [fake[1]])[0] is None)
check("etiquetas: portada en alta resolución", "600x600bb" in tag_fixer.hires_cover("https://x/100x100bb.jpg"))
real_search = tag_fixer.search_itunes
tag_fixer.search_itunes = lambda term, limit=6: fake
suggestion = tag_fixer.suggestion_for(poor)
tag_fixer.search_itunes = real_search
check("etiquetas: propuesta completa", suggestion and suggestion["proposed"]["album"] == "Random Access Memories"
      and suggestion["current"]["artist"] == "Música local")
target = os.path.join(tmp, "Daft Punk - Get Lucky.mp3")
shutil.copy(songs[2], target)
sug = {"path": target, "current": {}, "proposed": {"title": "Get Lucky", "artist": "Daft Punk",
                                                       "album": "Random Access Memories", "cover": ""}, "score": 0.95}
check("etiquetas: se aplican al archivo", tag_fixer.apply_suggestions([sug]) == 1
      and MetadataService.read_metadata(target)["artist"] == "Daft Punk")

# ---- listas automáticas y estadísticas
now = time.time()
lib = [dict(it, added_ts=now - 40 * 86400, duration_secs=200) for it in items]
lib[0]["added_ts"] = now - 3600
lib[1]["duration_secs"] = 500
stats = {lib[0]["local_path"]: (5, now), lib[1]["local_path"]: (1, now - 50 * 86400)}
smart = {k: t for k, _n, t in local_mixes.smart_lists(lib, stats, now)}
check("automática: añadidas esta semana", [i["local_path"] for i in smart["week"]] == [lib[0]["local_path"]])
check("automática: canciones largas", [i["local_path"] for i in smart["long"]] == [lib[1]["local_path"]])
check("automática: lo más escuchado", smart["top"][0]["local_path"] == lib[0]["local_path"])
check("automática: aún sin escuchar", all(stats.get(i["local_path"], (0, 0))[0] == 0 for i in smart["never"]))
check("redescubre: solo lo que lleva tiempo sin sonar",
      all(i["local_path"] != lib[0]["local_path"] for i in local_mixes.rediscover(lib, stats, now=now)))
library_db.register_play(items[0]["local_path"])
library_db.register_play(items[0]["local_path"])
library_db.register_play(items[1]["local_path"])
check("estadísticas: se cuentan las reproducciones", library_db.play_stats()[items[0]["local_path"]][0] == 2
      and library_db.top_played()[0] == items[0]["local_path"])

# ---- mover canciones de una playlist
pid = PlaylistService.create_playlist("Orden")
for it in items:
    PlaylistService.add_track_to_playlist(pid, it)
ids = [t["id"] for t in PlaylistService.get_playlists()[pid]["tracks"]]
PlaylistService.move_tracks(pid, [ids[2]], 0)
now_ids = [t["id"] for t in PlaylistService.get_playlists()[pid]["tracks"]]
check("mover: una canción pasa al principio", now_ids == [ids[2], ids[0], ids[1]] + ids[3:])
PlaylistService.move_tracks(pid, [ids[2], ids[0]], len(ids))
now_ids = [t["id"] for t in PlaylistService.get_playlists()[pid]["tracks"]]
check("mover: varias canciones al final conservando su orden", now_ids[-2:] == [ids[2], ids[0]])

# ---- ventana: selección múltiple, barra de acciones y reordenar
from ui.main_window import MainWindow

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(2.5)
w.open_list("downloads")
pump(1.5)
page = w.page_playlist
rows = page._ordered_rows()
w.select_row(rows[0])
w.select_row(rows[3], "range")
check("selección: Mayús + clic marca un rango", len(w._alive_rows()) == 4 and page.selection_bar.isVisible())
w.select_row(rows[1], "toggle")
check("selección: Ctrl + clic quita una", len(w._alive_rows()) == 3 and rows[1] not in w._alive_rows())
check("selección: el texto de la barra", "3 canciones" in page.selection_bar.count.text())
before = len(w.playback_queue)
page.selection_action("queue")
pump(0.4)          # la barra se pliega con una animación breve
check("selección: reproducir a continuación las 3", len(w.playback_queue) == before + 3 and not page.selection_bar.isVisible())
w.playback_queue.clear()
w.select_row(rows[0])
w.select_row(rows[2], "toggle")
w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
check("selección: Esc la quita", len(w._alive_rows()) == 0)

# arrastrar varias a una lista
fav_before = len(PlaylistService.get_favorites())
added = w.add_tracks_to_list("favorites", None, [dict(r.item_info) for r in rows[:3]])
check("arrastrar varias canciones a favoritas", added == 3 and len(PlaylistService.get_favorites()) == fav_before + 3)
for r in rows[:3]:
    PlaylistService.toggle_favorite(r.item_info)

# quitar varias de una playlist (con deshacer)
pid2 = PlaylistService.create_playlist("Varias")
for it in w.library_items()[:5]:
    PlaylistService.add_track_to_playlist(pid2, it)
w.open_list("playlist", pid2)
pump(1.2)
page = w.page_playlist
prow = page._ordered_rows()
w.select_row(prow[0])
w.select_row(prow[2], "range")
page.selection_action("remove")
pump(0.4)
check("quitar varias de la lista", len(PlaylistService.get_playlists()[pid2]["tracks"]) == 2)
w.perform_undo()
pump(0.4)
check("deshacer devuelve las varias en su sitio", len(PlaylistService.get_playlists()[pid2]["tracks"]) == 5)

# reordenar arrastrando
page = w.page_playlist
check("reordenar: permitido en una playlist con su orden", page.reorder_enabled())
ids = [t["id"] for t in PlaylistService.get_playlists()[pid2]["tracks"]]
page._reorder([ids[4]], 0)
pump(0.4)
check("reordenar: la última pasa a la primera", PlaylistService.get_playlists()[pid2]["tracks"][0]["id"] == ids[4])
page.set_sort("title")
check("reordenar: no se permite si está ordenada por otra cosa", not page.reorder_enabled())
page.set_sort("custom", False)

# biblioteca, Inicio y listas automáticas
w.open_library()
pump(0.8)
kinds = [t.kind for t in w.page_library.cards._tiles if hasattr(t, "kind")]
check("biblioteca: aparecen las listas automáticas", "smart" in kinds)
library_db.register_play(w.library_items()[0]["local_path"])
w.refresh_home()
pump(0.5)
check("Inicio: «Lo más escuchado» con tus reproducciones", not w.home_top_box.isHidden())
w.open_list("smart", "top")
pump(0.8)
check("lista automática «Lo más escuchado» se abre", w._current_list == ("smart", "top"))
PlaylistService.delete_playlist(pid)
PlaylistService.delete_playlist(pid2)
shutil.rmtree(tmp, ignore_errors=True)
print("FIN")
