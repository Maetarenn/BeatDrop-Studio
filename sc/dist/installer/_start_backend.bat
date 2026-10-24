@echo off
cd /d "C:\Users\hmaki\AppData\Local\Temp\_MEI111122\backend"
"C:\Users\hmaki\AppData\Roaming\BeatDrop Studio\venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8765 --log-level warning
