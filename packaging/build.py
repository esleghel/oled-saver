"""PyInstaller build script for OLED Saver."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent  # packaging/ -> repo root


def build():
    src = ROOT / "src"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "oled-saver",
        "--paths", str(src),
        "--hidden-import", "oled_saver.platform.base",
        "--hidden-import", "oled_saver.platform.kde",
        "--hidden-import", "oled_saver.platform.gnome",
        "--hidden-import", "oled_saver.platform.windows",
    ]
    # Include winsdk for Windows media detection
    if sys.platform == "win32":
        cmd += [
            "--hidden-import", "winsdk",
            "--hidden-import", "winsdk.windows.media.control",
        ]
    cmd.append(str(src / "oled_saver" / "app.py"))
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=ROOT)


if __name__ == "__main__":
    build()
