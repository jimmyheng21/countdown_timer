import tkinter as tk
import threading
import time
import os
import shutil
import subprocess
import tempfile
import winsound
import ctypes

try:
    from PIL import Image, ImageDraw
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from plyer import notification as plyer_notify
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

# ── Durations (seconds) ────────────────────────────────────────────────────────
FOCUS_DURATION = 25 * 60
BREAK_DURATION = 5  * 60

# ── Warm beige palette ─────────────────────────────────────────────────────────
BG         = "#FFF3E8"   # lightest cream
RING_BG    = "#EDD8C3"   # soft peach
SAND       = "#DDD3AF"   # warm sand

FOCUS_CLR  = "#CCA882"   # caramel  – focus ring
BREAK_CLR  = "#C8B098"   # mid-warm – break ring

TEXT_CLR   = "#5C3D2E"   # dark warm brown
MUTED_CLR  = "#B09070"   # medium warm brown

PHASE_NAMES     = {0: "FOCUS", 1: "BREAK"}
PHASE_COLOURS   = {0: FOCUS_CLR, 1: BREAK_CLR}
PHASE_DURATIONS = {0: FOCUS_DURATION, 1: BREAK_DURATION}

# ── Single instance ───────────────────────────────────────────────────────────
# Two instances would both poll/consume the one TOGGLE_SIGNAL file and fight
# over window visibility, desyncing the mini timer. Guard with a named mutex
# (Windows): the second instance sees ERROR_ALREADY_EXISTS. The handle is kept
# alive for the process lifetime via a module global; the OS frees it on exit.
_single_instance_handle = None

def _acquire_single_instance():
    # Returns True if this is the only instance, False if one is already running.
    # On any unexpected failure, returns True so the app never refuses to start.
    global _single_instance_handle
    ERROR_ALREADY_EXISTS = 183
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype  = ctypes.c_void_p
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        handle = k32.CreateMutexW(None, 0, "PomodoroTimer_SingleInstance")
        err = ctypes.get_last_error()
    except Exception:
        return True
    if not handle:
        return True
    if err == ERROR_ALREADY_EXISTS:
        return False
    _single_instance_handle = handle
    return True

# ── Global hotkey bridge ──────────────────────────────────────────────────────
# The global hotkey lives in AutoHotkey (see pomodoro.ahk), not in this process.
# AHK drops this signal file on the hotkey; the app polls for it and toggles the
# window itself, so app-managed state (the corner mini timer) stays correct.
# The app launches the script on start and terminates it on quit (see run /
# _do_quit), so Alt+2 is live exactly while the timer is — no manual step.
TOGGLE_SIGNAL = os.path.join(tempfile.gettempdir(), "pomodoro_toggle.signal")
AHK_SCRIPT    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "pomodoro.ahk")

def _find_autohotkey():
    # Locate the AutoHotkey interpreter: PATH first, then the usual v2/v1
    # install dirs. Returns the exe path, or None if AutoHotkey isn't installed.
    for name in ("AutoHotkey64", "AutoHotkey32", "AutoHotkey", "AutoHotkeyU64"):
        found = shutil.which(name)
        if found:
            return found
    rels = (
        r"Programs\AutoHotkey\v2\AutoHotkey64.exe",
        r"Programs\AutoHotkey\v2\AutoHotkey32.exe",
        r"AutoHotkey\v2\AutoHotkey64.exe",
        r"AutoHotkey\v2\AutoHotkey32.exe",
        r"AutoHotkey\v2\AutoHotkey.exe",
        r"AutoHotkey\AutoHotkey.exe",
    )
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("PROGRAMFILES"),
                 os.environ.get("PROGRAMFILES(X86)")):
        if not base:
            continue
        for rel in rels:
            p = os.path.join(base, rel)
            if os.path.isfile(p):
                return p
    return None

