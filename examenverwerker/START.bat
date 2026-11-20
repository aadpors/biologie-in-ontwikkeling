@echo off
cd /d "%~dp0"
if exist "Examenverwerker.exe" (
  start "" "%~dp0Examenverwerker.exe"
) else (
  py -3.12 app.py
  if errorlevel 1 pause
)
