@echo off
setlocal

echo ============================================
echo   Pomodoro Timer - Setup
echo ============================================
echo.

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
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
    set PYTHON=py
) else (
    set PYTHON=python
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
echo Setup complete! Double-click run.bat to start the timer.
echo.
pause
