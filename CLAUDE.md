# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Windows desktop Pomodoro timer (`countdown_timer.py`, ~500 lines, plain `tkinter`). It runs as a hidden tool window that lives in the system tray and a tiny always-on-top corner widget; there is no package structure, no test suite, and no build step.

## Commands

- **Install deps:** `setup.bat` (or `python -m pip install -r requirements.txt`). All three deps — `pystray`, `Pillow`, `plyer` — are **optional**; the app degrades gracefully without them (see below).
- **Run:** the **Pomodoro Timer** desktop shortcut, `run.bat` (prefers `pythonw` so there's no console window), or `python countdown_timer.py`.
- **Shortcut/icon:** `setup.bat` regenerates `pomodoro.ico` via `make_icon.py` (best effort — a committed `.ico` is the fallback if Pillow is missing) and runs `create_shortcut.ps1` to drop a Desktop `.lnk` targeting the windowed Python + `countdown_timer.py`. `make_icon.py` hardcodes the palette hexes mirrored from `countdown_timer.py` — keep them in sync if the palette changes.
- **No tests/lint exist.** Verify changes by byte-compiling (`python -m py_compile countdown_timer.py`) and by a **headless smoke test**: import the module, construct `PomodoroState()` + `TimerWindow(state)`, call `win.root.update()` (never `mainloop()` — it blocks), mutate `state.phase`/`state.time_remaining`, call `win._refresh_ui()`, inspect widget state via `.cget(...)`, then `win.root.destroy()`. This exercises real UI paths without the blocking event loop. A native window screenshot is not capturable from a headless tool context — to see it live, launch it and drive it manually.

## Platform

**Windows-only.** Hard dependencies on `winsound` (alert beeps), the `-toolwindow` attribute, and a PowerShell `NotifyIcon` fallback for notifications. Do not assume cross-platform.

## Architecture — the parts that span files/threads

**Model/view split.** `PomodoroState` holds all timer logic and is UI-agnostic; `TimerWindow` is the view and registers a tick callback via `state.add_tick_callback(...)`. State never touches tkinter.

**Concurrency is the load-bearing design — read this before editing timing or shutdown:**
- Beyond the Tk `mainloop`, there are up to two daemon threads: the per-run **timer thread** (`PomodoroState._run`) and the **tray icon** thread (`TrayApp.run_detached`). The AutoHotkey toggle is polled on the Tk thread via `root.after`, not a separate thread.
- All `PomodoroState` mutation is guarded by `self._lock`.
- **`_generation` counter:** incremented on every `start()`/phase rollover; each `_run` thread captures its `gen` and exits when it no longer matches. This is what prevents a stale thread surviving a pause+restart and double-counting. Preserve this pattern when touching `_run`/`_on_end`/`start`.
- **Cross-thread → Tk rule:** the only safe way to touch tkinter from a non-Tk thread is `self.root.after(0, fn)`. Every such call (`_schedule_refresh`, `_hotkey_callback`, `_quit`) is wrapped in `try/except Exception` — a destroyed window raises `TclError`, *not* only `RuntimeError`, so do not narrow these excepts.
- **Timing** is anchored to a `time.monotonic()` deadline (not by decrementing per sleep) so sleep overshoot doesn't accumulate drift over a session.
- **Shutdown:** `_quit` (callable from any thread) marshals to `_do_quit` (Tk thread) which stops the tray and calls `root.destroy()`; `mainloop()` then returns and the process exits — daemon threads die with it. There is intentionally **no `sys.exit()`**.

**Three visible surfaces, one source of truth.** The main window, the corner **mini timer** (shown only while the main window is withdrawn), and the **tray icon** all render from `PomodoroState` on each tick via `_refresh_ui`. The app **starts withdrawn**, so the mini timer is the initial visible surface. Visibility transitions (`show`, `_on_close`, `_toggle_visibility`) must keep main-window and mini-timer states opposite.

**Graceful degradation.** `HAS_TRAY` (pystray+Pillow) and `HAS_NOTIFY` (plyer) gate features at import. Notably, with no tray there's nothing to restore to, so `_on_close` **quits** instead of hiding — check `self._tray._icon is not None`, not the import flag. Notifications fall back to a hidden-PowerShell balloon when plyer is absent.

**Phase model.** Phases are integer keys into three parallel dicts: `PHASE_NAMES`, `PHASE_COLOURS`, `PHASE_DURATIONS` (currently `0=FOCUS`, `1=BREAK`; `_advance` alternates). To add/change a phase, update **all three dicts** together — they are looked up by the same key everywhere.

**Accent cohesion.** The active phase colour drives the badge, the progress ring, *and* the primary (Start/Pause) button. `_refresh_ui` re-tints the primary button only when the accent actually changes (not every tick, to avoid fighting hover state); hover/pressed shades are derived with `_shade()`.

**Window sizing.** The main window is **not** a hardcoded box — `_fit_window` measures content (`winfo_reqwidth/height`) plus `MARGIN_X/Y` and `_snap_top_right` places it. Don't reintroduce fixed `geometry()` dimensions.

**Global hotkey is external.** Alt+2 is owned by AutoHotkey (`pomodoro.ahk`), not this process. AHK drops a signal file (`TOGGLE_SIGNAL`, in the temp dir) on the hotkey; the app polls for it on the Tk thread (`_poll_toggle_signal`, every `SIGNAL_POLL_MS`) and runs `_toggle_visibility` itself. This indirection is deliberate: the app must own the toggle so the corner mini timer stays in sync, and the window title changes every tick so AHK can't match it. The app clears a stale signal at startup. If you add more AHK-triggered actions, follow the same drop-a-file / poll-and-consume pattern rather than reintroducing a Win32 message loop.
