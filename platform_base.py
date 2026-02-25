"""
Platform abstraction layer for OLED Blanker.

Provides a Platform ABC and a LinuxPlatform base class with shared Linux
functionality (EDID, MPRIS, signals, PID file, QCursor fallback).
"""

import os
import signal
import struct
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from PyQt6.QtCore import QPoint, QTimer

# Known OLED model patterns
OLED_KEYWORDS = ["OLED"]
OLED_MODEL_PATTERNS = [
    lambda m: " FO" in m or m.startswith("FO"),  # Gigabyte/AORUS QD-OLED
    lambda m: any(m.startswith(p) for p in [
        "OLED", "65C", "55C", "48C", "42C", "77C", "83C",
        "65G", "55G", "77G", "83G", "65B", "55B", "48B",
    ]),  # LG OLED
    lambda m: any(x in m for x in ["S95", "S90", "G85", "G80"]),  # Samsung
    lambda m: any(x in m for x in [
        "PG42UQ", "PG48UQ", "PG34WCDM", "PG27AQDM", "PG32UCDM",
        "PA32DC", "PG49WCD",
    ]),  # ASUS
    lambda m: any(x in m for x in ["AW3423", "AW2725", "AW3225"]),  # Dell/Alienware
    lambda m: "XENEON" in m and "OLED" in m.upper(),  # Corsair
    lambda m: any(x in m for x in ["MEG342C", "MPG321URX", "MPG271QRX"]),  # MSI
    lambda m: "INZONE" in m,  # Sony
]


def parse_edid_monitor_name(edid_bytes):
    """Extract monitor name from EDID descriptor blocks."""
    if len(edid_bytes) < 128:
        return None
    for offset in [54, 72, 90, 108]:
        if offset + 18 <= len(edid_bytes):
            desc = edid_bytes[offset : offset + 18]
            if desc[0:4] == b"\x00\x00\x00\xfc":
                return desc[5:].split(b"\x0a")[0].decode("ascii", errors="replace").strip()
    return None


def is_oled_model(model_name):
    """Check if a monitor model name matches known OLED patterns."""
    if not model_name:
        return False
    upper = model_name.upper()
    if any(kw in upper for kw in OLED_KEYWORDS):
        return True
    for fn in OLED_MODEL_PATTERNS:
        try:
            if fn(model_name):
                return True
        except Exception:
            continue
    return False


class Platform(ABC):
    """Abstract platform interface."""

    @abstractmethod
    def detect_monitors(self):
        """Return (oled_list, all_list) where each is [(connector, model)]."""

    @abstractmethod
    def get_all_outputs(self):
        """Return list of connected output names."""

    @abstractmethod
    def set_brightness(self, output_name, brightness_pct):
        """Set brightness on a single monitor (1-100%)."""

    @abstractmethod
    def set_brightness_all(self, brightness_pct):
        """Set brightness on all connected monitors."""

    @abstractmethod
    def is_media_playing(self):
        """Check if any media player is actively playing."""

    @abstractmethod
    def setup_idle(self, timeout_s, on_idle, on_resume):
        """Setup idle detection. Calls on_idle/on_resume callbacks."""

    @abstractmethod
    def restart_idle(self, timeout_s):
        """Restart idle detection with new timeout."""

    @abstractmethod
    def stop_idle(self):
        """Stop idle detection."""

    @abstractmethod
    def check_single_instance(self):
        """Check if another instance is running. Returns (is_running, pid_or_None)."""

    @abstractmethod
    def write_instance_info(self):
        """Write current instance info for single-instance checking."""

    @abstractmethod
    def send_toggle(self, pid):
        """Send toggle-pause signal to running instance."""

    @abstractmethod
    def setup_toggle_handler(self, callback):
        """Setup handler for toggle-pause signal from external sources."""

    @abstractmethod
    def cleanup_instance(self):
        """Cleanup instance info on exit."""

    def cleanup(self):
        """Full cleanup on exit."""
        self.stop_idle()
        self.cleanup_instance()


