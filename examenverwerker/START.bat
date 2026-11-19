@echo off
cd /d "%~dp0"
if exist "BiologieExamenverwerker.exe" (
  start "" "%~dp0BiologieExamenverwerker.exe"
) else (
  py -3.12 app.py
  if errorlevel 1 pause
)
