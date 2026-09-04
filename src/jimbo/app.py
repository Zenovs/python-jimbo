"""Die Oberfläche von Jiimbos Power App.

Ein Fenster mit drei Bereichen untereinander: Aufgabe, Code, Erklärung.
Die Anfragen an die API laufen in einem eigenen Thread, damit das Fenster
während des Wartens bedienbar bleibt.
"""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, APP_SLUG, ASCII_LOGO, __version__, api, runner, settings
from .editor import CodeEditor, monospace_font

REPO_URL = "https://github.com/Zenovs/python-jimbo"
CONSOLE_URL = "https://console.anthropic.com/settings/keys"

WARNUNG_AUSFUEHREN = (
    "Der Code läuft mit vollen Rechten auf deinem Rechner. Lies ihn vorher."
)


# --------------------------------------------------------------------------
# Einstellungen
# --------------------------------------------------------------------------

class EinstellungenDialog(QDialog):
    """API-Key, Modell und Standardordner."""

    def __init__(self, konfig: settings.Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(560)
        self._konfig = konfig

        self.feld_key = QLineEdit()
        self.feld_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.feld_key.setPlaceholderText("sk-ant-…")
        try:
            self.feld_key.setText(settings.load_api_key() or "")
        except settings.SchluesselspeicherFehler as fehler:
            QMessageBox.warning(self, "Passwortspeicher", str(fehler))

        zeigen = QCheckBox("Key anzeigen")
        zeigen.toggled.connect(
            lambda an: self.feld_key.setEchoMode(
                QLineEdit.EchoMode.Normal if an else QLineEdit.EchoMode.Password
            )
        )

        hinweis = QLabel(
            "Den Key bekommst du kostenlos auf "
            f'<a href="{CONSOLE_URL}">console.anthropic.com</a>. '
            "Er wird im Passwortspeicher deines Betriebssystems abgelegt, "
            "nicht in einer Datei."
        )
        hinweis.setOpenExternalLinks(True)
        hinweis.setWordWrap(True)

        self.feld_modell = QComboBox()
        for beschriftung, modell_id in settings.MODELS:
            self.feld_modell.addItem(beschriftung, modell_id)
        index = self.feld_modell.findData(konfig.model)
        self.feld_modell.setCurrentIndex(index if index >= 0 else 0)

        self.feld_ordner = QLineEdit(konfig.save_dir)
        self.feld_ordner.setPlaceholderText(str(Path.home()))
        knopf_ordner = QPushButton("Ordner wählen …")
        knopf_ordner.clicked.connect(self._waehle_ordner)
        zeile_ordner = QHBoxLayout()
        zeile_ordner.addWidget(self.feld_ordner, 1)
        zeile_ordner.addWidget(knopf_ordner)

        formular = QFormLayout()
        formular.addRow("API-Key:", self.feld_key)
        formular.addRow("", zeigen)
        formular.addRow("", hinweis)
        formular.addRow("Modell:", self.feld_modell)
        formular.addRow("Standardordner:", zeile_ordner)

        knoepfe = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        knoepfe.button(QDialogButtonBox.StandardButton.Ok).setText("Speichern")
        knoepfe.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        self.knopf_test = knoepfe.addButton(
            "Key testen", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.knopf_test.clicked.connect(self._teste_key)
        knoepfe.accepted.connect(self.accept)
        knoepfe.rejected.connect(self.reject)

        aussen = QVBoxLayout(self)
        aussen.addLayout(formular)
        aussen.addWidget(knoepfe)

    def _waehle_ordner(self) -> None:
        ordner = QFileDialog.getExistingDirectory(
            self, "Standardordner wählen", self.feld_ordner.text() or str(Path.home())
        )
        if ordner:
            self.feld_ordner.setText(ordner)

    def _teste_key(self) -> None:
        self.knopf_test.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            api.teste_verbindung(self.feld_key.text())
        except api.ApiFehler as fehler:
            QMessageBox.warning(self, "Test fehlgeschlagen", str(fehler))
        else:
            QMessageBox.information(
                self, "Test erfolgreich", "Der API-Key funktioniert."
            )
        finally:
            QApplication.restoreOverrideCursor()
            self.knopf_test.setEnabled(True)

    def accept(self) -> None:
        try:
            settings.save_api_key(self.feld_key.text())
        except settings.SchluesselspeicherFehler as fehler:
            QMessageBox.critical(self, "Passwortspeicher", str(fehler))
            return
        self._konfig.model = self.feld_modell.currentData()
        self._konfig.save_dir = self.feld_ordner.text().strip()
        self._konfig.save()
        super().accept()


# --------------------------------------------------------------------------
# API-Anfrage im Hintergrund
# --------------------------------------------------------------------------

class ApiWorker(QObject):
    """Führt einen API-Aufruf aus, ohne das Fenster zu blockieren."""

    teilcode = Signal(str)
    fertig = Signal(object)
    fehler = Signal(str)
    abgebrochen = Signal()

    def __init__(self, aufruf: Callable[..., api.Programm]) -> None:
        super().__init__()
        self._aufruf = aufruf
        self._abbruch = threading.Event()

    def abbrechen(self) -> None:
        self._abbruch.set()

    @Slot()
    def arbeite(self) -> None:
        try:
            programm = self._aufruf(
                on_code=self.teilcode.emit, abbrechen=self._abbruch.is_set
            )
        except api.Abgebrochen:
            self.abgebrochen.emit()
        except api.ApiFehler as fehler:
            self.fehler.emit(str(fehler))
        except Exception as fehler:  # letzte Rettungsleine
            self.fehler.emit(f"Unerwarteter Fehler: {fehler}")
        else:
            self.fertig.emit(programm)


# --------------------------------------------------------------------------
# Hauptfenster
# --------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Ein Fenster mit drei Bereichen: Aufgabe, Code, Erklärung."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 700)

        self.konfig = settings.Settings.load()
        self.datei: Path | None = None
        self.vorschlag = "programm.py"
        self._thread: QThread | None = None
        self._worker: ApiWorker | None = None

        self.lauf = runner.Ausfuehrung(self)
        self.lauf.ausgabe.connect(self._lauf_ausgabe)
        self.lauf.beendet.connect(self._lauf_beendet)
        self._lauf_puffer = ""
        self._lauf_art = "programm"

        self._baue_oberflaeche()
        self._baue_menue()
        self._baue_statusleiste()
        self._zeige_laufzustand(False)

        QTimer.singleShot(0, self._erster_start)

    # -- Aufbau ------------------------------------------------------------

    def _baue_oberflaeche(self) -> None:
        teiler = QSplitter(Qt.Orientation.Vertical)
        teiler.addWidget(self._bereich_aufgabe())
        teiler.addWidget(self._bereich_code())
        teiler.addWidget(self._bereich_erklaerung())
        teiler.setStretchFactor(0, 0)
        teiler.setStretchFactor(1, 1)
        teiler.setStretchFactor(2, 0)
        teiler.setSizes([150, 350, 200])
        self.setCentralWidget(teiler)

    def _bereich_aufgabe(self) -> QWidget:
        kasten = QGroupBox("1. Was soll das Programm tun?")

        self.feld_aufgabe = QPlainTextEdit()
        self.feld_aufgabe.setPlaceholderText(
            "Zum Beispiel: Schreibe ein Programm, das die Zahlen 1 bis 10 ausgibt."
        )

        self.knopf_erstellen = QPushButton("Programm erstellen")
        self.knopf_erstellen.setDefault(True)
        self.knopf_erstellen.clicked.connect(self._erstelle_programm)

        self.knopf_abbrechen = QPushButton("Abbrechen")
        self.knopf_abbrechen.clicked.connect(self._brich_anfrage_ab)
        self.knopf_abbrechen.setVisible(False)

        zeile = QHBoxLayout()
        zeile.addStretch(1)
        zeile.addWidget(self.knopf_abbrechen)
        zeile.addWidget(self.knopf_erstellen)

        aussen = QVBoxLayout(kasten)
        aussen.addWidget(self.feld_aufgabe)
        aussen.addLayout(zeile)
        return kasten

    def _bereich_code(self) -> QWidget:
        kasten = QGroupBox("2. Python-Code")

        self.feld_code = CodeEditor()
        self.feld_code.setPlaceholderText(
            "Hier erscheint der Code, sobald du oben auf «Programm erstellen» klickst."
        )

        self.knopf_speichern = QPushButton("Speichern")
        self.knopf_speichern.clicked.connect(self._speichere)
        self.knopf_ausfuehren = QPushButton("Ausführen")
        self.knopf_ausfuehren.clicked.connect(self._fuehre_aus)
        self.knopf_stoppen = QPushButton("Stoppen")
        self.knopf_stoppen.clicked.connect(self.lauf.stoppe)
        self.knopf_kopieren = QPushButton("Kopieren")
        self.knopf_kopieren.clicked.connect(self._kopiere)

        self.label_datei = QLabel("noch nicht gespeichert")
        self.label_datei.setStyleSheet("color: gray;")

        zeile = QHBoxLayout()
        zeile.addWidget(self.knopf_speichern)
        zeile.addWidget(self.knopf_ausfuehren)
        zeile.addWidget(self.knopf_stoppen)
        zeile.addWidget(self.knopf_kopieren)
        zeile.addSpacing(12)
        zeile.addWidget(self.label_datei, 1)

        aussen = QVBoxLayout(kasten)
        aussen.addWidget(self.feld_code)
        aussen.addLayout(zeile)
        return kasten

    def _bereich_erklaerung(self) -> QWidget:
        kasten = QGroupBox("3. Erklärung, Ausgabe und Änderungen")

        self.feld_erklaerung = QPlainTextEdit()
        self.feld_erklaerung.setReadOnly(True)
        self.feld_erklaerung.setPlaceholderText(
            "Hier steht in wenigen Sätzen, was das Programm macht."
        )

        self.feld_ausgabe = QPlainTextEdit()
        self.feld_ausgabe.setReadOnly(True)
        self.feld_ausgabe.setFont(monospace_font(10))
        self.feld_ausgabe.setPlaceholderText(
            "Hier erscheint, was das Programm ausgibt."
        )

        self.feld_eingabe = QLineEdit()
        self.feld_eingabe.setPlaceholderText(
            "Eingabe an das laufende Programm – mit Enter abschicken"
        )
        self.feld_eingabe.returnPressed.connect(self._sende_eingabe)
        self.knopf_senden = QPushButton("Senden")
        self.knopf_senden.clicked.connect(self._sende_eingabe)

        zeile_eingabe = QHBoxLayout()
        zeile_eingabe.addWidget(self.feld_eingabe, 1)
        zeile_eingabe.addWidget(self.knopf_senden)

        seite_ausgabe = QWidget()
        aussen_ausgabe = QVBoxLayout(seite_ausgabe)
        aussen_ausgabe.setContentsMargins(0, 0, 0, 0)
        aussen_ausgabe.addWidget(self.feld_ausgabe)
        aussen_ausgabe.addLayout(zeile_eingabe)

        self.reiter = QTabWidget()
        self.reiter.addTab(self.feld_erklaerung, "Erklärung")
        self.reiter.addTab(seite_ausgabe, "Ausgabe")

        self.feld_aenderung = QPlainTextEdit()
        self.feld_aenderung.setPlaceholderText(
            "Was soll anders sein? Zum Beispiel: Gib die Zahlen rückwärts aus."
        )
        self.feld_aenderung.setMaximumHeight(70)

        self.knopf_aendern = QPushButton("Ändern")
        self.knopf_aendern.clicked.connect(self._aendere_programm)

        zeile_aendern = QHBoxLayout()
        zeile_aendern.addWidget(self.feld_aenderung, 1)
        zeile_aendern.addWidget(self.knopf_aendern, 0, Qt.AlignmentFlag.AlignBottom)

        aussen = QVBoxLayout(kasten)
        aussen.addWidget(self.reiter)
        aussen.addLayout(zeile_aendern)
        return kasten

    def _baue_menue(self) -> None:
        menue_einstellungen = self.menuBar().addMenu("&Einstellungen")
        aktion = QAction("Einstellungen …", self)
        aktion.setShortcut("Ctrl+,")
        aktion.triggered.connect(self._oeffne_einstellungen)
        menue_einstellungen.addAction(aktion)

        self.menue_verlauf = self.menuBar().addMenu("&Verlauf")
        self.menue_verlauf.aboutToShow.connect(self._fuelle_verlauf)

        menue_hilfe = self.menuBar().addMenu("&Hilfe")
        aktion_repo = QAction("Projektseite öffnen", self)
        aktion_repo.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(REPO_URL))
        )
        menue_hilfe.addAction(aktion_repo)
        aktion_key = QAction("API-Key holen (console.anthropic.com)", self)
        aktion_key.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(CONSOLE_URL))
        )
        menue_hilfe.addAction(aktion_key)
        menue_hilfe.addSeparator()
        aktion_ueber = QAction(f"Über {APP_NAME}", self)
        aktion_ueber.triggered.connect(self._zeige_ueber)
        menue_hilfe.addAction(aktion_ueber)

    def _baue_statusleiste(self) -> None:
        self.label_modell = QLabel()
        self.label_verbindung = QLabel("Bereit")
        self.label_fehler = QLabel("")
        self.label_fehler.setStyleSheet("color: #c0392b;")

        leiste = self.statusBar()
        leiste.addWidget(self.label_modell)
        leiste.addWidget(QLabel("|"))
        leiste.addWidget(self.label_verbindung)
        leiste.addPermanentWidget(self.label_fehler)
        self._zeige_modell()

    # -- kleine Helfer -----------------------------------------------------

    def _zeige_modell(self) -> None:
        self.label_modell.setText(
            f"Modell: {settings.model_short_label(self.konfig.model)}"
        )

    def _setze_status(self, text: str) -> None:
        self.label_verbindung.setText(text)

    def _setze_fehler(self, text: str = "") -> None:
        self.label_fehler.setText(text)

    def _erster_start(self) -> None:
        """Beim allerersten Start gleich nach dem API-Key fragen."""
        try:
            key = settings.load_api_key()
        except settings.SchluesselspeicherFehler as fehler:
            QMessageBox.warning(self, "Passwortspeicher", str(fehler))
            return
        if not key:
            QMessageBox.information(
                self,
                f"Willkommen bei {APP_NAME}",
                "Damit die App Programme schreiben kann, braucht sie einen "
                "API-Key von Anthropic. Trage ihn im nächsten Fenster ein – "
                "du bekommst ihn auf console.anthropic.com.",
            )
            self._oeffne_einstellungen()

    def _oeffne_einstellungen(self) -> None:
        dialog = EinstellungenDialog(self.konfig, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._zeige_modell()
            self._setze_status("Einstellungen gespeichert")

    def _zeige_ueber(self) -> None:
        QMessageBox.about(
            self,
            f"Über {APP_NAME}",
            f"<pre>{ASCII_LOGO}</pre>"
            f"<b>{APP_NAME} {__version__}</b>"
            "<p>Beschreibe ein Programm in normaler Sprache – "
            "die App schreibt den Python-Code dazu.</p>"
            "<p>Achtung: erzeugter Code läuft ungeschützt auf deinem Rechner.</p>"
            f'<p><a href="{REPO_URL}">{REPO_URL}</a></p>',
        )

    def _fuelle_verlauf(self) -> None:
        """Die zuletzt gestellten Aufgaben als Menü."""
        self.menue_verlauf.clear()
        if not self.konfig.history:
            leer = QAction("(noch nichts)", self)
            leer.setEnabled(False)
            self.menue_verlauf.addAction(leer)
            return
        for aufgabe in self.konfig.history:
            kurz = aufgabe.replace("\n", " ")
            beschriftung = kurz if len(kurz) <= 70 else kurz[:67] + "…"
            aktion = QAction(beschriftung, self)
            aktion.setToolTip(aufgabe)
            aktion.triggered.connect(
                lambda _=False, text=aufgabe: self.feld_aufgabe.setPlainText(text)
            )
            self.menue_verlauf.addAction(aktion)
        self.menue_verlauf.addSeparator()
        loeschen = QAction("Verlauf löschen", self)
        loeschen.triggered.connect(self._loesche_verlauf)
        self.menue_verlauf.addAction(loeschen)

    def _loesche_verlauf(self) -> None:
        self.konfig.history = []
        self.konfig.save()

    # -- Anfragen an die API ----------------------------------------------

    def _erstelle_programm(self) -> None:
        aufgabe = self.feld_aufgabe.toPlainText().strip()
        if not aufgabe:
            QMessageBox.information(
                self, APP_NAME, "Beschreibe zuerst, was das Programm tun soll."
            )
            return
        self.konfig.remember_task(aufgabe)
        self.konfig.save()
        self._starte_anfrage(
            lambda **kw: api.erzeuge(aufgabe, self.konfig.model, self._key(), **kw),
            "Das Programm wird geschrieben …",
        )

    def _aendere_programm(self) -> None:
        wunsch = self.feld_aenderung.toPlainText().strip()
        code = self.feld_code.toPlainText().strip()
        if not code:
            QMessageBox.information(
                self, APP_NAME, "Es gibt noch keinen Code, der geändert werden könnte."
            )
            return
        if not wunsch:
            QMessageBox.information(
                self, APP_NAME, "Beschreibe zuerst, was am Programm anders sein soll."
            )
            return
        self._starte_anfrage(
            lambda **kw: api.verbessere(
                code, wunsch, self.konfig.model, self._key(), **kw
            ),
            "Das Programm wird geändert …",
        )

    def _key(self) -> str:
        try:
            return settings.load_api_key() or ""
        except settings.SchluesselspeicherFehler as fehler:
            raise api.ApiFehler(str(fehler)) from fehler

    def _starte_anfrage(self, aufruf, statustext: str) -> None:
        if self._thread is not None:
            return  # es läuft schon eine Anfrage

        self._setze_fehler()
        self._setze_status(statustext)
        self._zeige_anfragezustand(True)
        self.feld_code.setPlainText("")
        self.feld_erklaerung.setPlainText("")

        self._worker = ApiWorker(aufruf)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.arbeite)
        self._worker.teilcode.connect(self._zeige_teilcode)
        self._worker.fertig.connect(self._anfrage_fertig)
        self._worker.fehler.connect(self._anfrage_fehler)
        self._worker.abgebrochen.connect(self._anfrage_abgebrochen)
        self._thread.start()

    def _brich_anfrage_ab(self) -> None:
        if self._worker is not None:
            self._worker.abbrechen()
            self._setze_status("Wird abgebrochen …")

    def _beende_anfrage(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._zeige_anfragezustand(False)

    @Slot(str)
    def _zeige_teilcode(self, code: str) -> None:
        """Zeigt den Code, während er geschrieben wird."""
        self.feld_code.setPlainText(code)
        self.feld_code.verticalScrollBar().setValue(
            self.feld_code.verticalScrollBar().maximum()
        )

    @Slot(object)
    def _anfrage_fertig(self, programm: api.Programm) -> None:
        self.feld_code.setPlainText(programm.code)
        self.feld_erklaerung.setPlainText(programm.explanation)
        self.vorschlag = programm.filename
        self.datei = None
        self.label_datei.setText(f"Vorschlag: {programm.filename} (nicht gespeichert)")
        self.reiter.setCurrentIndex(0)
        self.feld_aenderung.clear()
        self._setze_status("Fertig")
        self._beende_anfrage()

    @Slot(str)
    def _anfrage_fehler(self, meldung: str) -> None:
        self._setze_status("Fehlgeschlagen")
        self._setze_fehler(meldung.split("\n")[0][:120])
        self._beende_anfrage()
        QMessageBox.warning(self, "Das hat nicht geklappt", meldung)

    @Slot()
    def _anfrage_abgebrochen(self) -> None:
        self._setze_status("Abgebrochen")
        self._beende_anfrage()

    def _zeige_anfragezustand(self, laeuft: bool) -> None:
        self.knopf_erstellen.setVisible(not laeuft)
        self.knopf_abbrechen.setVisible(laeuft)
        self.knopf_aendern.setEnabled(not laeuft)
        self.feld_code.setReadOnly(laeuft)

    # -- Speichern und Kopieren -------------------------------------------

    def _kopiere(self) -> None:
        code = self.feld_code.toPlainText()
        if not code.strip():
            return
        QApplication.clipboard().setText(code)
        self._setze_status("Code in die Zwischenablage kopiert")

    def _speichere(self) -> Path | None:
        code = self.feld_code.toPlainText()
        if not code.strip():
            QMessageBox.information(self, APP_NAME, "Es gibt noch keinen Code.")
            return None

        start = self.datei or (self.konfig.default_save_dir() / self.vorschlag)
        pfad, _ = QFileDialog.getSaveFileName(
            self, "Programm speichern", str(start), "Python-Dateien (*.py)"
        )
        if not pfad:
            return None

        ziel = Path(pfad)
        if ziel.suffix.lower() != ".py":
            ziel = ziel.with_suffix(".py")
        try:
            ziel.write_text(_mit_zeilenende(code), encoding="utf-8")
        except OSError as fehler:
            QMessageBox.critical(
                self, "Speichern fehlgeschlagen",
                f"Die Datei konnte nicht geschrieben werden:\n{fehler}",
            )
            return None

        self.datei = ziel
        self.vorschlag = ziel.name
        self.konfig.save_dir = str(ziel.parent)
        self.konfig.save()
        self.label_datei.setText(f"Gespeichert: {ziel}")
        self._setze_status(f"Gespeichert unter {ziel}")
        return ziel

    # -- Ausführen ---------------------------------------------------------

    def _fuehre_aus(self) -> None:
        code = self.feld_code.toPlainText()
        if not code.strip():
            QMessageBox.information(self, APP_NAME, "Es gibt noch keinen Code.")
            return
        if self.lauf.laeuft():
            QMessageBox.information(
                self, APP_NAME, "Es läuft bereits ein Programm. Stoppe es zuerst."
            )
            return
        if not self._warnung_bestaetigt():
            return

        python = runner.finde_python(erneut=True)
        if python is None:
            self._kein_python()
            return

        ziel = self._datei_zum_ausfuehren(code)
        if ziel is None:
            return

        self.feld_ausgabe.clear()
        self._lauf_puffer = ""
        self._lauf_art = "programm"
        self.reiter.setCurrentIndex(1)
        self._zeige_laufzustand(True)
        self._setze_status(f"Läuft mit {' '.join(python)}")
        self.lauf.starte_skript(python, ziel)

    def _warnung_bestaetigt(self) -> bool:
        """Einmalige Warnung vor dem ersten Ausführen."""
        if self.konfig.run_warning_acknowledged:
            return True
        antwort = QMessageBox.warning(
            self,
            "Bevor du Code ausführst",
            WARNUNG_AUSFUEHREN
            + "\n\nEs gibt keine Sandbox: Das Programm darf alles, was du "
            "auch darfst – Dateien lesen, schreiben und löschen.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if antwort != QMessageBox.StandardButton.Ok:
            return False
        self.konfig.run_warning_acknowledged = True
        self.konfig.save()
        return True

    def _kein_python(self) -> None:
        QMessageBox.critical(
            self,
            "Python nicht gefunden",
            "Auf diesem Rechner wurde kein Python gefunden. Der Code lässt "
            "sich deshalb nicht ausführen.\n\n"
            f"Installiere Python von {runner.PYTHON_DOWNLOAD} und setze bei "
            "der Installation den Haken bei «Add python.exe to PATH».",
        )
        QDesktopServices.openUrl(QUrl(runner.PYTHON_DOWNLOAD))

    def _datei_zum_ausfuehren(self, code: str) -> Path | None:
        """Die Datei, die gestartet wird – notfalls eine Arbeitskopie."""
        if self.datei is not None:
            try:
                self.datei.write_text(_mit_zeilenende(code), encoding="utf-8")
            except OSError as fehler:
                QMessageBox.critical(
                    self, "Speichern fehlgeschlagen", str(fehler)
                )
                return None
            return self.datei

        ordner = settings.config_dir() / "arbeitskopie"
        try:
            ordner.mkdir(parents=True, exist_ok=True)
            ziel = ordner / self.vorschlag
            ziel.write_text(_mit_zeilenende(code), encoding="utf-8")
        except OSError as fehler:
            QMessageBox.critical(
                self, "Ausführen fehlgeschlagen",
                "Für das Ausführen wird eine Arbeitskopie gebraucht, die sich "
                f"nicht anlegen liess:\n{fehler}\n\nSpeichere den Code zuerst.",
            )
            return None
        return ziel

    def _zeige_laufzustand(self, laeuft: bool) -> None:
        self.knopf_stoppen.setEnabled(laeuft)
        self.knopf_ausfuehren.setEnabled(not laeuft)
        self.feld_eingabe.setEnabled(laeuft)
        self.knopf_senden.setEnabled(laeuft)

    def _sende_eingabe(self) -> None:
        if not self.lauf.laeuft():
            return
        text = self.feld_eingabe.text()
        self.lauf.sende_eingabe(text)
        self._schreibe_ausgabe(text + "\n")
        self.feld_eingabe.clear()

    @Slot(str)
    def _lauf_ausgabe(self, text: str) -> None:
        self._lauf_puffer += text
        self._schreibe_ausgabe(text)

    def _schreibe_ausgabe(self, text: str) -> None:
        self.feld_ausgabe.moveCursor(self.feld_ausgabe.textCursor().MoveOperation.End)
        self.feld_ausgabe.insertPlainText(text)
        self.feld_ausgabe.ensureCursorVisible()

    @Slot(int)
    def _lauf_beendet(self, code: int) -> None:
        self._zeige_laufzustand(False)
        if self._lauf_art == "pip":
            # Nach einer Installation nicht noch einmal dieselbe Frage stellen.
            self._lauf_art = "programm"
            if code == 0:
                self._schreibe_ausgabe(
                    "\n[Modul installiert. Klicke noch einmal auf «Ausführen».]\n"
                )
                self._setze_status("Modul installiert")
            else:
                self._schreibe_ausgabe(
                    f"\n[Die Installation ist fehlgeschlagen (Code {code}).]\n"
                )
                self._setze_status("Installation fehlgeschlagen")
            return

        if code == 0:
            self._schreibe_ausgabe("\n[Programm beendet.]\n")
            self._setze_status("Programm beendet")
        else:
            self._schreibe_ausgabe(f"\n[Programm mit Fehler beendet (Code {code}).]\n")
            self._setze_status(f"Programm mit Fehler beendet (Code {code})")
        self._biete_modul_an()

    def _biete_modul_an(self) -> None:
        """Fehlt ein Modul, wird die Installation angeboten."""
        modul = runner.fehlendes_modul(self._lauf_puffer)
        if not modul:
            return

        if not runner.mit_pip_installierbar(modul):
            QMessageBox.information(
                self,
                "Modul fehlt",
                f"Das Programm braucht «{modul}».\n\n"
                + runner.rat_zu_modul(modul),
            )
            return

        antwort = QMessageBox.question(
            self,
            "Modul fehlt",
            f"Das Programm braucht das Zusatzmodul «{modul}», das auf diesem "
            "Rechner nicht installiert ist.\n\n"
            f"Soll es jetzt mit «pip install {modul}» nachinstalliert werden?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if antwort != QMessageBox.StandardButton.Yes:
            return
        python = runner.finde_python()
        if python is None:
            self._kein_python()
            return
        self._lauf_puffer = ""
        self._lauf_art = "pip"
        self._schreibe_ausgabe(f"\n[Installiere {modul} …]\n")
        self._zeige_laufzustand(True)
        self.lauf.starte_pip_install(python, modul, Path.home())

    # -- Fenster schliessen ------------------------------------------------

    def closeEvent(self, ereignis) -> None:  # noqa: N802 (Qt-Name)
        self.lauf.stoppe()
        if self._worker is not None:
            self._worker.abbrechen()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self.konfig.save()
        super().closeEvent(ereignis)


def _mit_zeilenende(text: str) -> str:
    """Sorgt für genau ein Zeilenende am Dateiende."""
    return text.rstrip("\n") + "\n"


def run() -> int:
    """Startet die Anwendung und liefert den Exit-Code."""
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_SLUG)

    icon_pfad = settings.resource_path("assets/icon.ico")
    if icon_pfad.exists():
        app.setWindowIcon(QIcon(str(icon_pfad)))

    fenster = MainWindow()
    fenster.show()

    # Selbsttest für den Build: prüft die Teile, die beim Packen gern
    # verloren gehen, und beendet sich sofort wieder.
    if os.environ.get("JIMBO_SELFTEST"):
        probleme = selbsttest(fenster)
        if probleme:
            print("Selbsttest fehlgeschlagen:", "; ".join(probleme))
            return 2
        QTimer.singleShot(0, app.quit)

    return app.exec()


def selbsttest(fenster: MainWindow) -> list[str]:
    """Prüft in der gepackten Anwendung, ob alles Nötige mitgekommen ist."""
    probleme: list[str] = []

    if not settings.resource_path("assets/icon.ico").exists():
        probleme.append("Das Symbol assets/icon.ico fehlt im Paket.")

    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            probleme.append("keyring findet keinen Passwortspeicher.")
    except Exception as fehler:  # pragma: no cover - nur im Paket relevant
        probleme.append(f"keyring liess sich nicht laden: {fehler}")

    try:
        import anthropic

        if not anthropic.__version__:
            probleme.append("Das Anthropic-SDK meldet keine Version.")
    except Exception as fehler:  # pragma: no cover - nur im Paket relevant
        probleme.append(f"Das Anthropic-SDK liess sich nicht laden: {fehler}")

    for name in ("feld_aufgabe", "feld_code", "feld_erklaerung", "feld_aenderung"):
        if getattr(fenster, name, None) is None:
            probleme.append(f"Das Feld {name} fehlt in der Oberfläche.")

    return probleme
