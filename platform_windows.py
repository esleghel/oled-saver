"""Windows platform backend for OLED Blanker."""

import ctypes
import ctypes.wintypes
import os
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QTimer

from platform_base import Platform, parse_edid_monitor_name, is_oled_model


class WindowsPlatform(Platform):
    """Windows backend: Win32 APIs for brightness, idle, single-instance."""

    MUTEX_NAME = "OLEDBlankerSingleInstance"
    IPC_PORT = 39271  # Localhost TCP port for toggle IPC

    def __init__(self):
        self._idle_timer = None
        self._idle_timeout = 120
        self._on_idle = None
        self._on_resume = None
        self._idle_active = False
        self._mutex = None
        self._ipc_thread = None
        self._ipc_server = None
        self._toggle_callback = None

    # --- Monitor Detection ---

    def detect_monitors(self):
        """Detect monitors using Qt screens + WMI EDID when available."""
        oled_monitors, all_monitors = [], []
        try:
            # Try WMI via PowerShell for EDID
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorID | "
                 "ForEach-Object { $name = ($_.UserFriendlyName | ForEach-Object { [char]$_ }) -join ''; "
                 "$id = ($_.InstanceName -split '\\\\')[1]; Write-Output \"$id|$name\" }"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                if "|" in line:
                    connector, model = line.split("|", 1)
                    model = model.strip().rstrip("\x00")
                    connector = connector.strip()
                    if not model:
                        model = "Unknown"
                    all_monitors.append((connector, model))
                    if is_oled_model(model):
                        oled_monitors.append((connector, model))
        except Exception:
            # Fallback: use display index names
            try:
                from PyQt6.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    for i, screen in enumerate(app.screens()):
                        name = screen.name() or f"Display-{i}"
                        all_monitors.append((name, name))
            except Exception:
                pass

        return oled_monitors, all_monitors

    def get_all_outputs(self):
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                return [s.name() for s in app.screens()]
        except Exception:
            pass
        return []

    # --- Brightness ---

    def set_brightness(self, output_name, brightness_pct):
        """Set brightness using SetDeviceGammaRamp (software gamma)."""
        pct = max(1, min(100, int(brightness_pct)))
        self._set_gamma_ramp(output_name, pct / 100.0)

    def set_brightness_all(self, brightness_pct):
        pct = max(1, min(100, int(brightness_pct)))
        outputs = self.get_all_outputs()
        factor = pct / 100.0
        for output in outputs:
            self._set_gamma_ramp(output, factor)
        return outputs

    def _set_gamma_ramp(self, output_name, factor):
        """Set gamma ramp for brightness control."""
        try:
            # Get device context for the display
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            # For simplicity, use the primary DC (affects main display)
            # For per-monitor control, need to enumerate displays
            hdc = user32.GetDC(0)
            if not hdc:
                return

            # Build gamma ramp
            ramp = (ctypes.c_ushort * 256 * 3)()
            for i in range(256):
                val = min(65535, int(i * 256 * factor))
                ramp[0][i] = val  # Red
                ramp[1][i] = val  # Green
                ramp[2][i] = val  # Blue

            gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
            user32.ReleaseDC(0, hdc)
        except Exception as e:
            print(f"Gamma ramp error: {e}", file=sys.stderr)

    # --- Idle Detection (GetLastInputInfo polling) ---

    def setup_idle(self, timeout_s, on_idle, on_resume):
        self._idle_timeout = timeout_s
        self._on_idle = on_idle
        self._on_resume = on_resume
        self._idle_active = False

        self._idle_timer = QTimer()
        self._idle_timer.setInterval(5000)
        self._idle_timer.timeout.connect(self._poll_idle)
        self._idle_timer.start()
        print(f"Idle: GetLastInputInfo polling (timeout: {timeout_s}s)")

    def restart_idle(self, timeout_s):
        self._idle_timeout = timeout_s

    def stop_idle(self):
        if self._idle_timer:
            self._idle_timer.stop()
            self._idle_timer = None

    def _poll_idle(self):
        """Poll Windows for idle time."""
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint),
                    ("dwTime", ctypes.c_uint),
                ]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))

            tick_count = ctypes.windll.kernel32.GetTickCount()
            idle_ms = tick_count - lii.dwTime
            idle_s = idle_ms / 1000.0

            if idle_s >= self._idle_timeout and not self._idle_active:
                self._idle_active = True
                if self._on_idle:
                    self._on_idle()
            elif idle_s < 2 and self._idle_active:
                self._idle_active = False
                if self._on_resume:
                    self._on_resume()
        except Exception:
            pass

    # --- Media Playing ---

    def is_media_playing(self):
        """On Windows, skip media check (return False)."""
        return False

    # --- Single Instance (Named Mutex) ---

    def check_single_instance(self):
        try:
            kernel32 = ctypes.windll.kernel32
            mutex = kernel32.CreateMutexW(None, False, self.MUTEX_NAME)
            last_error = kernel32.GetLastError()
            if last_error == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(mutex)
                return True, None
            self._mutex = mutex
            return False, None
        except Exception:
            return False, None

    def write_instance_info(self):
        pass  # Mutex handles this

    def send_toggle(self, pid):
        """Send toggle via TCP socket."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(("127.0.0.1", self.IPC_PORT))
                s.sendall(b"TOGGLE\n")
        except Exception:
            pass

    def setup_toggle_handler(self, callback):
        self._toggle_callback = callback
        self._ipc_thread = threading.Thread(target=self._ipc_listener, daemon=True)
        self._ipc_thread.start()

    def _ipc_listener(self):
        """Listen for toggle commands on TCP socket."""
        try:
            self._ipc_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._ipc_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._ipc_server.bind(("127.0.0.1", self.IPC_PORT))
            self._ipc_server.listen(1)
            while True:
                conn, _ = self._ipc_server.accept()
                data = conn.recv(64)
                conn.close()
                if b"TOGGLE" in data and self._toggle_callback:
                    QTimer.singleShot(0, self._toggle_callback)
        except Exception:
            pass

    def cleanup_instance(self):
        if self._ipc_server:
            try:
                self._ipc_server.close()
            except Exception:
                pass
        if self._mutex:
            try:
                ctypes.windll.kernel32.ReleaseMutex(self._mutex)
                ctypes.windll.kernel32.CloseHandle(self._mutex)
            except Exception:
                pass
