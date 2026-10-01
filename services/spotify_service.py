import re
import json
import logging
import requests

logger = logging.getLogger(__name__)


def is_spotify_url(text: str) -> bool:
    """Verifica si el texto introducido es un enlace de Spotify."""
    text = text.strip().lower()
    return "open.spotify.com/" in text or "spotify.link/" in text


def is_spotify_playlist_or_album(text: str) -> bool:
    """Verifica si es un enlace de playlist o álbum de Spotify."""
    text = text.strip().lower()
    return is_spotify_url(text) and ("/playlist/" in text or "/album/" in text)


def get_spotify_track_info(url: str) -> dict | None:
    """Extrae título, artista y portada de una pista de Spotify usando su página embed pública."""
    try:
        # Extraer ID o usar URL de embed
        match = re.search(r'spotify\.com/track/([a-zA-Z0-9]+)', url)
        if not match:
            # Probar vía oEmbed
            oembed_url = f"https://open.spotify.com/oembed?url={url}"
            r = requests.get(oembed_url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                title = data.get("title", "")
                author = data.get("author_name", "")
                thumb = data.get("thumbnail_url", "")
                return {
                    "title": title,
                    "artist": author,
                    "thumbnail": thumb,
                    "search_query": f"{author} - {title}" if author else title
                }
            return None

        track_id = match.group(1)
        embed_url = f"https://open.spotify.com/embed/track/{track_id}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(embed_url, headers=headers, timeout=6)
        if r.status_code == 200:
            data_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
            if data_match:
                d = json.loads(data_match.group(1))
                entity = d.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                title = entity.get("name", "")
                artists = [a.get("name") for a in entity.get("artists", []) if a.get("name")]
                artist = ", ".join(artists) if artists else "Artista"
                
                # Portada
                thumb = ""
                images = entity.get("album", {}).get("images", []) or entity.get("images", [])
                if images and isinstance(images, list) and len(images) > 0:
                    thumb = images[0].get("url", "")

                if not thumb:
                    try:
                        oembed_url = f"https://open.spotify.com/oembed?url={url}"
                        r_oe = requests.get(oembed_url, timeout=3)
                        if r_oe.status_code == 200:
                            thumb = r_oe.json().get("thumbnail_url", "")
                    except Exception:
                        pass

                return {
                    "title": title,
                    "artist": artist,
                    "thumbnail": thumb,
                    "search_query": f"{artist} - {title}"
                }
    except Exception as e:
        logger.error(f"Error resolviendo track de Spotify: {e}")
    return None


def get_spotify_collection_tracks(url: str) -> dict | None:
    """Extrae las canciones de una playlist o álbum de Spotify."""
    try:
        match = re.search(r'spotify\.com/(playlist|album)/([a-zA-Z0-9]+)', url)
        if not match:
            return None

        col_type = match.group(1)
        col_id = match.group(2)
        embed_url = f"https://open.spotify.com/embed/{col_type}/{col_id}"
        headers = {"User-Agent": "Mozilla/5.0"}

        r = requests.get(embed_url, headers=headers, timeout=8)
        if r.status_code != 200:
            return None

        data_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
        if not data_match:
            return None

        d = json.loads(data_match.group(1))
        entity = d.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        col_name = entity.get("name", "Colección Spotify")

        # Portada
        cover = ""
        images = entity.get("images", [])
        if images and isinstance(images, list):
            cover = images[0].get("url", "")

        tracks = []
        track_list = entity.get("trackList", [])
        for item in track_list:
            t_title = item.get("title")
            t_artists = [a.get("name") for a in item.get("artists", []) if a.get("name")]
            t_artist = ", ".join(t_artists) if t_artists else "Artista"
            if t_title:
                tracks.append({
                    "title": t_title,
                    "artist": t_artist,
                    "search_query": f"{t_artist} - {t_title}",
                    "thumbnail": cover
                })

        return {
            "name": col_name,
            "type": col_type,
            "cover": cover,
            "tracks": tracks
        }
    except Exception as e:
        logger.error(f"Error resolviendo playlist de Spotify: {e}")
        return None
