# Start de geïntegreerde Examenverwerker op Windows.
# Python 3.12 wordt bewust gekozen omdat de lokale OCR-engine ONNX Runtime
# nodig heeft en daarvoor op Windows stabiele Python 3.12-wheels beschikbaar
# zijn. Zo voorkomt dit script incompatibele Python-versies op de PATH.

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# Gebruik de Windows Python Launcher om niet per ongeluk een andere
# Python-versie te kiezen die toevallig als eerste op de PATH staat.
$Launcher = Get-Command py -ErrorAction SilentlyContinue
if (-not $Launcher) {
    throw "De Windows Python Launcher (py) is niet gevonden. Installeer Python 3.12 via https://www.python.org/downloads/ en vink 'Python Launcher' aan."
}

# Installeer de runtime met de moderne Python-installatiemanager wanneer
# de launcher 3.12 nog niet kan vinden. Dit voorkomt dat gebruikers zelf
# eerst een aparte installer moeten downloaden en configureren.
& py -3.12 --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Python 3.12 is nog niet geïnstalleerd. Installatie starten…'
    & py install 3.12
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 3.12 kon niet automatisch worden geïnstalleerd. Voer handmatig "py install 3.12" uit en start daarna opnieuw.'
    }
}

# Verifieer dat de runtime na installatie daadwerkelijk vindbaar is.
& py -3.12 --version
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.12 is na installatie niet beschikbaar via de launcher. Voer "py install 3.12" handmatig uit en start opnieuw.'
}

$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

# Een bestaande virtuele omgeving kan met een nieuwere, incompatibele
# Python-versie zijn aangemaakt. Verwijder in dat geval uitsluitend .venv;
# de examendatabase en alle bronbestanden staan buiten deze omgeving.
if (Test-Path $Python) {
    & $Python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Bestaande Python-omgeving is niet compatibel; omgeving opnieuw aanmaken…'
        Remove-Item -Recurse -Force (Join-Path $PSScriptRoot '.venv')
    }
}

if (-not (Test-Path $Python)) {
    Write-Host 'Python 3.12-omgeving aanmaken…'
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw 'De virtuele Python 3.12-omgeving kon niet worden aangemaakt.'
    }
}

# Werk pip bij en installeer alle applicatieafhankelijkheden in de
# gecontroleerde Python 3.12-omgeving.
Write-Host 'Benodigde Python-pakketten controleren…'
# Herstel pip eerst vanuit ensurepip: een venv kan een pip-package bevatten
# zonder pip.__main__, waardoor de normale pip-opdracht niet uitvoerbaar is.
& $Python -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) {
    Write-Host 'pip-bootstrap mislukt; de lokale .venv wordt opnieuw aangemaakt…'
    Remove-Item -Recurse -Force (Join-Path $PSScriptRoot '.venv')
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python-omgeving opnieuw aanmaken is mislukt.' }
    $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    & $Python -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'pip kon ook na opnieuw aanmaken niet worden hersteld.' }
}
# Test of pip daadwerkelijk uitvoerbaar is, niet alleen als pakket geregistreerd.
& $Python -m pip --version
if ($LASTEXITCODE -ne 0) {
    Write-Host 'pip is beschadigd; de lokale .venv wordt opnieuw aangemaakt…'
    Remove-Item -Recurse -Force (Join-Path $PSScriptRoot '.venv')
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python-omgeving opnieuw aanmaken is mislukt.' }
    $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    & $Python -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'pip kon na opnieuw aanmaken niet worden geinitialiseerd.' }
    & $Python -m pip --version
    if ($LASTEXITCODE -ne 0) { throw 'pip werkt ook in de nieuwe omgeving niet.' }
}
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw 'pip kon niet worden bijgewerkt.'
}
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw 'De benodigde Python-pakketten konden niet worden geïnstalleerd.'
}

Write-Host ''
Write-Host 'Examenverwerker starten op http://127.0.0.1:8000'
Write-Host 'Laat dit venster open zolang de applicatie wordt gebruikt.'
& $Python -m uvicorn examenverwerker.main:app --host 127.0.0.1 --port 8000
