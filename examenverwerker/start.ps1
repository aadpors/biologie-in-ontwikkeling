# Start de geïntegreerde Examenverwerker op Windows.
# De virtuele omgeving staat naast dit script; bestaande Python-installaties
# en andere projecten blijven daardoor ongemoeid.
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Write-Host 'Virtuele Python-omgeving aanmaken…'
    python -m venv .venv
}

if (-not (Test-Path $Python)) {
    throw 'Python 3.10 of hoger is niet gevonden. Installeer Python en probeer opnieuw.'
}

Write-Host 'Benodigde Python-pakketten controleren…'
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt

Write-Host ''
Write-Host 'Examenverwerker starten op http://127.0.0.1:8000'
Write-Host 'Laat dit venster open zolang de applicatie wordt gebruikt.'
& $Python -m uvicorn examenverwerker.main:app --host 127.0.0.1 --port 8000
