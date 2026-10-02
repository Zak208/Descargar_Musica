import logging
from services import http
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


_AVATAR_CACHE = {}

def get_artist_avatar(artist_name: str) -> str:
    """Obtiene la foto oficial del artista en HD vía Deezer API pública, priorizando por popularidad."""
    if not artist_name:
        return ""
    clean_name = artist_name.strip()
    if clean_name in _AVATAR_CACHE:
        return _AVATAR_CACHE[clean_name]

    try:
        r = http.get('https://api.deezer.com/search/artist', params={'q': clean_name}, timeout=4)
        if r.status_code == 200:
            data = r.json().get('data', [])
            if data and isinstance(data, list):
                # Ordenar por cantidad de fans para priorizar al artista principal verificado
                sorted_by_fans = sorted(data, key=lambda x: x.get('nb_fan', 0), reverse=True)
                # Buscar coincidencia exacta en nombre si existe
                best_match = sorted_by_fans[0]
                for candidate in sorted_by_fans:
                    if candidate.get('name', '').strip().lower() == clean_name.lower():
                        best_match = candidate
                        break
                avatar_url = best_match.get('picture_medium') or best_match.get('picture') or ""
                _AVATAR_CACHE[clean_name] = avatar_url
                return avatar_url
    except Exception as e:
        logger.warning(f"Error obteniendo foto de {clean_name}: {e}")
    return ""


class CatalogSearchWorker(QThread):
    results_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, query: str, limits: dict | None = None, parent=None):
        super().__init__(parent)
        self.query = query.strip()
        self.limits = {"artists": 7, "tracks": 20, "albums": 12}
        if limits:
            self.limits.update(limits)
        self.is_cancelled = False

    def run(self):
        try:
            results = {
                "artists": [],
                "albums": [],
                "tracks": []
            }

            seen_artist_names = set()
            seen_album_keys = set()
            seen_track_keys = set()

            # 1. Buscar artistas (iTunes con deduplicación rigurosa)
            try:
                r_art = http.get(
                    'https://itunes.apple.com/search',
                    params={'term': self.query, 'entity': 'musicArtist', 'limit': max(15, self.limits['artists'] * 2)},
                    timeout=5
                )
                if r_art.status_code == 200:
                    raw_artists = r_art.json().get('results', [])
                    picked = []
                    for item in raw_artists:
                        if self.is_cancelled:
                            return
                        name = item.get('artistName', '').strip()
                        norm_name = name.lower()
                        # Evitar nombres vacíos, demasiado cortos o duplicados
                        if not name or len(name) < 2 or norm_name in seen_artist_names:
                            continue
                        seen_artist_names.add(norm_name)
                        picked.append(item)
                        if len(picked) >= self.limits["artists"]:
                            break

                    # las fotos se piden varias a la vez (antes una detrás de otra)
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        avatars = list(pool.map(lambda it: get_artist_avatar(it.get('artistName', '').strip()), picked))
                    for item, avatar in zip(picked, avatars):
                        results["artists"].append({
                            "id": item.get('artistId'),
                            "name": item.get('artistName', '').strip(),
                            "genre": item.get('primaryGenreName', 'Música'),
                            "avatar": avatar
                        })

                # Si hay coincidencia exacta con el término de búsqueda, colocarla en primera posición
                query_lower = self.query.lower()
                results["artists"].sort(
                    key=lambda a: (0 if a["name"].lower() == query_lower else 1)
                )

            except Exception as e:
                logger.warning(f"Error buscando artistas: {e}")

            # 2. Buscar canciones (iTunes con deduplicación)
            try:
                r_tracks = http.get(
                    'https://itunes.apple.com/search',
                    params={'term': self.query, 'entity': 'song', 'limit': min(200, self.limits['tracks'] + 10)},
                    timeout=5
                )
                if r_tracks.status_code == 200:
                    for item in r_tracks.json().get('results', []):
                        if self.is_cancelled:
                            return
                        t_name = item.get('trackName', '').strip()
                        art_name = item.get('artistName', '').strip()
                        track_key = (t_name.lower(), art_name.lower())
                        if not t_name or track_key in seen_track_keys:
                            continue
                        seen_track_keys.add(track_key)

                        duration_s = item.get('trackTimeMillis', 0) // 1000
                        mins = duration_s // 60
                        secs = duration_s % 60
                        artwork = item.get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                        results["tracks"].append({
                            "title": t_name or 'Sin título',
                            "uploader": art_name or 'Artista Desconocido',
                            "album": item.get('collectionName', ''),
                            "duration_secs": duration_s,
                            "duration_str": f"{mins}:{secs:02d}",
                            "thumbnail": artwork,
                            "url": f"ytsearch1:{art_name} {t_name}",
                            "id": str(item.get('trackId', ''))
                        })
                        if len(results["tracks"]) >= self.limits["tracks"]:
                            break
            except Exception as e:
                logger.warning(f"Error buscando canciones: {e}")

            # 3. Buscar álbumes (iTunes con deduplicación)
            try:
                r_alb = http.get(
                    'https://itunes.apple.com/search',
                    params={'term': self.query, 'entity': 'album', 'limit': min(200, self.limits['albums'] + 8)},
                    timeout=5
                )
                if r_alb.status_code == 200:
                    for item in r_alb.json().get('results', []):
                        if self.is_cancelled:
                            return
                        col_name = item.get('collectionName', '').strip()
                        art_name = item.get('artistName', '').strip()
                        album_key = (col_name.lower(), art_name.lower())
                        if not col_name or album_key in seen_album_keys:
                            continue
                        seen_album_keys.add(album_key)

                        artwork = item.get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                        results["albums"].append({
                            "id": item.get('collectionId'),
                            "name": col_name,
                            "artist": art_name,
                            "year": item.get('releaseDate', '')[:4],
                            "track_count": item.get('trackCount', 0),
                            "cover": artwork
                        })
                        if len(results["albums"]) >= self.limits["albums"]:
                            break
            except Exception as e:
                logger.warning(f"Error buscando álbumes: {e}")

            if not self.is_cancelled:
                self.results_ready.emit(results)

        except Exception as e:
            if not self.is_cancelled:
                self.error_occurred.emit(str(e))


