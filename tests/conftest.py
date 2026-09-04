"""Gemeinsame Vorbereitungen für alle Tests."""

from __future__ import annotations

import os

import pytest

# Qt ohne Bildschirm betreiben – muss vor dem ersten Qt-Import gesetzt sein.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def eigener_konfigordner(tmp_path, monkeypatch):
    """Tests schreiben nie in den echten Einstellungsordner des Nutzers."""
    ordner = tmp_path / "konfig"
    ordner.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(ordner))
    monkeypatch.setenv("APPDATA", str(ordner))
    return ordner


@pytest.fixture(autouse=True)
def kein_echter_schluesselspeicher(monkeypatch):
    """Kein Test darf an den Passwortspeicher des Betriebssystems."""
    speicher: dict[tuple[str, str], str] = {}

    def get(service, user):
        return speicher.get((service, user))

    def setze(service, user, wert):
        speicher[(service, user)] = wert

    def loesche(service, user):
        speicher.pop((service, user), None)

    monkeypatch.setattr("keyring.get_password", get)
    monkeypatch.setattr("keyring.set_password", setze)
    monkeypatch.setattr("keyring.delete_password", loesche)
    return speicher
