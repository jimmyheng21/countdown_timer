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

The **Alt+2 global hotkey** is provided by [AutoHotkey v2](https://www.autohotkey.com/)
via `pomodoro.ahk`. If AutoHotkey is installed, the app **starts the script
automatically on launch and stops it on quit**, so Alt+2 works for as long as
the timer is running — no manual step. Without AutoHotkey installed, Alt+2 is
simply unavailable; everything else (tray, double-click) still works.

## Setup

Double-click **`setup.bat`**. It installs the optional dependencies and creates
a **"Pomodoro Timer" shortcut on your Desktop** (with the app icon). To install
the dependencies only:

```sh
python -m pip install -r requirements.txt
```

## Run

Launch from the **Pomodoro Timer** desktop shortcut, double-click **`run.bat`**
(both launch without a console window), or:

```sh
python countdown_timer.py
```

The app starts **hidden** — look for the mini timer in the top-right corner and
the icon in your system tray.

## Usage

| Action | How |
| --- | --- |
| Open the full window | **Double-click** the corner mini-timer, **Alt+2** (via AutoHotkey), or tray → **Open** |
| Minimise to the corner | **Double-click** the window (any non-button area), Close (✕), or **Alt+2** — it does not quit |
| Start / pause | **Start/Pause** button, or tray → **Start/Pause** |
| Reset the current phase | **Reset** |
| Skip to the next phase | **Skip →** |
| Quit | Tray → **Quit** |

### Alt+2 global hotkey (AutoHotkey)

The window-toggle hotkey is handled by AutoHotkey, not the app itself — but you
don't have to manage it:

1. Install [AutoHotkey v2](https://www.autohotkey.com/) once.
2. Start the timer normally. The app finds AutoHotkey, launches `pomodoro.ahk`,
   and stops it again when you quit — so **Alt+2 is live whenever the timer is**.
3. Press **Alt+2** anywhere to show/hide the window.

`pomodoro.ahk` simply drops a signal file in your temp folder on Alt+2; the
running app polls for it and toggles the window (and its corner mini timer) in
sync. Edit the `!2::` line in the script to rebind the key. You can still run
the script by hand (double-click, or `shell:startup`) if you want Alt+2 without
the app open.

## Files

| File | Purpose |
| --- | --- |
| `countdown_timer.py` | The entire application |
| `pomodoro.ahk` | AutoHotkey script providing the Alt+2 global hotkey |
| `setup.bat` | Installs dependencies and creates the desktop shortcut |
| `run.bat` | Launches the app (prefers `pythonw`) |
| `make_icon.py` | Generates `pomodoro.ico` (run by setup) |
| `create_shortcut.ps1` | Creates the desktop shortcut (run by setup) |
| `pomodoro.ico` | App / shortcut icon |
| `requirements.txt` | `pystray`, `Pillow`, `plyer` |