def _start_hotkey_helper():
    # Launch pomodoro.ahk so Alt+2 works for the app's lifetime. Best effort:
    # returns the Popen handle to terminate on quit, or None if AutoHotkey or
    # the script is missing (the tray icon and double-click still work).
    exe = _find_autohotkey()
    if not exe or not os.path.isfile(AHK_SCRIPT):
        return None
    try:
        return subprocess.Popen([exe, AHK_SCRIPT])
    except OSError:
        return None

# ── Pomodoro state ─────────────────────────────────────────────────────────────
class PomodoroState:
    def __init__(self):
        self.phase            = 0
        self.time_remaining   = FOCUS_DURATION
        self.is_running       = False
        self._lock            = threading.Lock()
        self._tick_callbacks  = []
        # Incremented on every start; each _run thread captures its own value
        # and exits when the value no longer matches, preventing stale threads
        # from surviving a pause+restart cycle.
        self._generation      = 0

    def add_tick_callback(self, cb):
        self._tick_callbacks.append(cb)

    def _notify(self):
        for cb in self._tick_callbacks:
            try:
                cb()
            except Exception:
                pass

    def start(self):
        with self._lock:
            if self.is_running:
                return
            # If a phase ended and the user paused during the alert, advance
            # now so pressing Start doesn't immediately re-trigger _on_end.
            if self.time_remaining <= 0:
                self._advance()
            self.is_running = True
            self._generation += 1
            gen = self._generation
        threading.Thread(target=self._run, args=(gen,), daemon=True).start()
        self._notify()   # immediate UI feedback regardless of caller (tray/window)

    def pause(self):
        with self._lock:
            self.is_running = False
        self._notify()   # immediate UI feedback regardless of caller (tray/window)

    def reset(self):
        with self._lock:
            self.is_running = False
            self.time_remaining = PHASE_DURATIONS[self.phase]
        self._notify()

    def skip(self):
        with self._lock:
            self.is_running = False
            self._advance()
        self._notify()

    def _advance(self):
        # Simple two-phase cycle: focus ↔ break.
        self.phase = 1 if self.phase == 0 else 0
        self.time_remaining = PHASE_DURATIONS[self.phase]

    def _run(self, gen):
        # Anchor to wall-clock time so individual sleep overshoots don't
        # accumulate into drift over a full 25-minute session.
        with self._lock:
            remaining = self.time_remaining
        deadline = time.monotonic() + remaining
        while True:
            time.sleep(1)
            with self._lock:
                if not self.is_running or self._generation != gen:
                    return
                self.time_remaining = max(0, round(deadline - time.monotonic()))
                done = self.time_remaining <= 0
            self._notify()
            if done:
                self._on_end(gen)
                return

    def _on_end(self, gen):
        _play_alert()
        with self._lock:
            if not self.is_running or self._generation != gen:
                # User paused/reset/skipped during the alert window — honour it.
                self._notify()
                return
            self._advance()
            self._generation += 1
            new_gen = self._generation
            # is_running stays True — the next _run thread starts immediately.
        _send_notification(self.phase)
        self._notify()
        threading.Thread(target=self._run, args=(new_gen,), daemon=True).start()


# ── Helpers ────────────────────────────────────────────────────────────────────
def _play_alert():
    try:
        for _ in range(3):
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            time.sleep(0.35)
    except Exception:
        pass

def _send_notification(next_phase):
    title = "Pomodoro Timer"
    msg   = f"Time for {PHASE_NAMES[next_phase].title()}!"
    if HAS_NOTIFY:
        try:
            plyer_notify.notify(title=title, message=msg,
                                app_name="Pomodoro Timer", timeout=6)
            return
        except Exception:
            pass
    try:
        import subprocess
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            "$n.Visible=$true;"
            f"$n.ShowBalloonTip(5000,'{title}','{msg}',[System.Windows.Forms.ToolTipIcon]::Info);"
            "Start-Sleep 6;$n.Dispose()"
        )
        subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", ps])
    except Exception:
        pass

def fmt_time(secs):
    return f"{secs // 60:02d}:{secs % 60:02d}"

