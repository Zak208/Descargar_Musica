"""Actualizar la propia aplicación desde GitHub.

Flujo: se mira la última versión publicada (Release) del repositorio, se descarga su .zip (solo desde GitHub, por HTTPS),
se comprueba su huella SHA-256 con el archivo `.sha256` publicado junto a él y se deja descomprimido en una carpeta de
preparación dentro de tus datos. Al pulsar «Reiniciar y actualizar», la aplicación se cierra y un pequeño script copia
los archivos nuevos sobre los de la carpeta del programa y lo vuelve a abrir. Tus datos (listas, ajustes, letras) viven
en `%APPDATA%` y no se tocan.

Solo funciona con el programa compilado (.exe); ejecutando desde el código fuente la actualización se hace con `git pull`."""
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from config import APP_DATA_DIR, load_settings, save_settings
from services import http, ytdlp_loader
from version import __version__

logger = logging.getLogger(__name__)

REPO = "Zak208/Descargar_Musica"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ALLOWED_PREFIX = f"https://github.com/{REPO}/releases/download/"
UPDATE_DIR = APP_DATA_DIR / "actualizacion"
STAGED_DIR = UPDATE_DIR / "preparada"
EXE_NAME = "Descargar_Musica.exe"
FOLDER_NAME = "Descargar_Musica"          # carpeta que contiene el .zip publicado
_SHA = re.compile(r"\b([0-9a-fA-F]{64})\b")


def can_self_update() -> bool:
    """Solo el programa compilado se puede actualizar solo."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def is_newer(version: str) -> bool:
    return ytdlp_loader.parse_version(version) > ytdlp_loader.parse_version(__version__)


# ------------------------------------------------------------------ la versión publicada
def fetch_release() -> dict | None:
    """{'version', 'zip_url', 'sha_url', 'size'} de la última versión publicada, o None si no se puede usar."""
    r = http.get(API_LATEST, headers={"Accept": "application/vnd.github+json"}, timeout=12)
    if r.status_code != 200:
        return None
    data = r.json()
    version = (data.get("tag_name") or "").strip().lstrip("vV")
    zip_url = sha_url = ""
    size = 0
    for asset in data.get("assets", []):
        name, url = asset.get("name", ""), asset.get("browser_download_url", "")
        if not url.startswith(ALLOWED_PREFIX):
            continue
        if name.endswith("-windows.zip"):
            zip_url, size = url, int(asset.get("size", 0) or 0)
        elif name.endswith("-windows.zip.sha256"):
            sha_url = url
    if not (version and zip_url and sha_url):
        return None            # sin huella publicada no se actualiza (no se podría comprobar la descarga)
    return {"version": version, "zip_url": zip_url, "sha_url": sha_url, "size": size}


# ------------------------------------------------------------------ descarga y preparación
def safe_extract(zip_path: str, dest: Path) -> None:
    """Descomprime sin dejar que ningún archivo se salga de la carpeta de destino."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if dest != target and dest not in target.parents:
                raise RuntimeError("El archivo descargado no es válido.")
        zf.extractall(dest)


def clear_staged() -> None:
    shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    settings = load_settings()
    if "staged_update" in settings:
        settings.pop("staged_update")
        save_settings(settings)


def staged_version() -> str | None:
    """Versión que ya está descargada y lista para instalar (si sigue siendo más nueva que la actual)."""
    info = load_settings().get("staged_update")
    if not isinstance(info, dict):
        return None
    version, folder = info.get("version", ""), Path(info.get("dir", ""))
    if version and is_newer(version) and (folder / EXE_NAME).is_file():
        return version
    if info:
        clear_staged()
    return None


def staged_folder() -> Path | None:
    info = load_settings().get("staged_update")
    return Path(info["dir"]) if isinstance(info, dict) and info.get("dir") else None


