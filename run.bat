@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" app.py
) else if exist ".venv\Scripts\python.exe" (
  start "" ".venv\Scripts\python.exe" app.py
) else (
  where pythonw >nul 2>nul
  if %errorlevel% equ 0 (
    start "" pythonw app.py
  ) else (
    python app.py
  )
)
