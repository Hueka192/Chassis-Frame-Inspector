@echo off
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    powershell -Command "Write-Host '[ERROR] Python not found. Install Python 3.9+' -Fore Red; Read-Host"
    exit /b 1
)

pip install -r requirements.txt --quiet >nul 2>&1

echo Starting Smart Quality Gate Inspection...
echo If the app does not appear, run manually: python main.py
echo (Errors will be logged to logs/inspector_*.log)
echo.
start /min /wait "" pythonw main.py

if errorlevel 1 (
    echo [ERROR] Application exited with code %errorlevel%.
    echo Run 'python main.py' to see full error output.
    pause
)
exit
