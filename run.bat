@echo off
setlocal
pushd "%~dp0" >nul 2>&1 || (
  echo [AzooKey Live Bridge] Failed to switch to script directory.
  exit /b 1
)

if not exist "app.py" (
  echo [AzooKey Live Bridge] app.py not found in "%CD%".
  popd
  exit /b 1
)

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" app.py %*
  goto :done
)
if exist ".venv\Scripts\python.exe" (
  start "" ".venv\Scripts\python.exe" app.py %*
  goto :done
)

rem Verify a real Python interpreter exists (avoid Windows Store empty alias stubs).
python --version >nul 2>&1
if not errorlevel 1 (
  where pythonw >nul 2>&1
  if not errorlevel 1 (
    start "" pythonw app.py %*
    goto :done
  )
  python app.py %*
  set "EXIT_CODE=%errorlevel%"
  popd
  exit /b %EXIT_CODE%
)

echo [AzooKey Live Bridge] 64-bit Python 3 was not found in PATH or .venv.
echo Please install 64-bit Python 3 ^(with tkinter^) and try again.
popd
exit /b 1

:done
popd
exit /b 0
