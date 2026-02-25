"""PyInstaller build script for OLED Saver."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "oled-saver",
        "--add-data", f"platform_base.py{':' if sys.platform != 'win32' else ';'}.",
        "--add-data", f"platform_kde.py{':' if sys.platform != 'win32' else ';'}.",
        "--add-data", f"platform_gnome.py{':' if sys.platform != 'win32' else ';'}.",
        "--add-data", f"platform_windows.py{':' if sys.platform != 'win32' else ';'}.",
        "--hidden-import", "platform_base",
        "--hidden-import", "platform_kde",
        "--hidden-import", "platform_gnome",
        "--hidden-import", "platform_windows",
        "oled_saver.py",
    ]
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=ROOT)


if __name__ == "__main__":
    build()
