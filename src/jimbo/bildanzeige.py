"""Zeigt ein Bild an, das ein erzeugtes Programm gezeichnet hat.

Das Bild wird immer so gross dargestellt, wie es der Platz erlaubt – aber nie
grösser als das Original, damit ein kleines Diagramm nicht verpixelt.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

HINWEIS = (
    "Hier erscheint das Bild, sobald ein Programm eines zeichnet –\n"
    "zum Beispiel ein Diagramm mit matplotlib."
)


class _Bildflaeche(QLabel):
    """Ein Bild, das sich per Doppelklick gross öffnen lässt."""

    doppelklick = Signal()

    def mouseDoubleClickEvent(self, ereignis) -> None:  # noqa: N802 (Qt-Name)
        super().mouseDoubleClickEvent(ereignis)
        self.doppelklick.emit()


class Bildanzeige(QWidget):
    """Ein Reiter, der das zuletzt erzeugte Bild zeigt."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pfad: Path | None = None
        self._pixmap: QPixmap | None = None

        self._bild = _Bildflaeche(HINWEIS)
        self._bild.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bild.setStyleSheet("color: gray;")
        self._bild.setToolTip(
            "Doppelklick öffnet das Bild in voller Grösse im Standardprogramm."
        )
        self._bild.doppelklick.connect(self._oeffne_extern)

        self._flaeche = QScrollArea()
        self._flaeche.setWidget(self._bild)
        self._flaeche.setWidgetResizable(True)
        self._flaeche.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._name = QLabel("")
        self._name.setStyleSheet("color: gray;")
        self._knopf_oeffnen = QPushButton("Im Standardprogramm öffnen")
        self._knopf_oeffnen.setEnabled(False)
        self._knopf_oeffnen.clicked.connect(self._oeffne_extern)

        zeile = QHBoxLayout()
        zeile.addWidget(self._name, 1)
        zeile.addWidget(self._knopf_oeffnen)

        aussen = QVBoxLayout(self)
        aussen.setContentsMargins(0, 0, 0, 0)
        aussen.addWidget(self._flaeche, 1)
        aussen.addLayout(zeile)

    # -- öffentlich --------------------------------------------------------

    @property
    def pfad(self) -> Path | None:
        """Das gerade gezeigte Bild, falls es eines gibt."""
        return self._pfad

    def zeige(self, pfad: Path) -> bool:
        """Zeigt das Bild. False, wenn es sich nicht darstellen liess."""
        pixmap = QPixmap(str(pfad))
        if pixmap.isNull():
            # Zum Beispiel SVG ohne passendes Qt-Modul: wenigstens anbieten,
            # die Datei im Standardprogramm zu öffnen.
            self._pfad = pfad
            self._pixmap = None
            self._bild.setPixmap(QPixmap())
            self._bild.setText(
                f"«{pfad.name}» wurde erzeugt, lässt sich hier aber nicht "
                "anzeigen."
            )
            self._name.setText(str(pfad))
            self._knopf_oeffnen.setEnabled(True)
            return False

        self._pfad = pfad
        self._pixmap = pixmap
        self._bild.setStyleSheet("")
        self._name.setText(f"{pfad.name}  ({pixmap.width()} × {pixmap.height()} Punkte)")
        self._knopf_oeffnen.setEnabled(True)
        self._passe_an()
        return True

    def leeren(self) -> None:
        self._pfad = None
        self._pixmap = None
        self._bild.setPixmap(QPixmap())
        self._bild.setStyleSheet("color: gray;")
        self._bild.setText(HINWEIS)
        self._name.setText("")
        self._knopf_oeffnen.setEnabled(False)

    # -- intern ------------------------------------------------------------

    def _oeffne_extern(self) -> None:
        if self._pfad is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._pfad)))

    def _passe_an(self) -> None:
        """Skaliert das Bild auf den sichtbaren Platz, aber nie hinauf."""
        if self._pixmap is None:
            return
        sichtbar = self._flaeche.viewport().size()
        breite = max(60, sichtbar.width() - 8)
        hoehe = max(60, sichtbar.height() - 8)
        if self._pixmap.width() <= breite and self._pixmap.height() <= hoehe:
            self._bild.setPixmap(self._pixmap)
            return
        self._bild.setPixmap(
            self._pixmap.scaled(
                breite, hoehe,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, ereignis) -> None:  # noqa: N802 (Qt-Name)
        super().resizeEvent(ereignis)
        self._passe_an()

    def showEvent(self, ereignis) -> None:  # noqa: N802 (Qt-Name)
        # Ein Reiter im Hintergrund kennt seine Groesse noch nicht - erst wenn
        # er sichtbar wird, laesst sich richtig skalieren.
        super().showEvent(ereignis)
        self._passe_an()
