"""Tests für runner.py – führt echte, winzige Python-Skripte aus."""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import QCoreApplication

from jimbo import runner


@pytest.fixture(scope="module")
def qt_app():
    """QProcess braucht eine Qt-Anwendung, damit Signale ankommen."""
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture(autouse=True)
def gemerktes_python_zuruecksetzen():
    """Nach jedem Test den gemerkten Python-Pfad vergessen."""
    yield
    runner._schon_gesucht = False
    runner._gefundenes_python = None


@pytest.fixture
def python_befehl():
    befehl = runner.finde_python()
    if befehl is None:
        pytest.skip("Auf diesem Rechner ist kein Python zum Ausführen installiert.")
    return befehl


def _lauf(qt_app, python, skript, eingabe=None, wartezeit=30_000):
    """Startet ein Skript und liefert (Ausgabe, Exit-Code)."""
    lauf = runner.Ausfuehrung()
    gesammelt: list[str] = []
    codes: list[int] = []
    lauf.ausgabe.connect(gesammelt.append)
    lauf.beendet.connect(codes.append)

    lauf.starte_skript(python, skript)
    assert lauf._prozess is not None
    assert lauf._prozess.waitForStarted(10_000)
    if eingabe is not None:
        lauf.sende_eingabe(eingabe)
    assert lauf._prozess.waitForFinished(wartezeit), "Das Skript lief zu lange."
    qt_app.processEvents()
    return "".join(gesammelt), (codes[0] if codes else None)


# --------------------------------------------------------------------------
# Python finden
# --------------------------------------------------------------------------

def test_kandidaten_beginnen_unter_windows_mit_py():
    befehle = runner.kandidaten()
    if sys.platform == "win32":
        assert befehle[0] == ["py", "-3"]
        assert ["python"] in befehle
    else:
        assert befehle[0] == ["python3"]


def test_finde_python_wird_gemerkt(monkeypatch):
    runner.finde_python(erneut=True)
    aufrufe = []
    monkeypatch.setattr(runner, "_laeuft", lambda b: aufrufe.append(b) or True)
    runner.finde_python()  # gemerktes Ergebnis, kein erneutes Suchen
    assert aufrufe == []


def test_finde_python_ohne_treffer(monkeypatch):
    monkeypatch.setattr(runner, "_laeuft", lambda _: False)
    assert runner.finde_python(erneut=True) is None


# --------------------------------------------------------------------------
# Fehlende Module erkennen
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ausgabe, erwartet",
    [
        ("ModuleNotFoundError: No module named 'requests'", "requests"),
        ('ModuleNotFoundError: No module named "pandas"', "pandas"),
        ("ModuleNotFoundError: No module named 'requests.adapters'", "requests"),
        ("Alles bestens", None),
        ("ImportError: cannot import name 'x'", None),
    ],
)
def test_fehlendes_modul(ausgabe, erwartet):
    assert runner.fehlendes_modul(ausgabe) == erwartet


# --------------------------------------------------------------------------
# Programme ausführen
# --------------------------------------------------------------------------

def test_ausgabe_wird_gemeldet(qt_app, python_befehl, tmp_path):
    skript = tmp_path / "hallo.py"
    skript.write_text("print('hallo welt')\n", encoding="utf-8")

    ausgabe, code = _lauf(qt_app, python_befehl, skript)
    assert "hallo welt" in ausgabe
    assert code == 0


def test_umlaute_kommen_richtig_an(qt_app, python_befehl, tmp_path):
    skript = tmp_path / "umlaute.py"
    skript.write_text("print('Grüezi, schön!')\n", encoding="utf-8")

    ausgabe, _ = _lauf(qt_app, python_befehl, skript)
    assert "Grüezi, schön!" in ausgabe


def test_fehler_landen_ebenfalls_in_der_ausgabe(qt_app, python_befehl, tmp_path):
    skript = tmp_path / "kaputt.py"
    skript.write_text("import gibtsnicht_xyz\n", encoding="utf-8")

    ausgabe, code = _lauf(qt_app, python_befehl, skript)
    assert code != 0
    assert runner.fehlendes_modul(ausgabe) == "gibtsnicht_xyz"


def test_eingabe_erreicht_das_programm(qt_app, python_befehl, tmp_path):
    skript = tmp_path / "frage.py"
    skript.write_text("name = input('Name? ')\nprint('Hallo', name)\n", encoding="utf-8")

    ausgabe, code = _lauf(qt_app, python_befehl, skript, eingabe="Jiimbo")
    assert "Hallo Jiimbo" in ausgabe
    assert code == 0


def test_programm_laeuft_im_ordner_der_datei(qt_app, python_befehl, tmp_path):
    skript = tmp_path / "wo.py"
    skript.write_text("from pathlib import Path\nprint(Path.cwd())\n", encoding="utf-8")

    ausgabe, _ = _lauf(qt_app, python_befehl, skript)
    # realpath, weil macOS /tmp auf /private/tmp zeigt.
    assert os.path.realpath(ausgabe.strip()) == os.path.realpath(tmp_path)


def test_endlosprogramm_laesst_sich_stoppen(qt_app, python_befehl, tmp_path):
    skript = tmp_path / "endlos.py"
    skript.write_text("while True:\n    pass\n", encoding="utf-8")

    lauf = runner.Ausfuehrung()
    lauf.starte_skript(python_befehl, skript)
    assert lauf._prozess is not None and lauf._prozess.waitForStarted(10_000)
    assert lauf.laeuft()

    lauf.stoppe()
    assert not lauf.laeuft()
