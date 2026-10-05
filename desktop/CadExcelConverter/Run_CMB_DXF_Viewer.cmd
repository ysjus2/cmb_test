@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ensure_vcredist.ps1"
if errorlevel 1 (
  echo.
  echo Microsoft Visual C++ Runtime prerequisite setup failed.
  echo Please contact the internal administrator.
  pause
  exit /b 1
)

start "" "%~dp0CMB_DXF_Viewer.exe"
exit /b 0
