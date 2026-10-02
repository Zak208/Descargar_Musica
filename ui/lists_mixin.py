"""Biblioteca y listas estilo Spotify: canciones que te gustan, descargas, playlists y menú de cada canción."""
import os
import re

import json

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMenu, QFileDialog

from config import HISTORY_FILE, get_download_dir
from services import library_db, local_mixes
from services.library_service import LibraryScanWorker, LibraryWatcher
from services.recommendation_service import AlbumResolver, ArtistResolver
from services.playlist_service import PlaylistService
from services.artist_service import ArtistService
from ui.icons import icon
from ui.styles import accent
from ui.sidebar import SideListItem
from ui.formatting import split_artists
from ui.save_popup import SavePopup
from ui.covers import import_cover, artist_avatar_path, AvatarDownloader
from ui.dialogs import ask_text
from ui.pages import Page


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower())


class ListsMixin:
    """Mezcla para MainWindow. Requiere: page_playlist, page_library, stacked_widget, playlists_container,
    notify(), switch_to_page(), _local_id(), _play_entry(), set_context() y toggle_shuffle()."""

    def init_lists_state(self):
        self._lib_items = None
        self._lib_worker = None
        self._rescan_pending = False
        self._history_cache = None
        self._home_dirty = False
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(900)
        self._rescan_timer.timeout.connect(self._start_scan)
        self._lib_watcher = LibraryWatcher(self)
        self._lib_watcher.changed.connect(self.rescan_library)
        self._lib_index = None
        self._current_list = None
        self._page_before_list = 0
        self._lib_filter = "all"
        self._side_items = {}
        self._avatar_jobs = []
        QTimer.singleShot(50, self._first_scan)

    # ------------------------------------------------------------ biblioteca
    def watch_library(self):
        """Vigila la carpeta de música: si borras, añades o renombras un archivo, la app se pone al día sola."""
        self._lib_watcher.watch(str(get_download_dir()))

    def invalidate_library(self):
        self._lib_index = None
        self._history_cache = None

    def library_items(self) -> list:
        """Canciones descargadas (más recientes primero) con título, artista, álbum y duración."""
        if self._lib_items is None:
            # aún no terminó la primera lectura (se hace en segundo plano): leerla aquí bloquearía la ventana
            if self._lib_worker is None or not self._lib_worker.isRunning():
                self._start_scan()
            return []
        return self._lib_items

    def rescan_library(self):
        """Vuelve a leer la biblioteca en segundo plano (con una pequeña espera para agrupar cambios)."""
        self._rescan_timer.start()

    def _first_scan(self):
        if self._lib_items is None and (self._lib_worker is None or not self._lib_worker.isRunning()):
            self._start_scan()

    def _start_scan(self):
        if self._lib_worker is not None and self._lib_worker.isRunning():
            self._rescan_pending = True
            return
        self._lib_worker = LibraryScanWorker(str(get_download_dir()))
        self._lib_worker.ready.connect(self._on_library_scanned)
        self._lib_worker.start()

    def _on_library_scanned(self, items: list):
        previous = {(it["local_path"], it["added_ts"]) for it in (self._lib_items or [])}
        current = {(it["local_path"], it["added_ts"]) for it in items}
        first = self._lib_items is None
        self._lib_items = items
        self.invalidate_library()
        if first or previous != current:
            self._home_dirty = True
            self.watch_library()
            self.refresh_playlists_sidebar()
            self.update_header_info()
            if self.stacked_widget.currentIndex() == Page.HOME:
                self.refresh_home()
                self._home_dirty = False
            self.reload_current_list()
            self.refresh_tiles_state()
            if not first:
                self._check_library_milestone(len(items))
            if first:
                self.refresh_recommendations()
                self.restore_session()
                QTimer.singleShot(900, self.maybe_show_welcome)
        if self._rescan_pending:
            self._rescan_pending = False
            self.rescan_library()

    def _check_library_milestone(self, count: int):
        """Al pasar de un múltiplo de 100 canciones (100, 200…), pequeña celebración."""
        from config import load_settings, save_settings
        settings = load_settings()
        last = int(settings.get("library_milestone", 0) or 0)
        reached = (count // 100) * 100
        if reached > last and reached >= 100:
            settings["library_milestone"] = reached
            save_settings(settings)
            self.notify(f"¡Ya tienes {reached} canciones en tu música!")
            self.celebrate("hito")
        elif reached < last:
            settings["library_milestone"] = reached
            save_settings(settings)

    def history_map(self) -> dict:
        """Historial de descargas (se lee una sola vez y se guarda en memoria)."""
        if self._history_cache is None:
            data = {}
            try:
                if HISTORY_FILE.exists():
                    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
            except Exception:
                data = {}
            self._history_cache = data if isinstance(data, dict) else {}
        return self._history_cache

    def _library_index(self) -> dict:
        if self._lib_index is None:
            index = {}
            for it in self.library_items():
                path = it['local_path']
                index.setdefault(_norm(os.path.splitext(os.path.basename(path))[0]), path)
                index.setdefault(_norm(f"{it['uploader']} - {it['title']}"), path)
            self._lib_index = index
        return self._lib_index

    def resolve_local(self, info: dict):
        """Ruta del archivo descargado de esta canción, o None si no está descargada."""
        lp = info.get('local_path')
        if lp and os.path.isfile(lp):
            return lp
        tid = str(info.get('id') or '')
        if tid:
            hist = self.history_map().get(tid)
            if hist and hist.get('file_path') and os.path.isfile(hist['file_path']):
                return hist['file_path']
        index = self._library_index()
        title, artist = info.get('title', ''), info.get('uploader', '')
        for key in (_norm(f"{artist} - {title}"), _norm(title) if not artist else None):
            if key and key in index:
                return index[key]
        return None

    # --------------------------------------------------------- barra lateral
    def set_library_filter(self, key: str):
        """Filtro de 'Tu biblioteca' en la barra lateral (Todo / Listas / Artistas), como en Spotify."""
        self._lib_filter = key
        for k, chip in getattr(self, "library_chips", {}).items():
            chip.setChecked(k == key)
        self.refresh_playlists_sidebar()

    def refresh_playlists_sidebar(self):
        """Actualiza las listas y artistas de la barra lateral. Solo toca las filas que cambiaron."""
        def count_text(n: int) -> str:
            return "Lista · 1 canción" if n == 1 else f"Lista · {n} canciones"

        entries = []   # (clave, tipo, id, título, subtítulo, firma)
        if self._lib_filter in ("all", "lists"):
            nfav = len(PlaylistService.get_favorites())
            entries.append(("favorites:favorites", "favorites", "favorites", "Canciones que te gustan", count_text(nfav), None))
            ndl = len(self._lib_items) if self._lib_items is not None else 0
            entries.append(("downloads:downloads", "downloads", "downloads", "Mis descargas", count_text(ndl), None))
            for p_id, p_data in PlaylistService.get_playlists().items():
                entries.append((f"playlist:{p_id}", "playlist", p_id, p_data.get("name", "Playlist"),
                                count_text(len(p_data.get("tracks", []))), PlaylistService.get_cover_path(p_id)))
        if self._lib_filter in ("all", "artists"):
            for art in ArtistService.get_followed():
                has_photo = os.path.exists(artist_avatar_path(art["id"]))
                entries.append((f"artist:{art['id']}", "artist", art["id"], art["name"], "Artista", has_photo))

        layout = self.playlists_container
        wanted = {e[0] for e in entries}

        def drop(key):
            widget, _sig = self._side_items.pop(key)
            layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()

        for key in [k for k in self._side_items if k not in wanted]:
            drop(key)

        for pos, (key, kind, list_id, title, subtitle, extra) in enumerate(entries):
            signature = (title, subtitle, extra)
            existing = self._side_items.get(key)
            if existing and existing[1] != signature:
                drop(key)
                existing = None
            if existing is None:
                item = SideListItem(kind, list_id, title, subtitle)
                if kind == "artist":
                    art = next((a for a in ArtistService.get_followed() if a["id"] == list_id), None)
                    item.clicked.connect(lambda a=art: a and self.open_artist_by_name(a))
                    item.context_requested.connect(lambda pos_, a=art: a and self._artist_menu(a, pos_))
                else:
                    item.clicked.connect(lambda k=kind, lid=list_id: self.open_list(k, lid))
                    item.track_dropped.connect(lambda info, k=kind, lid=list_id: self.on_track_dropped(k, lid, info))
                    if kind == "playlist":
                        item.context_requested.connect(lambda pos_, pid=list_id: self._playlist_menu(pid, pos_))
                layout.insertWidget(pos, item)
                self._side_items[key] = (item, signature)
            else:
                widget = existing[0]
                current = layout.itemAt(pos).widget() if pos < layout.count() else None
                if current is not widget:
                    layout.removeWidget(widget)
                    layout.insertWidget(pos, widget)

        hint = getattr(self, "side_hint", None)
        if hint is not None:
            hint.setVisible(self._lib_filter == "artists" and not ArtistService.get_followed())

    # ---------------------------------------------------------------- artistas
    def toggle_follow_artist(self, artist_id, name: str, avatar: str = "") -> bool:
        """Sigue o deja de seguir a un artista. Los que sigues aparecen en la barra lateral y en Inicio."""
        now_following = ArtistService.toggle(artist_id, name, avatar)
        if now_following:
            job = AvatarDownloader(artist_id, avatar)
            job.done.connect(lambda _id: self._on_avatar_ready())
            self._avatar_jobs.append(job)
            job.start()
            self.notify(f"Ahora sigues a {name}")
        else:
            self.notify_undo(f"Has dejado de seguir a {name}",
                             lambda: self.toggle_follow_artist(artist_id, name, avatar))
        self.refresh_playlists_sidebar()
        self.refresh_home()
        if self.stacked_widget.currentIndex() == Page.LIBRARY:
            self._load_library_page(animate=False)
        return now_following

    def _on_avatar_ready(self):
        self.refresh_playlists_sidebar()
        self.refresh_home()
        if self.stacked_widget.currentIndex() == Page.LIBRARY:
            self._load_library_page(animate=False)

    def _artist_menu(self, artist: dict, pos):
        menu = QMenu(self)
        menu.addAction(icon("user.svg"), "Ver perfil").triggered.connect(lambda: self.open_artist_by_name(artist))
        menu.addAction(icon("x.svg"), "Dejar de seguir").triggered.connect(
            lambda: self.toggle_follow_artist(artist["id"], artist["name"], artist.get("avatar", "")))
        menu.exec(pos)

    def _library_card_clicked(self, kind: str, list_id: str):
        if kind == "artist":
            art = next((a for a in ArtistService.get_followed() if a["id"] == list_id), None)
            if art:
                self.open_artist_by_name(art)
        else:
            self.open_list(kind, list_id)

    def unfollow_from_library(self, artist_id: str):
        art = next((a for a in ArtistService.get_followed() if a["id"] == artist_id), None)
        if art:
            self.toggle_follow_artist(art["id"], art["name"], art.get("avatar", ""))

    def _playlist_menu(self, p_id: str, pos):
        menu = QMenu(self)
        menu.addAction(icon("edit.svg"), "Cambiar nombre").triggered.connect(lambda: self.rename_playlist(p_id))
        menu.addAction(icon("palette.svg"), "Cambiar imagen").triggered.connect(lambda: self.change_playlist_cover(p_id))
        if PlaylistService.get_cover_path(p_id):
            menu.addAction(icon("x.svg"), "Quitar imagen").triggered.connect(lambda: self.remove_playlist_cover(p_id))
        menu.addSeparator()
        menu.addAction(icon("trash.svg"), "Eliminar lista").triggered.connect(lambda: self.delete_playlist(p_id))
        menu.exec(pos)

    def change_playlist_cover(self, p_id: str):
        path, _ = QFileDialog.getOpenFileName(
            self, "Elige una imagen para tu lista", "", "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        if import_cover(p_id, path):
            self.notify("Imagen de la lista actualizada")
            self.reload_current_list()
            self.refresh_playlists_sidebar()
        else:
            self.notify("No se pudo usar esa imagen. Prueba con otra.")

    def remove_playlist_cover(self, p_id: str):
        PlaylistService.set_cover_filename(p_id, None)
        self.notify("Imagen quitada")
        self.reload_current_list()
        self.refresh_playlists_sidebar()

    def rename_playlist(self, p_id: str):
        current = PlaylistService.get_playlists().get(p_id, {}).get("name", "")
        name, ok = ask_text(self, "Cambiar nombre", "Nuevo nombre de la lista", text=current, ok="Guardar")
        if ok and name.strip():
            PlaylistService.rename_playlist(p_id, name.strip())
            self.refresh_playlists_sidebar()
            if self._current_list == ("playlist", p_id):
                self.open_list("playlist", p_id)
            else:
                self.open_library()

    def delete_playlist(self, p_id: str):
        """Elimina la lista al momento y ofrece «Deshacer» (tus canciones descargadas nunca se borran)."""
        name = PlaylistService.get_playlists().get(p_id, {}).get("name", "esta lista")
        snapshot = PlaylistService.snapshot_playlist(p_id)
        if not PlaylistService.delete_playlist(p_id):
            return
        self.refresh_playlists_sidebar()
        self.open_library()

        def undo():
            if PlaylistService.restore_playlist(p_id, snapshot):
                self.refresh_playlists_sidebar()
                self.open_library()
        self.notify_undo(f"Lista «{name}» eliminada", undo)

    # ------------------------------------------------------------ navegación
    def open_library(self):
        self._current_list = None
        self._load_library_page(animate=True)
        self.switch_to_page(Page.LIBRARY)

    def _list_data(self, kind: str, list_id):
        """(nombre, canciones, id) de una lista, o None si ya no existe."""
        playlists = PlaylistService.get_playlists()
        if kind == "favorites":
            return "Canciones que te gustan", PlaylistService.get_favorites(), "favorites"
        if kind == "downloads":
            return "Mis descargas", self.library_items(), "downloads"
        if kind == "playlist" and list_id in playlists:
            return playlists[list_id].get("name", "Playlist"), playlists[list_id].get("tracks", []), list_id
        if kind == "genre" and self._custom_mix:
            return self._custom_mix["name"], self._custom_mix["tracks"], int(list_id or 0)
        if kind == "artist_local":
            return str(list_id), self.local_artist_items(str(list_id)), str(list_id)
        if kind == "album_local":
            return str(list_id), self.local_album_items(str(list_id)), str(list_id)
        if kind == "localmix":
            idx = int(list_id if list_id is not None else 0)
            if 0 <= idx < len(self._local_mixes):
                return self._local_mixes[idx]["name"], self._local_mixes[idx]["tracks"], idx
            return None
        if kind == "smart":
            found = self.smart_list_items(str(list_id))
            return (found[0], found[1], str(list_id)) if found else None
        if kind == "mix":
            mixes = (self._rec_data or {}).get("mixes", [])
            idx = int(list_id if list_id is not None else 0)
            if 0 <= idx < len(mixes):
                return mixes[idx]["name"], mixes[idx]["tracks"], idx
        return None

    def open_list(self, kind: str, list_id=None):
        data = self._list_data(kind, list_id)
        if data is None:
            return
        name, tracks, list_id = data
        current = self.stacked_widget.currentIndex()
        if current == 4 and self._current_list == (kind, list_id):
            self.page_playlist.sync(name, tracks)   # ya estás en esta lista: se actualiza sin recargar
            return
        if current != 4:
            self._page_before_list = current
        self._current_list = (kind, list_id)
        self.page_playlist.load(kind, list_id, name, tracks)
        self.switch_to_page(Page.LIST)
        self._travel_cover(lambda: self.page_playlist.tile)       # la portada pulsada viaja a la cabecera

    def open_playlist_page(self, p_id: str):
        self.open_list("playlist", p_id)

    def go_back_from_list(self):
        target = self._page_before_list if self._page_before_list not in (4,) else 5
        if target == 5:
            self.open_library()
        else:
            self.switch_to_page(target)

    def reload_current_list(self):
        """Pone al día lo que se está viendo (barra lateral y lista abierta) sin volver a cargarlo todo."""
        self.refresh_playlists_sidebar()
        if self.stacked_widget.currentIndex() == Page.LIST and self._current_list:
            kind, list_id = self._current_list
            data = self._list_data(kind, list_id)
            if data is None:
                self.open_library()
                return
            self.page_playlist.sync(data[0], data[1])
        elif self.stacked_widget.currentIndex() == Page.LIBRARY:
            self._load_library_page(animate=False)

    refresh_current_list = reload_current_list

    def _load_library_page(self, animate: bool = True):
        smart = [(k, n, len(t)) for k, n, t in local_mixes.smart_lists(self.library_items(), library_db.play_stats())]
        self.page_library.load(len(PlaylistService.get_favorites()), len(self.library_items()),
                               PlaylistService.get_playlists(), ArtistService.get_followed(), animate, smart)

    # ----------------------------------------------------------- reproducción
    def play_list(self, items: list, start, shuffle: bool = False):
        """Reproduce una lista: 'siguiente' y 'anterior' se mueven solo dentro de ella."""
        if self.is_offline():
            items = [i for i in items if self.playable(i)]      # sin conexión solo suena lo descargado
        if not items:
            if self.is_offline():
                self.notify("Sin conexión: en esta lista no hay canciones descargadas.")
            return
        import random
        self.set_context(items)
        if shuffle:
            if not self.is_shuffle_enabled:
                self.toggle_shuffle()
            start = random.randrange(len(items))
        self._play_entry(items[start or 0])

    def open_track_menu(self, info: dict, global_pos, extra=None):
        """Menú de una canción (los tres puntitos o el clic derecho), igual en búsqueda, listas y descargas."""
        menu = QMenu(self)
        local = info.get('local_path')
        local = local if (local and os.path.isfile(local)) else None

        def add(m, text, icon_name, slot, color=None):
            act = m.addAction(icon(icon_name, color) if color else icon(icon_name), text)
            act.triggered.connect(lambda _=False: slot())
            return act

        add(menu, "Reproducir", "play.svg", lambda: self._play_entry(info))
        add(menu, "Reproducir a continuación", "queue.svg", lambda: self.add_to_queue(info))
        menu.addSeparator()

        is_fav = PlaylistService.is_favorite(info.get('id'), info.get('title'), info.get('uploader', ''))
        add(menu, "Quitar de Canciones que te gustan" if is_fav else "Añadir a Canciones que te gustan",
            "added.svg" if is_fav else "plus_circle.svg",
            lambda: self.toggle_info_favorite(info), accent() if is_fav else None)

        pl_menu = menu.addMenu(icon("playlist.svg"), "Añadir a una lista")
        add(pl_menu, "Nueva lista...", "plus.svg", lambda: self.create_playlist_with_track(info))
        playlists = PlaylistService.get_playlists()
        if playlists:
            pl_menu.addSeparator()
            for p_id, data in playlists.items():
                act = pl_menu.addAction(data.get("name", "Lista"))
                act.triggered.connect(lambda _=False, pid=p_id: self.add_track_to_playlist(pid, info))

        if extra:   # por ejemplo «Quitar de esta lista» (solo en playlists propias)
            for text, callback in extra:
                add(menu, text, "x.svg", callback)

        if not local:
            add(menu, "Descargar", "download.svg", lambda: self.quick_download(dict(info)))

        # Ir al artista / al álbum
        menu.addSeparator()
        artists = split_artists(info.get("uploader", ""))
        if len(artists) == 1:
            add(menu, "Ir al artista", "user.svg", lambda a=artists[0]: self.open_artist_by_name({"name": a}))
        elif artists:
            sub = menu.addMenu(icon("user.svg"), "Ir al artista")
            for name in artists:
                act = sub.addAction(name)
                act.triggered.connect(lambda _=False, a=name: self.open_artist_by_name({"name": a}))
        if info.get("album"):
            add(menu, "Ir al álbum", "album.svg",
                lambda: self.open_album_by_name(artists[0] if artists else "", info["album"]))

        if local:
            menu.addSeparator()
            add(menu, "Editar nombre, artista y portada", "tag.svg", lambda: self.open_metadata_dialog(local))
            add(menu, "Cambiar nombre del archivo", "edit.svg", lambda: self.rename_file(local))
            add(menu, "Mostrar en la carpeta", "folder.svg", lambda: self.show_in_explorer(local))
            add(menu, "Borrar de mi música", "trash.svg", lambda: self.delete_file(local))
        menu.exec(global_pos)

    def open_album_by_name(self, artist: str, album: str):
        """Localiza el álbum de una canción y abre su página (sin conexión, muestra lo que tienes descargado de él)."""
        if self.is_offline():
            if self.local_album_items(album):
                self.open_list("album_local", album)
            else:
                self.notify("Sin conexión: no se puede abrir la página de este álbum.")
            return
        self.notify("Buscando el álbum...")
        self._album_resolver = AlbumResolver(artist, album)
        self._album_resolver.found.connect(self.open_album_details)
        self._album_resolver.failed.connect(lambda: self.notify("No se encontró la página de ese álbum."))
        self._album_resolver.start()

    def follow_artist_by_name(self, name: str, on_done=None):
        """Sigue a un artista del que solo se conoce el nombre (primero se localiza su perfil)."""
        resolver = ArtistResolver(name)

        def done(artist: dict):
            self.toggle_follow_artist(artist["id"], artist["name"], artist.get("avatar", ""))
            if on_done:
                on_done()

        resolver.found.connect(done)
        resolver.failed.connect(lambda: self.notify("No se pudo localizar a este artista."))
        self._follow_resolver = resolver
        resolver.start()

    def on_track_dropped(self, kind: str, list_id, infos):
        """Canciones soltadas sobre una lista de la barra lateral: se añaden a ella."""
        infos = [infos] if isinstance(infos, dict) else list(infos)
        start = None
        try:
            from PySide6.QtGui import QCursor
            start = QCursor.pos()
        except Exception:
            pass
        item = self.side_item(kind, list_id)           # la miniatura vuela hasta la lista y esta pulsa al llegar

        def arrived():
            from ui.animations import flash
            target = self.side_item(kind, list_id)
            if target is not None:
                flash(target, accent(), 0.28, 600, 8)

        self.add_tracks_to_list(kind, list_id, infos)
        self.fly_to(infos[0] if infos else {}, self.side_item(kind, list_id) or item, start, arrived)

    def add_tracks_to_list(self, kind: str, list_id, infos: list):
        """Añade varias canciones a «Canciones que te gustan» o a una playlist (sin repetir las que ya están)."""
        added = 0
        for info in infos:
            if kind == "favorites":
                if not PlaylistService.is_favorite(info.get("id"), info.get("title"), info.get("uploader", "")):
                    PlaylistService.toggle_favorite(info)
                    added += 1
            elif kind == "playlist":
                if PlaylistService.add_track_to_playlist(list_id, info):
                    added += 1
        name = ("Canciones que te gustan" if kind == "favorites"
                else PlaylistService.get_playlists().get(list_id, {}).get("name", "la lista"))
        if added:
            self.notify(f"{added} canción{'es' if added != 1 else ''} añadida{'s' if added != 1 else ''} a «{name}»")
        else:
            self.notify(f"Ya estaban en «{name}»")
        self.refresh_playlists_sidebar()
        self.refresh_current_list()
        self.sync_favorite_hearts()
        return added

    def save_button_clicked(self, info: dict, button):
        """Botón «+»: la primera vez guarda en «Canciones que te gustan»; si ya está guardada, abre la lista de listas."""
        if not PlaylistService.lists_containing(info):
            self.toggle_info_favorite(info)
            return
        popup = SavePopup(self, info)
        popup.popup_at(button)
        self._save_popup = popup

    def after_save_change(self, info: dict, key: str, now_in: bool):
        """Tras añadir/quitar una canción de una lista desde la listita: refresca marcas, barra lateral y lista abierta."""
        if key == "favorites":
            self.notify("Añadida a «Canciones que te gustan»" if now_in else "Quitada de «Canciones que te gustan»")
        else:
            name = PlaylistService.get_playlists().get(key, {}).get("name", "lista")
            self.notify(f"Añadida a «{name}»" if now_in else f"Quitada de «{name}»")
        self.sync_favorite_hearts()
        self.refresh_playlists_sidebar()
        self.refresh_current_list()

    def toggle_info_favorite(self, info: dict):
        stored = PlaylistService.get_favorite(str(info.get("id", "")), info.get("title", ""), info.get("uploader", ""))
        is_fav = PlaylistService.toggle_favorite(info)
        self.sync_favorite_hearts()
        if is_fav:
            self.notify("Añadida a «Canciones que te gustan»")
        elif stored:
            def undo():
                PlaylistService.restore_favorite(stored)
                self.sync_favorite_hearts()
                self.refresh_playlists_sidebar()
                self.refresh_current_list()
            self.notify_undo("Quitada de «Canciones que te gustan»", undo)
        else:
            self.notify("Quitada de «Canciones que te gustan»")
        self.refresh_playlists_sidebar()
        self.refresh_current_list()
