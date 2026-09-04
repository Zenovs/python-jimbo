"""Tests für die Oberfläche – ohne echten API-Zugriff und ohne Bildschirm."""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from jimbo import api, app, settings


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fenster(qt_app, monkeypatch):
    # Der Willkommensdialog darf in Tests nicht aufgehen.
    monkeypatch.setattr(app.MainWindow, "_erster_start", lambda self: None)
    monkeypatch.setattr(app.settings, "load_api_key", lambda: "sk-ant-test")
    w = app.MainWindow()
    yield w
    w.lauf.stoppe()
    w.close()


def _warte_bis(qt_app, bedingung, sekunden=30.0):
    """Wartet auf eine Bedingung – nach Uhrzeit, nicht nach Durchläufen.

    Eine Schleife über eine feste Zahl von Durchläufen ist auf schnellen
    Rechnern durch, bevor der Kindprozess überhaupt etwas ausgegeben hat.
    """
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if bedingung():
            return True
        qt_app.processEvents()
        time.sleep(0.005)
    return bedingung()


def _warte_auf_anfrage(qt_app, fenster):
    """Wartet, bis der Hintergrund-Thread fertig ist."""
    return _warte_bis(qt_app, lambda: fenster._thread is None)


def _programm(code="print('hallo')", filename="hallo.py", explanation="Gibt hallo aus."):
    return api.Programm(filename=filename, code=code, explanation=explanation)


# --------------------------------------------------------------------------
# Aufbau
# --------------------------------------------------------------------------

def test_fenster_hat_die_drei_bereiche(fenster):
    assert fenster.windowTitle() == "Jiimbos Power App"
    assert (fenster.width(), fenster.height()) == (1000, 700)
    ueberschriften = [
        fenster.centralWidget().widget(i).title() for i in range(3)
    ]
    assert ueberschriften[0].startswith("1.")
    assert ueberschriften[1].startswith("2.")
    assert ueberschriften[2].startswith("3.")


def test_statusleiste_zeigt_das_modell(fenster):
    assert "Claude Sonnet 5" in fenster.label_modell.text()
    assert fenster.label_verbindung.text() == "Bereit"
    assert fenster.label_fehler.text() == ""


def test_code_feld_hat_zeilennummern(fenster):
    fenster.feld_code.setPlainText("a = 1\nb = 2\nc = 3")
    assert fenster.feld_code.breite_der_zeilennummern() > 0
    assert fenster.feld_code.blockCount() == 3


# --------------------------------------------------------------------------
# Programm erstellen
# --------------------------------------------------------------------------

def test_erstellen_fuellt_code_und_erklaerung(qt_app, fenster, monkeypatch):
    monkeypatch.setattr(api, "erzeuge", lambda *a, **kw: _programm())
    fenster.feld_aufgabe.setPlainText("Gib hallo aus")
    fenster.knopf_erstellen.click()

    assert _warte_auf_anfrage(qt_app, fenster)
    assert fenster.feld_code.toPlainText() == "print('hallo')"
    assert fenster.feld_erklaerung.toPlainText() == "Gibt hallo aus."
    assert fenster.vorschlag == "hallo.py"
    assert fenster.label_verbindung.text() == "Fertig"


def test_erstellen_merkt_die_aufgabe_im_verlauf(qt_app, fenster, monkeypatch):
    monkeypatch.setattr(api, "erzeuge", lambda *a, **kw: _programm())
    fenster.feld_aufgabe.setPlainText("Zahlen 1 bis 10")
    fenster.knopf_erstellen.click()
    assert _warte_auf_anfrage(qt_app, fenster)
    assert fenster.konfig.history[0] == "Zahlen 1 bis 10"


def test_erstellen_ohne_aufgabe_fragt_nach(fenster, monkeypatch):
    gezeigt = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **kw: gezeigt.append(a[-1])
    )
    fenster.knopf_erstellen.click()
    assert gezeigt and "Beschreibe zuerst" in gezeigt[0]
    assert fenster._thread is None