class LinuxPlatform(Platform):
    """Base platform for Linux (shared KDE/GNOME functionality)."""

    PID_FILE = Path("/tmp") / f"oled-saver-{os.getuid()}.pid"

    def __init__(self):
        self._idle_poll_timer = None
        self._last_mouse_pos = QPoint()
        self._idle_ticks = 0
        self._idle_timeout = 120
        self._on_idle = None
        self._on_resume = None
        self._idle_active = False
        self._signal_timer = None
        self._toggle_callback = None

    # --- Monitor Detection (EDID) ---

    def detect_monitors(self):
        drm_base = Path("/sys/class/drm")
        oled_monitors, all_monitors = [], []
        if not drm_base.exists():
            return oled_monitors, all_monitors

        for connector_dir in sorted(drm_base.iterdir()):
            name = connector_dir.name
            if not any(x in name for x in ["-DP-", "-HDMI-", "-DVI-", "-VGA-", "-eDP-"]):
                continue
            status_file = connector_dir / "status"
            if not status_file.exists():
                continue
            try:
                status = status_file.read_text().strip()
            except OSError:
                continue
            if status != "connected":
                continue

            parts = name.split("-", 1)
            connector = parts[1] if len(parts) > 1 else name

            model = None
            edid_file = connector_dir / "edid"
            if edid_file.exists():
                try:
                    model = parse_edid_monitor_name(edid_file.read_bytes())
                except OSError:
                    pass

            all_monitors.append((connector, model or "Unknown"))
            if is_oled_model(model):
                oled_monitors.append((connector, model))

        return oled_monitors, all_monitors

    def get_all_outputs(self):
        try:
            result = subprocess.run(
                ["xrandr", "--listmonitors"],
                capture_output=True, text=True, timeout=3,
            )
            outputs = []
            for line in result.stdout.strip().splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 4:
                    outputs.append(parts[-1])
            return outputs
        except Exception:
            return []

    # --- Media Detection (MPRIS D-Bus) ---

    def is_media_playing(self):
        try:
            result = subprocess.run(
                ["dbus-send", "--print-reply", "--dest=org.freedesktop.DBus",
                 "/org/freedesktop/DBus", "org.freedesktop.DBus.ListNames"],
                capture_output=True, text=True, timeout=2,
            )
            # Extract player service names from dbus-send output
            # Lines look like: '      string "org.mpris.MediaPlayer2.firefox.instance_1_83"'
            players = []
            for line in result.stdout.splitlines():
                if "org.mpris.MediaPlayer2." in line:
                    # Extract the quoted string
                    start = line.find('"')
                    end = line.rfind('"')
                    if start != -1 and end > start:
                        players.append(line[start + 1 : end])
            for player in players:
                status_result = subprocess.run(
                    ["dbus-send", "--print-reply", f"--dest={player}",
                     "/org/mpris/MediaPlayer2",
                     "org.freedesktop.DBus.Properties.Get",
                     "string:org.mpris.MediaPlayer2.Player",
                     "string:PlaybackStatus"],
                    capture_output=True, text=True, timeout=2,
                )
                if '"Playing"' in status_result.stdout:
                    return True
            return False
        except Exception:
            return False

    # --- Idle Detection (QCursor polling fallback) ---

    def setup_idle(self, timeout_s, on_idle, on_resume):
        self._idle_timeout = timeout_s
        self._on_idle = on_idle
        self._on_resume = on_resume
        self._setup_polling_idle()

    def restart_idle(self, timeout_s):
        self._idle_timeout = timeout_s
        self._idle_ticks = 0

    def stop_idle(self):
        if self._idle_poll_timer:
            self._idle_poll_timer.stop()
            self._idle_poll_timer = None

    def _setup_polling_idle(self):
        from PyQt6.QtGui import QCursor
        self._last_mouse_pos = QCursor.pos()
        self._idle_ticks = 0
        self._idle_active = False
        self._idle_poll_timer = QTimer()
        self._idle_poll_timer.setInterval(5000)
        self._idle_poll_timer.timeout.connect(self._poll_idle)
        self._idle_poll_timer.start()
        print(f"Idle: polling mouse position every 5s (timeout: {self._idle_timeout}s)")

    def _poll_idle(self):
        from PyQt6.QtGui import QCursor
        current_pos = QCursor.pos()
        if current_pos != self._last_mouse_pos:
            self._last_mouse_pos = current_pos
            self._idle_ticks = 0
            if self._idle_active:
                self._idle_active = False
                if self._on_resume:
                    self._on_resume()
        else:
            self._idle_ticks += 5
            if self._idle_ticks >= self._idle_timeout and not self._idle_active:
                self._idle_active = True
                if self._on_idle:
                    self._on_idle()

    # --- Single Instance (PID file + Unix signals) ---

    def check_single_instance(self):
        if self.PID_FILE.exists():
            try:
                old_pid = int(self.PID_FILE.read_text().strip())
                os.kill(old_pid, 0)
                return True, old_pid
            except (ProcessLookupError, ValueError):
                self.PID_FILE.unlink(missing_ok=True)
        return False, None

    def write_instance_info(self):
        self.PID_FILE.write_text(str(os.getpid()))

    def send_toggle(self, pid):
        os.kill(pid, signal.SIGUSR1)

    def setup_toggle_handler(self, callback):
        self._toggle_callback = callback
        signal.signal(signal.SIGUSR1, self._handle_sigusr1)
        # Timer to allow signal processing in Qt event loop
        self._signal_timer = QTimer()
        self._signal_timer.start(500)
        self._signal_timer.timeout.connect(lambda: None)

    def _handle_sigusr1(self, signum, frame):
        if self._toggle_callback:
            QTimer.singleShot(0, self._toggle_callback)

    def cleanup_instance(self):
        try:
            self.PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def detect_platform():
    """Auto-detect and return the appropriate Platform instance."""
    if sys.platform == "win32":
        from platform_windows import WindowsPlatform
        return WindowsPlatform()

    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    session = os.environ.get("DESKTOP_SESSION", "").upper()

    if "KDE" in desktop or "PLASMA" in session:
        from platform_kde import KDEPlatform
        return KDEPlatform()
    else:
        from platform_gnome import GNOMEPlatform
        return GNOMEPlatform()
