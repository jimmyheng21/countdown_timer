@echo off
:: Try pythonw first (no console window), fall back to python
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0countdown_timer.py"
    exit /b 0
)

python --version >nul 2>&1
if %errorlevel% equ 0 (
    start "" python "%~dp0countdown_timer.py"
    exit /b 0
)

py --version >nul 2>&1
if %errorlevel% equ 0 (
    start "" py "%~dp0countdown_timer.py"
    exit /b 0
)

echo Python not found. Please run setup.bat first.
pause
