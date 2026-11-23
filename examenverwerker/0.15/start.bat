@echo off
setlocal
REM ================================================================
REM Examenverwerker starten op Windows
REM
REM Dit startbestand voorkomt dat PowerShell-opdrachten of een
REM aangepaste uitvoeringspolicy nodig zijn. De eerste keer wordt
REM een lokale virtuele Python-omgeving aangemaakt en worden de
REM benodigde pakketten geinstalleerd. Daarna wordt dezelfde omgeving
REM hergebruikt. Er worden geen systeembrede Python-pakketten gewijzigd.
REM ================================================================

REM Zorg dat alle relatieve paden naar deze map verwijzen, ook wanneer
REM de gebruiker het .bat-bestand via een snelkoppeling start.
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"

REM Controleer of Python beschikbaar is voordat we iets wijzigen.
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo FOUT: Python is niet gevonden.
    echo Installeer Python 3.10 of hoger via https://www.python.org/downloads/
    echo Vink tijdens de installatie 'Add Python to PATH' aan.
    echo Start daarna start.bat opnieuw.
    echo.
    pause
    exit /b 1
)

REM Maak alleen bij de eerste start een eigen virtuele omgeving.
if not exist "%PYTHON_EXE%" (
    echo Eerste start: Python-omgeving aanmaken...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo FOUT: De Python-omgeving kon niet worden aangemaakt.
        pause
        exit /b 1
    )
)

REM Controleer of de virtuele Python-omgeving daadwerkelijk bestaat.
if not exist "%PYTHON_EXE%" (
    echo.
    echo FOUT: Python 3.10 of hoger kon niet correct worden geinstalleerd.
    pause
    exit /b 1
)

REM Installeer of actualiseer de afhankelijkheden in de lokale omgeving.
echo Benodigde onderdelen controleren en installeren...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo FOUT: De benodigde onderdelen konden niet worden geinstalleerd.
    echo Controleer de internetverbinding en probeer het opnieuw.
    pause
    exit /b 1
)

REM Open de webinterface in de standaardbrowser. De server wordt
REM vervolgens in dit venster gestart; dit venster moet open blijven.
echo.
echo Examenverwerker wordt gestart op http://127.0.0.1:8000
echo Laat dit venster open zolang je de applicatie gebruikt.
echo Sluit de applicatie met Ctrl+C.
echo.
start "" "http://127.0.0.1:8000"
"%PYTHON_EXE%" -m uvicorn examenverwerker.main:app --host 127.0.0.1 --port 8000

REM Als de server stopt door een fout, blijft de melding zichtbaar.
echo.
echo De Examenverwerker is gestopt.
pause
endlocal