class AppUpdateWorker(QThread):
    """Descarga la versión nueva, comprueba su huella y la deja preparada. `done(versión)` o `failed(mensaje)`."""
    progress = Signal(int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        self.setPriority(QThread.LowPriority)
        try:
            release = fetch_release()
            if release is None:
                raise RuntimeError("La versión nueva todavía no está lista para descargarse.")
            if not is_newer(release["version"]):
                raise RuntimeError("Ya tienes la última versión.")
            sha_text = http.get(release["sha_url"], timeout=15).text
            m = _SHA.search(sha_text)
            if not m:
                raise RuntimeError("No se pudo comprobar la descarga.")
            expected = m.group(1).lower()
            shutil.rmtree(UPDATE_DIR, ignore_errors=True)
            UPDATE_DIR.mkdir(parents=True, exist_ok=True)
            part = UPDATE_DIR / "descarga.zip.part"
            sha = hashlib.sha256()
            with http.get(release["zip_url"], stream=True, timeout=30) as r, open(part, "wb") as f:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0)) or release["size"] or 1
                got = 0
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    f.write(chunk)
                    sha.update(chunk)
                    got += len(chunk)
                    self.progress.emit(min(99, int(100 * got / total)))
            if sha.hexdigest() != expected:
                raise RuntimeError("La descarga llegó dañada. Inténtalo de nuevo.")
            STAGED_DIR.mkdir(parents=True, exist_ok=True)
            safe_extract(str(part), STAGED_DIR)
            part.unlink(missing_ok=True)
            folder = STAGED_DIR / FOLDER_NAME
            if not (folder / EXE_NAME).is_file():
                raise RuntimeError("El archivo descargado no contiene el programa.")
            settings = load_settings()
            settings["staged_update"] = {"version": release["version"], "dir": str(folder)}
            save_settings(settings)
            self.progress.emit(100)
            self.done.emit(release["version"])
        except Exception as e:
            logger.warning(f"No se pudo descargar la actualización: {e}")
            shutil.rmtree(UPDATE_DIR, ignore_errors=True)
            self.failed.emit(str(e) or "No se pudo descargar.")


# ------------------------------------------------------------------ instalar y reiniciar
def build_script(staged: Path, target: Path, pid: int, exe_name: str = EXE_NAME, workdir: Path = UPDATE_DIR) -> Path:
    """Script de Windows que espera a que la aplicación se cierre, copia los archivos nuevos y la vuelve a abrir."""
    workdir.mkdir(parents=True, exist_ok=True)
    script = workdir / "instalar.cmd"
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        r'set "SYS=%SystemRoot%\System32"',          # programas de Windows con su ruta completa (no otros con el mismo nombre)
        f'set "SRC={staged}"',
        f'set "DST={target}"',
        f'set "STAGE={workdir}"',
        f"set PID={pid}",
        ":espera",
        r'"%SYS%\tasklist.exe" /FI "PID eq %PID%" 2>nul | "%SYS%\find.exe" "%PID%" >nul',
        "if not errorlevel 1 (",
        r'  "%SYS%\ping.exe" -n 2 127.0.0.1 >nul',
        "  goto espera",
        ")",
        r'"%SYS%\robocopy.exe" "%SRC%" "%DST%" /E /R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul',
        f'start "" "%DST%\\{exe_name}"',
        'rd /s /q "%STAGE%" >nul 2>&1',
    ]
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return script


def install_and_restart() -> bool:
    """Lanza el script de instalación (separado de la aplicación). Quien llama debe cerrar la aplicación enseguida."""
    folder = staged_folder()
    if folder is None or not (folder / EXE_NAME).is_file() or not can_self_update():
        return False
    try:
        script = build_script(folder, install_dir(), os.getpid())
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
        settings = load_settings()
        settings.pop("staged_update", None)
        save_settings(settings)
        return True
    except Exception as e:
        logger.warning(f"No se pudo lanzar la actualización: {e}")
        return False