class ArtistDetailsWorker(QThread):
    details_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, artist_id: int, artist_name: str, avatar: str = "", parent=None):
        super().__init__(parent)
        self.artist_id = artist_id
        self.artist_name = artist_name
        self.avatar = avatar
        self.is_cancelled = False

    def run(self):
        try:
            avatar = self.avatar or get_artist_avatar(self.artist_name)

            # Top canciones del artista (sin duplicados)
            top_tracks = []
            seen_song_names = set()
            try:
                r_songs = http.get(
                    'https://itunes.apple.com/lookup',
                    params={'id': self.artist_id, 'entity': 'song', 'limit': 15},
                    timeout=6
                )
                if r_songs.status_code == 200:
                    for item in r_songs.json().get('results', []):
                        if item.get('wrapperType') == 'track':
                            s_name = item.get('trackName', '').strip()
                            if not s_name or s_name.lower() in seen_song_names:
                                continue
                            seen_song_names.add(s_name.lower())

                            duration_s = item.get('trackTimeMillis', 0) // 1000
                            mins = duration_s // 60
                            secs = duration_s % 60
                            artwork = item.get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                            top_tracks.append({
                                "title": s_name,
                                "uploader": item.get('artistName', self.artist_name),
                                "album": item.get('collectionName', ''),
                                "duration_secs": duration_s,
                                "duration_str": f"{mins}:{secs:02d}",
                                "thumbnail": artwork,
                                "url": f"ytsearch1:{self.artist_name} {s_name}",
                                "id": str(item.get('trackId', ''))
                            })
                            if len(top_tracks) >= 8:
                                break
            except Exception as e:
                logger.warning(f"Error obteniendo canciones del artista: {e}")

            # Álbumes del artista (sin duplicados ni reediciones repetidas)
            albums = []
            seen_album_names = set()
            try:
                r_albums = http.get(
                    'https://itunes.apple.com/lookup',
                    params={'id': self.artist_id, 'entity': 'album', 'limit': 30},
                    timeout=6
                )
                if r_albums.status_code == 200:
                    for item in r_albums.json().get('results', []):
                        if item.get('wrapperType') == 'collection':
                            alb_title = item.get('collectionName', '').strip()
                            norm_alb = alb_title.lower()
                            if not alb_title or norm_alb in seen_album_names:
                                continue
                            seen_album_names.add(norm_alb)

                            artwork = item.get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                            albums.append({
                                "id": item.get('collectionId'),
                                "name": alb_title,
                                "artist": item.get('artistName', self.artist_name),
                                "year": item.get('releaseDate', '')[:4],
                                "track_count": item.get('trackCount', 0),
                                "cover": artwork
                            })
            except Exception as e:
                logger.warning(f"Error obteniendo álbumes del artista: {e}")

            if not self.is_cancelled:
                self.details_ready.emit({
                    "id": self.artist_id,
                    "name": self.artist_name,
                    "avatar": avatar,
                    "top_tracks": top_tracks,
                    "albums": albums
                })

        except Exception as e:
            if not self.is_cancelled:
                self.error_occurred.emit(str(e))


class AlbumDetailsWorker(QThread):
    details_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, album_id: int, parent=None):
        super().__init__(parent)
        self.album_id = album_id
        self.is_cancelled = False

    def run(self):
        try:
            r = http.get(
                'https://itunes.apple.com/lookup',
                params={'id': self.album_id, 'entity': 'song'},
                timeout=6
            )
            if r.status_code != 200:
                self.error_occurred.emit("No se pudo obtener información del álbum.")
                return

            results = r.json().get('results', [])
            if not results:
                self.error_occurred.emit("Álbum no encontrado.")
                return

            album_info = results[0]
            artist_name = album_info.get('artistName', 'Artista Desconocido')
            album_name = album_info.get('collectionName', 'Álbum')
            year = album_info.get('releaseDate', '')[:4]
            artwork = album_info.get('artworkUrl100', '').replace('100x100bb', '600x600bb')

            tracks = []
            for item in results[1:]:
                if item.get('wrapperType') == 'track':
                    duration_s = item.get('trackTimeMillis', 0) // 1000
                    mins = duration_s // 60
                    secs = duration_s % 60
                    track_no = item.get('trackNumber', len(tracks) + 1)
                    tracks.append({
                        "track_number": track_no,
                        "title": item.get('trackName', 'Pista'),
                        "uploader": artist_name,
                        "album": album_name,
                        "duration_secs": duration_s,
                        "duration_str": f"{mins}:{secs:02d}",
                        "thumbnail": artwork,
                        "url": f"ytsearch1:{artist_name} {item.get('trackName')}",
                        "id": str(item.get('trackId', ''))
                    })

            if not self.is_cancelled:
                self.details_ready.emit({
                    "id": self.album_id,
                    "name": album_name,
                    "artist": artist_name,
                    "year": year,
                    "cover": artwork,
                    "tracks": tracks
                })

        except Exception as e:
            if not self.is_cancelled:
                self.error_occurred.emit(str(e))
