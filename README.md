# Pomodoro Timer

A small, calm Pomodoro timer for Windows. It runs out of the way — hidden from
the taskbar, reachable from the system tray, and showing a tiny always-on-top
ring in the top-right corner while the main window is closed.

A simple **25-minute focus → 5-minute break** cycle, repeated.

## Features

- **Focus / break cycle** — 25 min focus, 5 min break, alternating automatically.
- **Corner mini timer** — a tiny progress ring + countdown pops into the
  top-right corner whenever the main window is hidden, so the time is always a
  glance away.
- **System tray** — start/pause, reset, open, and quit from the tray icon.
- **Global hotkey** — press **Alt+2** anywhere to show or hide the window
  (provided by AutoHotkey — see below).
- **Sound + desktop notification** at the end of each phase.
- **Warm, distraction-free design** — one accent colour flows through the phase
  badge, the progress ring, and the primary button.

## Requirements

- Windows
- Python 3.x ([python.org](https://www.python.org/downloads/) — tick *Add Python
  to PATH* during install)

The three Python dependencies (`pystray`, `Pillow`, `plyer`) are **optional**:
without them the timer still runs, but the tray icon and/or rich notifications
are reduced. Closing the window quits the app when the tray isn't available.

The **Alt+2 global hotkey** is optional too and is provided by
[AutoHotkey v2](https://www.autohotkey.com/) via `pomodoro.ahk` — the app works
without it (use the tray icon instead).

## Setup

Double-click **`setup.bat`** (installs the optional dependencies), or:

```sh
python -m pip install -r requirements.txt
```

## Run

Double-click **`run.bat`** (launches without a console window), or:

```sh
python countdown_timer.py
```

The app starts **hidden** — look for the mini timer in the top-right corner and
the icon in your system tray.

## Usage

| Action | How |
| --- | --- |
| Show / hide the window | **Alt+2** (via AutoHotkey), or tray → **Open** |
| Start / pause | **Start/Pause** button, or tray → **Start/Pause** |
| Reset the current phase | **Reset** |
| Skip to the next phase | **Skip →** |
| Hide to the corner | Close the window (✕) — it does not quit |
| Quit | Tray → **Quit** |

### Alt+2 global hotkey (AutoHotkey)

The window-toggle hotkey is handled by AutoHotkey, not the app itself:

1. Install [AutoHotkey v2](https://www.autohotkey.com/).
2. Double-click **`pomodoro.ahk`** (or drop a shortcut to it in `shell:startup`
   to run it at login).
3. With the timer running, press **Alt+2** anywhere to show/hide it.

`pomodoro.ahk` simply drops a signal file in your temp folder on Alt+2; the
running app polls for it and toggles the window (and its corner mini timer) in
sync. Edit the `!2::` line in the script to rebind the key.

## Files

| File | Purpose |
| --- | --- |
| `countdown_timer.py` | The entire application |
| `pomodoro.ahk` | AutoHotkey script providing the Alt+2 global hotkey |
| `setup.bat` | Installs optional dependencies |
| `run.bat` | Launches the app (prefers `pythonw`) |
| `requirements.txt` | `pystray`, `Pillow`, `plyer` |
