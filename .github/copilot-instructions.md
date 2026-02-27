# Copilot Instructions for OLED Saver

## Limba preferată

Răspunde în limba română, cu excepția codului și a numelor tehnice.

## Project Overview

OLED Saver is a cross-platform (Linux KDE/GNOME + Windows) PyQt6 system tray application that prevents OLED burn-in by blanking or dimming idle monitors. It auto-detects OLED monitors via EDID, skips when media is playing, and supports night mode auto-dimming.

## Running from Source

```bash
pip install PyQt6
pip install -e .
oled-saver
```

Requires Python 3.10+. On Linux, install `swayidle` for proper idle detection (otherwise falls back to mouse polling).

There is no test suite or linter configured.

## Architecture

### Entry Point & Main Controller

`src/oled_saver/app.py` contains both the entry point (`main()`) and the `OledBlanker` controller class. `OledBlanker` owns the Qt application lifecycle: system tray, black screen widgets, idle/resume callbacks, night mode timer, and pause state. It delegates all hardware interaction to a `Platform` instance.

### Platform Abstraction Layer

All platform-specific code lives in `src/oled_saver/platform/`. The hierarchy:

```
Platform (ABC)                    — base.py
├── LinuxPlatform                 — base.py (shared Linux: EDID, MPRIS, PID file, signals, QCursor fallback)
│   ├── KDEPlatform               — kde.py  (kscreen-doctor brightness, KDE PowerDevil inhibitors, swayidle)
│   └── GNOMEPlatform             — gnome.py (gdbus/xrandr brightness, GNOME session inhibitors, swayidle/Mutter)
└── WindowsPlatform               — windows.py (Win32 gamma ramp, GetLastInputInfo, winsdk media, named mutex + TCP IPC)
```

`detect_platform()` in `platform/__init__.py` selects the backend at startup using `sys.platform` and `XDG_CURRENT_DESKTOP`/`DESKTOP_SESSION`.

When adding a new platform feature (brightness, idle detection, media checking), implement it in the appropriate platform subclass. Shared Linux logic belongs in `LinuxPlatform`.

### Key Subsystems

- **Idle detection** has a fallback chain: `swayidle` → Mutter IdleMonitor (GNOME only) → QCursor mouse polling. On Windows: `GetLastInputInfo` polling.
- **Media inhibitor checking**: KDE PowerDevil D-Bus → MPRIS D-Bus; GNOME SessionManager D-Bus → MPRIS D-Bus; Windows: `SHQueryUserNotificationState` + `winsdk` media sessions.
- **Single instance**: PID file + Unix signals on Linux (`SIGUSR1`=toggle, `SIGUSR2`=idle trigger, `SIGURG`=resume). Named mutex + localhost TCP socket on Windows.
- **OLED detection**: EDID parsing from `/sys/class/drm/` with a curated list of known OLED model patterns in `base.py`.

### Configuration

`Config` class in `config.py` uses `configparser`. File location: `~/.config/oled-saver.conf` (Linux) or `%APPDATA%\OLED Saver\` (Windows). Config is loaded at startup and saved after each user change via the tray menu.

### Build & Release

`packaging/build.py` wraps PyInstaller for single-binary builds. The GitHub Actions workflow (`.github/workflows/release.yml`) triggers on version tags (`v*`), builds Linux + Windows binaries, and creates a GitHub Release.
