@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m pip install -r requirements.txt || goto :error
py -3.12 -m PyInstaller --noconfirm --clean --windowed --name Examenverwerker --onedir --collect-all pymupdf app.py || goto :error
copy /Y START.bat dist\Examenverwerker\START.bat >nul
copy /Y README.md dist\Examenverwerker\GEBRUIK.md >nul
copy /Y CHANGELOG.md dist\Examenverwerker\WIJZIGINGEN.md >nul
copy /Y TESTPLAN.md dist\Examenverwerker\TESTPLAN.md >nul
echo.
echo Portable programma staat in: %CD%\dist\Examenverwerker
echo Kopieer de volledige map naar een USB-stick of gewenste map.
pause
exit /b 0
:error
echo Er is iets misgegaan bij het bouwen. Controleer de foutmelding hierboven.
pause
exit /b 1
