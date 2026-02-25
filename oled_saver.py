#!/usr/bin/python3
"""
OLED Saver — Cross-Platform

Displays a fullscreen black window (or dims) on selected monitor(s) after
a configurable idle timeout. Designed to prevent burn-in on OLED displays.

Supports KDE Plasma, GNOME, and Windows.

Features:
- Auto-detects OLED monitors from EDID data
- Platform-native idle detection (swayidle, Mutter, GetLastInputInfo)
- Skips blanking when media is playing (MPRIS on Linux)
- Night mode: automatic brightness reduction during configured hours
- System tray icon with full control

Dependencies:
- Python 3 + PyQt6
- Linux: swayidle (recommended: sudo apt install swayidle)
"""

import configparser
import os
import sys
from datetime import datetime, time as dtime
from pathlib import Path

from PyQt6.QtCore import QTime, QTimer, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

# Add script directory to path for platform imports
sys.path.insert(0, str(Path(__file__).parent))
from platform_base import detect_platform, is_oled_model

CONFIG_DIR = Path.home() / ".config"
CONFIG_FILE = CONFIG_DIR / "oled-saver.conf"


class Config:
    """Configuration manager."""

    def __init__(self):
        self.timeout_seconds = 120
        self.monitor = "auto"
        self.check_inhibitors = True
        self.pause_duration_minutes = 30
        self.idle_action = "blank"  # "blank" or "dim"
        self.dim_brightness = 10
        self.night_mode_enabled = True
        self.night_mode_start = "22:00"
        self.night_mode_end = "07:00"
        self.night_mode_brightness = 20
        self.load()

    def load(self):
        if not CONFIG_FILE.exists():
            return
        cp = configparser.ConfigParser()
        cp.read(CONFIG_FILE)
        s = cp["oled-saver"] if "oled-saver" in cp else {}
        self.timeout_seconds = int(s.get("timeout_seconds", self.timeout_seconds))
        self.monitor = s.get("monitor", self.monitor)
        self.check_inhibitors = s.get("check_inhibitors", "true").lower() == "true"
        self.pause_duration_minutes = int(
            s.get("pause_duration_minutes", self.pause_duration_minutes)
        )
        self.night_mode_enabled = s.get("night_mode_enabled", "true").lower() == "true"
        self.night_mode_start = s.get("night_mode_start", self.night_mode_start)
        self.night_mode_end = s.get("night_mode_end", self.night_mode_end)
        self.night_mode_brightness = int(
            s.get("night_mode_brightness", self.night_mode_brightness)
        )
        self.idle_action = s.get("idle_action", self.idle_action)
        self.dim_brightness = int(s.get("dim_brightness", self.dim_brightness))

    def save(self):
        cp = configparser.ConfigParser()
        cp["oled-saver"] = {
            "timeout_seconds": str(self.timeout_seconds),
            "monitor": self.monitor,
            "check_inhibitors": str(self.check_inhibitors).lower(),
            "pause_duration_minutes": str(self.pause_duration_minutes),
            "night_mode_enabled": str(self.night_mode_enabled).lower(),
            "night_mode_start": self.night_mode_start,
            "night_mode_end": self.night_mode_end,
            "night_mode_brightness": str(self.night_mode_brightness),
            "idle_action": self.idle_action,
            "dim_brightness": str(self.dim_brightness),
        }
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            cp.write(f)

    @property
    def monitor_list(self):
        """Parse monitor field into list of connector names."""
        if self.monitor in ("auto", "all"):
            return [self.monitor]
        return [m.strip() for m in self.monitor.split(",") if m.strip()]

    @property
    def night_start_time(self):
        h, m = self.night_mode_start.split(":")
        return dtime(int(h), int(m))

    @property
    def night_end_time(self):
        h, m = self.night_mode_end.split(":")
        return dtime(int(h), int(m))


