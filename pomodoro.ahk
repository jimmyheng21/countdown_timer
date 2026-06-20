#Requires AutoHotkey v2.0
; ─────────────────────────────────────────────────────────────────────────────
;  Pomodoro Timer — global hotkey
;
;  Alt+2 shows/hides the timer window. AutoHotkey owns the hotkey; it drops a
;  signal file that the running app polls for and acts on (so the app keeps its
;  own window/mini-timer state in sync).
;
;  Usage:
;    1. Install AutoHotkey v2 from https://www.autohotkey.com/
;    2. Double-click this file (or add it to shell:startup to run at login).
;    3. Start the timer (run.bat). Press Alt+2 anywhere to show/hide it.
; ─────────────────────────────────────────────────────────────────────────────

signalFile := A_Temp "\pomodoro_toggle.signal"

!2:: {                              ; Alt + 2
    global signalFile
    try FileAppend("", signalFile)  ; create the file; app consumes & deletes it
}
