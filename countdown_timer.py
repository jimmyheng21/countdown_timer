import tkinter as tk
import threading
import time
import winsound
import ctypes
from ctypes import wintypes

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

# ── Global hotkey (Alt+2) via Win32 message-only window ───────────────────────
WM_HOTKEY  = 0x0312
MOD_ALT    = 0x0001
VK_2       = 0x32
HOTKEY_ID  = 1

def _start_hotkey_listener(callback):
    def _listener():
        hwnd = ctypes.windll.user32.CreateWindowExW(
            0, "STATIC", None, 0, 0, 0, 0, 0,
            wintypes.HWND(-3),  # HWND_MESSAGE
            None, None, None
        )
        if not ctypes.windll.user32.RegisterHotKey(hwnd, HOTKEY_ID, MOD_ALT, VK_2):
            ctypes.windll.user32.MessageBoxW(
                None,
                "Alt+2 is already registered by another app.\nThe hotkey will not work.",
                "Pomodoro Timer",
                0x30,  # MB_ICONWARNING
            )
        msg = wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), hwnd, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                callback()
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

    t = threading.Thread(target=_listener, daemon=True)
    t.start()

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

    def pause(self):
        with self._lock:
            self.is_running = False

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

    def __init__(self, state: PomodoroState):
        self._state = state
        self._tray  = None
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
        # Keep out of taskbar; accessible only via tray icon or Alt+2
        self.root.wm_attributes("-toolwindow", True)

        self._build_ui()
        self._build_mini()
        self._fit_window()    # size to content, then place top-right
        self.root.withdraw()  # start hidden — must precede mainloop()

        state.add_tick_callback(self._schedule_refresh)
        _start_hotkey_listener(self._hotkey_callback)
        # Window starts hidden, so the corner timer is the visible surface.
        self._show_mini()

    def _hotkey_callback(self):
        # Called from the Win32 hotkey listener thread — root.after is the only
        # safe cross-thread tkinter call, and it raises TclError/RuntimeError
        # if the window has already been destroyed.
        try:
            self.root.after(0, self._toggle_visibility)
        except Exception:
            pass

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root

        # Quiet brand eyebrow — letter-spaced caps, deliberately recessive so the
        # time stays the hero. Not bold: it labels, it doesn't announce.
        tk.Label(r, text="P O M O D O R O", bg=BG, fg=MUTED_CLR,
                 font=("Segoe UI", 9)).pack(pady=(16, 2))

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

        # Hotkey hint
        tk.Label(r, text="Alt+2  open / show", bg=BG, fg=MUTED_CLR,
                 font=("Segoe UI", 8)).pack(pady=(10, 14))

        self._refresh_ui()

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
        if self._state.is_running:
            self._state.pause()
        else:
            self._state.start()
        self._refresh_ui()

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
        m.withdraw()

    def _position_mini(self):
        self._mini.update_idletasks()
        w  = self._mini.winfo_width()
        sw = self._mini.winfo_screenwidth()
        self._mini.geometry(f"+{sw - w - 12}+12")

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
        if self._tray:
            self._tray.stop()
        self.root.destroy()

    def run(self):
        self._tray = TrayApp(self._state, self.show, self._quit)
        self._tray.run_detached()
        self._refresh_ui()
        self.root.mainloop()


# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    state  = PomodoroState()
    window = TimerWindow(state)
    window.run()
