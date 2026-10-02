import hashlib
import os
import shutil
import subprocess
import zipfile
import requests
from services import http
import logging
from config import FFMPEG_DIR, APP_DIR

logger = logging.getLogger(__name__)

MIN_EXE_BYTES = 5_000_000


def _expected_sha(zip_name: str) -> str | None:
    """Huella SHA-256 que BtbN publica junto a la descarga (checksums.sha256), o None si no se pudo leer."""
    try:
        r = http.get("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256", timeout=15)
        if r.status_code != 200:
            return None
        for line in r.text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == zip_name:
                return parts[0].lower()
    except Exception as e:
        logger.info(f"No se pudo leer la huella de FFmpeg: {e}")
    return None


class FFmpegService:
    @staticmethod
    def get_ffmpeg_path() -> str | None:
        """Busca ffmpeg en PATH del sistema, en APP_DIR o en FFMPEG_DIR."""
        # 1. En carpeta bin (empaquetada en la app o en el proyecto)
        from config import BASE_DIR
        bin_dir = BASE_DIR / "bin"
        if (bin_dir / "ffmpeg.exe").exists():
            if str(bin_dir) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            return str(bin_dir / "ffmpeg.exe")

        app_bin = APP_DIR / "bin"
        if (app_bin / "ffmpeg.exe").exists():
            if str(app_bin) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(app_bin) + os.pathsep + os.environ.get("PATH", "")
            return str(app_bin / "ffmpeg.exe")

        # 2. En PATH del sistema
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        
        # 3. En la carpeta app_data/ffmpeg/
        local_exe = FFMPEG_DIR / "ffmpeg.exe"
        if local_exe.exists() and local_exe.stat().st_size > MIN_EXE_BYTES:      # uno a medias no vale
            if str(FFMPEG_DIR) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ.get("PATH", "")
            return str(local_exe)
        
        # 4. En la carpeta raíz de la app
        app_exe = APP_DIR / "ffmpeg.exe"
        if app_exe.exists():
            if str(APP_DIR) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(APP_DIR) + os.pathsep + os.environ.get("PATH", "")
            return str(app_exe)
            
        return None

    @staticmethod
    def is_ffmpeg_available() -> bool:
        return FFmpegService.get_ffmpeg_path() is not None

    @staticmethod
    def download_ffmpeg_portable(progress_callback=None) -> bool:
        """
        Descarga una versión portable y ligera de ffmpeg para Windows si no está presente.
        """
        if FFmpegService.is_ffmpeg_available():
            return True
            
        url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        zip_path = FFMPEG_DIR / "ffmpeg_download.zip"
        
        try:
            if progress_callback:
                progress_callback("Descargando componentes de audio (FFmpeg)...")
                
            response = http.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            digest = hashlib.sha256()

            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            percent = int((downloaded / total_size) * 100)
                            progress_callback(f"Descargando componentes (FFmpeg): {percent}%")
                            
            expected = _expected_sha(url.rsplit("/", 1)[-1])
            if expected and digest.hexdigest() != expected:
                raise RuntimeError("La descarga de FFmpeg llegó dañada.")
            if progress_callback:
                progress_callback("Descomprimiendo componentes...")
                
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    if member.endswith("ffmpeg.exe"):          # ffprobe no hace falta: ahorra ~145 MB de disco
                        filename = os.path.basename(member)
                        target_file = FFMPEG_DIR / filename
                        part = FFMPEG_DIR / (filename + ".part")        # se extrae aparte: un corte no deja un .exe a medias
                        with zip_ref.open(member) as source, open(part, "wb") as target:
                            shutil.copyfileobj(source, target)
                        check = subprocess.run([str(part), "-version"], capture_output=True, timeout=30,
                                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        if check.returncode != 0:
                            part.unlink(missing_ok=True)
                            raise RuntimeError("El FFmpeg descargado no funciona.")
                        os.replace(part, target_file)
                            
            if zip_path.exists():
                zip_path.unlink()
                
            return FFmpegService.is_ffmpeg_available()
        except Exception as e:
            logger.error(f"Error descargando ffmpeg: {e}")
            if zip_path.exists():
                try:
                    zip_path.unlink()
                except Exception:
                    pass
            return False
