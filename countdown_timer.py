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
FOCUS_DURATION       = 25 * 60
SHORT_BREAK          = 5  * 60
LONG_BREAK           = 15 * 60
SESSIONS_BEFORE_LONG = 4

# ── Warm beige palette ─────────────────────────────────────────────────────────
BG         = "#FFF3E8"   # lightest cream
RING_BG    = "#EDD8C3"   # soft peach
SAND       = "#DDD3AF"   # warm sand

FOCUS_CLR  = "#CCA882"   # caramel  – focus ring
SHORT_CLR  = "#C8B098"   # mid-warm – short break ring
LONG_CLR   = "#B8A888"   # muted sand – long break ring

TEXT_CLR   = "#5C3D2E"   # dark warm brown
MUTED_CLR  = "#B09070"   # medium warm brown

BTN_BG     = "#EDD8C3"
BTN_HOVER  = "#DDD3AF"
BTN_ACTIVE = "#CCC3A0"

PHASE_NAMES     = {0: "FOCUS", 1: "SHORT BREAK", 2: "LONG BREAK"}
PHASE_COLOURS   = {0: FOCUS_CLR, 1: SHORT_CLR,   2: LONG_CLR}
PHASE_DURATIONS = {0: FOCUS_DURATION, 1: SHORT_BREAK, 2: LONG_BREAK}

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
        self.session_count    = 0
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
        if self.phase == 0:
            self.session_count += 1
            self.phase = 2 if self.session_count % SESSIONS_BEFORE_LONG == 0 else 1
        else:
            self.phase = 0
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
    RING_SIZE = 240
    RING_W    = 14

    def __init__(self, state: PomodoroState):
        self._state = state
        self._tray  = None

        self.root = tk.Tk()
        self.root.title("Pomodoro Timer")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("400x500")
        self.root.update_idletasks()
        self._snap_top_right()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Keep out of taskbar; accessible only via tray icon or Alt+2
        self.root.wm_attributes("-toolwindow", True)
        self.root.withdraw()  # start hidden

        self._build_ui()
        state.add_tick_callback(self._schedule_refresh)
        _start_hotkey_listener(self._hotkey_callback)

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

        # App title
        tk.Label(r, text="POMODORO  TIMER", bg=BG, fg=MUTED_CLR,
                 font=("Segoe UI", 10, "bold"), pady=14).pack()

        # Phase badge — use FOCUS_CLR directly so it stays in sync with
        # PHASE_COLOURS[0]; a separate CARAMEL alias would diverge silently.
        self._lbl_phase = tk.Label(r, text="FOCUS", bg=BG, fg=FOCUS_CLR,
                                   font=("Segoe UI", 12, "bold"))
        self._lbl_phase.pack()

        # Ring canvas
        cs = self.RING_SIZE + 20
        self._canvas = tk.Canvas(r, width=cs, height=cs, bg=BG,
                                  highlightthickness=0)
        self._canvas.pack(pady=8)

        cx = cy = cs // 2
        rv = self.RING_SIZE // 2
        rw = self.RING_W

        self._ring_bg_id = self._canvas.create_arc(
            cx-rv, cy-rv, cx+rv, cy+rv,
            start=90, extent=359.9, style=tk.ARC,
            outline=RING_BG, width=rw
        )
        self._ring_id = self._canvas.create_arc(
            cx-rv, cy-rv, cx+rv, cy+rv,
            start=90, extent=0, style=tk.ARC,
            outline=FOCUS_CLR, width=rw
        )
        self._lbl_time = self._canvas.create_text(
            cx, cy, text="25:00",
            font=("Segoe UI", 46, "bold"), fill=TEXT_CLR
        )

        # Session dots
        dot_frame = tk.Frame(r, bg=BG)
        dot_frame.pack(pady=2)
        self._dots = []
        for _ in range(SESSIONS_BEFORE_LONG):
            d = tk.Label(dot_frame, text="●", bg=BG, fg=RING_BG,
                         font=("Segoe UI", 13))
            d.pack(side=tk.LEFT, padx=4)
            self._dots.append(d)

        # Buttons
        btn_row = tk.Frame(r, bg=BG)
        btn_row.pack(pady=18)
        self._btn_start = self._btn(btn_row, "Start",  self._toggle_start)
        self._btn_reset = self._btn(btn_row, "Reset",  lambda: self._state.reset())
        self._btn_skip  = self._btn(btn_row, "Skip →", lambda: self._state.skip())
        for b in (self._btn_start, self._btn_reset, self._btn_skip):
            b.pack(side=tk.LEFT, padx=7)

        # Hotkey hint
        tk.Label(r, text="Alt+2  open / show", bg=BG, fg=MUTED_CLR,
                 font=("Segoe UI", 8)).pack()

        self._refresh_ui()

    def _btn(self, parent, text, cmd):
        b = tk.Button(
            parent, text=text, command=cmd,
            bg=BTN_BG, fg=TEXT_CLR, activebackground=BTN_ACTIVE,
            activeforeground=TEXT_CLR, relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            width=8, cursor="hand2",
            borderwidth=0, highlightthickness=0,
            padx=8, pady=7
        )
        b.bind("<Enter>", lambda e: b.configure(bg=BTN_HOVER))
        b.bind("<Leave>", lambda e: b.configure(bg=BTN_BG))
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

        status = "▶" if s.is_running else "⏸"
        self.root.title(f"{status} {fmt_time(t)} · {PHASE_NAMES[ph]}")

        completed = (SESSIONS_BEFORE_LONG if ph == 2
                     else s.session_count % SESSIONS_BEFORE_LONG)
        for i, d in enumerate(self._dots):
            d.configure(fg=clr if i < completed else RING_BG)

        self._btn_start.configure(text="Pause" if s.is_running else "Start")

        if self._tray:
            self._tray.update(ph, t)

    # ── Window management ──────────────────────────────────────────────────────
    def _on_close(self):
        # Check the actual runtime instance, not the import-time flag — the
        # tray icon could fail to appear even when pystray imports cleanly.
        if self._tray is not None and self._tray._icon is not None:
            self.root.withdraw()
        else:
            self._do_quit()

    def _snap_top_right(self):
        w = 400
        h = 500
        sw = self.root.winfo_screenwidth()
        x  = sw - w - 10
        y  = 10
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def show(self):
        self._snap_top_right()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _toggle_visibility(self):
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.root.withdraw()

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
