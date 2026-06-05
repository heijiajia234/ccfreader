@echo off
setlocal

set "ROOT=%~dp0"
set "SRC=%ROOT%zotero-upstream"
set "NODE=%ROOT%tools\node-v20.20.2-win-x64"
set "GIT=D:\Git"
set "TEXZIP=D:\tex\miktex\bin\x64"

set "PATH=%ROOT%tools\rsync-shim;%ROOT%tools\python-shim;%NODE%;%GIT%\cmd;%GIT%\usr\bin;%GIT%\mingw64\bin;%TEXZIP%;%PATH%"
set "npm_config_script_shell=%GIT%\usr\bin\bash.exe"

cd /d "%SRC%" || exit /b 1
call "%NODE%\npm.cmd" run clean-build || exit /b 1

"%GIT%\usr\bin\bash.exe" -lc "cd /c/Users/jy/Documents/zotero/zotero-upstream && export PATH='/c/Users/jy/Documents/zotero/tools/rsync-shim:/c/Users/jy/Documents/zotero/tools/python-shim:/c/Users/jy/Documents/zotero/tools/node-v20.20.2-win-x64:/d/Git/cmd:/d/Git/usr/bin:/d/Git/mingw64/bin:/d/tex/miktex/bin/x64:$PATH' && export npm_config_script_shell=/d/Git/usr/bin/bash.exe && app/scripts/dir_build -p w -a x64 -q"
exit /b %ERRORLEVEL%
