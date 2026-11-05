@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_mvp.ps1" %*
if errorlevel 1 (
  echo Startup failed. Please check the message above.
  pause
  exit /b 1
)
