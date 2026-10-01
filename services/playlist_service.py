import json
import uuid
from datetime import datetime
import logging
from config import FAVORITES_FILE, PLAYLISTS_FILE, COVERS_DIR

logger = logging.getLogger(__name__)


class PlaylistService:
    @staticmethod
    def _load_json(file_path, default_val):
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error cargando {file_path}: {e}")
        return default_val

    @staticmethod
    def _save_json(file_path, data):
        try:
            from config import atomic_write_json
            atomic_write_json(file_path, data)
        except Exception as e:
            logger.error(f"Error guardando {file_path}: {e}")

    # ================= FAVORITOS =================
    @classmethod
    def get_favorites(cls) -> list:
        return cls._load_json(FAVORITES_FILE, [])

    @classmethod
    def is_favorite(cls, track_id: str, track_title: str = "") -> bool:
        favs = cls.get_favorites()
        for t in favs:
            if track_id and str(t.get("id")) == str(track_id):
                return True
            if track_title and t.get("title", "").strip().lower() == track_title.strip().lower():
                return True
        return False

    @classmethod
    def toggle_favorite(cls, track_info: dict) -> bool:
        """Alterna el estado de favorito de una canción. Retorna True si ahora es favorita."""
        favs = cls.get_favorites()
        track_id = str(track_info.get("id", ""))
        title = track_info.get("title", "").strip().lower()

        found_idx = -1
        for idx, t in enumerate(favs):
            if (track_id and str(t.get("id")) == track_id) or (title and t.get("title", "").strip().lower() == title):
                found_idx = idx
                break

        if found_idx >= 0:
            favs.pop(found_idx)
            cls._save_json(FAVORITES_FILE, favs)
            return False
        else:
            item = {
                "id": track_id or str(uuid.uuid4())[:8],
                "title": track_info.get("title", "Canción"),
                "uploader": track_info.get("uploader", "Artista Desconocido"),
                "album": track_info.get("album", ""),
                "duration_str": track_info.get("duration_str", "0:00"),
                "duration_secs": track_info.get("duration_secs", 0),
                "thumbnail": track_info.get("thumbnail", ""),
                "url": track_info.get("url", f"ytsearch1:{track_info.get('uploader', '')} {track_info.get('title', '')}"),
                "added_at": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            if track_info.get("local_path"):
                item["local_path"] = track_info["local_path"]
                item["already_downloaded"] = True
            favs.insert(0, item)
            cls._save_json(FAVORITES_FILE, favs)
            return True

    # ================= PLAYLISTS PROPIAS =================
    @classmethod
    def get_playlists(cls) -> dict:
        return cls._load_json(PLAYLISTS_FILE, {})

    @classmethod
    def create_playlist(cls, name: str) -> str:
        playlists = cls.get_playlists()
        p_id = str(uuid.uuid4())[:8]
        playlists[p_id] = {
            "id": p_id,
            "name": name.strip(),
            "created_at": datetime.now().strftime("%d/%m/%Y"),
            "tracks": []
        }
        cls._save_json(PLAYLISTS_FILE, playlists)
        return p_id

    @classmethod
    def delete_playlist(cls, playlist_id: str) -> bool:
        playlists = cls.get_playlists()
        if playlist_id in playlists:
            del playlists[playlist_id]
            cls._save_json(PLAYLISTS_FILE, playlists)
            return True
        return False

    @classmethod
    def rename_playlist(cls, playlist_id: str, new_name: str) -> bool:
        playlists = cls.get_playlists()
        if playlist_id in playlists:
            playlists[playlist_id]["name"] = new_name.strip()
            cls._save_json(PLAYLISTS_FILE, playlists)
            return True
        return False

    @classmethod
    def get_cover_path(cls, playlist_id: str):
        """Ruta de la imagen personalizada de una playlist, o None si no tiene."""
        name = cls.get_playlists().get(playlist_id, {}).get("cover")
        if name and (COVERS_DIR / name).exists():
            return str(COVERS_DIR / name)
        return None

    @classmethod
    def set_cover_filename(cls, playlist_id: str, filename) -> bool:
        playlists = cls.get_playlists()
        if playlist_id not in playlists:
            return False
        if filename:
            playlists[playlist_id]["cover"] = filename
        else:
            old = playlists[playlist_id].pop("cover", None)
            if old:
                try:
                    (COVERS_DIR / old).unlink()
                except OSError:
                    pass
        cls._save_json(PLAYLISTS_FILE, playlists)
        return True

    @classmethod
    def add_track_to_playlist(cls, playlist_id: str, track_info: dict) -> bool:
        playlists = cls.get_playlists()
        if playlist_id not in playlists:
            return False

        tracks = playlists[playlist_id].setdefault("tracks", [])
        track_id = str(track_info.get("id", ""))
        title = track_info.get("title", "").strip().lower()

        # Evitar duplicados exactos en la misma playlist
        for t in tracks:
            if (track_id and str(t.get("id")) == track_id) or (title and t.get("title", "").strip().lower() == title):
                return False

        item = {
            "id": track_id or str(uuid.uuid4())[:8],
            "title": track_info.get("title", "Canción"),
            "uploader": track_info.get("uploader", "Artista Desconocido"),
            "album": track_info.get("album", ""),
            "duration_str": track_info.get("duration_str", "0:00"),
            "duration_secs": track_info.get("duration_secs", 0),
            "thumbnail": track_info.get("thumbnail", ""),
            "url": track_info.get("url", f"ytsearch1:{track_info.get('uploader', '')} {track_info.get('title', '')}"),
            "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        if track_info.get("local_path"):
            item["local_path"] = track_info["local_path"]
            item["already_downloaded"] = True
        tracks.append(item)
        cls._save_json(PLAYLISTS_FILE, playlists)
        return True

    @classmethod
    def remove_track_from_playlist(cls, playlist_id: str, track_id: str) -> bool:
        playlists = cls.get_playlists()
        if playlist_id not in playlists:
            return False

        tracks = playlists[playlist_id].get("tracks", [])
        initial_len = len(tracks)
        playlists[playlist_id]["tracks"] = [t for t in tracks if str(t.get("id")) != str(track_id)]
        if len(playlists[playlist_id]["tracks"]) < initial_len:
            cls._save_json(PLAYLISTS_FILE, playlists)
            return True
        return False
