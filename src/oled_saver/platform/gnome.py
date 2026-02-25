"""GNOME platform backend for OLED Blanker."""

import os
import signal
import subprocess

from PyQt6.QtCore import QProcess, QTimer

from oled_saver.platform.base import LinuxPlatform


class GNOMEPlatform(LinuxPlatform):
    """GNOME backend: gdbus/xrandr brightness + swayidle/Mutter idle."""

    def __init__(self):
        super().__init__()
        self._swayidle_process = None
        self._restarting = False
        self._use_gdbus = self._check_gdbus_brightness()

    def _check_gdbus_brightness(self):
        """Check if GNOME brightness control via gdbus is available."""
        try:
            result = subprocess.run(
                ["gdbus", "introspect", "--session",
                 "--dest", "org.gnome.SettingsDaemon.Power",
                 "--object-path", "/org/gnome/SettingsDaemon/Power"],
                capture_output=True, text=True, timeout=3,
            )
            return "Brightness" in result.stdout
        except Exception:
            return False

    # --- Brightness ---

    def set_brightness(self, output_name, brightness_pct):
        pct = max(1, min(100, int(brightness_pct)))
        # Try gnome-randr first, then xrandr fallback
        if not self._set_brightness_xrandr(output_name, pct):
            pass  # Already logged

    def set_brightness_all(self, brightness_pct):
        pct = max(1, min(100, int(brightness_pct)))
        outputs = self.get_all_outputs()

        if self._use_gdbus:
            # GNOME SettingsDaemon controls all displays together
            try:
                subprocess.run(
                    ["gdbus", "call", "--session",
                     "--dest", "org.gnome.SettingsDaemon.Power",
                     "--object-path", "/org/gnome/SettingsDaemon/Power",
                     "--method", "org.freedesktop.DBus.Properties.Set",
                     "org.gnome.SettingsDaemon.Power.Screen",
                     "Brightness", f"<int32 {pct}>"],
                    capture_output=True, timeout=3,
                )
                return outputs
            except Exception:
                pass

        # Fallback: xrandr per-output
        for output in outputs:
            self._set_brightness_xrandr(output, pct)
        return outputs

    def _set_brightness_xrandr(self, output_name, brightness_pct):
        """Set brightness via xrandr (software gamma)."""
        value = max(0.1, min(1.0, brightness_pct / 100.0))
        try:
            subprocess.run(
                ["xrandr", "--output", output_name, "--brightness", f"{value:.2f}"],
                capture_output=True, timeout=3,
            )
            return True
        except Exception:
            return False

    # --- Idle Detection (swayidle preferred, Mutter fallback, QCursor last resort) ---

    def setup_idle(self, timeout_s, on_idle, on_resume):
        self._idle_timeout = timeout_s
        self._on_idle = on_idle
        self._on_resume = on_resume

        swayidle_path = subprocess.run(
            ["which", "swayidle"], capture_output=True, text=True
        ).stdout.strip()

        if swayidle_path:
            self._start_swayidle(swayidle_path)
        elif self._check_mutter_idle():
            self._setup_mutter_idle()
        else:
            print(
                "No idle backend found. Using mouse polling.\n"
                "  Install swayidle for better detection: sudo apt install swayidle",
                file=__import__("sys").stderr,
            )
            self._setup_polling_idle()

    def restart_idle(self, timeout_s):
        self._idle_timeout = timeout_s
        if self._swayidle_process and self._swayidle_process.state() != QProcess.ProcessState.NotRunning:
            self._restarting = True
            self._swayidle_process.finished.disconnect(self._on_swayidle_finished)
            self._swayidle_process.kill()
            self._swayidle_process.waitForFinished(2000)
            self._restarting = False
            swayidle_path = subprocess.run(
                ["which", "swayidle"], capture_output=True, text=True
            ).stdout.strip()
            if swayidle_path:
                self._start_swayidle(swayidle_path)
        else:
            self._idle_ticks = 0

    def stop_idle(self):
        if self._swayidle_process:
            self._swayidle_process.kill()
            self._swayidle_process.waitForFinished(2000)
            self._swayidle_process = None
        super().stop_idle()

    def _check_mutter_idle(self):
        """Check if Mutter IdleMonitor is available."""
        try:
            result = subprocess.run(
                ["gdbus", "introspect", "--session",
                 "--dest", "org.gnome.Mutter.IdleMonitor",
                 "--object-path", "/org/gnome/Mutter/IdleMonitor/Core"],
                capture_output=True, text=True, timeout=3,
            )
            return "AddIdleWatch" in result.stdout
        except Exception:
            return False

    def _setup_mutter_idle(self):
        """Use Mutter IdleMonitor D-Bus for idle detection via polling."""
        self._mutter_timer = QTimer()
        self._mutter_timer.setInterval(5000)
        self._mutter_timer.timeout.connect(self._poll_mutter_idle)
        self._mutter_timer.start()
        self._idle_active = False
        print(f"Idle: Mutter IdleMonitor (timeout: {self._idle_timeout}s)")

    def _poll_mutter_idle(self):
        """Poll Mutter for idle time."""
        try:
            result = subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", "org.gnome.Mutter.IdleMonitor",
                 "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
                 "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"],
                capture_output=True, text=True, timeout=2,
            )
            # Output like "(uint64 12345,)" — milliseconds
            idle_ms = int(result.stdout.strip().strip("()").split()[1].rstrip(","))
            idle_s = idle_ms / 1000.0

            if idle_s >= self._idle_timeout and not self._idle_active:
                self._idle_active = True
                if self._on_idle:
                    self._on_idle()
            elif idle_s < self._idle_timeout and self._idle_active:
                self._idle_active = False
                if self._on_resume:
                    self._on_resume()
        except Exception:
            pass

    # swayidle methods (same pattern as KDE)
    def _start_swayidle(self, swayidle_path):
        pid = os.getpid()
        signal.signal(signal.SIGUSR2, self._handle_idle_signal)
        signal.signal(signal.SIGURG, self._handle_resume_signal)

        if self._idle_poll_timer:
            self._idle_poll_timer.stop()
            self._idle_poll_timer = None

        self._swayidle_process = QProcess()
        self._swayidle_process.setProgram(swayidle_path)
        self._swayidle_process.setArguments([
            "-w",
            "timeout", str(self._idle_timeout),
            f"kill -12 {pid}",
            "resume",
            f"kill -23 {pid}",
        ])
        self._swayidle_process.finished.connect(self._on_swayidle_finished)
        self._swayidle_process.start()
        print(f"Idle: swayidle (timeout: {self._idle_timeout}s)")

    def _on_swayidle_finished(self, exit_code, exit_status):
        if self._restarting:
            return
        print(f"swayidle exited (code={exit_code}). Falling back to polling.",
              file=__import__("sys").stderr)
        self._setup_polling_idle()

    def _handle_idle_signal(self, signum, frame):
        if self._on_idle:
            QTimer.singleShot(0, self._on_idle)

    def _handle_resume_signal(self, signum, frame):
        if self._on_resume:
            QTimer.singleShot(0, self._on_resume)
