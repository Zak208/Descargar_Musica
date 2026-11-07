import logging
from services import http
from services.timefmt import format_duration
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

            # 2. Buscar canciones con Deezer (RANKING de popularidad) + iTunes (fallback y complemento)
            track_candidates = []
            q_lower = self.query.lower()

            # A. Deezer search ordenado por popularidad de escuchas globales (RANKING)
            try:
                r_dz = http.get(
                    'https://api.deezer.com/search',
                    params={'q': self.query, 'order': 'RANKING', 'limit': min(60, self.limits['tracks'] * 2)},
                    timeout=4
                )
                if r_dz.status_code == 200:
                    for it in r_dz.json().get('data', []):
                        if self.is_cancelled:
                            return
                        t_name = it.get('title', '').strip()
                        art_name = it.get('artist', {}).get('name', '').strip()
                        track_key = (t_name.lower(), art_name.lower())
                        if not t_name or track_key in seen_track_keys:
                            continue
                        seen_track_keys.add(track_key)
                        duration_s = int(it.get('duration', 0) or 0)
                        album_obj = it.get('album', {})
                        artwork = album_obj.get('cover_big') or album_obj.get('cover_medium') or album_obj.get('cover') or ''
                        track_candidates.append({
                            "title": t_name,
                            "uploader": art_name or 'Artista Desconocido',
                            "album": album_obj.get('title', ''),
                            "duration_secs": duration_s,
                            "duration_str": format_duration(duration_s, blank_zero=False),
                            "thumbnail": artwork,
                            "preview_url": it.get('preview') or '',
                            "url": f"ytsearch1:{art_name} {t_name}",
                            "id": str(it.get('id', '')),
                            "rank": int(it.get('rank', 0) or 0)
                        })
            except Exception as e:
                logger.debug(f"Error consultando Deezer tracks: {e}")

            # B. iTunes search (cobertura complementaria)
            try:
                r_tracks = http.get(
                    'https://itunes.apple.com/search',
                    params={'term': self.query, 'entity': 'song', 'limit': min(50, self.limits['tracks'] + 10)},
                    timeout=4
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
                        artwork = item.get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                        track_candidates.append({
                            "title": t_name or 'Sin título',
                            "uploader": art_name or 'Artista Desconocido',
                            "album": item.get('collectionName', ''),
                            "duration_secs": duration_s,
                            "duration_str": format_duration(duration_s, blank_zero=False),
                            "thumbnail": artwork,
                            "preview_url": item.get('previewUrl') or '',
                            "url": f"ytsearch1:{art_name} {t_name}",
                            "id": str(item.get('trackId', '')),
                            "rank": 0
                        })
            except Exception as e:
                logger.debug(f"Error consultando iTunes tracks: {e}")

            # C. Puntuación multivariable y ordenación por relevancia estilo Spotify
            def _calc_score(t):
                title = t.get('title', '').lower()
                artist = t.get('uploader', '').lower()
                rank = t.get('rank', 0)
                score = 0.0

                # Coincidencia con título
                if title == q_lower:
                    score += 1000.0
                elif title.startswith(q_lower):
                    score += 700.0
                elif q_lower in title:
                    score += 400.0

                # Coincidencia con artista
                if artist == q_lower:
                    score += 850.0
                elif artist.startswith(q_lower):
                    score += 550.0
                elif q_lower in artist:
                    score += 350.0

                # Palabras individuales
                q_words = [w for w in q_lower.split() if len(w) > 2]
                if q_words and all(w in title or w in artist for w in q_words):
                    score += 200.0

                # Popularidad global de escuchas (Deezer rank)
                score += min(1000.0, rank / 1000.0)

                # Penalizar versiones secundarias si el usuario no las pidió expresamente
                for word in ('remix', 'karaoke', 'tribute', 'tributo', 'cover', 'instrumental'):
                    if word in title and word not in q_lower:
                        score -= 250.0

                return score

            track_candidates.sort(key=_calc_score, reverse=True)
            results["tracks"] = track_candidates[:self.limits["tracks"]]

            # 3. Buscar álbumes (Deezer + iTunes con prioridad a paquetes completos)
            album_candidates = []
            try:
                r_dz_alb = http.get(
                    'https://api.deezer.com/search/album',
                    params={'q': self.query, 'limit': min(30, self.limits['albums'] + 10)},
                    timeout=4
                )
                if r_dz_alb.status_code == 200:
                    for it in r_dz_alb.json().get('data', []):
                        if self.is_cancelled:
                            return
                        title = it.get('title', '').strip()
                        art = it.get('artist', {}).get('name', '').strip()
                        key = (title.lower(), art.lower())
                        if not title or key in seen_album_keys:
                            continue
                        seen_album_keys.add(key)
                        track_count = int(it.get('nb_tracks', 0) or 0)
                        cover = it.get('cover_big') or it.get('cover_medium') or it.get('cover') or ''
                        album_candidates.append({
                            "id": f"dz_{it.get('id')}",
                            "name": title,
                            "artist": art,
                            "year": (it.get('release_date') or '')[:4],
                            "track_count": track_count,
                            "cover": cover,
                            "type": "single" if track_count <= 2 else "album"
                        })
            except Exception as e:
                logger.debug(f"Error consultando Deezer álbumes: {e}")

            try:
                r_alb = http.get(
                    'https://itunes.apple.com/search',
                    params={'term': self.query, 'entity': 'album', 'limit': min(30, self.limits['albums'] + 8)},
                    timeout=4
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
                        track_count = int(item.get('trackCount', 0) or 0)
                        is_single = track_count <= 2 or col_name.lower().endswith(' - single')
                        album_candidates.append({
                            "id": item.get('collectionId'),
                            "name": col_name,
                            "artist": art_name,
                            "year": item.get('releaseDate', '')[:4],
                            "track_count": track_count,
                            "cover": artwork,
                            "type": "single" if is_single else "album"
                        })
            except Exception as e:
                logger.debug(f"Error consultando iTunes álbumes: {e}")

            # Priorizar álbumes completos (paquetes) sobre singles de 1 cancion
            album_candidates.sort(key=lambda a: (0 if a.get("type") == "album" else 1, -a.get("track_count", 0)))
            results["albums"] = album_candidates[:self.limits["albums"]]

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

            # Top canciones del artista por popularidad real (Deezer API / iTunes)
            top_tracks = []
            seen_song_names = set()

            # 1. Intentar Deezer para ranking por número de reproducciones / popularidad
            try:
                r_dz = http.get('https://api.deezer.com/search/artist', params={'q': self.artist_name}, timeout=4)
                if r_dz.status_code == 200:
                    dz_data = r_dz.json().get('data', [])
                    if dz_data:
                        dz_art = dz_data[0]
                        dz_id = dz_art.get('id')
                        r_top = http.get(f'https://api.deezer.com/artist/{dz_id}/top', params={'limit': 30}, timeout=5)
                        if r_top.status_code == 200:
                            for item in r_top.json().get('data', []):
                                s_name = (item.get('title_short') or item.get('title', '')).strip()
                                if not s_name or s_name.lower() in seen_song_names:
                                    continue
                                seen_song_names.add(s_name.lower())
                                duration_s = int(item.get('duration', 0) or 0)
                                alb_obj = item.get('album', {})
                                artwork = alb_obj.get('cover_big') or alb_obj.get('cover_medium', '')
                                top_tracks.append({
                                    "title": s_name,
                                    "uploader": item.get('artist', {}).get('name', self.artist_name),
                                    "album": alb_obj.get('title', ''),
                                    "duration_secs": duration_s,
                                    "duration_str": format_duration(duration_s, blank_zero=False),
                                    "thumbnail": artwork,
                                    "preview_url": item.get('preview') or '',
                                    "url": f"ytsearch1:{self.artist_name} {s_name}",
                                    "id": f"dz_{item.get('id', '')}"
                                })
            except Exception as e:
                logger.warning(f"Error consultando top tracks de Deezer para {self.artist_name}: {e}")

            # 2. Fallback o complemento con iTunes si Deezer devolvió pocas pistas
            if len(top_tracks) < 5:
                try:
                    r_songs = http.get(
                        'https://itunes.apple.com/lookup',
                        params={'id': self.artist_id, 'entity': 'song', 'limit': 50},
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
                                artwork = item.get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                                top_tracks.append({
                                    "title": s_name,
                                    "uploader": item.get('artistName', self.artist_name),
                                    "album": item.get('collectionName', ''),
                                    "duration_secs": duration_s,
                                    "duration_str": format_duration(duration_s, blank_zero=False),
                                    "thumbnail": artwork,
                                    "preview_url": item.get('previewUrl') or '',
                                    "url": f"ytsearch1:{self.artist_name} {s_name}",
                                    "id": str(item.get('trackId', ''))
                                })
                except Exception as e:
                    logger.warning(f"Error obteniendo canciones del artista en iTunes: {e}")

            # Álbumes del artista (sin duplicados ni reediciones repetidas)
            albums = []
            seen_album_names = set()
            try:
                r_albums = http.get(
                    'https://itunes.apple.com/lookup',
                    params={'id': self.artist_id, 'entity': 'album', 'limit': 100},
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
                            t_cnt = int(item.get('trackCount', 0) or 0)
                            is_sgl = t_cnt <= 2 or norm_alb.endswith(' - single')
                            albums.append({
                                "id": item.get('collectionId'),
                                "name": alb_title,
                                "artist": item.get('artistName', self.artist_name),
                                "year": item.get('releaseDate', '')[:4],
                                "track_count": t_cnt,
                                "cover": artwork,
                                "type": "single" if is_sgl else "album"
                            })
            except Exception as e:
                logger.warning(f"Error obteniendo álbumes del artista: {e}")

            # Álbumes completos primero, luego sencillos
            albums.sort(key=lambda a: (0 if a.get("type") == "album" else 1, -a.get("track_count", 0)))

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

    def __init__(self, album_id, parent=None):
        super().__init__(parent)
        self.album_id = album_id
        self.is_cancelled = False

    def run(self):
        try:
            raw_id = str(self.album_id or "").strip()
            is_deezer = raw_id.startswith("dz_")
            clean_id = raw_id.replace("dz_", "").strip()

            # 1. Si es ID de Deezer (o explícito con prefijo dz_)
            if is_deezer:
                try:
                    r_dz = http.get(f"https://api.deezer.com/album/{clean_id}", timeout=6)
                    if r_dz.status_code == 200:
                        data = r_dz.json()
                        if not data.get("error") and "tracks" in data:
                            self._parse_deezer(data)
                            return
                except Exception as e:
                    logger.debug(f"Error consultando Deezer album {clean_id}: {e}")

            # 2. Intentar iTunes (por collectionId estándar)
            if clean_id.isdigit():
                try:
                    r_it = http.get(
                        "https://itunes.apple.com/lookup",
                        params={"id": clean_id, "entity": "song"},
                        timeout=6
                    )
                    if r_it.status_code == 200:
                        results = r_it.json().get("results", [])
                        if results:
                            self._parse_itunes(results)
                            return
                except Exception as e:
                    logger.debug(f"Error consultando iTunes album {clean_id}: {e}")

            # 3. Fallback a Deezer si iTunes no devolvió resultados o si clean_id era de Deezer
            try:
                r_dz = http.get(f"https://api.deezer.com/album/{clean_id}", timeout=6)
                if r_dz.status_code == 200:
                    data = r_dz.json()
                    if not data.get("error") and "tracks" in data:
                        self._parse_deezer(data)
                        return
            except Exception as e:
                logger.debug(f"Error en fallback Deezer album {clean_id}: {e}")

            if not self.is_cancelled:
                self.error_occurred.emit("Álbum no encontrado.")

        except Exception as e:
            if not self.is_cancelled:
                self.error_occurred.emit(str(e))

    def _parse_deezer(self, dz_data: dict):
        album_name = dz_data.get("title", "Álbum")
        artist_name = dz_data.get("artist", {}).get("name", "Artista Desconocido")
        year = (dz_data.get("release_date") or "")[:4]
        artwork = dz_data.get("cover_xl") or dz_data.get("cover_big") or dz_data.get("cover_medium") or dz_data.get("cover") or ""
        tracks = []
        for i, item in enumerate(dz_data.get("tracks", {}).get("data", [])):
            duration_s = int(item.get("duration", 0) or 0)
            track_no = item.get("track_position") or (i + 1)
            t_title = (item.get("title_short") or item.get("title", "Pista")).strip()
            t_artist = item.get("artist", {}).get("name", artist_name)
            tracks.append({
                "track_number": track_no,
                "title": t_title,
                "uploader": t_artist,
                "album": album_name,
                "duration_secs": duration_s,
                "duration_str": format_duration(duration_s, blank_zero=False),
                "thumbnail": artwork,
                "preview_url": item.get("preview") or "",
                "url": f"ytsearch1:{t_artist} {t_title}",
                "id": "dz_" + str(item.get("id", ""))
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

    def _parse_itunes(self, results: list):
        album_info = results[0]
        artist_name = album_info.get("artistName", "Artista Desconocido")
        album_name = album_info.get("collectionName", "Álbum")
        year = album_info.get("releaseDate", "")[:4]
        artwork = album_info.get("artworkUrl100", "").replace("100x100bb", "600x600bb")

        tracks = []
        for item in results[1:]:
            if item.get("wrapperType") == "track":
                duration_s = item.get("trackTimeMillis", 0) // 1000
                track_no = item.get("trackNumber", len(tracks) + 1)
                t_name = item.get("trackName", "Pista")
                tracks.append({
                    "track_number": track_no,
                    "title": t_name,
                    "uploader": artist_name,
                    "album": album_name,
                    "duration_secs": duration_s,
                    "duration_str": format_duration(duration_s, blank_zero=False),
                    "thumbnail": artwork,
                    "preview_url": item.get("previewUrl") or "",
                    "url": f"ytsearch1:{artist_name} {t_name}",
                    "id": str(item.get("trackId", ""))
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
