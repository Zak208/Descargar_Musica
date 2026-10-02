"""Pruebas de la base: datos fuera del programa, copia de seguridad, espacio, sesión, ayuda, recorrido y primer uso.
Se ejecuta desde la carpeta del proyecto:  python dev_tools/prueba_base.py"""
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import _aislar  # noqa: F401  (datos temporales: no se tocan los del usuario)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication([])
import config
from services import backup_service, storage_service, session_service, diagnostics_service, quality


def check(label, cond):
    print(("OK   " if cond else "FALLO"), label, flush=True)


def pump(s=0.3):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


# ---- migración de datos desde la carpeta del programa
old = Path(tempfile.mkdtemp(prefix="viejo_"))
new = Path(tempfile.mkdtemp(prefix="nuevo_")) / "datos"
(old / "playlists.json").write_text('{"a": {"name": "Mi lista", "tracks": []}}', encoding="utf-8")
(old / "letras").mkdir()
(old / "letras" / "x.json").write_text('{"text": "hola", "source": "user"}', encoding="utf-8")
(old / "whisper").mkdir()
(old / "whisper" / "modelo.bin").write_bytes(b"0" * 100)
real_legacy = config.LEGACY_DATA_DIR
config.LEGACY_DATA_DIR = old
config._migrate_legacy_data(new)
config.LEGACY_DATA_DIR = real_legacy
check("migración: se copian listas y letras", (new / "playlists.json").exists() and (new / "letras" / "x.json").exists())
check("migración: lo pesado se mueve (whisper)", (new / "whisper" / "modelo.bin").exists() and not (old / "whisper").exists())
check("migración: la carpeta antigua conserva lo pequeño", (old / "playlists.json").exists())
(new / "playlists.json").write_text("{}", encoding="utf-8")
config.LEGACY_DATA_DIR = old
config._migrate_legacy_data(new)
config.LEGACY_DATA_DIR = real_legacy
check("migración: no se repite ni pisa datos", (new / "playlists.json").read_text(encoding="utf-8") == "{}")

# ---- copia de seguridad
data = config.APP_DATA_DIR
(data / "playlists.json").write_text('{"p1": {"name": "Gym", "tracks": []}}', encoding="utf-8")
(data / "favoritos.json").write_text('[{"id": "1", "title": "Tema"}]', encoding="utf-8")
(data / "letras").mkdir(exist_ok=True)
(data / "letras" / "k.json").write_text('{"text": "letra", "source": "user"}', encoding="utf-8")
(data / "img_cache").mkdir(exist_ok=True)
(data / "img_cache" / "a.bin").write_bytes(b"1" * 2048)
zip_path = Path(tempfile.mkdtemp()) / "copia.zip"
n = backup_service.create_backup(zip_path)
with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
check("copia: incluye listas, favoritos y letras, no cachés", n >= 3 and "playlists.json" in names
      and "letras/k.json" in names and not any(x.startswith("img_cache") for x in names))
check("copia: se reconoce como válida", backup_service.inspect_backup(zip_path) is not None)
bad = Path(tempfile.mkdtemp()) / "mala.zip"
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("hola.txt", "no soy una copia")
check("copia: un zip cualquiera se rechaza", backup_service.inspect_backup(bad) is None)
(data / "playlists.json").write_text("{}", encoding="utf-8")
backup_service.restore_backup(zip_path)
check("restaurar: vuelven las listas", "Gym" in (data / "playlists.json").read_text(encoding="utf-8"))
check("restaurar: antes se guarda el estado actual", any(backup_service.BACKUP_DIR.glob("antes-de-restaurar-*.zip")))
evil = Path(tempfile.mkdtemp()) / "evil.zip"
with zipfile.ZipFile(evil, "w") as z:
    z.writestr("COPIA.txt", "x")
    z.writestr("../fuera.txt", "peligro")
    z.writestr("letras/../../fuera2.txt", "peligro")
    z.writestr("settings.json", '{"theme": "spotify"}')
backup_service.restore_backup(evil)
check("restaurar: ignora rutas peligrosas", not (data.parent / "fuera.txt").exists() and not (data.parent.parent / "fuera2.txt").exists()
      and (data / "settings.json").exists())

# ---- espacio
rows = {r["key"]: r for r in storage_service.usage()}
check("espacio: ve la caché de imágenes", rows["imagenes"]["bytes"] >= 2048 and rows["imagenes"]["clearable"])
check("espacio: las letras no se pueden borrar desde ahí", not rows["letras"]["clearable"] and storage_service.clear("letras") == 0)
freed = storage_service.clear("imagenes")
check("espacio: se libera la caché", freed >= 2048 and not any((data / "img_cache").iterdir()))
check("formato de tamaños", storage_service.format_bytes(1536) == "1 KB" or storage_service.format_bytes(1536).endswith("KB"))
check("calidades con tamaño", "9 MB" in quality.label("320") and quality.encoder("flac")[2] == "flac"
      and quality.postprocessor("128")["preferredquality"] == "128")

# ---- sesión
session_service.save({"volume": 40, "track": "x.mp3"})
check("sesión: se guarda y se lee", session_service.load().get("volume") == 40)
check("informe: sin ruta personal y con versión", "Descargador de Música" in diagnostics_service.build_report()
      and os.path.expanduser("~") not in diagnostics_service.build_report())

# ---- ventana principal: ayuda, recorrido, primer uso, estados vacíos
from ui.main_window import MainWindow
from ui.welcome import WelcomeDialog
from ui.tour import TourOverlay

w = MainWindow()
w.audio_output.setVolume(0)
w.resize(1360, 860)
w.show()
pump(2.5)
check("ajustes: grupos de espacio y copia presentes", w.settings_dialog.btn_backup is not None and w.settings_dialog.space_grid.count() > 0)
w.open_list("downloads")
pump(1.5)
w.start_tour()
pump(0.5)
check("recorrido: se muestra y avanza", w.tour.isVisible() and w.tour.index == 0)
w.tour.next_step()
check("recorrido: segundo paso", w.tour.index == 1)
for _ in range(10):
    if w.tour.isVisible():
        w.tour.next_step()
pump(0.3)
check("recorrido: termina solo al final", not w.tour.isVisible())

# estado vacío con botón en una lista propia sin canciones
from services.playlist_service import PlaylistService
pid = PlaylistService.create_playlist("Vacía")
w.open_list("playlist", pid)
pump(1.0)
page = w.page_playlist
check("lista vacía: mensaje y botón de acción", page.empty_lbl.isVisible() and page.empty_btn.isVisible()
      and page.empty_btn.text() == "Añadir canciones")
PlaylistService.delete_playlist(pid)

# asistente de primer uso
dlg = WelcomeDialog(w)
check("asistente: 4 pasos", dlg.steps.count() == 4)
dlg.steps.setCurrentIndex(1)
dlg.group.buttons()[1].setChecked(True)
dlg._next()
check("asistente: la calidad elegida se guarda", config.get_audio_quality() == "128")
config.set_audio_quality("320")
print("FIN")
