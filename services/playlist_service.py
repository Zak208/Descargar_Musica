import copy
import os
import uuid
from datetime import datetime
import logging
from config import FAVORITES_FILE, PLAYLISTS_FILE, COVERS_DIR, atomic_write_json, read_json

logger = logging.getLogger(__name__)


_UNKNOWN_ARTIST = "artista desconocido"


def _norm(text) -> str:
    return " ".join(str(text or "").strip().lower().split())


class PlaylistService:
    # Caché en memoria de favoritos y listas: pasar el ratón por una fila consultaba estos archivos cada vez.
    # Se invalida sola si el archivo cambia (fecha y tamaño) o al guardar.
    _cache: dict = {}

    @staticmethod
    def _stamp(file_path):
        try:
            st = os.stat(file_path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    @classmethod
    def _shared(cls, file_path, default_val):
        """Datos compartidos (NO se deben modificar). Para modificar, usa `_load_json`."""
        stamp = cls._stamp(file_path)
        hit = cls._cache.get(str(file_path))
        if hit is not None and hit[0] == stamp:
            return hit[1]
        data = read_json(file_path, None)
        if data is None or not isinstance(data, type(default_val)):
            data = copy.deepcopy(default_val)
        cls._cache[str(file_path)] = (cls._stamp(file_path), data)
        return data

    @classmethod
    def _load_json(cls, file_path, default_val):
        return copy.deepcopy(cls._shared(file_path, default_val))

    @classmethod
    def _save_json(cls, file_path, data):
        try:
            atomic_write_json(file_path, data)
            cls._cache[str(file_path)] = (cls._stamp(file_path), copy.deepcopy(data))
        except Exception as e:
            cls._cache.pop(str(file_path), None)
            logger.error(f"Error guardando {file_path}: {e}")

    @staticmethod
    def _same(t: dict, track_id: str, title: str, artist: str = "") -> bool:
        """¿Es la misma canción? Mismo identificador o, si no, mismo título y el mismo artista (si se conocen los dos)."""
        if track_id and str(t.get("id")) == track_id:
            return True
        if not title or _norm(t.get("title")) != title:
            return False
        other = _norm(t.get("uploader"))
        if not artist or not other or artist == _UNKNOWN_ARTIST or other == _UNKNOWN_ARTIST:
            return True
        return artist == other or artist in other or other in artist

    # ================= FAVORITOS =================
    @classmethod
    def get_favorites(cls) -> list:
        return cls._load_json(FAVORITES_FILE, [])

    @classmethod
    def is_favorite(cls, track_id: str, track_title: str = "", artist: str = "") -> bool:
        title = _norm(track_title)
        return any(cls._same(t, str(track_id or ""), title, _norm(artist)) for t in cls._shared(FAVORITES_FILE, []))

    @classmethod
    def toggle_favorite(cls, track_info: dict) -> bool:
        """Alterna el estado de favorito de una canción. Retorna True si ahora es favorita."""
        favs = cls.get_favorites()
        track_id = str(track_info.get("id", ""))
        title = _norm(track_info.get("title"))
        artist = _norm(track_info.get("uploader"))

        found_idx = -1
        for idx, t in enumerate(favs):
            if cls._same(t, track_id, title, artist):
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
    def snapshot_playlist(cls, playlist_id: str):
        """Copia de una lista (para poder deshacer su borrado)."""
        import copy
        data = cls.get_playlists().get(playlist_id)
        return copy.deepcopy(data) if data else None

    @classmethod
    def restore_playlist(cls, playlist_id: str, data: dict) -> bool:
        playlists = cls.get_playlists()
        if playlist_id in playlists or not data:
            return False
        playlists[playlist_id] = data
        cls._save_json(PLAYLISTS_FILE, playlists)
        return True

    @classmethod
    def insert_track(cls, playlist_id: str, item: dict, index: int) -> bool:
        """Vuelve a poner una canción en su sitio de la lista (para deshacer «quitar de la lista»)."""
        playlists = cls.get_playlists()
        if playlist_id not in playlists:
            return False
        tracks = playlists[playlist_id].setdefault("tracks", [])
        if any(str(t.get("id")) == str(item.get("id")) for t in tracks):
            return False
        tracks.insert(max(0, min(index, len(tracks))), item)
        cls._save_json(PLAYLISTS_FILE, playlists)
        return True

    @classmethod
    def move_tracks(cls, playlist_id: str, track_ids: list, to_index: int) -> bool:
        """Mueve canciones dentro de la lista a la posición `to_index` (la posición se cuenta antes de moverlas)."""
        playlists = cls.get_playlists()
        if playlist_id not in playlists:
            return False
        tracks = playlists[playlist_id].get("tracks", [])
        wanted = [str(t) for t in track_ids]
        moving = [t for t in tracks if str(t.get("id")) in wanted]
        if not moving:
            return False
        before = sum(1 for i, t in enumerate(tracks) if i < to_index and str(t.get("id")) in wanted)
        rest = [t for t in tracks if str(t.get("id")) not in wanted]
        at = max(0, min(len(rest), to_index - before))
        playlists[playlist_id]["tracks"] = rest[:at] + moving + rest[at:]
        cls._save_json(PLAYLISTS_FILE, playlists)
        return True

    @classmethod
    def track_index(cls, playlist_id: str, track_id: str) -> int:
        tracks = cls.get_playlists().get(playlist_id, {}).get("tracks", [])
        return next((i for i, t in enumerate(tracks) if str(t.get("id")) == str(track_id)), -1)

    @classmethod
    def restore_favorite(cls, item: dict) -> bool:
        """Vuelve a poner una canción en favoritas, tal cual estaba (para deshacer)."""
        favs = cls.get_favorites()
        if any(str(t.get("id")) == str(item.get("id")) for t in favs):
            return False
        favs.insert(0, item)
        cls._save_json(FAVORITES_FILE, favs)
        return True

    @classmethod
    def get_favorite(cls, track_id: str, title: str = "", artist: str = ""):
        title = _norm(title)
        for t in cls._shared(FAVORITES_FILE, []):
            if cls._same(t, str(track_id or ""), title, _norm(artist)):
                return dict(t)
        return None

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
        title = _norm(track_info.get("title"))
        artist = _norm(track_info.get("uploader"))

        # Evitar duplicados exactos en la misma playlist
        for t in tracks:
            if cls._same(t, track_id, title, artist):
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

    # ================= PERTENENCIA A LISTAS =================
    @classmethod
    def lists_containing(cls, track_info: dict) -> set:
        """Claves de las listas donde está la canción: 'favorites' y/o los identificadores de tus playlists."""
        track_id = str(track_info.get("id", ""))
        title = _norm(track_info.get("title"))
        artist = _norm(track_info.get("uploader"))
        found = set()
        if any(cls._same(t, track_id, title, artist) for t in cls._shared(FAVORITES_FILE, [])):
            found.add("favorites")
        for p_id, data in cls._shared(PLAYLISTS_FILE, {}).items():
            if any(cls._same(t, track_id, title, artist) for t in data.get("tracks", [])):
                found.add(p_id)
        return found

    @classmethod
    def toggle_in_playlist(cls, playlist_id: str, track_info: dict) -> bool:
        """Añade la canción a la lista o la quita si ya estaba. Devuelve True si ahora está dentro."""
        track_id = str(track_info.get("id", ""))
        title = _norm(track_info.get("title"))
        artist = _norm(track_info.get("uploader"))
        tracks = cls._shared(PLAYLISTS_FILE, {}).get(playlist_id, {}).get("tracks", [])
        match = next((t for t in tracks if cls._same(t, track_id, title, artist)), None)
        if match is None:
            return cls.add_track_to_playlist(playlist_id, track_info)
        cls.remove_track_from_playlist(playlist_id, match.get("id"))
        return False

    @classmethod
    def relocate(cls, old_path: str, new_path: str = "") -> int:
        """Una canción cambió de sitio (o se borró): actualiza su ruta en favoritos y listas. Devuelve cuántas entradas tocó."""
        if not old_path:
            return 0
        key = os.path.normcase(os.path.abspath(old_path))
        changed = 0
        favs = cls._load_json(FAVORITES_FILE, [])
        playlists = cls._load_json(PLAYLISTS_FILE, {})
        groups = [(favs, FAVORITES_FILE, [favs]),
                  (playlists, PLAYLISTS_FILE, [p.get("tracks", []) for p in playlists.values()])]
        for data, file_path, lists in groups:
            touched = False
            for tracks in lists:
                for t in tracks:
                    lp = t.get("local_path")
                    if lp and os.path.normcase(os.path.abspath(lp)) == key:
                        if new_path:
                            t["local_path"] = new_path
                        else:
                            t.pop("local_path", None)
                            t.pop("already_downloaded", None)
                        touched = True
                        changed += 1
            if touched:
                cls._save_json(file_path, data)
        return changed
