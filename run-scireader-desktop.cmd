@echo off
setlocal
cd /d "%~dp0apps\scireader-desktop"
if not exist node_modules (
  call npm install
)
call npm run preview
