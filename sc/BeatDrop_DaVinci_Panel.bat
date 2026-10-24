@echo off
title BeatDrop Studio

:: Backend calismiyorsa arka planda baslat
netstat -ano | findstr 8765 >nul
if errorlevel 1 (
    start "" /B "%APPDATA%\BeatDrop Studio\venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8765
)

:: Paneli ac
start "" "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" "C:\Users\hmaki\.gemini\antigravity\scratch\smart-sound-design\davinci-script\davinci_bridge.py"
