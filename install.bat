@echo off
REM ===========================================================================
REM  Richtet Jiimbos Power App auf einem Windows-Rechner ein.
REM
REM  Aufruf im cmd - laedt das Projekt bei Bedarf selbst herunter:
REM    curl -L -o install.bat https://raw.githubusercontent.com/Zenovs/python-jimbo/main/install.bat && install.bat
REM
REM  Umlaute stehen hier bewusst als ae/oe/ue: das cmd-Fenster zeigt UTF-8
REM  sonst als Kauderwelsch an.
REM ===========================================================================
setlocal
cd /d "%~dp0"
title Jiimbos Power App einrichten

echo.
echo ===========================================
echo   Jiimbos Power App - Einrichtung
echo ===========================================
echo.

REM --------------------------------------------------------------------------
REM  1. Python suchen
REM --------------------------------------------------------------------------
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :python_da

python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :python_da

echo FEHLER: Auf diesem Rechner wurde kein Python gefunden.
echo.
echo   Hole es von https://www.python.org/downloads/
echo   und setze bei der Installation den Haken bei
echo   "Add python.exe to PATH".
echo.
echo   Danach dieses Fenster schliessen und install.bat neu starten.
start https://www.python.org/downloads/
goto :fehlschlag

:python_da
for /f "tokens=*" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo   [1/4] Gefunden: %PYVER%

%PY% -c "import sys; sys.exit(0 if (3,12) <= sys.version_info < (3,15) else 1)" >nul 2>&1
if not errorlevel 1 goto :version_ok
echo.
echo FEHLER: Gebraucht wird Python 3.12, 3.13 oder 3.14.
echo         Gefunden wurde: %PYVER%
goto :fehlschlag

:version_ok

REM --------------------------------------------------------------------------
REM  2. Projekt holen, falls install.bat allein heruntergeladen wurde
REM --------------------------------------------------------------------------
if exist requirements.txt goto :quelle_da

echo   [2/4] Lade das Projekt von GitHub ...
curl -L --fail -o "%TEMP%\jimbo.zip" https://github.com/Zenovs/python-jimbo/archive/refs/heads/main.zip
if errorlevel 1 goto :download_fehler

tar -xf "%TEMP%\jimbo.zip"
if errorlevel 1 goto :download_fehler
del "%TEMP%\jimbo.zip" >nul 2>&1

cd python-jimbo-main
if errorlevel 1 goto :download_fehler
echo         Entpackt nach: %CD%
goto :einrichten

:quelle_da
echo   [2/4] Projekt liegt bereits hier: %CD%

REM --------------------------------------------------------------------------
REM  3. Virtuelle Umgebung und Pakete
REM --------------------------------------------------------------------------
:einrichten
echo   [3/4] Lege die virtuelle Umgebung an ...
if exist ".venv\Scripts\python.exe" goto :venv_da
%PY% -m venv .venv
if errorlevel 1 goto :venv_fehler

:venv_da
set "VPY=%CD%\.venv\Scripts\python.exe"
if not exist "%VPY%" goto :venv_fehler

echo   [4/4] Installiere die Pakete. Das dauert ein paar Minuten ...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_fehler
if exist requirements-dev.txt "%VPY%" -m pip install -r requirements-dev.txt

REM --------------------------------------------------------------------------
REM  4. Startdatei schreiben
REM --------------------------------------------------------------------------
> start.bat echo @echo off
>> start.bat echo REM Startet Jiimbos Power App.
>> start.bat echo cd /d "%%~dp0"
>> start.bat echo set PYTHONPATH=%%~dp0src
>> start.bat echo start "" ".venv\Scripts\pythonw.exe" -m jimbo

echo.
echo ===========================================
echo   Fertig.
echo ===========================================
echo.
echo   Starten:  Doppelklick auf start.bat
echo             (im Ordner %CD%)
echo.
echo   Wenn nichts passiert, zeigt dieser Befehl den Grund:
echo             .venv\Scripts\python.exe -m jimbo
echo.
echo   Beim ersten Start fragt die App nach deinem API-Key.
echo   Den bekommst du auf https://console.anthropic.com
echo.
if not defined CI pause
exit /b 0

REM --------------------------------------------------------------------------
REM  Fehlerausgaenge
REM --------------------------------------------------------------------------
:download_fehler
echo.
echo FEHLER: Das Projekt liess sich nicht herunterladen.
echo         Pruefe die Internetverbindung. Alternativ von Hand holen:
echo         https://github.com/Zenovs/python-jimbo/archive/refs/heads/main.zip
goto :fehlschlag

:venv_fehler
echo.
echo FEHLER: Die virtuelle Umgebung liess sich nicht anlegen.
echo         Loesche den Ordner .venv und versuche es noch einmal.
goto :fehlschlag

:pip_fehler
echo.
echo FEHLER: Die Pakete liessen sich nicht installieren.
echo         Haeufigste Ursache: keine Internetverbindung oder eine
echo         Firewall, die pip blockiert.
goto :fehlschlag

:fehlschlag
echo.
if not defined CI pause
exit /b 1
