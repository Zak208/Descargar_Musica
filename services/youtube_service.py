import os
import re
import json
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from services.ffmpeg_service import FFmpegService
from services.metadata_service import MetadataService
from config import HISTORY_FILE, get_download_dir, get_audio_quality, get_organize_mode
from services import quality as quality_service

logger = logging.getLogger(__name__)
history_lock = threading.Lock()


def _yt():
    """yt-dlp se carga solo cuando hace falta (ahorra ~27 MB de memoria y 0,3 s de CPU al abrir la aplicación)."""
    from services import ytdlp_loader
    return ytdlp_loader.get()



def is_youtube_url(text: str) -> bool:
    """Verifica si el texto introducido es un enlace de YouTube."""
    text = text.strip().lower()
    return "youtube.com/" in text or "youtu.be/" in text


def is_playlist_url(text: str) -> bool:
    """Verifica si el texto es un enlace a una lista de reproducción."""
    text = text.strip().lower()
    return is_youtube_url(text) and ("list=" in text or "/playlist" in text)


def sanitize_filename(name: str) -> str:
    """Elimina caracteres ilegales en nombres de archivo de Windows."""
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip('. ')
    return sanitized or "Audio"


def clean_youtube_title(raw_title: str, raw_uploader: str = "") -> tuple[str, str]:
    """
    Limpia títulos de YouTube eliminando coletillas molestas como:
    (Official Music Video), [Video Oficial], (Lyric Video), 4K, etc.
    Separa limpiamente Artista y Nombre de Canción.
    """
    title = raw_title

    def paren_replacer(match):
        content = match.group(0).lower()
        # Conservar colaboraciones, remixes, acústicos o en directo relevantes
        keep_keywords = ['feat', 'ft.', 'remix', 'live', 'acoustic', 'cover', 'versión', 'version', 'en vivo']
        if any(w in content for w in keep_keywords):
            return match.group(0)
        # Eliminar coletillas de videoclip / formato
        junk_keywords = [
            'official', 'oficial', 'video', 'audio', 'lyric', 'letra',
            'videoclip', 'clip', 'remaster', '4k', '1080p', 'hd', 'hq',
            'visualizer', 'video musical', 'video lyric', 'subtitulado'
        ]
        if any(w in content for w in junk_keywords):
            return ''
        return match.group(0)

    # Reemplazar paréntesis y corchetes con información basura
    title = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', paren_replacer, title)
    title = re.sub(r'\s+', ' ', title).strip(' -|[]_')

    artist = (raw_uploader or "").strip()
    if ' - ' in title:
        parts = title.split(' - ', 1)
        artist = parts[0].strip()
        song = parts[1].strip()
    else:
        song = title.strip()
        if artist:
            # Limpiar canales automáticos de YouTube Music ("Artista - Topic" o "VEVO")
            artist = re.sub(r'\s*-\s*Topic$', '', artist, flags=re.IGNORECASE)
            artist = re.sub(r'VEVO$', '', artist, flags=re.IGNORECASE).strip()

    return artist or "Artista Desconocido", song or "Sin Título"


def check_history(url_or_id: str) -> dict | None:
    """Comprueba si un video ya fue descargado previamente."""
    if not HISTORY_FILE.exists():
        return None
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
            return history.get(url_or_id)
    except Exception:
        return None


def save_to_history(video_id: str, title: str, file_path: str):
    """Guarda el registro de la descarga en el archivo de historial."""
    with history_lock:
        history = {}
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = {}

        history[video_id] = {
            "title": title,
            "file_path": file_path,
            "date": str(Path(file_path).stat().st_mtime) if Path(file_path).exists() else ""
        }

        try:
            from config import atomic_write_json
            atomic_write_json(HISTORY_FILE, history)
        except Exception as e:
            logger.error(f"Error guardando historial: {e}")


