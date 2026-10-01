"""Descargas: listas y álbumes en paralelo, descargas sueltas, información de la barra superior y 'álbum como lista'."""
from config import get_download_dir, get_audio_quality, get_parallel_downloads
from services.playlist_service import PlaylistService
from services.youtube_service import DownloadWorker
from ui.common import _ACTIVE_THREADS
from ui.covers import PlaylistCoverFromUrl
from ui.friendly import friendly_error


class DownloadsMixin:
    """Mezcla para MainWindow. Requiere: downloads (DownloadsTracker), downloads_panel, topbar, notify()."""

    def init_downloads_state(self):
        self.batch_queue = []
        self.batch_total = 0
        self.batch_completed_count = 0
        self.batch_active_workers = 0
        self.max_parallel_workers = get_parallel_downloads()
        self._cover_jobs = []

    # ----------------------------------------------------- barra superior
    def show_downloads_panel(self):
        self.downloads_panel.toggle()

    def on_downloads_changed(self):
        """Actualiza el botón y el texto informativo de la barra superior."""
        active = self.downloads.active()
        self.topbar.set_download_count(len(active))
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

    def update_header_info(self):
        """Texto general de la barra superior cuando no se está descargando nada."""
        if self.downloads.active():
            return
        n = len(self._lib_items) if self._lib_items is not None else 0
        self.topbar.set_info(f"{n} canciones en tu música" if n != 1 else "1 canción en tu música")

    # ------------------------------------------------------------- lotes
    def start_batch_download(self, items: list):
        """Descarga varias canciones a la vez (hasta 3 en paralelo)."""
        self.batch_queue = [item for item in items if not item.get('already_downloaded')
                            and not self.resolve_local(item)]
        if not self.batch_queue:
            self.notify("Ya tienes todas estas canciones descargadas.")
            return

        self.batch_total = len(self.batch_queue)
        self.batch_completed_count = 0
        self.batch_active_workers = 0
        self.max_parallel_workers = get_parallel_downloads()

        self.batch_banner.setVisible(True)
        self.batch_banner_label.setText(f"Descargando {self.batch_total} canciones...")
        self.notify(f"Descargando {self.batch_total} canciones. Puedes verlas en «Descargas».")

        for _ in range(min(self.max_parallel_workers, len(self.batch_queue))):
            self.download_next_parallel_worker()

    def download_next_parallel_worker(self):
        if not self.batch_queue:
            if self.batch_active_workers == 0:
                self.batch_banner_label.setText(f"¡Listo! {self.batch_total} canciones descargadas")
                self.notify("Descarga completada")
                self.refresh_sidebar_library()
            return

        item = self.batch_queue.pop(0)
        self.batch_active_workers += 1
        worker = DownloadWorker(item, str(get_download_dir()), get_audio_quality())
        self.downloads.track(worker, item)
        _ACTIVE_THREADS.add(worker)
        worker.finished_signal.connect(lambda res, w=worker: self.on_parallel_worker_finished(res, w))
        worker.start()

    def on_parallel_worker_finished(self, result: dict, worker):
        _ACTIVE_THREADS.discard(worker)
        self.batch_active_workers -= 1
        self.batch_completed_count += 1
        self.batch_banner_label.setText(f"Descargando… {self.batch_completed_count} de {self.batch_total}")
        self.download_next_parallel_worker()   # la biblioteca se actualiza una sola vez, al terminar el lote

    # ------------------------------------------------ canciones sueltas
    def quick_download(self, info: dict, on_done=None):
        """Descarga una canción directamente (sin pasar por la lista de resultados)."""
        worker = DownloadWorker(info, str(get_download_dir()), get_audio_quality())
        self.downloads.track(worker, info)
        _ACTIVE_THREADS.add(worker)
        worker.finished_signal.connect(lambda res, w=worker, it=info, cb=on_done: self._quick_download_done(res, w, it, cb))
        worker.start()
        self.notify(f"Descargando «{info.get('title', 'canción')}»…")

    def _quick_download_done(self, result: dict, worker, info: dict, callback=None):
        _ACTIVE_THREADS.discard(worker)
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
