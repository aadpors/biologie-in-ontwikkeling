@echo off
setlocal
REM ================================================================
REM Examenverwerker starten op Windows
REM
REM De lokale OCR-engine gebruikt ONNX Runtime. Daarvoor gebruiken we
REM bewust Python 3.12: die versie heeft beschikbare Windows-wheels voor
REM alle benodigde OCR-afhankelijkheden. Een willekeurige nieuwere Python
REM (bijvoorbeeld een preview/nieuwe hoofdversie) kan pip anders laten
REM mislukken met "No matching distribution found".
REM
REM De virtuele omgeving staat uitsluitend in deze projectmap. Als daarin
REM eerder een incompatibele Python-versie is gebruikt, wordt alleen die
REM wegwerpomgeving opnieuw aangemaakt; examendata blijft onaangeroerd.
REM ================================================================

REM Zorg dat alle relatieve paden naar deze map verwijzen, ook wanneer
REM de gebruiker het .bat-bestand via een snelkoppeling start.
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"

REM Gebruik de Windows Python Launcher om exact Python 3.12 te kiezen.
REM Zo hangt de applicatie niet af van de eerste "python" op de PATH.
where py >nul 2>nul
if errorlevel 1 (
    echo.
    echo FOUT: De Windows Python Launcher ^(py^) is niet gevonden.
    echo Installeer Python 3.12 vanaf https://www.python.org/downloads/
    echo en vink tijdens de installatie 'Python Launcher' aan.
    echo Start daarna start.bat opnieuw.
    echo.
    pause
    exit /b 1
)

py -3.12 --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo FOUT: Python 3.12 is niet geinstalleerd.
    echo De lokale OCR-engine vereist momenteel Python 3.12.
    echo Installeer Python 3.12 vanaf https://www.python.org/downloads/
    echo en start daarna start.bat opnieuw.
    echo.
    pause
    exit /b 1
)

REM Controleer een bestaande omgeving op de juiste Python-hoofd- en
REM subversie. Alleen .venv wordt verwijderd; imports, examens en database
REM staan buiten deze map en blijven dus behouden.
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo Bestaande Python-omgeving is niet compatibel. Omgeving opnieuw aanmaken...
        rmdir /s /q .venv
    )
)

REM Maak de virtuele omgeving altijd expliciet met Python 3.12.
if not exist "%PYTHON_EXE%" (
    echo Python 3.12-omgeving aanmaken...
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo.
        echo FOUT: De Python 3.12-omgeving kon niet worden aangemaakt.
        pause
        exit /b 1
    )
)

REM Controleer of de omgeving daadwerkelijk met Python 3.12 is aangemaakt.
if not exist "%PYTHON_EXE%" (
    echo.
    echo FOUT: Python 3.12 kon niet correct worden geinitialiseerd.
    pause
    exit /b 1
)

REM Installeer of actualiseer de afhankelijkheden in de lokale omgeving.
REM Door de interpreter hierboven vast te leggen, kan pip een passende
REM ONNX Runtime-wheel voor Windows installeren.
echo Benodigde onderdelen controleren en installeren...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 (
    echo.
    echo FOUT: pip kon niet worden bijgewerkt.
    pause
    exit /b 1
)
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo FOUT: De benodigde onderdelen konden niet worden geinstalleerd.
    echo Controleer de internetverbinding en probeer het opnieuw.
    pause
    exit /b 1
)

REM Open de webinterface nadat de afhankelijkheden zijn geinstalleerd.
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
