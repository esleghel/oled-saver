"""Main application controller for OLED Saver."""

import logging
import os
import sys
import traceback
from pathlib import Path

# Setup logging BEFORE any other imports so we catch import errors
def _setup_logging():
    """Setup file logging (especially useful on Windows where there's no console)."""
    if sys.platform == "win32":
        log_dir = Path(os.environ.get("APPDATA", Path.home())) / "OLED Saver"
    else:
        log_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "oled-saver"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "oled-saver.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    logging.info(f"OLED Saver starting — log: {log_file}")
    return log_file

_log_file = _setup_logging()

try:
    from datetime import datetime

    from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QObject
    from PyQt6.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap
    from PyQt6.QtWidgets import (
        QApplication,
        QInputDialog,
        QMenu,
        QSystemTrayIcon,
        QWidget,
    )

    from oled_saver.config import Config
    from oled_saver.dialogs import MonitorSelectDialog, NightSettingsDialog
    from oled_saver.platform import detect_platform
except Exception:
    logging.critical(f"Import error:\n{traceback.format_exc()}")
    sys.exit(1)


class BlackScreen(QWidget):
    """Fullscreen black window for OLED burn-in protection."""

    dismissed = None  # Set by OledBlanker to a callback

    def __init__(self, target_screen):
        super().__init__()
        self._target_screen = target_screen
        self.setWindowTitle("OLED Saver")
        self.setStyleSheet("background-color: black;")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # Don't show in taskbar
        )
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setMouseTracking(True)
        self._ignore_first_move = True

    def show_on_monitor(self):
        """Show fullscreen on the target monitor."""
        self._ignore_first_move = True
        geo = self._target_screen.geometry()
        self.setGeometry(geo)
        self.windowHandle()  # Ensure window handle is created
        if self.windowHandle():
            self.windowHandle().setScreen(self._target_screen)
        self.showFullScreen()

    def _dismiss(self):
        if self.dismissed:
            self.dismissed()
        else:
            self.hide()

    def mousePressEvent(self, event):
        self._dismiss()

    def mouseMoveEvent(self, event):
        if self._ignore_first_move:
            self._ignore_first_move = False
            return
        self._dismiss()

    def keyPressEvent(self, event):
        self._dismiss()


class DimOverlay(QWidget):
    """Semi-transparent fullscreen overlay for dimming. Input passes through."""

    def __init__(self, target_screen):
        super().__init__()
        self._target_screen = target_screen
        self.setWindowTitle("OLED Saver Dim")
        self.setStyleSheet("background-color: black;")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )

    def show_on_monitor(self, brightness_pct):
        """Show dimming overlay. brightness_pct=10 means 90% opacity."""
        opacity = (100 - max(1, min(100, brightness_pct))) / 100.0
        self.setWindowOpacity(opacity)
        geo = self._target_screen.geometry()
        self.setGeometry(geo)
        self.windowHandle()
        if self.windowHandle():
            self.windowHandle().setScreen(self._target_screen)
        self.showFullScreen()


class SignalBridge(QObject):
    """Bridge Unix signals to Qt signals."""
    toggle_pause = pyqtSignal()


