"""Einstellungen von Jiimbos Power App: Modelle, Pfade, API-Key.

Der API-Key wird NIE in einer Datei im Projektordner gespeichert, sondern
über `keyring` im Anmeldeinformationsspeicher des Betriebssystems
(Windows: Anmeldeinformationsverwaltung, macOS: Schlüsselbund).
Alles andere (gewähltes Modell, Standardordner, Verlauf) landet als JSON in
einer Datei im Benutzerprofil – dort steht kein Geheimnis drin.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import keyring
from keyring.errors import KeyringError

from . import APP_SLUG

# Auswahl der Modelle für das Dropdown in den Einstellungen.
# Neue Modelle können hier einfach ergänzt werden: (Anzeigename, Modell-ID).
MODELS: list[tuple[str, str]] = [
    ("Claude Sonnet 5 – Standard, gutes Verhältnis von Preis und Qualität", "claude-sonnet-5"),
    ("Claude Opus 5 – stärker, aber teurer", "claude-opus-5"),
    ("Claude Haiku 4.5 – am schnellsten und günstigsten", "claude-haiku-4-5"),
]

DEFAULT_MODEL = "claude-sonnet-5"

# Name, unter dem der Schlüssel im Anmeldeinformationsspeicher abgelegt wird.
KEYRING_SERVICE = APP_SLUG
KEYRING_USERNAME = "anthropic-api-key"

MAX_HISTORY = 20


def model_label(model_id: str) -> str:
    """Anzeigename zu einer Modell-ID; unbekannte IDs werden durchgereicht."""
    for label, value in MODELS:
        if value == model_id:
            return label
    return model_id


def model_short_label(model_id: str) -> str:
    """Kurzer Name fürs Statusleisten-Feld, ohne die Erklärung dahinter."""
    return model_label(model_id).split(" – ")[0]


def config_dir() -> Path:
    """Ordner für die Einstellungsdatei.

    Windows: %APPDATA%\\JiimbosPowerApp,
    macOS/Linux: ~/.config/JiimbosPowerApp bzw. $XDG_CONFIG_HOME.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_SLUG
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        if base:
            return Path(base) / APP_SLUG
    return Path.home() / ".config" / APP_SLUG


def settings_file() -> Path:
    return config_dir() / "einstellungen.json"


def resource_path(relative: str) -> Path:
    """Pfad zu einer mitgelieferten Datei (z. B. dem Icon).

    Funktioniert sowohl im Quellcode-Betrieb als auch in der von PyInstaller
    gepackten .exe, die ihre Dateien in einen temporären Ordner entpackt.
    """
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir) / relative
    return Path(__file__).resolve().parents[2] / relative


# --------------------------------------------------------------------------
# API-Key im Anmeldeinformationsspeicher
# --------------------------------------------------------------------------

class SchluesselspeicherFehler(RuntimeError):
    """Der Anmeldeinformationsspeicher des Systems ist nicht ansprechbar."""


def load_api_key() -> str | None:
    """Liest den API-Key. None, wenn noch keiner hinterlegt ist."""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) or None
    except KeyringError as fehler:
        raise SchluesselspeicherFehler(
            "Der Passwortspeicher des Betriebssystems konnte nicht gelesen "
            "werden. Der API-Key lässt sich deshalb nicht laden."
        ) from fehler


def save_api_key(key: str) -> None:
    """Legt den API-Key im Passwortspeicher ab (ein leerer Wert löscht ihn)."""
    try:
        if key.strip():
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key.strip())
        else:
            delete_api_key()
    except KeyringError as fehler:
        raise SchluesselspeicherFehler(
            "Der API-Key konnte nicht im Passwortspeicher des Betriebssystems "
            "gespeichert werden."
        ) from fehler


def delete_api_key() -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass  # war gar nicht gesetzt – kein Grund zur Aufregung
    except KeyringError as fehler:
        raise SchluesselspeicherFehler(
            "Der API-Key konnte nicht gelöscht werden."
        ) from fehler


# --------------------------------------------------------------------------
# Übrige Einstellungen als JSON-Datei
# --------------------------------------------------------------------------

@dataclass
class Settings:
    """Alles ausser dem API-Key. Wird als JSON im Benutzerprofil abgelegt."""

    model: str = DEFAULT_MODEL
    save_dir: str = ""
    run_warning_acknowledged: bool = False
    history: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Settings":
        """Liest die Einstellungen; bei Problemen gelten die Standardwerte."""
        try:
            daten = json.loads(settings_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(daten, dict):
            return cls()

        bekannt = {f for f in cls.__dataclass_fields__}
        gefiltert = {k: v for k, v in daten.items() if k in bekannt}
        einstellungen = cls(**gefiltert)
        # Ein von Hand verfälschtes Modell darf die App nicht lahmlegen.
        if not isinstance(einstellungen.model, str) or not einstellungen.model:
            einstellungen.model = DEFAULT_MODEL
        if not isinstance(einstellungen.history, list):
            einstellungen.history = []
        einstellungen.history = [h for h in einstellungen.history if isinstance(h, str)]
        return einstellungen

    def save(self) -> None:
        """Schreibt die Einstellungen. Fehler werden bewusst verschluckt –
        die App soll deswegen nicht abstürzen."""
        try:
            config_dir().mkdir(parents=True, exist_ok=True)
            settings_file().write_text(
                json.dumps(self.__dict__, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def remember_task(self, aufgabe: str) -> None:
        """Merkt sich eine Aufgabe im Verlauf (die letzten 20, ohne Doppelte)."""
        text = aufgabe.strip()
        if not text:
            return
        self.history = [h for h in self.history if h != text]
        self.history.insert(0, text)
        del self.history[MAX_HISTORY:]

    def default_save_dir(self) -> Path:
        """Ordner, den der Speichern-Dialog vorschlägt."""
        if self.save_dir and Path(self.save_dir).is_dir():
            return Path(self.save_dir)
        return Path.home()
