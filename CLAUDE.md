# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Windows desktop Pomodoro timer (`countdown_timer.py`, ~550 lines, plain `tkinter`). It runs as a hidden tool window that lives in the system tray and a tiny always-on-top corner widget; there is no package structure, no test suite, and no build step.

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
- **Cross-thread → Tk rule:** the only safe way to touch tkinter from a non-Tk thread is `self.root.after(0, fn)`. The cross-thread callers — `_schedule_refresh` (from the timer thread via `_notify`) and `_quit` (from the tray thread) — wrap it in `try/except Exception` because a destroyed window raises `TclError`, *not* only `RuntimeError`; do not narrow these excepts. (`_poll_toggle_signal` already runs on the Tk thread, so it toggles directly.)
- **Timing** is anchored to a `time.monotonic()` deadline (not by decrementing per sleep) so sleep overshoot doesn't accumulate drift over a session.
- **Shutdown:** `_quit` (callable from any thread) marshals to `_do_quit` (Tk thread) which stops the tray and calls `root.destroy()`; `mainloop()` then returns and the process exits — daemon threads die with it. There is intentionally **no `sys.exit()`**.

**Three visible surfaces, one source of truth.** The main window, the corner **mini timer** (shown only while the main window is withdrawn), and the **tray icon** all render from `PomodoroState` on each tick via `_refresh_ui`. The app **starts withdrawn**, so the mini timer is the initial visible surface. Visibility transitions (`show`, `_on_close`, `_toggle_visibility`) must keep main-window and mini-timer states opposite. Both double-click gestures — on the mini (open) and on the window's non-button widgets (minimise), bound via `_bind_double_toggle` — route through the single `_toggle_visibility`, which picks the direction from `root.state()`; don't add direction-specific handlers.

**Graceful degradation.** `HAS_TRAY` (pystray+Pillow) and `HAS_NOTIFY` (plyer) gate features at import. Notably, with no tray there's nothing to restore to, so `_on_close` **quits** instead of hiding — check `self._tray._icon is not None`, not the import flag. Notifications fall back to a hidden-PowerShell balloon when plyer is absent.

**State mutators all `_notify()`.** `start`, `pause`, `reset`, and `skip` each call `_notify()` so every surface refreshes immediately regardless of which thread/UI triggered them (window button *or* tray menu). Don't reintroduce a direct `_refresh_ui()` in the window button handler — that was removed once these notified, and it would double-refresh. A new mutator must `_notify()` too, or the tray path will show stale state.

**Single instance.** `_acquire_single_instance()` (named Win32 mutex, `CreateMutexW`) guards `__main__`; a second launch shows an "already running" `MessageBoxW` and the script just ends (no `sys.exit`). This prevents two instances from both consuming the one `TOGGLE_SIGNAL` and desyncing. The mutex handle is held in a module global for the process lifetime; the OS frees it on exit. On any failure the guard returns `True` (never blocks startup).

**Phase model.** Phases are integer keys into three parallel dicts: `PHASE_NAMES`, `PHASE_COLOURS`, `PHASE_DURATIONS` (currently `0=FOCUS`, `1=BREAK`; `_advance` alternates). To add/change a phase, update **all three dicts** together — they are looked up by the same key everywhere.

**Accent cohesion.** The active phase colour drives the badge, the progress ring, *and* the primary (Start/Pause) button. `_refresh_ui` re-tints the primary button only when the accent actually changes (not every tick, to avoid fighting hover state); hover/pressed shades are derived with `_shade()`.

**Window sizing.** The main window is **not** a hardcoded box — `_fit_window` measures content (`winfo_reqwidth/height`) plus `MARGIN_X/Y` and `_snap_top_right` places it. Don't reintroduce fixed `geometry()` dimensions.

**Global hotkey is external but app-managed.** Alt+2 is owned by AutoHotkey (`pomodoro.ahk`), not this process. `run()` launches the script via `_start_hotkey_helper` (which locates the interpreter with `_find_autohotkey` — PATH then the usual v2/v1 install dirs) and `_do_quit` calls `terminate()` on that one `Popen` handle (`self._ahk`), so Alt+2 is live for exactly the app's lifetime and *only the app's own* AHK instance is killed — never another script. If AutoHotkey isn't installed, the helper returns `None` and the feature is silently absent (tray + double-click still work). AHK drops a signal file (`TOGGLE_SIGNAL`, temp dir) on the hotkey; the app polls for it on the Tk thread (`_poll_toggle_signal`, every `SIGNAL_POLL_MS`) and runs `_toggle_visibility` itself. This indirection is deliberate: the app must own the toggle so the corner mini timer stays in sync, and the window title changes every tick so AHK can't match it. The app clears a stale signal at startup. The launch is in `run()`, not `__init__`, to keep construction side-effect-free for the headless smoke test. If you add more AHK-triggered actions, follow the same drop-a-file / poll-and-consume pattern rather than reintroducing a Win32 message loop.
