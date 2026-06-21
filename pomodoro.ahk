#Requires AutoHotkey v2.0
#SingleInstance Force          ; a relaunch replaces any prior instance
; ─────────────────────────────────────────────────────────────────────────────
;  Pomodoro Timer — global hotkey
;
;  Alt+2 shows/hides the timer window. AutoHotkey owns the hotkey; it drops a
;  signal file that the running app polls for and acts on (so the app keeps its
;  own window/mini-timer state in sync).
;
;  The timer app launches this script automatically on start and closes it on
;  quit, so normally you don't run it by hand. You can still launch it directly
;  (double-click, or add to shell:startup) if you want Alt+2 without the app.
;  Requires AutoHotkey v2 — https://www.autohotkey.com/
; ─────────────────────────────────────────────────────────────────────────────

signalFile := A_Temp "\pomodoro_toggle.signal"

!2:: {                              ; Alt + 2
    global signalFile
    try FileAppend("", signalFile)  ; create the file; app consumes & deletes it
}
