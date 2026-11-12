@echo off
cd /d "%~dp0galpretrans"
where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "" pythonw -m galui
) else (
  python -m galui
)
