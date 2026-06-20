# Creates a "Pomodoro Timer" shortcut on the Desktop, launching the app with a
# windowed Python (no console) and the generated pomodoro.ico. Invoked by
# setup.bat; safe to run on its own. Re-running just overwrites the shortcut.

$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot

# Prefer a windowed launcher so no console window flashes on start.
$py = Get-Command pythonw -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command pyw     -ErrorAction SilentlyContinue }
if (-not $py) { $py = Get-Command python  -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Host '[!] Python not found - shortcut not created. Run setup.bat first.'
    exit 1
}

$script  = Join-Path $dir 'countdown_timer.py'
$ico     = Join-Path $dir 'pomodoro.ico'
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk     = Join-Path $desktop 'Pomodoro Timer.lnk'

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath       = $py.Source
$sc.Arguments        = '"' + $script + '"'
$sc.WorkingDirectory = $dir
$sc.Description       = 'Pomodoro Timer'
if (Test-Path $ico) { $sc.IconLocation = $ico }
$sc.Save()

Write-Host "[OK] Desktop shortcut created: $lnk"