def test_fehler_landet_in_der_statusleiste(qt_app, fenster, monkeypatch):
    def kaputt(*a, **kw):
        raise api.ApiFehler("Keine Verbindung zur Anthropic-API.")

    monkeypatch.setattr(api, "erzeuge", kaputt)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    fenster.feld_aufgabe.setPlainText("Irgendwas")
    fenster.knopf_erstellen.click()

    assert _warte_auf_anfrage(qt_app, fenster)
    assert "Keine Verbindung" in fenster.label_fehler.text()
    assert fenster.label_verbindung.text() == "Fehlgeschlagen"


def test_teilcode_wird_waehrend_des_streams_angezeigt(qt_app, fenster, monkeypatch):
    def mit_stream(*a, on_code=None, abbrechen=None, **kw):
        for teil in ["pri", "print(1)"]:
            on_code(teil)
        return _programm(code="print(1)")

    monkeypatch.setattr(api, "erzeuge", mit_stream)
    fenster.feld_aufgabe.setPlainText("Aufgabe")
    fenster.knopf_erstellen.click()
    assert _warte_auf_anfrage(qt_app, fenster)
    assert fenster.feld_code.toPlainText() == "print(1)"


# --------------------------------------------------------------------------
# Ändern
# --------------------------------------------------------------------------

def test_aendern_schickt_den_aktuellen_code(qt_app, fenster, monkeypatch):
    gesehen = {}

    def merke(code, wunsch, *a, **kw):
        gesehen["code"] = code
        gesehen["wunsch"] = wunsch
        return _programm(code="print('neu')")

    monkeypatch.setattr(api, "verbessere", merke)
    fenster.feld_code.setPlainText("print('alt')")
    fenster.feld_aenderung.setPlainText("Sag neu statt alt")
    fenster.knopf_aendern.click()

    assert _warte_auf_anfrage(qt_app, fenster)
    assert gesehen == {"code": "print('alt')", "wunsch": "Sag neu statt alt"}
    assert fenster.feld_code.toPlainText() == "print('neu')"


def test_aendern_ohne_code_fragt_nach(fenster, monkeypatch):
    gezeigt = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **kw: gezeigt.append(a[-1])
    )
    fenster.feld_aenderung.setPlainText("irgendwas")
    fenster.knopf_aendern.click()
    assert gezeigt and "noch keinen Code" in gezeigt[0]


# --------------------------------------------------------------------------
# Speichern, Kopieren
# --------------------------------------------------------------------------

def test_speichern_schreibt_die_datei(fenster, monkeypatch, tmp_path):
    ziel = tmp_path / "meins.py"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **kw: (str(ziel), "")
    )
    fenster.feld_code.setPlainText("print('hallo')")
    fenster._speichere()

    assert ziel.read_text(encoding="utf-8") == "print('hallo')\n"
    assert fenster.datei == ziel
    assert fenster.konfig.save_dir == str(tmp_path)


def test_speichern_ergaenzt_die_endung(fenster, monkeypatch, tmp_path):
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **kw: (str(tmp_path / "ohne_endung"), ""),
    )
    fenster.feld_code.setPlainText("x = 1")
    pfad = fenster._speichere()
    assert pfad is not None and pfad.name == "ohne_endung.py"


def test_speichern_abgebrochen_schreibt_nichts(fenster, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))
    fenster.feld_code.setPlainText("x = 1")
    assert fenster._speichere() is None
    assert fenster.datei is None


def test_kopieren(qt_app, fenster):
    fenster.feld_code.setPlainText("print('kopiert')")
    fenster.knopf_kopieren.click()
    assert QApplication.clipboard().text() == "print('kopiert')"


# --------------------------------------------------------------------------
# Ausführen
# --------------------------------------------------------------------------

def test_warnung_kommt_nur_einmal(fenster, monkeypatch):
    gezeigt = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **kw: gezeigt.append(a[2]) or QMessageBox.StandardButton.Ok,
    )
    assert fenster._warnung_bestaetigt()
    assert fenster._warnung_bestaetigt()

    assert len(gezeigt) == 1
    assert app.WARNUNG_AUSFUEHREN in gezeigt[0]
    assert fenster.konfig.run_warning_acknowledged


def test_warnung_abgelehnt_verhindert_das_ausfuehren(fenster, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **kw: QMessageBox.StandardButton.Cancel
    )
    assert not fenster._warnung_bestaetigt()
    assert not fenster.konfig.run_warning_acknowledged


