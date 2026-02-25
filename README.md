# 🛡️ OLED Saver

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![GitHub Release](https://img.shields.io/github/v/release/esleghel/oled-saver)](https://github.com/esleghel/oled-saver/releases)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-lightgrey)

A lightweight system tray app that blanks or dims your OLED screen when you're idle — without interrupting your music, movies, or games. Works on Linux (KDE, GNOME) and Windows.

---

## Why?

OLED burn-in is real and permanent. Static UI elements (taskbar, browser chrome, desktop icons) slowly etch into the panel over time.

The built-in OS options don't really help:

| | Native Screensaver | DPMS / Screen Off | **OLED Saver** |
|---|:---:|:---:|:---:|
| Turns pixels off | ❌ Animations still light pixels | ✅ But... | ✅ |
| Keeps multi-monitor layout | ✅ | ❌ Windows shift around | ✅ |
| Knows which monitor is OLED | ❌ | ❌ Blanks everything | ✅ Auto-detects |
| Skips when watching video | ❌ | ❌ | ✅ |
| Skips when music is playing | ❌ | ❌ | ✅ |
| Works on Wayland | ❌ Most don't | ⚠️ Depends | ✅ |
| Night mode (auto-dim) | ❌ | ❌ | ✅ |

---

## Features

- **Auto-detects OLED monitors** from EDID (LG, Samsung, Gigabyte AORUS, ASUS, Dell/Alienware, etc.)
- **Cross-platform** — KDE Plasma, GNOME, Windows. Wayland-native.
- **Smart exceptions** — won't blank when media is playing (YouTube, Spotify, VLC, games)
- **Night mode** — auto-dims all monitors on a schedule (e.g., 22:00–07:00)
- **Blank or dim** — full black screen or reduced brightness, your choice
- **System tray** — pause, resume, manual blank/dim, monitor selection
- **Configurable timeout** — 30s to 600s
- **Global hotkey** — `Super+B` to toggle pause (Linux)

---

## Download & Install

Grab the latest from [**Releases**](https://github.com/esleghel/oled-saver/releases):

| Platform | Download | How to install |
|----------|----------|----------------|
| 🐧 **Linux** | `oled-saver-linux.zip` | `unzip` → `./install.sh` |
| 🪟 **Windows** | `oled-saver-windows-installer.exe` | Run installer (adds autostart) |
| 🪟 **Windows** (portable) | `oled-saver-windows.zip` | Extract and run `oled-saver.exe` |

<details>
<summary><b>Running from source</b></summary>

Requires Python 3.10+ and PyQt6.

```bash
pip install PyQt6
pip install .
oled-saver
```

On Linux, install `swayidle` for best idle detection:
```bash
sudo apt install swayidle
```
</details>

---

## System Tray Menu

```
⏸ Pause (30 min)          — Temporarily disable
─────────────────
🔲 Blank Now               — Instant OLED protection
🔅 Dim Now                 — Reduce brightness
─────────────────
⏱ Set Timeout...          — 30–600 seconds
⚙ Idle Action             — Blank or dim + brightness %
─────────────────
🌙 Night Mode (22:00) ✓   — Auto-dim on schedule
🌙 Night Settings...       — Configure hours & brightness
─────────────────
🖥 Monitors...             — Select target monitors
─────────────────
❌ Quit
```

---

## Configuration

Config file: `~/.config/oled-saver.conf` (Linux) or `%APPDATA%\OLED Saver\` (Windows)

| Setting | Description | Default |
|---|---|---|
| `timeout_seconds` | Idle time before action | `120` |
| `monitor` | `auto` (EDID) or connector name (`DP-1`) | `auto` |
| `idle_action` | `blank` or `dim` | `blank` |
| `dim_brightness` | Brightness % when dimmed | `10` |
| `check_inhibitors` | Skip when media is playing | `true` |
| `night_mode_enabled` | Auto-dim at night | `true` |
| `night_mode_start` / `_end` | Night schedule | `22:00` / `07:00` |
| `night_mode_brightness` | Night brightness % | `20` |
| `pause_duration_minutes` | Pause duration | `30` |

---

## Advanced

### Supported Platforms

| Platform | Brightness Control | Idle Detection |
|----------|-------------------|----------------|
| **KDE Plasma** | `kscreen-doctor` | `swayidle` / mouse polling |
| **GNOME** | `gdbus` / `xrandr` | `swayidle` / Mutter IdleMonitor |
| **Windows** | Win32 gamma ramp | `GetLastInputInfo` |

### Global Hotkey (Super+B) — Linux

KDE: System Settings → Shortcuts → Custom Shortcuts → Command: `oled-saver-toggle`

Windows: Use AutoHotkey or PowerToys to bind a key (app toggles pause if already running).

### Signals (Linux)

| Signal | Action |
|--------|--------|
| `SIGUSR1` | Toggle pause |
| `SIGUSR2` | Trigger idle action |
| `SIGURG` | Trigger resume |

---

## License

[GPL-3.0](LICENSE)
