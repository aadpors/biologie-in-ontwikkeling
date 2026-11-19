@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m pip install -r requirements.txt || goto :error
py -3.12 -m PyInstaller --noconfirm --clean --windowed --name BiologieExamenverwerker --onedir --collect-all pymupdf app.py || goto :error
copy /Y START.bat dist\BiologieExamenverwerker\START.bat >nul
copy /Y README.md dist\BiologieExamenverwerker\GEBRUIK.md >nul
copy /Y CHANGELOG.md dist\BiologieExamenverwerker\WIJZIGINGEN.md >nul
copy /Y TESTPLAN.md dist\BiologieExamenverwerker\TESTPLAN.md >nul
echo.
echo Portable programma staat in: %CD%\dist\BiologieExamenverwerker
echo Kopieer de volledige map naar een USB-stick of gewenste map.
pause
exit /b 0
:error
echo Er is iets misgegaan bij het bouwen. Controleer de foutmelding hierboven.
pause
exit /b 1
