-- BeatDrop Studio DaVinci Resolve Launcher
local python_exe = "C:\\Users\\hmaki\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"
local script_path = "C:\\Users\\hmaki\\.gemini\\antigravity\\scratch\\smart-sound-design\\davinci-script\\davinci_bridge.py"

local venv_python = os.getenv("APPDATA") .. "\\BeatDrop Studio\\venv\\Scripts\\python.exe"
local file = io.open(python_exe, "r")
if file then
    file:close()
else
    python_exe = venv_python
end

local cmd = string.format('start "" "%s" "%s"', python_exe, script_path)
os.execute(cmd)
