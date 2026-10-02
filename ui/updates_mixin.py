"""Actualizaciones de la aplicación y del motor de descargas (botón azul de la barra superior)."""
from PySide6.QtCore import (
    QUrl
)
from PySide6.QtGui import QDesktopServices
from config import (
    load_settings, save_settings
)
from version import __version__
from ui import perf
from ui.friendly import friendly_error
from services import app_updater, update_service, ytdlp_loader


UPDATE_POLL_MS = 10 * 60 * 1000       # cada cuánto mira si hay versión nueva mientras la aplicación está abierta
UPDATE_MIN_GAP_S = 5 * 60             # y nunca más a menudo que esto (también al abrirla)


class UpdatesMixin:
    """Mezcla para MainWindow."""

    # ---------- actualizaciones (motor de descargas y aplicación) ----------
    def check_updates(self, manual: bool = False):
        """Mira en GitHub si hay versión nueva. Solo con conexión; sola, una vez cada 24 horas."""
        if self.is_offline():
            if manual:
                self.notify("Sin conexión: no se puede buscar actualizaciones.")
            return
        if not manual and not update_service.due("last_update_check", UPDATE_MIN_GAP_S):
            return
        worker = getattr(self, "_update_check", None)
        if worker is not None and worker.isRunning():
            return
        if manual:
            self.notify("Buscando actualizaciones...")
        self._update_check = update_service.UpdateCheckWorker(self)
        worker = self._update_check
        self._update_check.result.connect(lambda app_new, engine_new: self._on_update_result(app_new, engine_new, manual, worker.ok))
        self._update_check.start()

    def _on_update_result(self, app_new: str, engine_new: str, manual: bool, ok: bool = True):
        update_service.mark_checked("last_update_check")
        if not ok and not app_new and not engine_new:
            try:
                self.settings_dialog.set_update_status("No se pudo consultar GitHub. Inténtalo de nuevo en un rato.")
            except (AttributeError, RuntimeError):
                pass
            if manual:
                self.notify("No se pudo buscar actualizaciones ahora mismo.")
            return
        status = (f"Hay una versión nueva de la aplicación: {app_new}" if app_new else
                  f"Hay una versión nueva del motor de descargas: {engine_new}" if engine_new else
                  f"Todo al día · versión {__version__}")
        try:
            self.settings_dialog.set_update_status(status)
        except (AttributeError, RuntimeError):
            pass
        self._pending_engine = engine_new
        dlg = getattr(self, "help_dialog", None)
        if dlg is not None:
            dlg.btn_engine.setVisible(bool(engine_new))
            dlg.btn_app.setVisible(bool(app_new))
            dlg.refresh_updates()
            if app_new:
                dlg.lbl_app.setText(f"Aplicación: versión {__version__} · hay una versión nueva ({app_new})")
            if engine_new:
                dlg.lbl_engine.setText(f"Motor de descargas (yt-dlp): versión {ytdlp_loader.active_version()} · "
                                       f"hay una nueva ({engine_new})")
        if engine_new:
            self._offer_engine_update(engine_new, manual)
        elif self._engine_state == "available":
            self._set_engine_state(None)
        if app_new and app_updater.can_self_update():
            self._offer_app_update(app_new, manual)
        elif app_new:
            margin = self.toast_margin()
            self.toast.show_message(f"Hay una versión nueva de Descargador de Música ({app_new})", bottom_margin=margin,
                                    action=("Ver novedades", self.open_app_releases))
        elif manual and not engine_new:
            self.notify("Todo está al día.")

    # ---------- actualizar la propia aplicación (botón azul arriba a la izquierda) ----------
    def _restore_pending_update(self):
        """Si quedó una versión ya descargada de otra vez, el botón «Reiniciar y actualizar» aparece enseguida."""
        if not app_updater.can_self_update():
            return
        version = app_updater.staged_version()
        if version:
            self._update_version = version
            self._set_update_state("ready")

    def _offer_app_update(self, version: str, manual: bool = False):
        self._update_version = version
        if self._update_state in ("downloading", "ready") and getattr(self, "_update_version_ready", None) == version:
            return
        if app_updater.staged_version() == version:
            self._set_update_state("ready")
        elif perf.saving_reason(self.network):                 # batería baja o datos medidos: se descarga cuando tú quieras
            self._set_update_state("available")
        else:
            self._start_app_download()
        if manual:
            self.notify(f"Hay una versión nueva ({version}): mira el botón azul de arriba a la izquierda.")

    def _set_update_state(self, state):
        self._update_state = state
        if state == "ready":
            self._update_version_ready = getattr(self, "_update_version", "")
        self._refresh_update_button()

    def _set_engine_state(self, state, pct: int = 0):
        self._engine_state = state
        self._engine_pct = pct
        self._refresh_update_button()

    def _refresh_update_button(self):
        """Un solo botón azul para las dos clases de novedad: primero la aplicación y, si no hay, el motor de descargas."""
        state, v = self._update_state, getattr(self, "_update_version", "")
        if state == "available":
            self.topbar.set_update_button(f"Actualizar a la {v}", True, "Descarga la versión nueva (se instala al reiniciar)")
        elif state == "downloading":
            self.topbar.set_update_button(f"Descargando la {v}…", False, "Se está descargando la versión nueva")
        elif state == "ready":
            self.topbar.set_update_button(f"Reiniciar y actualizar a la {v}", True,
                                          "Se cierra la aplicación, se instala la versión nueva y se vuelve a abrir")
        elif self._engine_state == "available":
            self.topbar.set_update_button("Actualizar el descargador de canciones", True,
                                          f"Hay una versión nueva ({self._engine_version}) del motor que descarga las canciones")
        elif self._engine_state == "downloading":
            self.topbar.set_update_button(f"Descargando el descargador de canciones… {self._engine_pct}%", False,
                                          "Se está descargando la versión nueva del motor de descargas")
        elif self._engine_state == "ready":
            self.topbar.set_update_button("Reiniciar para usar el descargador nuevo", True,
                                          "El motor de descargas ya está actualizado: se usará al volver a abrir la aplicación")
        else:
            self.topbar.set_update_button("")

    def _offer_engine_update(self, version: str, manual: bool = False):
        """Hay un yt-dlp más nuevo: se avisa con el botón azul (y se descarga solo si así lo tienes en Ajustes)."""
        if self._engine_state in ("downloading", "ready"):
            return
        self._engine_version = version
        if load_settings().get("ytdlp_auto_update", True) and not perf.saving_reason(self.network):
            self.update_engine(quiet=True)
        else:
            self._set_engine_state("available")
            if manual:
                self.notify(f"Hay una versión nueva del motor de descargas ({version}): mira el botón azul de arriba a la izquierda.")

    def _announce_finished_update(self):
        """Tras actualizar y reabrir, confirma a qué versión se ha pasado."""
        settings = load_settings()
        previous = settings.get("last_run_version", "")
        if previous != __version__:
            settings["last_run_version"] = __version__
            save_settings(settings)
            if previous and ytdlp_loader.parse_version(__version__) > ytdlp_loader.parse_version(previous):
                margin = self.toast_margin()
                self.toast.show_message(f"Descargador de Música se ha actualizado a la versión {__version__}", bottom_margin=margin,
                                        action=("Ver novedades", self.open_app_releases))

    def _start_app_download(self):
        worker = self._app_update_worker
        if worker is not None and worker.isRunning():
            return
        self._set_update_state("downloading")
        worker = app_updater.AppUpdateWorker(self)
        worker.progress.connect(lambda pct: self.topbar.set_update_button(
            f"Descargando la {self._update_version}… {pct}%", False, "Se está descargando la versión nueva"))
        worker.done.connect(self._on_app_download_done)
        worker.failed.connect(self._on_app_download_failed)
        self._app_update_worker = worker
        worker.start()

    def _on_app_download_done(self, version: str):
        self._update_version = version
        self._set_update_state("ready")
        self.notify(f"La versión {version} está lista: pulsa el botón azul para reiniciar y actualizar.")

    def _on_app_download_failed(self, message: str):
        self._set_update_state("available")
        self.notify(f"No se pudo descargar la actualización: {friendly_error(message)}")

    def _on_update_clicked(self):
        if self._update_state == "available":
            self._start_app_download()
        elif self._update_state == "ready":
            self.restart_and_update()
        elif self._update_state is None or self._update_state == "":
            if self._engine_state == "available":
                self.update_engine()
            elif self._engine_state == "ready":
                self.restart_app()

    def restart_and_update(self):
        """Cierra la aplicación, instala la versión descargada y la vuelve a abrir."""
        if not app_updater.install_and_restart():
            self.notify("No se pudo preparar la actualización. Inténtalo de nuevo más tarde.")
            self._set_update_state("available")
            return
        self.quit_app()

    def update_engine(self, quiet: bool = False):
        tag = getattr(self, "_pending_engine", "")
        if not tag:
            self.check_updates(manual=True)
            return
        worker = getattr(self, "_engine_worker", None)
        if worker is not None and worker.isRunning():
            return
        dlg = getattr(self, "help_dialog", None)
        self._engine_version = tag
        self._set_engine_state("downloading", 0)
        self._engine_worker = update_service.YtdlpUpdateWorker(tag, self)
        if dlg is not None:
            dlg.update_progress.setVisible(True)
            dlg.update_progress.setValue(0)
            self._engine_worker.progress.connect(dlg.update_progress.setValue)
        self._engine_worker.progress.connect(lambda pct: self._set_engine_state("downloading", pct))
        self._engine_worker.done.connect(lambda v: self._on_engine_updated(v, quiet))
        self._engine_worker.failed.connect(lambda msg: self._on_engine_failed(msg, quiet))
        self._engine_worker.start()

    def _on_engine_updated(self, version: str, quiet: bool):
        self._pending_engine = ""
        dlg = getattr(self, "help_dialog", None)
        if dlg is not None:
            dlg.update_progress.setVisible(False)
            dlg.btn_engine.setVisible(False)
            dlg.refresh_updates()
        if ytdlp_loader.is_loaded():
            self._set_engine_state("ready")             # el motor viejo sigue en uso: hasta reiniciar no cambia
            self.notify(f"El descargador de canciones se ha actualizado a {version}: pulsa el botón azul para reiniciar y usarlo.")
        else:
            self._set_engine_state(None)
            self.notify(f"Motor de descargas actualizado a {version}")

    def _on_engine_failed(self, message: str, quiet: bool):
        dlg = getattr(self, "help_dialog", None)
        if dlg is not None:
            dlg.update_progress.setVisible(False)
        self._set_engine_state("available" if self._pending_engine else None)
        if not quiet:
            self.notify(f"No se pudo actualizar: {friendly_error(message)}")

    def open_app_releases(self):
        QDesktopServices.openUrl(QUrl(update_service.APP_PAGE))
