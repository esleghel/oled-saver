# OLED Saver

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![GitHub Release](https://img.shields.io/github/v/release/esleghel/oled-saver)](https://github.com/esleghel/oled-saver/releases)

Prevent OLED burn-in by automatically blanking or dimming your monitor after idle timeout. Runs in the system tray with night mode, smart exceptions, and cross-platform support.

## Download

Pre-built binaries on the [Releases](https://github.com/esleghel/oled-saver/releases) page:

| Platform | File | Notes |
|----------|------|-------|
| **Linux** | `oled-saver-linux.zip` | Standalone binary + install script |
| **Windows** | `oled-saver-windows-installer.exe` | Installer with autostart |
| **Windows** | `oled-saver-windows.zip` | Standalone exe (portable) |

### Linux Install

```bash
unzip oled-saver-linux.zip
cd oled-saver-linux
chmod +x install.sh
./install.sh
```

### Windows Install

Run `oled-saver-windows-installer.exe` — it installs the app, creates a Start Menu shortcut, and adds it to autostart.

## Features

- **Auto-detects OLED monitors** from EDID data (Gigabyte AORUS FO, LG OLED, Samsung S95/S90, ASUS, Dell/Alienware, etc.)
- **Wayland-native idle detection** via `swayidle` (with mouse-position polling fallback)
- **Smart exceptions** — won't blank when power management is inhibited (games, video players, presentations)
- **Night mode** — automatically dims all monitors after a configurable hour (default 22:00)
- **System tray icon** — pause/resume, custom timeout, night mode toggle/settings, quit
- **Global hotkey** — `Super+B` to toggle pause

## Supported Platforms

| Platform | Brightness Control | Idle Detection |
|----------|-------------------|----------------|
| **KDE Plasma** | `kscreen-doctor` | `swayidle` / mouse polling |
| **GNOME** | `gdbus` / `xrandr` | `swayidle` / Mutter IdleMonitor / mouse polling |
| **Windows** | Win32 gamma ramp | `GetLastInputInfo` |

## Running from Source

Requires Python 3.10+ and PyQt6.

```bash
pip install PyQt6
python -m oled_saver
```

Or install as a package:
```bash
pip install .
oled-saver
```

On Linux, install `swayidle` for best idle detection:
```bash
sudo apt install swayidle
```

## System Tray Menu

```
⏸ Pause (30 min)          — Temporarily disable idle actions
─────────────────
🔲 Blank Now               — Manually blank OLED screen
🔅 Dim Now                 — Manually dim OLED screen
─────────────────
⏱ Set Timeout (120s)...   — Custom idle timeout (30–600s)
⚙ Idle Action             — Choose blank or dim on idle + set dim %
─────────────────
🌙 Night Mode (22:00) ✓   — Toggle night brightness
🌙 Night Settings...       — Configure start/end time & brightness %
─────────────────
🖥 Monitors...             — Select target monitors
─────────────────
❌ Quit
```

## Configuration

Config file: `~/.config/oled-saver.conf`

```ini
[oled-saver]
timeout_seconds = 120
monitor = auto
check_inhibitors = true
pause_duration_minutes = 30
idle_action = blank
dim_brightness = 10
night_mode_enabled = true
night_mode_start = 22:00
night_mode_end = 07:00
night_mode_brightness = 20
```

| Setting | Description | Default |
|---|---|---|
| `timeout_seconds` | Idle time before blanking OLED | `120` |
| `monitor` | `auto` (EDID detection) or connector name like `DP-1` | `auto` |
| `check_inhibitors` | Skip idle action when media is playing | `true` |
| `pause_duration_minutes` | Duration of manual pause | `30` |
| `idle_action` | Action on idle: `blank` or `dim` | `blank` |
| `dim_brightness` | OLED brightness % when dimmed | `10` |
| `night_mode_enabled` | Enable automatic night dimming | `true` |
| `night_mode_start` | Time to start dimming (HH:MM) | `22:00` |
| `night_mode_end` | Time to restore brightness (HH:MM) | `07:00` |
| `night_mode_brightness` | Brightness % during night hours | `20` |

## Global Hotkey (Super+B)

### Linux (KDE)
System Settings → Shortcuts → Custom Shortcuts → Add → Command/URL:
- Trigger: `Super+B`
- Command: `oled-saver-toggle` (after install) or `~/.local/bin/oled-saver-toggle`

### Windows
The installer does not add a global hotkey. Use AutoHotkey or Windows PowerToys to bind a key to launching the app (it toggles pause if already running).

## Signals (Linux)

- `SIGUSR1` — Toggle pause (used by global hotkey)
- `SIGUSR2` — Trigger idle action (used internally by swayidle)
- `SIGURG` — Trigger resume (used internally by swayidle)

## License

[GPL-3.0](LICENSE)
