"""Artistas que sigue el usuario (como 'seguir' en Spotify). Se guardan en un archivo JSON local."""
import json
import logging
from datetime import datetime

from config import ARTISTS_FILE, atomic_write_json

logger = logging.getLogger(__name__)


class ArtistService:
    @staticmethod
    def _load() -> dict:
        try:
            if ARTISTS_FILE.exists():
                with open(ARTISTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.warning(f"No se pudieron leer los artistas seguidos: {e}")
        return {}

    @staticmethod
    def _save(data: dict) -> None:
        try:
            atomic_write_json(ARTISTS_FILE, data)
        except Exception as e:
            logger.warning(f"No se pudieron guardar los artistas seguidos: {e}")

    @classmethod
    def get_followed(cls) -> list:
        """Artistas seguidos, el último en seguirse primero."""
        items = list(cls._load().values())
        items.sort(key=lambda a: a.get("followed_at", ""), reverse=True)
        return items

    @classmethod
    def is_following(cls, artist_id) -> bool:
        return str(artist_id) in cls._load()

    @classmethod
    def follow(cls, artist_id, name: str, avatar: str = "") -> None:
        data = cls._load()
        data[str(artist_id)] = {
            "id": str(artist_id),
            "name": name,
            "avatar": avatar or "",
            "followed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        cls._save(data)

    @classmethod
    def unfollow(cls, artist_id) -> None:
        data = cls._load()
        if data.pop(str(artist_id), None) is not None:
            cls._save(data)

    @classmethod
    def toggle(cls, artist_id, name: str, avatar: str = "") -> bool:
        """Sigue o deja de seguir. Devuelve True si ahora se sigue al artista."""
        if cls.is_following(artist_id):
            cls.unfollow(artist_id)
            return False
        cls.follow(artist_id, name, avatar)
        return True
