@echo off
title Chassis Frame Inspector
cd /d "%~dp0"

echo [INFO] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+
    pause
    exit /b 1
)

echo [INFO] Installing/checking dependencies...
pip install -r requirements.txt --quiet

echo [INFO] Starting Chassis Frame Inspector...
python main.py
pause
