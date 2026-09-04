"""Startet erzeugten Python-Code in einem eigenen Prozess.

Der Code läuft mit dem Python, das auf dem Rechner installiert ist – nicht in
der App selbst. Es gibt bewusst keine Sandbox: das Programm darf alles, was
die angemeldete Person auch darf. Darauf weist die App vor dem ersten Start hin.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

PYTHON_DOWNLOAD = "https://www.python.org/downloads/"

# ModuleNotFoundError: No module named 'requests'
_FEHLENDES_MODUL = re.compile(
    r"ModuleNotFoundError: No module named ['\"]([A-Za-z0-9_.]+)['\"]"
)

_gefundenes_python: list[str] | None = None
_schon_gesucht = False


def _laeuft(befehl: list[str]) -> bool:
    """Prüft, ob sich mit diesem Befehl tatsächlich Python starten lässt."""
    try:
        fertig = subprocess.run(
            [*befehl, "--version"],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return fertig.returncode == 0


def kandidaten() -> list[list[str]]:
    """Die Befehle, mit denen nach Python gesucht wird – in dieser Reihenfolge."""
    if sys.platform == "win32":
        return [["py", "-3"], ["python"], ["python3"]]
    return [["python3"], ["python"]]


def finde_python(erneut: bool = False) -> list[str] | None:
    """Sucht das installierte Python. None, wenn keines gefunden wurde.

    Das Ergebnis wird gemerkt, damit nicht bei jedem Start gesucht wird.
    """
    global _gefundenes_python, _schon_gesucht
    if _schon_gesucht and not erneut:
        return _gefundenes_python

    _gefundenes_python = next((b for b in kandidaten() if _laeuft(b)), None)
    _schon_gesucht = True
    return _gefundenes_python


def fehlendes_modul(ausgabe: str) -> str | None:
    """Liest aus einer Fehlerausgabe den Namen des fehlenden Moduls."""
    treffer = _FEHLENDES_MODUL.search(ausgabe)
    if not treffer:
        return None
    return treffer.group(1).split(".")[0]


def _umgebung() -> QProcessEnvironment:
    """Umgebung des Kindprozesses: Ausgabe in UTF-8 und ohne Puffer."""
    umgebung = QProcessEnvironment.systemEnvironment()
    umgebung.insert("PYTHONIOENCODING", "utf-8")
    umgebung.insert("PYTHONUNBUFFERED", "1")
    return umgebung


class Ausfuehrung(QObject):
    """Ein laufendes Programm: liefert Ausgabe zeilenweise an die Oberfläche."""

    ausgabe = Signal(str)
    beendet = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._prozess: QProcess | None = None

    def laeuft(self) -> bool:
        return (
            self._prozess is not None
            and self._prozess.state() != QProcess.ProcessState.NotRunning
        )

    def starte(self, python: list[str], argumente: list[str], ordner: Path) -> None:
        """Startet `python` mit den Argumenten im angegebenen Ordner."""
        self.stoppe()
        prozess = QProcess(self)
        prozess.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        prozess.setProcessEnvironment(_umgebung())
        prozess.setWorkingDirectory(str(ordner))
        prozess.readyReadStandardOutput.connect(self._lies)
        prozess.finished.connect(self._fertig)
        prozess.errorOccurred.connect(self._fehler)
        self._prozess = prozess
        prozess.start(python[0], [*python[1:], *argumente])

    def starte_skript(self, python: list[str], skript: Path) -> None:
        """Führt eine .py-Datei aus (`-u` sorgt für sofortige Ausgabe)."""
        self.starte(python, ["-u", str(skript)], skript.parent)

    def starte_pip_install(self, python: list[str], modul: str, ordner: Path) -> None:
        """Installiert ein fehlendes Modul mit pip nach."""
        self.starte(python, ["-m", "pip", "install", modul], ordner)

    def sende_eingabe(self, text: str) -> None:
        """Schickt eine Zeile an das laufende Programm (für `input()`)."""
        if self.laeuft() and self._prozess is not None:
            self._prozess.write((text + os.linesep).encode("utf-8"))

    def stoppe(self) -> None:
        """Beendet das laufende Programm, notfalls hart."""
        if self._prozess is None:
            return
        if self._prozess.state() != QProcess.ProcessState.NotRunning:
            self._prozess.terminate()
            if not self._prozess.waitForFinished(2000):
                self._prozess.kill()
                self._prozess.waitForFinished(2000)

    def _lies(self) -> None:
        if self._prozess is None:
            return
        roh = bytes(self._prozess.readAllStandardOutput())
        if roh:
            self.ausgabe.emit(roh.decode("utf-8", errors="replace"))

    def _fertig(self, code: int, _status) -> None:
        self._lies()
        self.beendet.emit(code)

    def _fehler(self, fehler: QProcess.ProcessError) -> None:
        if fehler == QProcess.ProcessError.FailedToStart:
            self.ausgabe.emit(
                "\n[Python liess sich nicht starten. Ist es noch installiert?]\n"
            )
            self.beendet.emit(-1)
