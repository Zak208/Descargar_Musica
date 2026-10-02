"""Tema visual y alto contraste."""
from PySide6.QtWidgets import (
    QWidget, QApplication
)
from config import (
    set_theme, load_settings
)
from ui.styles import (get_theme_stylesheet, THEME_CONFIGS, set_active_theme, retheme_stylesheet,
                       contrast_stylesheet, high_contrast_enabled)
from ui import motion, snapshot, frames
from ui.now_playing import cover_color


class ThemeMixin:
    """Mezcla para MainWindow."""

    def _update_live_accent(self):
        """«Colores que cambian con la canción» (apagado por defecto): lo pintado a mano en la barra de reproducción toma un
        tono de la portada. La hoja de estilos global no se toca (reaplicarla cada canción costaría decenas de ms)."""
        from PySide6.QtGui import QColor
        from ui import styles
        color = None
        if load_settings().get("dynamic_accent", False) and self.current_item_info:
            c = self._cover_color()
            if c is not None:
                tone = QColor(c)
                tone.setHslF(max(tone.hslHueF(), 0.0), max(0.55, min(0.85, tone.hslSaturationF() + 0.2)), 0.60)
                color = tone.name()
        styles.set_live_accent(color)
        live = styles.live_accent()
        if hasattr(self, "visualizer"):
            self.visualizer.set_accent_color(live)
        for w in (self.seek_slider, self.volume_slider, self.btn_play_pause):
            w.update()

    def set_high_contrast(self, enabled: bool):
        """Alto contraste: textos y bordes más claros. Se aplica al instante."""
        from config import load_settings, save_settings
        settings = load_settings()
        settings["high_contrast"] = bool(enabled)
        save_settings(settings)
        self._set_theme_filter(self.current_theme != "spotify" or enabled)
        self.setStyleSheet(get_theme_stylesheet(self.current_theme))
        for w in self.findChildren(QWidget):
            qss = w.styleSheet()
            if qss and len(qss) < 20000 and not w.property("noRetheme"):
                new_qss = retheme_stylesheet(qss, self.current_theme)
                if enabled:
                    new_qss = contrast_stylesheet(new_qss)
                if new_qss != qss:
                    w.setStyleSheet(new_qss)

    def _set_theme_filter(self, active: bool):
        app = QApplication.instance()
        if active:
            app.installEventFilter(self._theme_filter)
        else:
            app.removeEventFilter(self._theme_filter)

    def on_theme_changed(self):
        theme_key = self.theme_combo.currentData()
        if theme_key:
            central = self.centralWidget()
            before = snapshot.grab(central) if (motion.enabled() and central is not None and central.isVisible()) else None
            set_theme(theme_key)
            set_active_theme(theme_key)
            self._set_theme_filter(theme_key != "spotify" or high_contrast_enabled())
            self.current_theme = theme_key
            self.setStyleSheet(get_theme_stylesheet(theme_key))
            accent_hex = THEME_CONFIGS.get(theme_key, {}).get("accent", "#1ED760")
            if hasattr(self, 'visualizer'):
                self.visualizer.set_accent_color(accent_hex)
            frames.clear()
            self._apply_title_bar()
            self.update_player_heart_icon()
            self.topbar.refresh_accent()
            for w in self.findChildren(QWidget):
                qss = w.styleSheet()
                if qss and len(qss) < 20000 and not w.property("noRetheme"):
                    new_qss = retheme_stylesheet(qss, theme_key)
                    if new_qss != qss:
                        w.setStyleSheet(new_qss)
            if before is not None:
                snapshot.crossfade(central, before, 260)           # los colores se mezclan en vez de saltar

    def _cover_color(self):
        pix = self.player_thumb.pixmap()
        return cover_color(pix) if pix is not None and not pix.isNull() else None