class SearchWorker(QThread):
    results_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self.query = query.strip()
        self.is_cancelled = False

    def run(self):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'skip_download': True,
                'socket_timeout': 15,
                'retries': 3,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web']
                    }
                }
            }

            from services.spotify_service import (
                is_spotify_url, is_spotify_playlist_or_album,
                get_spotify_track_info, get_spotify_collection_tracks
            )

            results = []

            if is_spotify_url(self.query):
                if is_spotify_playlist_or_album(self.query):
                    col = get_spotify_collection_tracks(self.query)
                    if col and col.get("tracks"):
                        for t in col["tracks"][:30]:
                            if self.is_cancelled:
                                break
                            search_q = f"ytsearch1:{t['search_query']}"
                            with _yt().YoutubeDL(ydl_opts) as ydl_s:
                                try:
                                    sub_info = ydl_s.extract_info(search_q, download=False)
                                    if sub_info and "entries" in sub_info and sub_info["entries"]:
                                        entry = sub_info["entries"][0]
                                        item = self._parse_video_info(entry)
                                        item["title"] = t["title"]
                                        item["uploader"] = t["artist"]
                                        if t.get("thumbnail"):
                                            item["thumbnail"] = t["thumbnail"]
                                        item["is_playlist_item"] = True
                                        results.append(item)
                                except Exception:
                                    pass
                else:
                    sp_track = get_spotify_track_info(self.query)
                    if sp_track:
                        search_q = f"ytsearch1:{sp_track['search_query']}"
                        with _yt().YoutubeDL(ydl_opts) as ydl_s:
                            sub_info = ydl_s.extract_info(search_q, download=False)
                            if sub_info and "entries" in sub_info and sub_info["entries"]:
                                entry = sub_info["entries"][0]
                                item = self._parse_video_info(entry)
                                item["title"] = sp_track["title"]
                                item["uploader"] = sp_track["artist"]
                                if sp_track.get("thumbnail"):
                                    item["thumbnail"] = sp_track["thumbnail"]
                                results.append(item)
            elif is_youtube_url(self.query):
                if is_playlist_url(self.query):
                    ydl_opts["playlistend"] = 40
                with _yt().YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(self.query, download=False)
                    if info:
                        if 'entries' in info:
                            for entry in info['entries']:
                                if entry and not self.is_cancelled:
                                    item = self._parse_video_info(entry)
                                    item["is_playlist_item"] = True
                                    results.append(item)
                        else:
                            results.append(self._parse_video_info(info))
            else:
                # Búsqueda de hasta 10 canciones
                search_query = f"ytsearch10:{self.query}"
                with _yt().YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(search_query, download=False)
                    if info and 'entries' in info:
                        for entry in info['entries']:
                            if entry and not self.is_cancelled:
                                results.append(self._parse_video_info(entry))

            if not self.is_cancelled:
                self.results_ready.emit(results)
        except Exception as e:
            logger.error(f"Error en búsqueda: {e}")
            if not self.is_cancelled:
                self.error_occurred.emit(f"No se pudieron encontrar resultados: {str(e)}")

    def _parse_video_info(self, info: dict) -> dict:
        video_id = info.get('id', '')
        url = info.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}"

        thumbnails = info.get('thumbnails', [])
        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
        if thumbnails and isinstance(thumbnails, list):
            thumbnail_url = thumbnails[-1].get('url', thumbnail_url)

        duration_secs = info.get('duration', 0) or 0
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        duration_str = f"{minutes}:{seconds:02d}"

        raw_title = info.get('title', 'Sin título')
        raw_uploader = info.get('uploader') or info.get('channel') or 'Artista Desconocido'

        # Limpieza inteligente de metadatos
        clean_artist, clean_title = clean_youtube_title(raw_title, raw_uploader)

        already_downloaded = check_history(video_id) is not None

        return {
            'id': video_id,
            'title': clean_title,
            'raw_title': raw_title,
            'uploader': clean_artist,
            'raw_uploader': raw_uploader,
            'url': url,
            'thumbnail': thumbnail_url,
            'duration_secs': duration_secs,
            'duration_str': duration_str,
            'already_downloaded': already_downloaded
        }


class PreviewAudioWorker(QThread):
    loading = Signal()
    ready = Signal(str)
    error = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.is_cancelled = False

    def run(self):
        self.loading.emit()
        try:
            # Usar ba/b y cliente android para sortear el error 403 Forbidden de YouTube
            ydl_opts = {
                'format': 'ba/b',
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 15,
                'retries': 3,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web']
                    }
                }
            }
            with _yt().YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if info and 'entries' in info and info['entries']:
                    stream_url = info['entries'][0].get('url')
                else:
                    stream_url = info.get('url') if info else None

                if self.is_cancelled:
                    return

                if stream_url:
                    self.ready.emit(stream_url)
                else:
                    self.error.emit("No se pudo obtener el audio directo de esta pista.")
        except Exception as e:
            if not self.is_cancelled:
                self.error.emit(f"Error al cargar vista previa: {str(e)}")


def duration_tolerance(expected: float) -> float:
    """Diferencia de duración que se acepta entre la canción esperada y la descargada."""
    return max(12.0, expected * 0.08)


def rank_candidates(entries: list, expected: float) -> list:
    """Ordena resultados de YouTube: primero los de duración parecida a la esperada (en el orden de relevancia que
    dio YouTube) y después, de más a menos cercanos. Devuelve sus direcciones."""
    close, far = [], []
    for rank, entry in enumerate(entries):
        if not entry:
            continue
        vid = entry.get("id")
        url = entry.get("webpage_url") or entry.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
        if not url:
            continue
        dur = entry.get("duration")
        diff = abs(float(dur) - expected) if dur else None
        if diff is not None and diff <= duration_tolerance(expected):
            close.append((rank, url))
        else:
            far.append((diff if diff is not None else 1e9, rank, url))
    far.sort()
    return [u for _r, u in close] + [u for _d, _r, u in far]


