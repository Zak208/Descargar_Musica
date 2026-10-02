"""Descargas: listas y álbumes en paralelo, descargas sueltas, información de la barra superior y 'álbum como lista'."""
import logging

from config import get_download_dir, get_audio_quality, get_parallel_downloads
from services import pending_downloads, quality as quality_service, storage_service
from services.network_service import is_network_error
from services.playlist_service import PlaylistService
from services.youtube_service import DownloadWorker
from ui.common import _ACTIVE_THREADS
from ui.covers import PlaylistCoverFromUrl
from ui.dialogs import ask_confirm
from ui import winext
from ui.friendly import friendly_error


class DownloadsMixin:
    """Mezcla para MainWindow. Requiere: downloads (DownloadsTracker), downloads_panel, topbar, notify()."""

    def init_downloads_state(self):
        self.batch_queue = []
        self.batch_total = 0
        self.batch_completed_count = 0
        self.batch_paused = False
        self._batch_workers = []
        self.max_parallel_workers = get_parallel_downloads()
        self._cover_jobs = []

    # ----------------------------------------------------- barra superior
    def show_downloads_panel(self):
        self.downloads_panel.toggle()

    def on_downloads_changed(self):
        """Actualiza el botón y el texto informativo de la barra superior."""
        active = self.downloads.active()
        self.topbar.set_download_count(len(active))
        was_busy = getattr(self, "_dl_was_busy", False)
        self._dl_was_busy = bool(active)
        self.topbar.set_download_progress(self.downloads.overall_percent() if active else None)
        taskbar = getattr(self, "taskbar", None)
        if taskbar is not None and taskbar.ok:
            if active:
                taskbar.set_progress(self.downloads.overall_percent())
                if self.batch_paused:
                    taskbar.set_state(winext.TBPF_PAUSED)
            else:
                taskbar.set_progress(None)
        if was_busy and not active:
            self.topbar.download_finished_flash()           # el anillo se completa y parpadea una vez
            if taskbar is not None and taskbar.ok and not self.isActiveWindow():
                from ui.icons import icon
                from ui.styles import accent
                taskbar.set_overlay(icon("check_circle.svg", accent()).pixmap(16, 16), "Descargas terminadas")
        if active:
            self._download_info_reset.stop()
            n = len(active)
            self.topbar.set_info(f"Descargando {n} {'canción' if n == 1 else 'canciones'} · {self.downloads.overall_percent()}%")
        else:
            finished = [e for e in self.downloads.entries.values() if e["state"] == "done"]
            if finished and not self._download_info_reset.isActive():
                self.topbar.set_info("Descarga completada")
                self._download_info_reset.start(5000)
            elif not finished:
                self.update_header_info()

    def download_fraction(self, info: dict):
        """Avance (0 a 1) de la descarga en marcha de esa canción, o None si todavía no se sabe."""
        title, artist = info.get("title", ""), info.get("uploader", "")
        for entry in self.downloads.entries.values():
            if entry["state"] in ("active", "converting") and entry["title"] == title and entry["artist"] == artist:
                return entry["percent"] / 100.0 if entry["percent"] > 0 else None
        return None

    def update_header_info(self):
        """Texto general de la barra superior cuando no se está descargando nada."""
        if self.downloads.active():
            return
        n = len(self._lib_items) if self._lib_items is not None else 0
        self.topbar.set_info(f"{n} canciones en tu música" if n != 1 else "1 canción en tu música")

    # ------------------------------------------------------------- lotes
    def _batch_keys(self) -> set:
        keys = {str(i.get("id") or i.get("url") or i.get("title")) for i in self.batch_queue}
        keys |= {str(w.item_info.get("id") or w.item_info.get("url") or w.item_info.get("title"))
                 for w in self._batch_workers}
        keys |= {str((e.get("info") or {}).get("id") or (e.get("info") or {}).get("url") or (e.get("info") or {}).get("title"))
                 for e in self.downloads.active()}        # también las sueltas que están bajando ahora mismo
        return keys

    def estimate_download(self, items: list) -> tuple:
        """(megabytes que ocuparán, bytes libres en el disco)"""
        quality = get_audio_quality()
        need = sum(quality_service.estimate_mb(quality, float(i.get("duration_secs") or 210)) for i in items)
        return need, storage_service.free_disk_bytes(get_download_dir())

    def confirm_download_size(self, items: list) -> bool:
        """Avisa antes de descargar mucho o con poco espacio libre (en el resto de casos no pregunta nada)."""
        need_mb, free = self.estimate_download(items)
        free_mb = free / (1024 * 1024)
        low = free_mb < need_mb * 2 + 300
        if need_mb < 150 and not low:
            return True
        n = len(items)
        msg = (f"Vas a descargar {n} canción{'es' if n != 1 else ''}: ocuparán unos {need_mb:.0f} MB "
               f"y en tu disco quedan {storage_service.format_bytes(free)} libres.")
        if low:
            msg += "\n\nVa justo de espacio. Con «Ahorrar espacio» (en Ajustes) las canciones ocupan menos de la mitad."
        return ask_confirm(self, "Descargar canciones", msg + "\n\n¿Quieres continuar?", ok="Descargar")

    def start_batch_download(self, items: list, from_pending: bool = False):
        """Descarga varias canciones (por defecto 3 a la vez; 1 en equipos modestos). Si ya hay descargas en marcha,
        las nuevas se suman a la cola. Sin conexión quedan pendientes."""
        new = [item for item in items if not item.get('already_downloaded') and not self.resolve_local(item)]
        if not new:
            if not from_pending:
                self.notify("Ya tienes todas estas canciones descargadas.")
            return
        if self.is_offline():
            self.queue_download(new)
            self.notify(f"Sin conexión: {len(new)} canciones quedan pendientes y se descargarán cuando vuelva internet.")
            return
        known = self._batch_keys()
        new = [i for i in new if str(i.get("id") or i.get("url") or i.get("title")) not in known]
        if not new:
            self.notify("Esas canciones ya están en la cola de descargas.")
            return
        if not from_pending and not self.confirm_download_size(new):
            return

        if self.batch_queue or self._batch_workers:       # ya hay un lote en marcha: se suman a la cola
            self.batch_queue.extend(new)
            self.batch_total += len(new)
        else:
            self.batch_queue = list(new)
            self.batch_total = len(new)
            self.batch_completed_count = 0
        self.batch_paused = False
        self.batch_banner.setVisible(True)
        self.batch_banner_label.setText(f"Descargando {self.batch_total} canciones...")
        self.notify(f"Descargando {len(new)} canciones. Puedes verlas en «Descargas».")
        self._fill_batch_workers()

    def _fill_batch_workers(self):
        """Pone en marcha tantas descargas como permita el límite del equipo (y la pausa)."""
        self.max_parallel_workers = get_parallel_downloads()
        while self.batch_queue and not self.batch_paused and len(self._batch_workers) < self.max_parallel_workers:
            item = self.batch_queue.pop(0)
            worker = DownloadWorker(item, str(get_download_dir()), get_audio_quality())
            self._batch_workers.append(worker)
            self.downloads.track(worker, item)
            _ACTIVE_THREADS.add(worker)
            worker.finished_signal.connect(lambda res, w=worker: self.on_parallel_worker_finished(res, w))
            worker.start()
        if not self.batch_queue and not self._batch_workers:
            self.batch_banner_label.setText(f"¡Listo! {self.batch_total} canciones descargadas")
            self.notify("Descarga completada")
            if self.batch_total >= 5:
                self.celebrate("lote")
            self.refresh_sidebar_library()
        self._refresh_queue_controls()


    def on_parallel_worker_finished(self, result: dict, worker):
        _ACTIVE_THREADS.discard(worker)
        if worker in self._batch_workers:
            self._batch_workers.remove(worker)
        self._settle_pending(result, worker.item_info)
        self.batch_completed_count += 1
        if result.get("success") and result.get("warning"):
            logging.info(f"Descargada con aviso: {result['warning']}")
        paused = " (en pausa)" if self.batch_paused and self.batch_queue else ""
        self.batch_banner_label.setText(f"Descargando… {self.batch_completed_count} de {self.batch_total}{paused}")
        self._fill_batch_workers()   # la biblioteca se actualiza una sola vez, al terminar el lote

    # ---- pausar, reanudar y cancelar la cola
    def pause_batch(self):
        self.batch_paused = True
        self.notify("Descargas en pausa: terminan las que ya empezaron.")
        self._refresh_queue_controls()

    def resume_batch(self):
        self.batch_paused = False
        self.notify("Descargas reanudadas")
        self._fill_batch_workers()

    def cancel_batch_queue(self):
        n = len(self.batch_queue)
        self.batch_queue = []
        self.batch_paused = False
        self.notify(f"Se quitaron {n} canciones de la cola" if n else "No había nada en la cola")
        self._fill_batch_workers()

    def _refresh_queue_controls(self):
        if hasattr(self, "downloads_panel"):
            self.downloads_panel.refresh_queue()
        self.on_downloads_changed()

    # ------------------------------------------------ canciones sueltas
    def _settle_pending(self, result: dict, info: dict):
        """Si se descargó, deja de estar pendiente; si falló por falta de internet, queda pendiente."""
        if result.get("success"):
            pending_downloads.remove(info)
            self._reload_pending_keys()
        elif is_network_error(result.get("error")):
            self.queue_download(info)

    def quick_download(self, info: dict, on_done=None):
        """Descarga una canción directamente (sin pasar por la lista de resultados). Sin conexión queda pendiente."""
        if str(info.get("id") or info.get("url") or info.get("title")) in self._batch_keys():
            self.notify(f"«{info.get('title', 'canción')}» ya se está descargando.")
            if on_done is not None:
                on_done({"success": False, "cancelled": True})
            return
        if self.is_offline():
            self.queue_download(info)
            self.notify(f"Sin conexión: «{info.get('title', 'canción')}» se descargará cuando vuelva internet.")
            if on_done is not None:
                on_done({"success": False, "queued": True})
            return
        need_mb, free = self.estimate_download([info])
        if free < (need_mb + 250) * 1024 * 1024:           # casi sin espacio: se avisa antes de empezar
            if not ask_confirm(self, "Poco espacio en el disco",
                               f"Solo quedan {storage_service.format_bytes(free)} libres. ¿Quieres descargar de todas formas?\n\n"
                               "Con «Ahorrar espacio» (en Ajustes) las canciones ocupan menos de la mitad.", ok="Descargar"):
                if on_done is not None:
                    on_done({"success": False, "cancelled": True})
                return
        self.fly_to(info, self.topbar.btn_downloads)
        worker = DownloadWorker(info, str(get_download_dir()), get_audio_quality())
        self.downloads.track(worker, info)
        _ACTIVE_THREADS.add(worker)
        worker.finished_signal.connect(lambda res, w=worker, it=info, cb=on_done: self._quick_download_done(res, w, it, cb))
        worker.start()
        self.notify(f"Descargando «{info.get('title', 'canción')}»…")

    def _quick_download_done(self, result: dict, worker, info: dict, callback=None):
        _ACTIVE_THREADS.discard(worker)
        self._settle_pending(result, info)
        if result.get("success"):
            self.notify(f"«{info.get('title', 'Canción')}» descargada")
            self.refresh_sidebar_library()
        else:
            self.notify(friendly_error(result.get("error")))
        if callback is not None:
            callback(result)

    # ------------------------------------------------- álbum como lista
    def download_album_as_list(self, album: dict):
        """Descarga el álbum entero y crea una lista nueva con sus canciones (y su portada)."""
        tracks = album.get("tracks", [])
        if not tracks:
            return
        name = album.get("name", "Álbum")
        playlist_id = PlaylistService.create_playlist(name)
        for track in tracks:
            PlaylistService.add_track_to_playlist(playlist_id, track)
        if album.get("cover"):
            job = PlaylistCoverFromUrl(playlist_id, album["cover"])
            job.done.connect(lambda _pid: self.refresh_playlists_sidebar())
            self._cover_jobs.append(job)
            job.start()
        self.refresh_playlists_sidebar()
        self.start_batch_download(tracks)
        self.notify(f"Lista «{name}» creada. Se están descargando sus canciones.")
