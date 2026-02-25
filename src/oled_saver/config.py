"""Configuration manager for OLED Saver."""

import configparser
from datetime import time as dtime
from pathlib import Path

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
