"""Das Code-Feld: Schrift mit fester Breite, Zeilennummern, Einfärbung.

Die Farben richten sich danach, ob das System hell oder dunkel eingestellt ist.
"""

from __future__ import annotations

import builtins
import keyword

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextFormat,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget


def monospace_font(punkte: int = 11) -> QFont:
    """Schrift mit fester Zeichenbreite, wie sie für Code üblich ist."""
    schrift = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    schrift.setPointSize(punkte)
    return schrift


class PythonHighlighter(QSyntaxHighlighter):
    """Färbt Schlüsselwörter, Texte, Zahlen und Kommentare ein."""

    def __init__(self, dokument, dunkel: bool) -> None:
        super().__init__(dokument)

        def format_fuer(farbe: str, fett: bool = False, kursiv: bool = False):
            f = QTextCharFormat()
            f.setForeground(QColor(farbe))
            if fett:
                f.setFontWeight(QFont.Weight.Bold)
            f.setFontItalic(kursiv)
            return f

        if dunkel:
            schluessel, text, zahl, kommentar, eingebaut = (
                "#c792ea", "#c3e88d", "#f78c6c", "#7f848e", "#82aaff"
            )
        else:
            schluessel, text, zahl, kommentar, eingebaut = (
                "#7b1fa2", "#0b7c3f", "#b35c00", "#8a8f98", "#0b62c4"
            )

        self._schluesselwort = format_fuer(schluessel, fett=True)
        self._text = format_fuer(text)
        self._zahl = format_fuer(zahl)
        self._kommentar = format_fuer(kommentar, kursiv=True)
        self._eingebaut = format_fuer(eingebaut)

        self._schluesselwoerter = set(keyword.kwlist) | set(keyword.softkwlist)
        self._eingebaute = {n for n in dir(builtins) if not n.startswith("_")}

    def highlightBlock(self, zeile: str) -> None:  # noqa: N802 (Qt-Name)
        i = 0
        laenge = len(zeile)
        while i < laenge:
            zeichen = zeile[i]

            if zeichen == "#":
                self.setFormat(i, laenge - i, self._kommentar)
                return

            if zeichen in "\"'":
                i = self._faerbe_text(zeile, i)
                continue

            if zeichen.isdigit() and (i == 0 or not _wortzeichen(zeile[i - 1])):
                start = i
                while i < laenge and (zeile[i].isalnum() or zeile[i] in "._"):
                    i += 1
                self.setFormat(start, i - start, self._zahl)
                continue

            if zeichen.isalpha() or zeichen == "_":
                start = i
                while i < laenge and _wortzeichen(zeile[i]):
                    i += 1
                wort = zeile[start:i]
                if wort in self._schluesselwoerter:
                    self.setFormat(start, i - start, self._schluesselwort)
                elif wort in self._eingebaute:
                    self.setFormat(start, i - start, self._eingebaut)
                continue

            i += 1

    def _faerbe_text(self, zeile: str, start: int) -> int:
        """Färbt eine Zeichenkette ab `start` und liefert die Position danach."""
        anfuehrung = zeile[start]
        i = start + 1
        while i < len(zeile):
            if zeile[i] == "\\":
                i += 2
                continue
            if zeile[i] == anfuehrung:
                i += 1
                break
            i += 1
        self.setFormat(start, i - start, self._text)
        return i


def _wortzeichen(zeichen: str) -> bool:
    return zeichen.isalnum() or zeichen == "_"


class _Zeilennummern(QWidget):
    """Der schmale Streifen links neben dem Code."""

    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt-Name)
        return QSize(self._editor.breite_der_zeilennummern(), 0)

    def paintEvent(self, ereignis) -> None:  # noqa: N802 (Qt-Name)
        self._editor.zeichne_zeilennummern(ereignis)


class CodeEditor(QPlainTextEdit):
    """Ein Textfeld für Python-Code mit Zeilennummern."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(monospace_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))

        self._streifen = _Zeilennummern(self)
        dunkel = self.palette().base().color().lightness() < 128
        self._farbe_streifen = QColor("#2b2b2b") if dunkel else QColor("#f0f0f0")
        self._farbe_nummer = QColor("#888888")
        self._farbe_zeile = QColor("#3a3a3a") if dunkel else QColor("#eef4ff")
        self.highlighter = PythonHighlighter(self.document(), dunkel)

        self.blockCountChanged.connect(self._passe_rand_an)
        self.updateRequest.connect(self._aktualisiere_streifen)
        self.cursorPositionChanged.connect(self._hebe_zeile_hervor)
        self._passe_rand_an()
        self._hebe_zeile_hervor()

    # -- Zeilennummern -----------------------------------------------------

    def breite_der_zeilennummern(self) -> int:
        stellen = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * stellen

    def _passe_rand_an(self) -> None:
        self.setViewportMargins(self.breite_der_zeilennummern(), 0, 0, 0)

    def _aktualisiere_streifen(self, rechteck: QRect, dy: int) -> None:
        if dy:
            self._streifen.scroll(0, dy)
        else:
            self._streifen.update(
                0, rechteck.y(), self._streifen.width(), rechteck.height()
            )
        if rechteck.contains(self.viewport().rect()):
            self._passe_rand_an()

    def resizeEvent(self, ereignis) -> None:  # noqa: N802 (Qt-Name)
        super().resizeEvent(ereignis)
        inhalt = self.contentsRect()
        self._streifen.setGeometry(
            QRect(inhalt.left(), inhalt.top(),
                  self.breite_der_zeilennummern(), inhalt.height())
        )

    def zeichne_zeilennummern(self, ereignis) -> None:
        maler = QPainter(self._streifen)
        maler.fillRect(ereignis.rect(), self._farbe_streifen)
        maler.setPen(self._farbe_nummer)

        block = self.firstVisibleBlock()
        nummer = block.blockNumber()
        oben = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        unten = oben + self.blockBoundingRect(block).height()

        while block.isValid() and oben <= ereignis.rect().bottom():
            if block.isVisible() and unten >= ereignis.rect().top():
                maler.drawText(
                    0, int(oben), self._streifen.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, str(nummer + 1),
                )
            block = block.next()
            oben = unten
            unten = oben + self.blockBoundingRect(block).height()
            nummer += 1

    def _hebe_zeile_hervor(self) -> None:
        """Hinterlegt die Zeile, in der der Cursor steht."""
        auswahl = QTextEdit.ExtraSelection()
        auswahl.format.setBackground(self._farbe_zeile)
        auswahl.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        auswahl.cursor = self.textCursor()
        auswahl.cursor.clearSelection()
        self.setExtraSelections([auswahl])
