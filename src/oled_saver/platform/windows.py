"""Windows platform backend for OLED Saver."""

import asyncio
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

from oled_saver.platform.base import Platform, parse_edid_monitor_name, is_oled_model

# SHQueryUserNotificationState return values
QUNS_NOT_PRESENT = 1
QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4
QUNS_ACCEPTS_NOTIFICATIONS = 5
QUNS_QUIET_TIME = 6
QUNS_APP = 7

# Media playback status (Windows.Media.Control)
_MEDIA_PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing

def _is_fullscreen_app_running():
    """Check if a fullscreen/D3D/presentation app is running via shell32."""
    try:
        state = ctypes.c_int(0)
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
        return state.value in (QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)
    except Exception:
        return False


def _is_media_session_playing():
    """Check if any Windows media session is currently playing (browsers, Spotify, VLC, etc.)."""
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        )

        async def _check():
            manager = await SessionManager.request_async()
            sessions = manager.get_sessions()
            for session in sessions:
                info = session.get_playback_info()
                if info and info.playback_status == _MEDIA_PLAYING:
                    return True
            return False

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_check())
        finally:
            loop.close()
    except ImportError:
        return False
    except Exception:
        return False


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
        """Detect monitors using EnumDisplayMonitors + EnumDisplayDevices (ctypes)."""
        oled_monitors, all_monitors = [], []
        try:
            all_monitors = self._enum_display_monitors()
            for connector, model in all_monitors:
                if is_oled_model(model):
                    oled_monitors.append((connector, model))
        except Exception:
            # Fallback: Qt screens
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

    def _enum_display_monitors(self):
        """Enumerate monitors via Win32 EnumDisplayMonitors + EnumDisplayDevices."""
        user32 = ctypes.windll.user32

        class DISPLAY_DEVICE(ctypes.Structure):
            _fields_ = [
                ('cb', ctypes.wintypes.DWORD),
                ('DeviceName', ctypes.c_wchar * 32),
                ('DeviceString', ctypes.c_wchar * 128),
                ('StateFlags', ctypes.wintypes.DWORD),
                ('DeviceID', ctypes.c_wchar * 128),
                ('DeviceKey', ctypes.c_wchar * 128),
            ]

        DISPLAY_DEVICE_ACTIVE = 0x00000001
        monitors = []
        idx = 0
        while True:
            adapter = DISPLAY_DEVICE()
            adapter.cb = ctypes.sizeof(adapter)
            if not user32.EnumDisplayDevicesW(None, idx, ctypes.byref(adapter), 0):
                break
            idx += 1
            if not (adapter.StateFlags & DISPLAY_DEVICE_ACTIVE):
                continue
            # Get the monitor attached to this adapter
            monitor = DISPLAY_DEVICE()
            monitor.cb = ctypes.sizeof(monitor)
            if user32.EnumDisplayDevicesW(adapter.DeviceName, 0, ctypes.byref(monitor), 0):
                model = monitor.DeviceString.strip() or "Unknown"
            else:
                model = adapter.DeviceString.strip() or "Unknown"
            connector = adapter.DeviceName.strip()
            monitors.append((connector, model))
        return monitors

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
        """Check if media is playing or a fullscreen app is running."""
        return _is_fullscreen_app_running() or _is_media_session_playing()

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
