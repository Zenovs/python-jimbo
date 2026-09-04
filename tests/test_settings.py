"""Tests für die Einstellungen und das Projektgerüst (Etappe 1)."""

from __future__ import annotations

import jimbo
from jimbo import settings


def test_standardmodell_ist_in_der_liste():
    ids = [model_id for _, model_id in settings.MODELS]
    assert settings.DEFAULT_MODEL in ids


def test_modell_anzeigename():
    assert "Sonnet" in settings.model_label("claude-sonnet-5")
    # Unbekannte IDs werden unverändert durchgereicht.
    assert settings.model_label("gibt-es-nicht") == "gibt-es-nicht"


def test_konfigordner_traegt_den_app_namen(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert settings.config_dir().name == jimbo.APP_SLUG


def test_icon_liegt_im_projekt():
    assert settings.resource_path("assets/icon.ico").exists()


def test_ascii_logo_ist_rechteckig():
    zeilen = jimbo.ASCII_LOGO.strip("\n").splitlines()
    assert len(zeilen) > 5
    assert all(set(z) <= set("#: ") for z in zeilen)