def verify_download(path: str, expected: float) -> tuple:
    """(ok, motivo). Comprueba que el archivo existe, se puede leer y dura lo esperado."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < 30_000:
            return False, "El archivo descargado está vacío o incompleto."
        import mutagen
        audio = mutagen.File(path)
        length = float(getattr(getattr(audio, "info", None), "length", 0) or 0)
        if audio is None or length < 1:
            return False, "El archivo descargado no se puede leer."
        if expected > 0 and abs(length - expected) > max(20.0, expected * 0.15):
            return False, f"Dura {int(length)} s y se esperaban unos {int(expected)} s (puede ser otra versión)."
        return True, ""
    except Exception as e:
        return False, f"No se pudo comprobar el archivo: {e}"


class DownloadWorker(QThread):
    """Descarga una canción. Comprueba el resultado y, si no es lo esperado (otra versión, archivo dañado, no
    disponible), prueba automáticamente con otro resultado de YouTube (hasta 3 intentos)."""
    progress_signal = Signal(dict)
    finished_signal = Signal(dict)
    MAX_ATTEMPTS = 3

    def __init__(self, item_info: dict, output_dir: str = None, quality: str = None, parent=None, organize: str = None):
        super().__init__(parent)
        self.item_info = item_info
        self.output_dir = output_dir or str(get_download_dir())
        self.quality = quality or get_audio_quality()
        self.organize = organize if organize is not None else get_organize_mode()
        self.is_cancelled = False

    # ------------------------------------------------------------ carpeta
    def target_dir(self, artist: str, album: str) -> Path:
        """Por defecto todo va junto en la carpeta principal; si el usuario lo pide, por artista o artista y álbum."""
        base = Path(self.output_dir)
        first = re.split(r"\s*(?:&|,|;|/|\bfeat\.?|\bft\.?)\s*", artist or "", maxsplit=1)[0].strip()
        if self.organize == "artist":
            return base / sanitize_filename(first or "Artista desconocido")
        if self.organize == "artist_album":
            return base / sanitize_filename(first or "Artista desconocido") / sanitize_filename(album or "Sin álbum")
        return base

    # --------------------------------------------------------- candidatos
    def _candidates(self, url: str, expected: float) -> list:
        """Direcciones a probar, de la mejor a la peor. Para búsquedas («ytsearch1:artista canción») se miran varios
        resultados y se prefiere el que dura lo esperado."""
        if not (url.startswith("ytsearch1:") and expected > 0):
            return [url]
        try:
            opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True,
                    "socket_timeout": 15, "extractor_args": {"youtube": {"player_client": ["android", "web"]}}}
            with _yt().YoutubeDL(opts) as ydl:
                info = ydl.extract_info("ytsearch6:" + url[len("ytsearch1:"):], download=False)
            ranked = rank_candidates((info or {}).get("entries") or [], expected)
            return ranked[:self.MAX_ATTEMPTS] or [url]
        except Exception as e:
            logger.info(f"No se pudieron comparar versiones, se usa la primera: {e}")
            return [url]

    @staticmethod
    def _should_retry(error: Exception) -> bool:
        text = str(error).lower()
        if "cancelada" in text:
            return False
        from services.network_service import is_network_error
        return not is_network_error(text)       # sin internet no sirve probar con otra versión

    # ---------------------------------------------------------------- run
    def run(self):
        url = self.item_info['url']
        video_id = self.item_info['id']
        title = self.item_info['title']
        artist = self.item_info['uploader']
        thumbnail = self.item_info.get('thumbnail')
        album_val = self.item_info.get('album', '')
        expected = float(self.item_info.get('duration_secs') or 0)

        ffmpeg_path = FFmpegService.get_ffmpeg_path()
        target_dir = self.target_dir(artist, album_val)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Nombre de archivo limpio y profesional: Artista - Canción
        base_name = sanitize_filename(f"{artist} - {title}")
        format_code = (self.quality or '320').lower()
        final_ext = quality_service.encoder(format_code)[2]
        postprocessors = [quality_service.postprocessor(format_code)]
        out_template = str(target_dir / f"{base_name}.%(ext)s")
        final_file = str(target_dir / f"{base_name}.{final_ext}")

        ydl_opts = {
            'format': 'ba/b',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'keepvideo': False,
            'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
            'progress_hooks': [self._on_progress],
            'postprocessors': postprocessors,
            'socket_timeout': 20,
            'retries': 3,
        }
        if ffmpeg_path:
            ydl_opts['ffmpeg_location'] = os.path.dirname(ffmpeg_path) if ffmpeg_path.endswith('.exe') else ffmpeg_path

        candidates = self._candidates(url, expected)
        last_error = "No se pudo descargar."
        fallback = None                     # (ruta, motivo) de la versión «menos mala» si ninguna cumple
        success = False
        warning = ""
        try:
            for attempt, candidate in enumerate(candidates[:self.MAX_ATTEMPTS], 1):
                if self.is_cancelled:
                    raise RuntimeError("Descarga cancelada por el usuario")
                try:
                    with _yt().YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(candidate, download=True)
                        if info and 'entries' in info and info['entries']:
                            info = info['entries'][0]
                        downloaded_file = ydl.prepare_filename(info)
                    produced = os.path.splitext(downloaded_file)[0] + f".{final_ext}"
                except Exception as e:
                    last_error = str(e)
                    if self.is_cancelled or not self._should_retry(e):
                        raise
                    logger.info(f"Intento {attempt} fallido para {title}: {e}")
                    continue
                ok, reason = verify_download(produced, expected)
                if ok:
                    success = True
                    break
                last_error = reason
                logger.info(f"Intento {attempt} para {title}: {reason}")
                if os.path.isfile(produced) and "esperaban" in reason and attempt < len(candidates):
                    # no es la duración esperada, pero es un audio válido: se guarda por si ninguna otra sirve
                    if fallback and os.path.isfile(fallback[0]):
                        os.remove(fallback[0])
                    alt = produced + ".alt"
                    os.replace(produced, alt)
                    fallback = (alt, reason)
                elif os.path.isfile(produced) and "esperaban" in reason:
                    # último intento y tampoco coincide: se compara con la guardada y se queda la más parecida
                    if fallback is None:
                        fallback = (produced, reason)
                    else:
                        os.remove(fallback[0])
                        fallback = (produced, reason)
                elif os.path.isfile(produced):
                    os.remove(produced)
            if success:
                if fallback and os.path.isfile(fallback[0]):
                    os.remove(fallback[0])          # ya hay una buena: la «menos mala» sobra
                fallback = None
            elif fallback and os.path.isfile(fallback[0]):      # nada mejor: se queda la menos mala
                if os.path.abspath(fallback[0]) != os.path.abspath(final_file):
                    os.replace(fallback[0], final_file)
                warning = fallback[1]
                fallback = None
            else:
                raise RuntimeError(last_error)

            # Incrustar metadatos (portada, artista, título y álbum)
            if os.path.exists(final_file):
                MetadataService.embed_metadata(
                    mp3_path=final_file, title=title, artist=artist, album=album_val, thumbnail_url=thumbnail)
                self._embed_lyrics(final_file, title, artist)
                save_to_history(video_id, f"{artist} - {title}", final_file)

            self.finished_signal.emit({
                'success': True,
                'video_id': video_id,
                'title': f"{artist} - {title}",
                'artist': artist,
                'mp3_path': final_file,
                'warning': warning,
                'error': None
            })

        except Exception as e:
            logger.error(f"Error descargando {url}: {e}")
            if fallback and os.path.isfile(fallback[0]):
                try:
                    os.remove(fallback[0])
                except OSError:
                    pass
            self.finished_signal.emit({
                'success': False,
                'video_id': video_id,
                'title': title,
                'mp3_path': None,
                'error': str(e)
            })

    @staticmethod
    def _embed_lyrics(path: str, title: str, artist: str):
        """Busca la letra y la guarda dentro del archivo (así funciona sin internet y viaja con la canción).
        Si no hay letra o falla, no pasa nada."""
        try:
            from services import lyrics_service, lyrics_store, network_service
            if not network_service.is_online():
                return
            result = lyrics_service.fetch_lyrics(title, artist, max_seconds=8)
            if result:
                lyrics_store.write_embedded(path, result)
                lyrics_store.save_online(lyrics_store.key_for(title, artist), result)
        except Exception as e:
            logger.info(f"No se pudo guardar la letra en el archivo: {e}")

    def _on_progress(self, d):
        if self.is_cancelled:
            raise Exception("Descarga cancelada por el usuario")

        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed', 0) or 0
            eta = d.get('eta', 0) or 0

            percent = 0
            if total > 0:
                percent = int((downloaded / total) * 100)

            speed_mb = speed / (1024 * 1024) if speed else 0

            self.progress_signal.emit({
                'video_id': self.item_info['id'],
                'percent': percent,
                'speed_mb': speed_mb,
                'eta_secs': eta,
                'status': 'downloading'
            })
        elif d['status'] == 'finished':
            self.progress_signal.emit({
                'video_id': self.item_info['id'],
                'percent': 99,
                'speed_mb': 0,
                'eta_secs': 0,
                'status': 'converting'
            })
