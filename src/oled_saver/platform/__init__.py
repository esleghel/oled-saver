"""Platform abstraction for OLED Saver."""

import os
import sys

from oled_saver.platform.base import Platform, LinuxPlatform, parse_edid_monitor_name, is_oled_model


def detect_platform():
    """Auto-detect and return the appropriate Platform instance."""
    if sys.platform == "win32":
        from oled_saver.platform.windows import WindowsPlatform
        return WindowsPlatform()

    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    session = os.environ.get("DESKTOP_SESSION", "").upper()

    if "KDE" in desktop or "PLASMA" in session:
        from oled_saver.platform.kde import KDEPlatform
        return KDEPlatform()
    else:
        from oled_saver.platform.gnome import GNOMEPlatform
        return GNOMEPlatform()
