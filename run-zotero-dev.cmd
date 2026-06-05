@echo off
setlocal
set "ROOT=%~dp0"
set "APP=%ROOT%zotero-upstream\app\staging\Zotero_win-x64\zotero.exe"
set "PROFILE=%ROOT%zotero-dev-profile"
set "PY=%ROOT%tools\reflow-venv\Scripts\python.exe"
set "SERVICE=%ROOT%reflow-service\service.py"

if not exist "%APP%" (
  echo Missing %APP%
  echo Run the build command from the notes first.
  exit /b 1
)

if not exist "%PROFILE%" mkdir "%PROFILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:27621/health' | Out-Null } catch { Start-Process -WindowStyle Hidden -FilePath '%PY%' -ArgumentList '%SERVICE%' }"
start "" "%APP%" -profile "%PROFILE%" -no-remote
