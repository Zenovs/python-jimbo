# Baut JiimbosPowerApp.exe.
#
# Aufruf im Projektordner:   powershell -ExecutionPolicy Bypass -File build.ps1
# Ergebnis:                  dist\JiimbosPowerApp.exe

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$Venv   = Join-Path $PSScriptRoot ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Lege die virtuelle Umgebung an ..." -ForegroundColor Cyan
    py -3 -m venv $Venv
}

Write-Host "Installiere die Abhaengigkeiten ..." -ForegroundColor Cyan
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt -r requirements-dev.txt

Write-Host "Lasse die Tests laufen ..." -ForegroundColor Cyan
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Die Tests sind fehlgeschlagen - es wird nicht gebaut." }

Write-Host "Raeume alte Ergebnisse weg ..." -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
Remove-Item -Force *.spec -ErrorAction SilentlyContinue

Write-Host "Baue die .exe ..." -ForegroundColor Cyan
& $Python -m PyInstaller `
    --onefile `
    --windowed `
    --clean `
    --noconfirm `
    --name JiimbosPowerApp `
    --icon assets\icon.ico `
    --paths src `
    --add-data "assets\icon.ico;assets" `
    --exclude-module tkinter `
    --exclude-module pytest `
    --exclude-module PyInstaller `
    launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller ist fehlgeschlagen." }

Write-Host "Pruefe, ob die .exe startet ..." -ForegroundColor Cyan
$env:JIMBO_SELFTEST = "1"
& "dist\JiimbosPowerApp.exe"
$code = $LASTEXITCODE
Remove-Item Env:\JIMBO_SELFTEST
if ($code -ne 0) { throw "Die gebaute .exe startet nicht (Exit-Code $code)." }

$groesse = [math]::Round((Get-Item "dist\JiimbosPowerApp.exe").Length / 1MB, 1)
Write-Host "Fertig: dist\JiimbosPowerApp.exe ($groesse MB)" -ForegroundColor Green
