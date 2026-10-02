"""Inicio estilo Spotify: accesos rápidos, recientes, recomendaciones según tu música y artistas seguidos."""
import logging

from ui import perf


from services.artist_service import ArtistService
from services.playlist_service import PlaylistService
from services.recommendation_service import (
    RecommendationWorker, ArtistResolver, GenreTracksWorker, build_taste_profile, signature, load_cache, load_stale_cache
)
from ui.home_shelves import (
    TrackTile, ArtistTile, MixTile, GenreTile, QuickTile, make_shelf, clear_layout
)
from ui.formatting import format_total
from ui.home_widgets import RecentTrackCard
from ui.spotify_views import AlbumCard


class HomeMixin:
    """Mezcla para MainWindow. Requiere los widgets creados por home_page.build_home_page()."""

    def init_home_state(self):
        self._rec_worker = None
        self._rec_data = None
        self._resolver = None
        self._genre_worker = None
        self._custom_mix = None

    # --------------------------------------------------------------- inicio
    def refresh_home(self):
        """Rellena lo que depende de tu biblioteca: accesos rápidos, recientes y artistas que sigues."""
        if not hasattr(self, "home_recents_layout"):
            return

        offline = self.is_offline()
        self.home_offline_box.setVisible(offline)
        if offline:
            self.home_status_lbl.setText("")

        # Mixes hechos con tu música descargada (sirven con y sin conexión)
        self.refresh_local_mixes()
        clear_layout(self.home_local_mixes_row)
        for i, mix in enumerate(self._local_mixes):
            tile = MixTile(mix, i)
            tile.clicked.connect(lambda _m, idx=i: self.open_list("localmix", idx))
            self.home_local_mixes_row.addWidget(tile)
        self.home_local_mixes_box.setVisible(bool(self._local_mixes))
        if offline:      # lo que necesita internet se esconde
            for box in (self.home_mixes_box, self.home_releases_box, self.home_artists_box, self.home_tracks_box,
                        self.home_charts_box, self.home_genres_box):
                box.setVisible(False)
            clear_layout(self.home_because_layout)

        # Recientes
        clear_layout(self.home_recents_layout)
        recent = self.library_items()[:14]
        for info in recent:
            card = RecentTrackCard(info)
            card.clicked.connect(self.play_from_library)
            self.home_recents_layout.addWidget(card)
        paths = recent
        self.home_recents_box.setVisible(bool(recent))

        # Accesos rápidos
        clear_layout(self.home_quick_grid)
        entries = [("favorites", "favorites", "Canciones que te gustan"), ("downloads", "downloads", "Mis descargas")]
        for p_id, data in list(PlaylistService.get_playlists().items())[:4]:
            entries.append(("playlist", p_id, data.get("name", "Playlist")))
        for art in ArtistService.get_followed()[:2]:
            entries.append(("artist", art["id"], art["name"]))
        entries = entries[:8]
        columns = 4
        for i, (kind, list_id, title) in enumerate(entries):
            tile = QuickTile(kind, list_id, title)
            if kind == "artist":
                art = next(a for a in ArtistService.get_followed() if a["id"] == list_id)
                tile.clicked.connect(lambda a=art: self.open_artist_by_name(a))
            else:
                tile.clicked.connect(lambda k=kind, lid=list_id: self.open_list(k, lid))
            self.home_quick_grid.addWidget(tile, i // columns, i % columns)
        for c in range(columns):
            self.home_quick_grid.setColumnStretch(c, 1)

        # Tus artistas
        clear_layout(self.home_followed_row)
        followed = ArtistService.get_followed()
        for art in followed:
            tile = ArtistTile(art)
            tile.clicked.connect(self.open_artist_by_name)
            self.home_followed_row.addWidget(tile)
        self.home_followed_box.setVisible(bool(followed))

        self.home_howto_box.setVisible(not paths and not followed)

        # Resumen de tu música
        items = self.library_items()
        artists = {(i.get("uploader") or "").lower() for i in items if i.get("uploader")}
        total = format_total(sum(int(i.get("duration_secs", 0) or 0) for i in items))
        parts = [f"{len(items)} canciones"]
        if total:
            parts.append(total)
        if artists:
            parts.append(f"{len(artists)} artistas")
        parts.append(f"{len(PlaylistService.get_favorites())} favoritas")
        parts.append(f"{len(PlaylistService.get_playlists())} listas")
        self.home_stats_lbl.setText("Tu música: " + "  ·  ".join(parts) if items else "")

    # ------------------------------------------------------ recomendaciones
    def refresh_recommendations(self, force: bool = False):
        """Analiza tu música y prepara las recomendaciones (con caché para que Inicio abra al instante)."""
        if self.is_offline():
            return          # sin conexión no se piden recomendaciones: Inicio muestra tu música
        try:
            profile = build_taste_profile(self.library_items(), PlaylistService.get_favorites(),
                                          ArtistService.get_followed())
        except Exception as e:
            logging.warning(f"No se pudo analizar la biblioteca: {e}")
            return
        followed = ArtistService.get_followed()
        sig = signature(profile["seeds"], [a["id"] for a in followed])

        if not force:
            cached = load_cache(sig)
            if cached:
                self._render_recommendations(cached)
                return
            stale = load_stale_cache()
            if stale and self._rec_data is None:
                self._render_recommendations(stale)   # algo que ver mientras se actualiza
            reason = perf.saving_reason(self.network)
            if stale and reason:
                self.home_status_lbl.setText(f"Recomendaciones sin actualizar ({reason})")
                return          # con batería baja o datos medidos no se piden recomendaciones nuevas solas

        if self._rec_worker is not None and self._rec_worker.isRunning():
            return
        self.home_status_lbl.setText("Preparando recomendaciones...")
        self._rec_worker = RecommendationWorker(profile, followed)
        self._rec_worker.ready.connect(self._on_recommendations_ready)
        self._rec_worker.finished.connect(lambda: self.home_status_lbl.setText("")
                                          if self._rec_data is not None else self.home_status_lbl.setText(
                                              "Sin conexión: no se pudieron preparar recomendaciones"))
        self._rec_worker.start()

    def _on_recommendations_ready(self, data: dict):
        self._render_recommendations(data)
        if self._rec_data is not None:
            self.home_status_lbl.setText("")

    def _render_recommendations(self, data: dict):
        self._rec_data = data
        if self.is_offline():
            return

        def tracks_shelf(box, row, tracks):
            clear_layout(row)
            for t in tracks:
                row.addWidget(TrackTile(t, self, tracks))
            box.setVisible(bool(tracks))

        # Mixes
        clear_layout(self.home_mixes_row)
        for i, mix in enumerate(data.get("mixes", [])):
            tile = MixTile(mix, i)
            tile.clicked.connect(lambda m, idx=i: self.open_mix(idx))
            self.home_mixes_row.addWidget(tile)
        self.home_mixes_box.setVisible(bool(data.get("mixes")))

        # Novedades de artistas seguidos
        clear_layout(self.home_releases_row)
        for album in data.get("releases", []):
            card = AlbumCard(album)
            card.clicked.connect(self.open_album_details)
            self.home_releases_row.addWidget(card)
        self.home_releases_box.setVisible(bool(data.get("releases")))

        # "Porque escuchas a X"
        clear_layout(self.home_because_layout)
        for block in data.get("because", []):
            box, row = make_shelf(f"Porque escuchas a {block['artist']}", 262)
            for t in block["tracks"]:
                row.addWidget(TrackTile(t, self, block["tracks"]))
            self.home_because_layout.addWidget(box)

        # Artistas parecidos
        clear_layout(self.home_artists_row)
        for art in data.get("artists", []):
            tile = ArtistTile(art)
            tile.clicked.connect(self.open_artist_by_name)
            self.home_artists_row.addWidget(tile)
        self.home_artists_box.setVisible(bool(data.get("artists")))

        # Géneros
        clear_layout(self.home_genres_row)
        for i, genre in enumerate(data.get("genres", [])):
            tile = GenreTile(genre, i)
            tile.clicked.connect(self.open_genre)
            self.home_genres_row.addWidget(tile)
        self.home_genres_box.setVisible(bool(data.get("genres")))

        tracks_shelf(self.home_tracks_box, self.home_tracks_row, data.get("tracks", []))
        tracks_shelf(self.home_charts_box, self.home_charts_row, data.get("charts", []))

    def refresh_tiles_state(self):
        """Actualiza el corazón y el estado de descarga de las canciones sugeridas."""
        for tile in self.page_intro.findChildren(TrackTile):
            try:
                tile.refresh_state()
            except RuntimeError:
                pass

    # -------------------------------------------------------------- acciones
    def play_shelf(self, tracks: list, item: dict, pixmap=None):
        """Reproduce una canción de una sección de Inicio; 'siguiente' recorre esa sección."""
        self.set_context(tracks)
        if item.get("local_path"):
            self.play_local_file(item["local_path"])
        else:
            self.play_preview(item, None, pixmap)

    def open_artist_by_name(self, artist: dict):
        """Abre el perfil de un artista; si solo se conoce su nombre, lo localiza antes."""
        if self.is_offline():
            name = artist.get("name", "")
            if self.local_artist_items(name):
                self.open_list("artist_local", name)      # sin conexión: tus canciones de ese artista
            else:
                self.notify("Sin conexión: no se puede abrir el perfil de este artista.")
            return
        art_id = str(artist.get("id", ""))
        if art_id.isdigit():
            self.open_artist_profile(int(art_id), artist.get("name", ""), artist.get("avatar", ""))
            return
        name = artist.get("name", "")
        self.notify(f"Buscando a {name}...")
        self._resolver = ArtistResolver(name, artist.get("picture", ""))
        self._resolver.found.connect(lambda a: self.open_artist_profile(int(a["id"]), a["name"], a.get("avatar", "")))
        self._resolver.failed.connect(lambda: self.perform_search(name))
        self._resolver.start()

    def open_genre(self, genre: dict):
        """Abre una lista con lo más escuchado de un género."""
        self.notify(f"Cargando {genre['name']}...")
        self._genre_worker = GenreTracksWorker(genre["id"])
        self._genre_worker.ready.connect(lambda tracks, g=genre: self._show_genre(g, tracks))
        self._genre_worker.start()

    def _show_genre(self, genre: dict, tracks: list):
        if not tracks:
            self.notify("No se pudieron cargar las canciones de este género.")
            return
        index = int(genre.get("index", 0))
        self._custom_mix = {"name": genre["name"], "artists": [], "tracks": tracks, "index": index}
        self._current_list = None
        self.open_list("genre", index)

    def open_mix(self, index: int):
        self.open_list("mix", index)

