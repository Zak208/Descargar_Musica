import os
import requests
from services import http
import logging
from pathlib import Path
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture

logger = logging.getLogger(__name__)


class MetadataService:
    @staticmethod
    def embed_metadata(mp3_path: str, title: str, artist: str, album: str = "", thumbnail_url: str = None) -> bool:
        """Incrusta título, artista, álbum y carátula en archivos MP3, M4A o FLAC."""
        try:
            audio_path = Path(mp3_path)
            if not audio_path.exists():
                return False

            ext = audio_path.suffix.lower()

            image_data = None
            mime_type = "image/jpeg"
            if thumbnail_url:
                try:
                    res = http.get(thumbnail_url, timeout=10)
                    if res.status_code == 200:
                        image_data = res.content
                        mime_type = "image/png" if thumbnail_url.lower().endswith(".png") else "image/jpeg"
                except Exception as img_err:
                    logger.warning(f"No se pudo descargar la portada: {img_err}")

            if ext == ".mp3":
                try:
                    tags = ID3(mp3_path)
                except ID3NoHeaderError:
                    tags = ID3()

                if title:
                    tags["TIT2"] = TIT2(encoding=3, text=title)
                if artist:
                    tags["TPE1"] = TPE1(encoding=3, text=artist)
                if album:
                    tags["TALB"] = TALB(encoding=3, text=album)

                if image_data:
                    tags["APIC"] = APIC(
                        encoding=3,
                        mime=mime_type,
                        type=3,  # Front cover
                        desc="Cover",
                        data=image_data
                    )
                tags.save(mp3_path)
                return True

            elif ext == ".m4a":
                audio = MP4(mp3_path)
                if title:
                    audio["\xa9nam"] = [title]
                if artist:
                    audio["\xa9ART"] = [artist]
                if album:
                    audio["\xa9alb"] = [album]
                if image_data:
                    cov_fmt = MP4Cover.FORMAT_PNG if mime_type == "image/png" else MP4Cover.FORMAT_JPEG
                    audio["covr"] = [MP4Cover(image_data, imageformat=cov_fmt)]
                audio.save()
                return True

            elif ext == ".flac":
                audio = FLAC(mp3_path)
                if title:
                    audio["title"] = [title]
                if artist:
                    audio["artist"] = [artist]
                if album:
                    audio["album"] = [album]
                if image_data:
                    pic = Picture()
                    pic.data = image_data
                    pic.type = 3
                    pic.mime = mime_type
                    audio.clear_pictures()
                    audio.add_picture(pic)
                audio.save()
                return True

            return False
        except Exception as e:
            logger.error(f"Error incrustando metadatos en {mp3_path}: {e}")
            return False

    @staticmethod
    def read_metadata(file_path: str) -> dict:
        """Lee los metadatos actuales de un archivo de audio (MP3, M4A, FLAC)."""
        result = {
            "title": "",
            "artist": "",
            "album": "",
            "has_cover": False,
            "cover_data": None
        }
        try:
            ext = Path(file_path).suffix.lower()
            if ext == ".mp3":
                tags = ID3(file_path)
                if "TIT2" in tags:
                    result["title"] = str(tags["TIT2"])
                if "TPE1" in tags:
                    result["artist"] = str(tags["TPE1"])
                if "TALB" in tags:
                    result["album"] = str(tags["TALB"])
                for key in tags.keys():
                    if key.startswith("APIC"):
                        result["has_cover"] = True
                        result["cover_data"] = tags[key].data
                        break
            elif ext == ".m4a":
                audio = MP4(file_path)
                if "\xa9nam" in audio:
                    result["title"] = str(audio["\xa9nam"][0])
                if "\xa9ART" in audio:
                    result["artist"] = str(audio["\xa9ART"][0])
                if "\xa9alb" in audio:
                    result["album"] = str(audio["\xa9alb"][0])
                if "covr" in audio and audio["covr"]:
                    result["has_cover"] = True
                    result["cover_data"] = bytes(audio["covr"][0])
            elif ext == ".flac":
                audio = FLAC(file_path)
                if "title" in audio:
                    result["title"] = str(audio["title"][0])
                if "artist" in audio:
                    result["artist"] = str(audio["artist"][0])
                if "album" in audio:
                    result["album"] = str(audio["album"][0])
                if audio.pictures:
                    result["has_cover"] = True
                    result["cover_data"] = audio.pictures[0].data
        except Exception:
            pass
        return result

    @staticmethod
    def update_metadata(file_path: str, title: str, artist: str, album: str = "", new_cover_path: str = None) -> bool:
        """Actualiza manualmente metadatos y carátula de un archivo (MP3, M4A, FLAC)."""
        try:
            ext = Path(file_path).suffix.lower()
            img_data = None
            mime = "image/jpeg"
            if new_cover_path and os.path.exists(new_cover_path):
                with open(new_cover_path, "rb") as f:
                    img_data = f.read()
                mime = "image/png" if new_cover_path.lower().endswith(".png") else "image/jpeg"

            if ext == ".mp3":
                try:
                    tags = ID3(file_path)
                except ID3NoHeaderError:
                    tags = ID3()
                tags["TIT2"] = TIT2(encoding=3, text=title)
                tags["TPE1"] = TPE1(encoding=3, text=artist)
                if album:
                    tags["TALB"] = TALB(encoding=3, text=album)
                if img_data:
                    tags["APIC"] = APIC(
                        encoding=3,
                        mime=mime,
                        type=3,
                        desc="Cover",
                        data=img_data
                    )
                tags.save(file_path)
                return True
            elif ext == ".m4a":
                audio = MP4(file_path)
                audio["\xa9nam"] = [title]
                audio["\xa9ART"] = [artist]
                if album:
                    audio["\xa9alb"] = [album]
                if img_data:
                    cov_fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
                    audio["covr"] = [MP4Cover(img_data, imageformat=cov_fmt)]
                audio.save()
                return True
            elif ext == ".flac":
                audio = FLAC(file_path)
                audio["title"] = [title]
                audio["artist"] = [artist]
                if album:
                    audio["album"] = [album]
                if img_data:
                    pic = Picture()
                    pic.data = img_data
                    pic.type = 3
                    pic.mime = mime
                    audio.clear_pictures()
                    audio.add_picture(pic)
                audio.save()
                return True
            return False
        except Exception as e:
            logger.error(f"Error actualizando metadatos de {file_path}: {e}")
            return False
