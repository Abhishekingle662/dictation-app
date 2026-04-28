@echo off
setlocal

set APP_DIR=%~dp0
set LAUNCHER=%APP_DIR%launch.vbs
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
:: Resolve the actual Desktop path (handles OneDrive redirection)
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set DESKTOP=%%D

echo Installing Dictation App...

:: Desktop shortcut
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s  = $ws.CreateShortcut('%DESKTOP%\Dictation.lnk');" ^
  "$s.TargetPath     = 'wscript.exe';" ^
  "$s.Arguments      = '\""%LAUNCHER%\"\"';" ^
  "$s.WorkingDirectory = '%APP_DIR%';" ^
  "$s.Description    = 'Dictation App';" ^
  "$s.Save()"

:: Startup shortcut (auto-launch on login)
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s  = $ws.CreateShortcut('%STARTUP%\Dictation.lnk');" ^
  "$s.TargetPath     = 'wscript.exe';" ^
  "$s.Arguments      = '\""%LAUNCHER%\"\"';" ^
  "$s.WorkingDirectory = '%APP_DIR%';" ^
  "$s.Description    = 'Dictation App';" ^
  "$s.Save()"

echo.
echo Done!
echo   - Desktop shortcut created
echo   - App will now launch automatically on Windows login
echo   - Logs are written to: %APP_DIR%dictation.log
echo.
pause