class MonitorSelectDialog(QDialog):
    """Dialog to select which monitor(s) to target for idle actions."""

    def __init__(self, monitors, preselected=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OLED Saver — Select Monitors")
        self.selected_connectors = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select monitors for blank/dim:"))

        self.list_widget = QListWidget()
        for connector, model in monitors:
            item = QListWidgetItem(f"{connector}  —  {model}")
            item.setData(Qt.ItemDataRole.UserRole, connector)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if preselected and connector in preselected:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        self.selected_connectors = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self.selected_connectors.append(item.data(Qt.ItemDataRole.UserRole))
        if self.selected_connectors:
            self.accept()


class NightSettingsDialog(QDialog):
    """Dialog to configure night mode settings."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Night Mode Settings")
        self.config = config

        layout = QFormLayout(self)

        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        self.start_edit.setTime(QTime.fromString(config.night_mode_start, "HH:mm"))
        layout.addRow("Start time:", self.start_edit)

        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("HH:mm")
        self.end_edit.setTime(QTime.fromString(config.night_mode_end, "HH:mm"))
        layout.addRow("End time:", self.end_edit)

        self.brightness_spin = QSpinBox()
        self.brightness_spin.setRange(5, 100)
        self.brightness_spin.setSuffix("%")
        self.brightness_spin.setValue(config.night_mode_brightness)
        layout.addRow("Brightness:", self.brightness_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return (
            self.start_edit.time().toString("HH:mm"),
            self.end_edit.time().toString("HH:mm"),
            self.brightness_spin.value(),
        )


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
        # Ignore the initial mouse move that happens when the window appears
        if self._ignore_first_move:
            self._ignore_first_move = False
            return
        self._dismiss()

    def keyPressEvent(self, event):
        self._dismiss()


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
        self.target_screens = []
        self.pause_timer = None
        self.night_active = False

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
            bs.dismissed = self._undo_idle_action
            self.black_screens.append(bs)

        # Setup system tray
        self._setup_tray()

        # Setup idle detection via platform
        self.platform.setup_idle(
            self.config.timeout_seconds,
            self._try_idle_action,
            self._undo_idle_action,
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
                # Show selection dialog (auto-detect failed)
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
                # Try partial match
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

        # Manual triggers
        menu.addAction("🔲 Blank Now").triggered.connect(self._manual_blank)
        menu.addAction("🔅 Dim Now").triggered.connect(self._manual_dim)
        menu.addSeparator()

        # Custom timeout
        timeout_action = menu.addAction(
            f"⏱ Set Timeout ({self.config.timeout_seconds}s)..."
        )
        timeout_action.triggered.connect(self._show_timeout_dialog)
        self.timeout_action = timeout_action

        # Idle action submenu
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

        # Night mode
        self.night_toggle_action = menu.addAction("")
        self._update_night_toggle_label()
        self.night_toggle_action.triggered.connect(self._toggle_night_mode)

        night_settings_action = menu.addAction("🌙 Night Settings...")
        night_settings_action.triggered.connect(self._show_night_settings)

        menu.addSeparator()

        # Monitor selection
        self.monitor_action = menu.addAction("")
        self._update_monitor_label()
        self.monitor_action.triggered.connect(self._show_monitor_dialog)

        menu.addSeparator()
        menu.addAction("❌ Quit").triggered.connect(self._quit)

        self.tray.setContextMenu(menu)
        self.tray.setToolTip("OLED Saver — Active")
        self.tray.show()

    def _make_icon(self, color):
        """Generate a simple colored circle icon."""
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        # Draw circle with dark border
        painter.setBrush(QColor(color))
        painter.drawEllipse(4, 4, size - 8, size - 8)
        # Inner highlight
        painter.setBrush(QColor(255, 255, 255, 60))
        painter.drawEllipse(12, 8, size // 3, size // 3)
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

    def _undo_idle_action(self):
        """Undo whatever idle action is currently active."""
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
        """Dim target monitors to configured brightness."""
        if self.dimmed:
            return
        self.dimmed = True
        self._dim_mouse_pos = None
        for screen in self.target_screens:
            self.platform.set_brightness(screen.name(), self.config.dim_brightness)
        names = [s.name() for s in self.target_screens]
        print(f"Screen dimmed to {self.config.dim_brightness}% on {names}")

    def _undo_dim(self):
        """Restore target monitors brightness from dim state."""
        if not self.dimmed:
            return
        self.dimmed = False
        self._stop_dismiss_watcher()
        restore_pct = self.config.night_mode_brightness if self.night_active else 100
        for screen in self.target_screens:
            self.platform.set_brightness(screen.name(), restore_pct)
        names = [s.name() for s in self.target_screens]
        print(f"Screen undimmed to {restore_pct}% on {names}")

    def _start_dismiss_watcher(self):
        """Start watching for mouse movement to dismiss dim."""
        from PyQt6.QtGui import QCursor
        self._dim_mouse_pos = QCursor.pos()
        if not hasattr(self, '_dismiss_timer') or self._dismiss_timer is None:
            self._dismiss_timer = QTimer()
            self._dismiss_timer.setInterval(500)  # Check every 500ms
            self._dismiss_timer.timeout.connect(self._check_dismiss)
        self._dismiss_timer.start()

    def _stop_dismiss_watcher(self):
        """Stop the dismiss watcher."""
        if hasattr(self, '_dismiss_timer') and self._dismiss_timer:
            self._dismiss_timer.stop()

    def _check_dismiss(self):
        """Check if mouse moved to dismiss dim."""
        from PyQt6.QtGui import QCursor
        if not self.dimmed:
            self._stop_dismiss_watcher()
            return
        pos = QCursor.pos()
        if self._dim_mouse_pos is not None and pos != self._dim_mouse_pos:
            self._undo_dim()
        self._dim_mouse_pos = pos

    def _toggle_pause(self):
        """Toggle pause state."""
        self.paused = not self.paused
        if self.paused:
            self._undo_idle_action()
            self.pause_action.setText("▶ Resume")
            # Auto-resume after pause duration
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
        """Manually trigger blank screen."""
        self._undo_idle_action()
        self._do_blank()

    def _manual_dim(self):
        """Manually trigger dim."""
        self._undo_idle_action()
        self._do_dim()
        self._start_dismiss_watcher()

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
            self._undo_idle_action()
            self.config.monitor = ",".join(dialog.selected_connectors)
            self.config.save()
            # Rebuild target screens and black screens
            self.target_screens = self._find_target_screens()
            self.black_screens = []
            for screen in self.target_screens:
                bs = BlackScreen(screen)
                bs.dismissed = self._undo_idle_action
                self.black_screens.append(bs)
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
        self.night_timer.setInterval(60_000)  # Check every minute
        self.night_timer.timeout.connect(self._check_night_mode)
        self.night_timer.start()
        # Run initial check
        self._check_night_mode()

    def _is_night_time(self):
        """Check if current time is within night hours."""
        now = datetime.now().time()
        start = self.config.night_start_time
        end = self.config.night_end_time
        if start <= end:
            # e.g., 08:00 – 20:00 (same day)
            return start <= now < end
        else:
            # e.g., 22:00 – 07:00 (crosses midnight)
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
            # Re-check immediately with new settings
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
        self._undo_idle_action()
        if self.night_active:
            self._restore_brightness()
        self.platform.cleanup()
        self.app.quit()

    def cleanup(self):
        """Cleanup on exit."""
        if self.dimmed:
            for screen in self.target_screens:
                self.platform.set_brightness(screen.name(), 100)
        if self.night_active:
            self.platform.set_brightness_all(100)
        self.platform.cleanup()


def main():
    # Detect platform
    platform = detect_platform()
    print(f"Platform: {type(platform).__name__}")

    # Check for existing instance
    is_running, old_pid = platform.check_single_instance()
    if is_running:
        print(f"Already running (PID {old_pid}). Sending toggle.", file=sys.stderr)
        if old_pid:
            platform.send_toggle(old_pid)
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("OLED Saver")
    app.setQuitOnLastWindowClosed(False)

    blanker = OledBlanker(app, platform)

    # Cleanup on exit
    import atexit
    atexit.register(blanker.cleanup)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
