"""KDE Plasma platform backend for OLED Blanker."""

import os
import signal
import subprocess

from PyQt6.QtCore import QProcess, QTimer

from oled_saver.platform.base import LinuxPlatform


class KDEPlatform(LinuxPlatform):
    """KDE Plasma backend: kscreen-doctor brightness + swayidle idle."""

    def __init__(self):
        super().__init__()
        self._swayidle_process = None
        self._restarting = False

    # --- Brightness (kscreen-doctor) ---

    def set_brightness(self, output_name, brightness_pct):
        pct = max(1, min(100, int(brightness_pct)))
        try:
            subprocess.run(
                ["kscreen-doctor", f"output.{output_name}.brightness.{pct}"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    def set_brightness_all(self, brightness_pct):
        pct = max(1, min(100, int(brightness_pct)))
        outputs = self.get_all_outputs()
        args = [f"output.{name}.brightness.{pct}" for name in outputs]
        if args:
            try:
                subprocess.run(["kscreen-doctor"] + args, capture_output=True, timeout=5)
            except Exception:
                pass
        return outputs

    # --- Idle Detection (swayidle + fallback) ---

    def setup_idle(self, timeout_s, on_idle, on_resume):
        self._idle_timeout = timeout_s
        self._on_idle = on_idle
        self._on_resume = on_resume

        swayidle_path = subprocess.run(
            ["which", "swayidle"], capture_output=True, text=True
        ).stdout.strip()

        if swayidle_path:
            self._start_swayidle(swayidle_path)
        else:
            print(
                "swayidle not found. Using mouse polling fallback.\n"
                "  Install: sudo apt install swayidle",
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
            # Polling fallback — just reset ticks
            self._idle_ticks = 0

    def stop_idle(self):
        if self._swayidle_process:
            self._swayidle_process.kill()
            self._swayidle_process.waitForFinished(2000)
            self._swayidle_process = None
        super().stop_idle()

    def _start_swayidle(self, swayidle_path):
        pid = os.getpid()
        # SIGUSR2 (12) = idle, SIGURG (23) = resume
        signal.signal(signal.SIGUSR2, self._handle_idle_signal)
        signal.signal(signal.SIGURG, self._handle_resume_signal)

        # Stop polling if running
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