def _shade(hex_clr, f):
    # Multiply each RGB channel by f (<1 darkens) — used to derive hover/pressed
    # states from the live phase accent so the whole palette shifts together.
    h = hex_clr.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r, g, b = (max(0, min(255, round(c * f))) for c in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


# ── Tray icon ──────────────────────────────────────────────────────────────────
def _make_tray_icon(phase):
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    col  = PHASE_COLOURS[phase].lstrip("#")
    r, g, b = int(col[0:2],16), int(col[2:4],16), int(col[4:6],16)
    draw.ellipse([4, 4, size-4, size-4], fill=(r, g, b, 255))
    return img

class TrayApp:
    def __init__(self, state, show_cb, quit_cb):
        self._state      = state
        self._show       = show_cb
        self._quit       = quit_cb
        self._icon       = None
        self._icon_cache = {}   # phase → PIL Image; built once, reused every tick
        if HAS_TRAY:
            self._build()

    def _get_icon(self, phase):
        if phase not in self._icon_cache:
            self._icon_cache[phase] = _make_tray_icon(phase)
        return self._icon_cache[phase]

    def _build(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open", lambda: self._show(), default=True),
            pystray.MenuItem("Start/Pause", lambda: self._toggle()),
            pystray.MenuItem("Reset",       lambda: self._state.reset()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit",        lambda: self._quit()),
        )
        self._icon = pystray.Icon(
            "pomodoro", self._get_icon(self._state.phase),
            "Pomodoro Timer", menu
        )

    def _toggle(self):
        if self._state.is_running:
            self._state.pause()
        else:
            self._state.start()

    def run_detached(self):
        if self._icon:
            threading.Thread(target=self._icon.run, daemon=True).start()

    def update(self, phase, time_remaining):
        if self._icon:
            self._icon.icon  = self._get_icon(phase)
            self._icon.title = f"{PHASE_NAMES[phase]} – {fmt_time(time_remaining)}"

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass


# ── Main window ────────────────────────────────────────────────────────────────
class TimerWindow:
    RING_SIZE    = 240
    RING_W       = 16   # progress arc — slightly heavier than the track
    RING_TRACK_W = 8    # unfilled rail behind it
    MARGIN_X     = 16   # symmetric horizontal padding around content
    MARGIN_Y     = 8    # breathing room below the content
    SIGNAL_POLL_MS = 250  # how often to check for AutoHotkey's toggle signal

    def __init__(self, state: PomodoroState):
        self._state = state
        self._tray  = None
        self._ahk   = None   # Popen handle for pomodoro.ahk (started in run())
        self._mini  = None   # tiny corner timer, shown while main window hidden
        self._w     = 320    # placeholder; recomputed from content in _fit_window
        self._h     = 484
        # Live accent (phase colour) + derived hover shade; drives the primary
        # button so badge, ring and button always share one colour.
        self._accent       = FOCUS_CLR
        self._accent_hover = _shade(FOCUS_CLR, 0.90)

        self.root = tk.Tk()
        self.root.title("Pomodoro Timer")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Keep out of taskbar; accessible via the tray icon or the AutoHotkey hotkey
        self.root.wm_attributes("-toolwindow", True)

        self._build_ui()
        self._build_mini()
        self._fit_window()    # size to content, then place top-right
        self.root.withdraw()  # start hidden — must precede mainloop()

        state.add_tick_callback(self._schedule_refresh)
        # Discard any stale signal from a previous run, then watch for AutoHotkey.
        self._consume_toggle_signal()
        self.root.after(self.SIGNAL_POLL_MS, self._poll_toggle_signal)
        # Window starts hidden, so the corner timer is the visible surface.
        self._show_mini()

    @staticmethod
    def _consume_toggle_signal():
        # Atomically consume the signal. Returns True iff the file existed and
        # was removed by this call — so a transient lock (AHK mid-write) reports
        # False and is retried next poll rather than toggling without consuming.
        try:
            os.remove(TOGGLE_SIGNAL)
            return True
        except OSError:
            return False  # absent (normal) or briefly locked (retry next poll)

    def _poll_toggle_signal(self):
        # Runs on the Tk thread, so it can toggle directly. AutoHotkey drops
        # TOGGLE_SIGNAL on the hotkey; toggle only when we actually consumed it.
        if self._consume_toggle_signal():
            self._toggle_visibility()
        self.root.after(self.SIGNAL_POLL_MS, self._poll_toggle_signal)

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root

        # Quiet brand eyebrow — letter-spaced caps, deliberately recessive so the
        # time stays the hero. Not bold: it labels, it doesn't announce.
        eyebrow = tk.Label(r, text="P O M O D O R O", bg=BG, fg=MUTED_CLR,
                           font=("Segoe UI", 9))
        eyebrow.pack(pady=(16, 2))

        # Phase badge — carries the live accent (FOCUS_CLR / BREAK_CLR).
        self._lbl_phase = tk.Label(r, text="FOCUS", bg=BG, fg=FOCUS_CLR,
                                   font=("Segoe UI", 11, "bold"))
        self._lbl_phase.pack()

        # Ring canvas — thin track with a heavier progress arc over it.
        cs = self.RING_SIZE + 20
        self._canvas = tk.Canvas(r, width=cs, height=cs, bg=BG,
                                  highlightthickness=0)
        self._canvas.pack(pady=(6, 10))

        cx = cy = cs // 2
        rv = self.RING_SIZE // 2

        self._ring_bg_id = self._canvas.create_arc(
            cx-rv, cy-rv, cx+rv, cy+rv,
            start=90, extent=359.9, style=tk.ARC,
            outline=RING_BG, width=self.RING_TRACK_W
        )
        self._ring_id = self._canvas.create_arc(
            cx-rv, cy-rv, cx+rv, cy+rv,
            start=90, extent=0, style=tk.ARC,
            outline=FOCUS_CLR, width=self.RING_W
        )
        self._lbl_time = self._canvas.create_text(
            cx, cy, text="25:00",
            font=("Segoe UI", 48, "bold"), fill=TEXT_CLR
        )

        # Buttons — one primary action (Start/Pause) filled with the accent,
        # two quiet ghost actions beside it.
        btn_row = tk.Frame(r, bg=BG)
        btn_row.pack(pady=(2, 4))
        self._btn_start = self._btn(btn_row, "Start",  self._toggle_start, primary=True)
        self._btn_reset = self._btn(btn_row, "Reset",  lambda: self._state.reset())
        self._btn_skip  = self._btn(btn_row, "Skip →", lambda: self._state.skip())
        self._btn_start.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_reset.pack(side=tk.LEFT, padx=6)
        self._btn_skip.pack(side=tk.LEFT, padx=(6, 0))

        # Hint
        hint = tk.Label(r, text="Alt+2 or double-click  ·  show / minimise",
                        bg=BG, fg=MUTED_CLR, font=("Segoe UI", 8))
        hint.pack(pady=(10, 14))

        # Double-click any non-button surface to minimise back to the corner.
        # Bind the individual non-button widgets, NOT root: binding root would
        # also catch double-clicks on the buttons (root is in their bindtags)
        # and minimise unexpectedly. Each widget here fires the toggle once.
        self._bind_double_toggle(eyebrow, self._lbl_phase, self._canvas, hint)

        self._refresh_ui()

    def _bind_double_toggle(self, *widgets):
        for w in widgets:
            w.bind("<Double-Button-1>", lambda e: self._toggle_visibility())

    def _btn(self, parent, text, cmd, primary=False):
        if primary:
            b = tk.Button(
                parent, text=text, command=cmd,
                bg=self._accent, fg=BG,
                activebackground=_shade(self._accent, 0.82), activeforeground=BG,
                relief=tk.FLAT, font=("Segoe UI", 10, "bold"),
                width=9, cursor="hand2", borderwidth=0, highlightthickness=0,
                padx=10, pady=8
            )
            b.bind("<Enter>", lambda e: b.configure(bg=self._accent_hover))
            b.bind("<Leave>", lambda e: b.configure(bg=self._accent))
        else:
            b = tk.Button(
                parent, text=text, command=cmd,
                bg=BG, fg=TEXT_CLR,
                activebackground=SAND, activeforeground=TEXT_CLR,
                relief=tk.FLAT, font=("Segoe UI", 10),
                width=7, cursor="hand2", borderwidth=0, highlightthickness=0,
                padx=8, pady=8
            )
            b.bind("<Enter>", lambda e: b.configure(bg=RING_BG))
            b.bind("<Leave>", lambda e: b.configure(bg=BG))
        return b

    # ── Handlers ───────────────────────────────────────────────────────────────
    def _toggle_start(self):
        # start()/pause() now _notify(), so the refresh happens via the tick
        # callback — no direct _refresh_ui() needed (and the tray path gets it too).
        if self._state.is_running:
            self._state.pause()
        else:
            self._state.start()

    def _schedule_refresh(self):
        try:
            self.root.after(0, self._refresh_ui)
        except Exception:
            pass

    def _refresh_ui(self):
        s     = self._state
        t     = s.time_remaining
        ph    = s.phase
        clr   = PHASE_COLOURS[ph]
        total = PHASE_DURATIONS[ph]

        frac   = t / total if total else 0
        extent = frac * 359.9
        self._canvas.itemconfigure(self._ring_id, extent=extent, outline=clr)
        self._canvas.itemconfigure(self._lbl_time, text=fmt_time(t))

        self._lbl_phase.configure(text=PHASE_NAMES[ph], fg=clr)

        # Re-tint the primary button only when the phase accent actually changes,
        # so it doesn't fight the hover state on every one-second tick.
        if clr != self._accent:
            self._accent       = clr
            self._accent_hover = _shade(clr, 0.90)
            self._btn_start.configure(bg=clr, activebackground=_shade(clr, 0.82))

        status = "▶" if s.is_running else "⏸"
        self.root.title(f"{status} {fmt_time(t)} · {PHASE_NAMES[ph]}")

        self._btn_start.configure(text="Pause" if s.is_running else "Start")

        self._update_mini()

        if self._tray:
            self._tray.update(ph, t)

    # ── Mini corner timer ───────────────────────────────────────────────────────
    MINI_RING = 17   # outer radius of the tiny ring
    MINI_W    = 4    # ring stroke width
    MINI_X    = 12   # gap from the right screen edge
    MINI_Y    = 50   # gap from the top — below maximised windows' title-bar buttons

    def _build_mini(self):
        # Borderless, always-on-top pill that "pops out" in the top-right corner
        # while the main window is hidden. Display-only — no click handlers.
        m = tk.Toplevel(self.root)
        m.overrideredirect(True)            # no title bar / no taskbar entry
        m.wm_attributes("-topmost", True)
        m.configure(bg=FOCUS_CLR)           # outer bg shows as a thin coloured edge
        inner = tk.Frame(m, bg=BG)
        inner.pack(padx=2, pady=2)

        d = 2 * self.MINI_RING
        self._mini_canvas = tk.Canvas(inner, width=d, height=d, bg=BG,
                                      highlightthickness=0)
        self._mini_canvas.pack(side=tk.LEFT, padx=(7, 3), pady=5)
        r = self.MINI_RING - self.MINI_W
        c = self.MINI_RING
        self._mini_canvas.create_arc(c-r, c-r, c+r, c+r, start=90, extent=359.9,
                                     style=tk.ARC, outline=RING_BG, width=self.MINI_W)
        self._mini_ring = self._mini_canvas.create_arc(
            c-r, c-r, c+r, c+r, start=90, extent=0, style=tk.ARC,
            outline=FOCUS_CLR, width=self.MINI_W)

        self._mini_time = tk.Label(inner, text=fmt_time(self._state.time_remaining),
                                   bg=BG, fg=TEXT_CLR, font=("Segoe UI", 14, "bold"))
        self._mini_time.pack(side=tk.LEFT, padx=(2, 9))

        self._mini = m
        # Double-click anywhere on the mini opens the full window (the same
        # toggle the window's double-click / Close uses, in reverse). Bind the
        # toplevel ONLY: child clicks reach it via bindtags, and binding the
        # children too would fire the toggle twice (leaf + toplevel) per click.
        m.configure(cursor="hand2")
        self._bind_double_toggle(m)
        m.withdraw()

    def _position_mini(self):
        self._mini.update_idletasks()
        w  = self._mini.winfo_width()
        sw = self._mini.winfo_screenwidth()
        self._mini.geometry(f"+{sw - w - self.MINI_X}+{self.MINI_Y}")

    def _update_mini(self):
        if self._mini is None:
            return
        s     = self._state
        ph    = s.phase
        clr   = PHASE_COLOURS[ph]
        total = PHASE_DURATIONS[ph]
        frac  = s.time_remaining / total if total else 0
        self._mini_canvas.itemconfigure(self._mini_ring, extent=frac * 359.9,
                                        outline=clr)
        self._mini_time.configure(text=fmt_time(s.time_remaining))
        self._mini.configure(bg=clr)

    def _show_mini(self):
        if self._mini is None:
            return
        self._update_mini()
        self._mini.deiconify()
        self._position_mini()
        self._mini.lift()

    def _hide_mini(self):
        if self._mini is not None:
            self._mini.withdraw()

    # ── Window management ──────────────────────────────────────────────────────
    def _on_close(self):
        # Check the actual runtime instance, not the import-time flag — the
        # tray icon could fail to appear even when pystray imports cleanly.
        if self._tray is not None and self._tray._icon is not None:
            self.root.withdraw()
            self._show_mini()
        else:
            self._do_quit()

    def _fit_window(self):
        # Right-size to the content instead of a hardcoded box, so the window
        # hugs the ring (~288px wide) rather than leaving dead side margins.
        self.root.update_idletasks()
        self._w = self.root.winfo_reqwidth()  + 2 * self.MARGIN_X
        self._h = self.root.winfo_reqheight() + self.MARGIN_Y
        self._snap_top_right()

    def _snap_top_right(self):
        sw = self.root.winfo_screenwidth()
        x  = max(0, sw - self._w - 10)
        y  = 10
        self.root.geometry(f"{self._w}x{self._h}+{x}+{y}")

    def show(self):
        self._hide_mini()
        self._snap_top_right()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _toggle_visibility(self):
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.root.withdraw()
            self._show_mini()

    def _request_show(self):
        # Called from the tray thread. Tcl is not thread-safe, so marshal to the
        # Tk thread (mirrors _quit) instead of running show() off-thread.
        try:
            self.root.after(0, self.show)
        except Exception:
            pass

    def _quit(self):
        # Called from any thread (tray menu, hotkey). Marshals to the main
        # thread so root.destroy() runs in the correct tkinter context.
        try:
            self.root.after(0, self._do_quit)
        except Exception:
            pass

    def _do_quit(self):
        # Must run on the main thread. After root.destroy(), mainloop() returns
        # and the process exits naturally — daemon threads are killed then.
        if self._ahk is not None:
            try:
                self._ahk.terminate()   # stop only the AHK script we launched
            except Exception:
                pass
        if self._tray:
            self._tray.stop()
        self.root.destroy()

    def run(self):
        self._ahk  = _start_hotkey_helper()   # Alt+2 lives for the app's lifetime
        self._tray = TrayApp(self._state, self._request_show, self._quit)
        self._tray.run_detached()
        self._refresh_ui()
        self.root.mainloop()


# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if _acquire_single_instance():
        state  = PomodoroState()
        window = TimerWindow(state)
        window.run()
    else:
        # Already running — tell the user and exit (no sys.exit; the script just
        # ends and the process closes). Avoids two instances fighting the signal.
        ctypes.windll.user32.MessageBoxW(
            None, "Pomodoro Timer is already running.",
            "Pomodoro Timer", 0x40)  # MB_ICONINFORMATION