def test_ohne_python_kommt_eine_deutliche_meldung(fenster, monkeypatch):
    fenster.konfig.run_warning_acknowledged = True
    monkeypatch.setattr(app.runner, "finde_python", lambda erneut=False: None)
    gezeigt = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **kw: gezeigt.append(a[2])
    )
    monkeypatch.setattr(app.QDesktopServices, "openUrl", lambda *a: True)

    fenster.feld_code.setPlainText("print(1)")
    fenster.knopf_ausfuehren.click()
    assert gezeigt and "kein Python gefunden" in gezeigt[0]


def test_arbeitskopie_wird_angelegt_wenn_nicht_gespeichert(fenster):
    fenster.vorschlag = "test_lauf.py"
    ziel = fenster._datei_zum_ausfuehren("print(1)")
    assert ziel is not None
    assert ziel.read_text(encoding="utf-8") == "print(1)\n"
    assert ziel.parent == settings.config_dir() / "arbeitskopie"


def test_ausfuehren_zeigt_die_ausgabe(qt_app, fenster, monkeypatch, tmp_path):
    python = app.runner.finde_python()
    if python is None:
        pytest.skip("Kein Python zum Ausführen gefunden.")

    fenster.konfig.run_warning_acknowledged = True
    fenster.datei = tmp_path / "lauf.py"
    fenster.feld_code.setPlainText("print('aus dem Programm')")
    fenster.knopf_ausfuehren.click()

    fertig = _warte_bis(
        qt_app,
        lambda: not fenster.lauf.laeuft()
        and "Programm beendet" in fenster.feld_ausgabe.toPlainText(),
    )

    assert fertig, f"Zeitüberschreitung, Ausgabe war: {fenster.feld_ausgabe.toPlainText()!r}"
    assert "aus dem Programm" in fenster.feld_ausgabe.toPlainText()
    assert fenster.reiter.currentIndex() == 1


def test_fehlendes_modul_wird_angeboten(fenster, monkeypatch):
    gefragt = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **kw: gefragt.append(a[2]) or QMessageBox.StandardButton.No,
    )
    fenster._lauf_puffer = "ModuleNotFoundError: No module named 'requests'"
    fenster._biete_modul_an()
    assert gefragt and "«requests»" in gefragt[0]


# --------------------------------------------------------------------------
# Einstellungen
# --------------------------------------------------------------------------

def test_einstellungen_speichern_key_und_modell(qt_app, monkeypatch):
    konfig = settings.Settings()
    dialog = app.EinstellungenDialog(konfig)
    dialog.feld_key.setText("sk-ant-neuer-key")
    dialog.feld_modell.setCurrentIndex(dialog.feld_modell.findData("claude-opus-5"))
    dialog.accept()

    assert settings.load_api_key() == "sk-ant-neuer-key"
    assert konfig.model == "claude-opus-5"
    assert settings.settings_file().exists()


def test_einstellungen_zeigen_den_vorhandenen_key(qt_app):
    settings.save_api_key("sk-ant-vorhanden")
    dialog = app.EinstellungenDialog(settings.Settings())
    assert dialog.feld_key.text() == "sk-ant-vorhanden"
    from PySide6.QtWidgets import QLineEdit
    assert dialog.feld_key.echoMode() == QLineEdit.EchoMode.Password


def test_key_test_meldet_fehler(qt_app, monkeypatch):
    monkeypatch.setattr(
        app.api, "teste_verbindung",
        lambda key: (_ for _ in ()).throw(api.ApiFehler("Key ungültig")),
    )
    gezeigt = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: gezeigt.append(a[2]))
    dialog = app.EinstellungenDialog(settings.Settings())
    dialog._teste_key()
    assert gezeigt == ["Key ungültig"]


def test_nach_pip_install_wird_nicht_erneut_gefragt(fenster, monkeypatch):
    """Sonst könnte sich die Frage nach dem Modul endlos wiederholen."""
    gefragt = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **kw: gefragt.append(a[2]) or QMessageBox.StandardButton.No,
    )
    fenster._lauf_art = "pip"
    fenster._lauf_puffer = "ModuleNotFoundError: No module named 'requests'"
    fenster._lauf_beendet(0)

    assert gefragt == []
    assert fenster._lauf_art == "programm"
    assert "Modul installiert" in fenster.feld_ausgabe.toPlainText()