class OledBlanker:
    """Main application controller."""

    def __init__(self, app, platform):
        self.app = app
        self.platform = platform
        self.config = Config()
        self.paused = False
        self.blanked = False
        self.dimmed = False
        self.black_screens = []
        self.dim_overlays = []
        self.target_screens = []
        self.pause_timer = None
        self.night_active = False
        self._manual_override = False

        # Signal bridge for external toggle
        self.signal_bridge = SignalBridge()
        self.signal_bridge.toggle_pause.connect(self._toggle_pause)

        # Detect target monitors
        self.target_screens = self._find_target_screens()
        if not self.target_screens:
            print("ERROR: No target monitor found. Exiting.", file=sys.stderr)
            sys.exit(1)

        # Create black screen widgets (one per target)
        self.black_screens = []
        for screen in self.target_screens:
            bs = BlackScreen(screen)
            bs.dismissed = self._dismiss_action
            self.black_screens.append(bs)

        # Create dim overlay widgets (one per target)
        self.dim_overlays = [DimOverlay(s) for s in self.target_screens]

        # Setup system tray
        self._setup_tray()

        # Setup idle detection via platform
        self.platform.setup_idle(
            self.config.timeout_seconds,
            self._try_idle_action,
            self._on_idle_resume,
        )

        # Setup night mode
        self._setup_night_mode()

        # Instance management via platform
        self.platform.write_instance_info()
        self.platform.setup_toggle_handler(self.signal_bridge.toggle_pause.emit)

    def _find_target_screens(self):
        """Find QScreens for the configured monitor(s)."""
        screens = self.app.screens()
        screen_map = {s.name(): s for s in screens}
        oled_monitors, all_monitors = self.platform.detect_monitors()
        target_connectors = []

        if self.config.monitor == "all":
            target_connectors = [name for name, _ in all_monitors]
        elif self.config.monitor == "auto":
            if oled_monitors:
                target_connectors = [name for name, _ in oled_monitors]
                print(f"Auto-detected OLED(s): {oled_monitors}")
            elif all_monitors:
                dialog = MonitorSelectDialog(all_monitors)
                if dialog.exec() and dialog.selected_connectors:
                    target_connectors = dialog.selected_connectors
                    self.config.monitor = ",".join(target_connectors)
                    self.config.save()
                else:
                    return []
            else:
                print("No monitors found.", file=sys.stderr)
                return []
        else:
            target_connectors = self.config.monitor_list

        # Resolve connector names to QScreens
        result = []
        for conn in target_connectors:
            if conn in screen_map:
                result.append(screen_map[conn])
            else:
                for sname, sobj in screen_map.items():
                    if conn in sname or sname in conn:
                        result.append(sobj)
                        break
                else:
                    print(f"WARNING: Screen '{conn}' not found. Available: {list(screen_map)}", file=sys.stderr)

        if not result and screens:
            print("WARNING: No configured screens found, using primary.", file=sys.stderr)
            result = [screens[0]]

        print(f"Target monitors: {[s.name() for s in result]}")
        return result

    def _setup_tray(self):
        """Setup system tray icon and menu."""
        self.tray = QSystemTrayIcon(self.app)
        self._update_tray_icon()

        menu = QMenu()
        self.pause_action = menu.addAction("⏸ Pause (30 min)")
        self.pause_action.triggered.connect(self._toggle_pause)
        menu.addSeparator()

        menu.addAction("🔲 Blank Now").triggered.connect(self._manual_blank)
        menu.addAction("🔅 Dim Now").triggered.connect(self._manual_dim)
        menu.addSeparator()

        timeout_action = menu.addAction(
            f"⏱ Set Timeout ({self.config.timeout_seconds}s)..."
        )
        timeout_action.triggered.connect(self._show_timeout_dialog)
        self.timeout_action = timeout_action

        idle_menu = menu.addMenu("⚙ Idle Action")
        self.idle_blank_action = idle_menu.addAction("Blank screen")
        self.idle_blank_action.setCheckable(True)
        self.idle_blank_action.triggered.connect(lambda: self._set_idle_action("blank"))
        self.idle_dim_action = idle_menu.addAction("Dim screen")
        self.idle_dim_action.setCheckable(True)
        self.idle_dim_action.triggered.connect(lambda: self._set_idle_action("dim"))
        idle_menu.addSeparator()
        idle_menu.addAction("Set dim brightness...").triggered.connect(
            self._show_dim_brightness_dialog
        )
        self._update_idle_action_checks()

        menu.addSeparator()

        self.night_toggle_action = menu.addAction("")
        self._update_night_toggle_label()
        self.night_toggle_action.triggered.connect(self._toggle_night_mode)

        night_settings_action = menu.addAction("🌙 Night Settings...")
        night_settings_action.triggered.connect(self._show_night_settings)

        menu.addSeparator()

        self.monitor_action = menu.addAction("")
        self._update_monitor_label()
        self.monitor_action.triggered.connect(self._show_monitor_dialog)

        menu.addSeparator()
        menu.addAction("❌ Quit").triggered.connect(self._quit)

        self.tray.setContextMenu(menu)
        self.tray.setToolTip("OLED Saver — Active")
        self.tray.show()

    def _get_icon_path(self):
        """Find the app icon file."""
        import os
        # Check relative to this file (source), then relative to exe (PyInstaller)
        candidates = [
            Path(__file__).parent.parent.parent / "assets" / "icon-64.png",
            Path(getattr(sys, '_MEIPASS', '')) / "assets" / "icon-64.png",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def _make_icon(self, color):
        """Load app icon with a colored status dot overlay."""
        size = 64
        dot_size = 20

        # Try loading the real icon
        icon_path = self._get_icon_path()
        if icon_path:
            pixmap = QPixmap(icon_path).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        else:
            # Fallback: plain colored circle
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(4, 4, size - 8, size - 8)
            painter.end()
            return QIcon(pixmap)

        # Draw status dot (bottom-right corner)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        # White border around dot
        painter.setBrush(QColor(255, 255, 255, 200))
        painter.drawEllipse(size - dot_size - 2, size - dot_size - 2, dot_size + 4, dot_size + 4)
        # Colored dot
        painter.setBrush(QColor(color))
        painter.drawEllipse(size - dot_size, size - dot_size, dot_size, dot_size)
        painter.end()
        return QIcon(pixmap)

    def _update_tray_icon(self):
        """Update tray icon based on current state."""
        if self.paused:
            self.tray.setIcon(self._make_icon("#FFA500"))  # Orange = paused
            self.tray.setToolTip("OLED Saver — Paused")
        else:
            self.tray.setIcon(self._make_icon("#00CC66"))  # Green = active
            self.tray.setToolTip("OLED Saver — Active")

    def _try_idle_action(self):
        """Perform configured idle action (blank or dim), checking exceptions."""
        if self.paused:
            return
        if self.blanked or self.dimmed:
            return
        if self.config.check_inhibitors and self.platform.is_media_playing():
            print("Idle action skipped: media is playing")
            return

        if self.config.idle_action == "dim":
            self._do_dim()
            self._start_dismiss_watcher()
        else:
            self._do_blank()

    def _on_idle_resume(self):
        """Called by idle system on resume — respects manual override."""
        if self._manual_override:
            return
        self._dismiss_action()

    def _dismiss_action(self):
        """Dismiss any active blank/dim from any source."""
        self._manual_override = False
        if self.blanked:
            self._undo_blank()
        if self.dimmed:
            self._undo_dim()

    def _do_blank(self):
        """Show fullscreen black window on target monitors."""
        if self.blanked:
            return
        self.blanked = True
        for bs in self.black_screens:
            bs.show_on_monitor()
        names = [s.name() for s in self.target_screens]
        print(f"Screen blanked on {names}")

    def _undo_blank(self):
        """Hide blank screens."""
        if not self.blanked:
            return
        self.blanked = False
        for bs in self.black_screens:
            bs.hide()
        print("Screen unblanked")

    def _do_dim(self):
        """Dim target monitors via semi-transparent overlay."""
        if self.dimmed:
            return
        self.dimmed = True
        self._dim_mouse_pos = None
        for overlay in self.dim_overlays:
            overlay.show_on_monitor(self.config.dim_brightness)
        names = [s.name() for s in self.target_screens]
        print(f"Screen dimmed to {self.config.dim_brightness}% on {names}")

    def _undo_dim(self):
        """Remove dim overlays."""
        if not self.dimmed:
            return
        self.dimmed = False
        self._stop_dismiss_watcher()
        for overlay in self.dim_overlays:
            overlay.hide()
        names = [s.name() for s in self.target_screens]
        print(f"Screen undimmed on {names}")

    def _start_dismiss_watcher(self):
        """Start watching for mouse movement to dismiss dim."""
        self._dim_mouse_pos = QCursor.pos()
        if not hasattr(self, '_dismiss_timer') or self._dismiss_timer is None:
            self._dismiss_timer = QTimer()
            self._dismiss_timer.setInterval(500)
            self._dismiss_timer.timeout.connect(self._check_dismiss)
        self._dismiss_timer.start()

    def _stop_dismiss_watcher(self):
        """Stop the dismiss watcher."""
        if hasattr(self, '_dismiss_timer') and self._dismiss_timer:
            self._dismiss_timer.stop()

    def _check_dismiss(self):
        """Check if mouse moved to dismiss dim."""
        if not self.dimmed:
            self._stop_dismiss_watcher()
            return
        pos = QCursor.pos()
        if self._dim_mouse_pos is not None and pos != self._dim_mouse_pos:
            self._dismiss_action()
        self._dim_mouse_pos = pos

    def _toggle_pause(self):
        """Toggle pause state."""
        self.paused = not self.paused
        if self.paused:
            self._dismiss_action()
            self.pause_action.setText("▶ Resume")
            if self.pause_timer:
                self.pause_timer.stop()
            self.pause_timer = QTimer()
            self.pause_timer.setSingleShot(True)
            self.pause_timer.timeout.connect(self._toggle_pause)
            self.pause_timer.start(self.config.pause_duration_minutes * 60 * 1000)
            self.tray.showMessage(
                "OLED Saver",
                f"Paused for {self.config.pause_duration_minutes} minutes",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        else:
            self.pause_action.setText("⏸ Pause (30 min)")
            if self.pause_timer:
                self.pause_timer.stop()
                self.pause_timer = None
            self.tray.showMessage(
                "OLED Saver",
                "Resumed — monitoring for idle",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        self._update_tray_icon()

    def _show_timeout_dialog(self):
        """Show dialog to set custom idle timeout."""
        seconds, ok = QInputDialog.getInt(
            None,
            "Set Idle Timeout",
            "Timeout (seconds):",
            self.config.timeout_seconds,
            30,   # min
            600,  # max
            10,   # step
        )
        if ok:
            self._set_timeout(seconds)

    def _set_timeout(self, seconds):
        """Change idle timeout."""
        self.config.timeout_seconds = seconds
        self.config.save()
        self.platform.restart_idle(seconds)

        self.tray.showMessage(
            "OLED Saver",
            f"Timeout set to {seconds}s",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )
        self.timeout_action.setText(f"⏱ Set Timeout ({seconds}s)...")

    def _manual_blank(self):
        """Manually trigger blank screen (deferred to let menu close)."""
        self._dismiss_action()
        self._manual_override = True
        QTimer.singleShot(150, self._do_blank)

    def _manual_dim(self):
        """Manually trigger dim (deferred to let menu close)."""
        self._dismiss_action()
        self._manual_override = True
        def _deferred():
            self._do_dim()
            self._start_dismiss_watcher()
        QTimer.singleShot(150, _deferred)

    def _set_idle_action(self, action):
        """Set the idle action (blank or dim)."""
        self.config.idle_action = action
        self.config.save()
        self._update_idle_action_checks()
        self.tray.showMessage(
            "OLED Saver",
            f"Idle action: {action}",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def _update_idle_action_checks(self):
        """Update checkmarks on idle action menu items."""
        self.idle_blank_action.setChecked(self.config.idle_action == "blank")
        self.idle_dim_action.setChecked(self.config.idle_action == "dim")

    def _show_dim_brightness_dialog(self):
        """Show dialog to set dim brightness."""
        pct, ok = QInputDialog.getInt(
            None,
            "Dim Brightness",
            "Brightness % when dimmed:",
            self.config.dim_brightness,
            1,    # min
            100,  # max
            5,    # step
        )
        if ok:
            self.config.dim_brightness = pct
            self.config.save()
            self.tray.showMessage(
                "OLED Saver",
                f"Dim brightness: {pct}%",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _update_monitor_label(self):
        """Update monitor selection label in tray menu."""
        names = [s.name() for s in self.target_screens]
        self.monitor_action.setText(f"🖥 Monitors: {', '.join(names)}...")

    def _show_monitor_dialog(self):
        """Show dialog to select target monitors."""
        _, all_monitors = self.platform.detect_monitors()
        current_names = [s.name() for s in self.target_screens]
        dialog = MonitorSelectDialog(all_monitors, preselected=current_names)
        if dialog.exec() and dialog.selected_connectors:
            self._dismiss_action()
            self.config.monitor = ",".join(dialog.selected_connectors)
            self.config.save()
            self.target_screens = self._find_target_screens()
            self.black_screens = []
            for screen in self.target_screens:
                bs = BlackScreen(screen)
                bs.dismissed = self._dismiss_action
                self.black_screens.append(bs)
            self.dim_overlays = [DimOverlay(s) for s in self.target_screens]
            self._update_monitor_label()
            names = [s.name() for s in self.target_screens]
            self.tray.showMessage(
                "OLED Saver",
                f"Monitors: {', '.join(names)}",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    # --- Night Mode ---

    def _setup_night_mode(self):
        """Setup timer that checks time and applies night brightness."""
        self.night_timer = QTimer()
        self.night_timer.setInterval(60_000)
        self.night_timer.timeout.connect(self._check_night_mode)
        self.night_timer.start()
        self._check_night_mode()

    def _is_night_time(self):
        """Check if current time is within night hours."""
        now = datetime.now().time()
        start = self.config.night_start_time
        end = self.config.night_end_time
        if start <= end:
            return start <= now < end
        else:
            return now >= start or now < end

    def _check_night_mode(self):
        """Periodic check: apply or remove night brightness."""
        if not self.config.night_mode_enabled:
            if self.night_active:
                self._restore_brightness()
            return

        should_dim = self._is_night_time()
        if should_dim and not self.night_active:
            self._apply_night_brightness()
        elif not should_dim and self.night_active:
            self._restore_brightness()

    def _apply_night_brightness(self):
        """Dim all monitors to night brightness."""
        outputs = self.platform.set_brightness_all(self.config.night_mode_brightness)
        self.night_active = True
        self._update_night_toggle_label()
        print(
            f"Night mode ON: {self.config.night_mode_brightness}% on {outputs}"
        )

    def _restore_brightness(self):
        """Restore all monitors to full brightness."""
        outputs = self.platform.set_brightness_all(100)
        self.night_active = False
        self._update_night_toggle_label()
        print(f"Night mode OFF: 100% on {outputs}")

    def _toggle_night_mode(self):
        """Toggle night mode enabled/disabled."""
        self.config.night_mode_enabled = not self.config.night_mode_enabled
        self.config.save()
        if not self.config.night_mode_enabled and self.night_active:
            self._restore_brightness()
        elif self.config.night_mode_enabled:
            self._check_night_mode()
        self._update_night_toggle_label()
        state = "enabled" if self.config.night_mode_enabled else "disabled"
        self.tray.showMessage(
            "OLED Saver",
            f"Night mode {state}",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def _update_night_toggle_label(self):
        """Update night mode toggle label in tray menu."""
        if self.config.night_mode_enabled:
            status = "ON" if self.night_active else f"from {self.config.night_mode_start}"
            self.night_toggle_action.setText(f"🌙 Night Mode ({status}) ✓")
        else:
            self.night_toggle_action.setText("🌙 Night Mode (disabled)")

    def _show_night_settings(self):
        """Show night mode settings dialog."""
        dialog = NightSettingsDialog(self.config)
        if dialog.exec():
            start, end, brightness = dialog.get_values()
            self.config.night_mode_start = start
            self.config.night_mode_end = end
            self.config.night_mode_brightness = brightness
            self.config.save()
            self._update_night_toggle_label()
            if self.night_active:
                self._restore_brightness()
            self._check_night_mode()
            self.tray.showMessage(
                "OLED Saver",
                f"Night: {start}–{end} at {brightness}%",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _quit(self):
        """Clean shutdown."""
        self._dismiss_action()
        if self.night_active:
            self._restore_brightness()
        self.platform.cleanup()
        self.app.quit()

    def cleanup(self):
        """Cleanup on exit."""
        if self.dimmed:
            for overlay in self.dim_overlays:
                overlay.hide()
        if self.night_active:
            self.platform.set_brightness_all(100)
        self.platform.cleanup()


def main():
    log = logging.getLogger(__name__)

    try:
        platform = detect_platform()
        log.info(f"Platform: {type(platform).__name__}")

        is_running, old_pid = platform.check_single_instance()
        if is_running:
            log.warning(f"Already running (PID {old_pid}). Sending toggle.")
            if old_pid:
                platform.send_toggle(old_pid)
            sys.exit(1)

        app = QApplication(sys.argv)
        app.setApplicationName("OLED Saver")
        app.setQuitOnLastWindowClosed(False)

        blanker = OledBlanker(app, platform)
        log.info("App initialized, entering main loop")

        import atexit
        atexit.register(blanker.cleanup)

        sys.exit(app.exec())
    except Exception:
        log.critical(f"Fatal error:\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
