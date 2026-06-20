@echo off
setlocal

echo ============================================
echo   Pomodoro Timer - Setup
echo ============================================
echo.

:: Check for Python (prefer 'python', fall back to the 'py' launcher).
:: Uses && + "if not defined" rather than %errorlevel% inside a block — a
:: nested "if %errorlevel%" would expand at parse time and ignore py's result.
set "PYTHON="
python --version >nul 2>&1 && set "PYTHON=python"
if not defined PYTHON (
    py --version >nul 2>&1 && set "PYTHON=py"
)
if not defined PYTHON (
    echo [!] Python not found.
    echo.
    echo Please install Python first:
    echo   1. Go to https://www.python.org/downloads/
    echo   2. Download the latest Python 3.x installer
    echo   3. Run it and CHECK "Add Python to PATH"
    echo   4. Re-run this setup.bat after installation
    echo.
    pause
    exit /b 1
)

echo [OK] Python found.
echo.
echo Installing dependencies...
%PYTHON% -m pip install --upgrade pip >nul 2>&1
%PYTHON% -m pip install pystray Pillow plyer

if %errorlevel% neq 0 (
    echo.
    echo [!] Some packages failed to install.
    echo     The app will still work but system tray / notifications may be limited.
) else (
    echo.
    echo [OK] All dependencies installed.
)

echo.
echo Creating desktop shortcut...
:: Refresh the app icon (best effort; a committed pomodoro.ico is used as fallback)
%PYTHON% "%~dp0make_icon.py" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"

echo.
echo Setup complete! Launch from the "Pomodoro Timer" desktop shortcut,
echo or double-click run.bat.
echo.
pause
