"""Aufruf der Anthropic-API: Prompt, Streaming und Auswertung der Antwort.

Das Modell antwortet mit einem JSON-Objekt aus Dateiname, Code und Erklärung.
Weil die Antwort im Stream eintrifft, kann der Code schon während des
Schreibens angezeigt werden – dafür sorgt `teilcode()`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

import anthropic

# Wie viele Token die Antwort höchstens lang sein darf. Ein Einsteiger-Programm
# braucht selten mehr als ein paar hundert; der Wert ist grosszügig gewählt.
MAX_TOKENS = 16_000

# Wie lange auf die API gewartet wird, bevor abgebrochen wird (Sekunden).
TIMEOUT_SEKUNDEN = 180.0

SYSTEM_PROMPT = """\
Du schreibst kurze Python-Programme für Menschen, die Python gerade erst lernen.

Antworte ausschliesslich mit einem JSON-Objekt in genau dieser Form:
{"filename": "...", "code": "...", "explanation": "..."}

Regeln:
- Kein Text vor oder nach dem JSON-Objekt, keine Markdown-Codeblöcke.
- "code": ein vollständiges, sofort lauffähiges Python-Programm. Verwende die
  Standardbibliothek. Externe Module nur, wenn die Aufgabe es wirklich
  verlangt; dann steht als allererste Zeile des Codes ein Kommentar der Form
  "# pip install modulname".
- Die Kommentare im Code sind auf Deutsch und für Einsteiger verständlich.
  Erkläre darin, was ein Abschnitt tut, nicht wie Python funktioniert.
- Der Code fragt nichts ab, was die Aufgabe nicht verlangt, und läuft ohne
  weitere Dateien im gleichen Ordner.
- "explanation": auf Deutsch, höchstens fünf Sätze, ohne Code.
- "filename": ein kurzer, sprechender Dateiname aus Kleinbuchstaben,
  Ziffern und Unterstrichen, mit der Endung .py, zum Beispiel "zahlen_ausgeben.py".
"""

ERINNERUNG = (
    "Deine letzte Antwort war kein gültiges JSON. Antworte jetzt "
    "ausschliesslich mit dem JSON-Objekt, ohne Codeblock und ohne weiteren Text."
)


class ApiFehler(RuntimeError):
    """Ein Fehler, dessen Text der Nutzerin direkt gezeigt werden kann."""


class Abgebrochen(RuntimeError):
    """Die Anfrage wurde vom Nutzer abgebrochen."""


@dataclass
class Programm:
    """Das Ergebnis einer Anfrage."""

    filename: str
    code: str
    explanation: str


# --------------------------------------------------------------------------
# Antwort auswerten
# --------------------------------------------------------------------------

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)

_ESCAPES = {
    '"': '"', "\\": "\\", "/": "/", "b": "\b",
    "f": "\f", "n": "\n", "r": "\r", "t": "\t",
}


def ohne_fences(text: str) -> str:
    """Entfernt einen umschliessenden Markdown-Codeblock, falls vorhanden."""
    treffer = _FENCE.match(text.strip())
    return treffer.group(1) if treffer else text.strip()


def json_objekt(text: str) -> dict:
    """Holt das erste vollständige JSON-Objekt aus einem Text.

    Verkraftet Codeblöcke und Geplauder vor oder nach dem Objekt.
    """
    roh = ohne_fences(text)
    start = roh.find("{")
    if start == -1:
        raise ValueError("Im Text steht kein JSON-Objekt.")

    tiefe = 0
    im_text = False
    maskiert = False
    for i in range(start, len(roh)):
        zeichen = roh[i]
        if im_text:
            if maskiert:
                maskiert = False
            elif zeichen == "\\":
                maskiert = True
            elif zeichen == '"':
                im_text = False
            continue
        if zeichen == '"':
            im_text = True
        elif zeichen == "{":
            tiefe += 1
        elif zeichen == "}":
            tiefe -= 1
            if tiefe == 0:
                return json.loads(roh[start : i + 1])
    raise ValueError("Das JSON-Objekt ist unvollständig.")


def teilcode(puffer: str) -> str:
    """Liest aus einer noch unvollständigen Antwort den bisherigen Code.

    Damit lässt sich der Code schon anzeigen, während er geschrieben wird.
    """
    treffer = re.search(r'"code"\s*:\s*"', puffer)
    if not treffer:
        return ""

    ergebnis: list[str] = []
    i = treffer.end()
    while i < len(puffer):
        zeichen = puffer[i]
        if zeichen == '"':
            break
        if zeichen != "\\":
            ergebnis.append(zeichen)
            i += 1
            continue
        # Maskierte Zeichen: unvollständige am Pufferende einfach weglassen.
        if i + 1 >= len(puffer):
            break
        folge = puffer[i + 1]
        if folge == "u":
            if i + 6 > len(puffer):
                break
            try:
                ergebnis.append(chr(int(puffer[i + 2 : i + 6], 16)))
            except ValueError:
                pass
            i += 6
        else:
            ergebnis.append(_ESCAPES.get(folge, folge))
            i += 2
    return "".join(ergebnis)


def sicherer_dateiname(vorschlag: str, ersatz: str = "programm.py") -> str:
    """Macht aus dem Vorschlag des Modells einen harmlosen Dateinamen."""
    name = (vorschlag or "").strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    if not name:
        return ersatz
    if not name.endswith(".py"):
        name += ".py"
    return name[:80]


def _zu_programm(daten: dict) -> Programm:
    code = daten.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Die Antwort enthält keinen Code.")
    erklaerung = daten.get("explanation")
    return Programm(
        filename=sicherer_dateiname(daten.get("filename", "")),
        code=code.strip("\n"),
        explanation=erklaerung.strip() if isinstance(erklaerung, str) else "",
    )


# --------------------------------------------------------------------------
# Anfragen an die API
# --------------------------------------------------------------------------

def _client(api_key: str) -> anthropic.Anthropic:
    if not api_key or not api_key.strip():
        raise ApiFehler(
            "Es ist noch kein API-Key hinterlegt. Trage ihn unter "
            "«Einstellungen» ein – du bekommst ihn auf console.anthropic.com."
        )
    return anthropic.Anthropic(
        api_key=api_key.strip(), timeout=TIMEOUT_SEKUNDEN
    )


def _ohne_key(text: str, api_key: str) -> str:
    """Stellt sicher, dass der Schlüssel in keiner Meldung auftaucht."""
    key = (api_key or "").strip()
    return text.replace(key, "…") if len(key) > 8 else text


def _uebersetze(fehler: Exception, api_key: str) -> ApiFehler:
    """Macht aus einer SDK-Ausnahme eine Meldung, die Einsteiger verstehen."""
    if isinstance(fehler, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ApiFehler(
            "Der API-Key wurde nicht akzeptiert. Prüfe unter «Einstellungen», "
            "ob er vollständig und noch gültig ist."
        )
    if isinstance(fehler, anthropic.RateLimitError):
        return ApiFehler(
            "Zu viele Anfragen in kurzer Zeit (oder das Guthaben ist "
            "aufgebraucht). Warte einen Moment und versuche es noch einmal."
        )
    if isinstance(fehler, anthropic.APITimeoutError):
        return ApiFehler(
            "Die Antwort hat zu lange gedauert. Versuche es noch einmal."
        )
    if isinstance(fehler, anthropic.APIConnectionError):
        return ApiFehler(
            "Keine Verbindung zur Anthropic-API. Prüfe deine "
            "Internetverbindung und versuche es noch einmal."
        )
    if isinstance(fehler, anthropic.NotFoundError):
        return ApiFehler(
            "Dieses Modell steht deinem Zugang nicht zur Verfügung. "
            "Wähle unter «Einstellungen» ein anderes Modell."
        )
    if isinstance(fehler, anthropic.APIStatusError):
        return ApiFehler(
            f"Die Anthropic-API hat mit Fehler {fehler.status_code} geantwortet: "
            f"{_ohne_key(str(getattr(fehler, 'message', '') or fehler), api_key)}"
        )
    return ApiFehler(
        "Unerwarteter Fehler beim Aufruf der API: "
        f"{_ohne_key(str(fehler), api_key)}"
    )


def _stream(
    client: anthropic.Anthropic,
    modell: str,
    nachrichten: list[dict],
    on_code: Callable[[str], None] | None,
    abbrechen: Callable[[], bool] | None,
) -> str:
    """Führt eine Anfrage aus und liefert den gesammelten Antworttext."""
    puffer = ""
    zuletzt_gemeldet = ""
    with client.messages.stream(
        model=modell,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=nachrichten,
    ) as stream:
        for stueck in stream.text_stream:
            if abbrechen and abbrechen():
                raise Abgebrochen()
            puffer += stueck
            if on_code:
                aktuell = teilcode(puffer)
                if aktuell != zuletzt_gemeldet:
                    zuletzt_gemeldet = aktuell
                    on_code(aktuell)
    return puffer


def _frage(
    nachrichten: list[dict],
    modell: str,
    api_key: str,
    on_code: Callable[[str], None] | None = None,
    abbrechen: Callable[[], bool] | None = None,
) -> Programm:
    """Fragt die API und wertet die Antwort aus – bei Parse-Fehler ein Versuch mehr."""
    client = _client(api_key)
    versuche = [nachrichten, nachrichten + [{"role": "user", "content": ERINNERUNG}]]

    letzter_parse_fehler: Exception | None = None
    for versuch in versuche:
        try:
            antwort = _stream(client, modell, versuch, on_code, abbrechen)
        except (Abgebrochen, ApiFehler):
            raise
        except Exception as fehler:  # SDK- und Netzwerkfehler
            raise _uebersetze(fehler, api_key) from fehler

        try:
            return _zu_programm(json_objekt(antwort))
        except (ValueError, TypeError) as fehler:
            letzter_parse_fehler = fehler

    raise ApiFehler(
        "Die Antwort des Modells war zweimal hintereinander unbrauchbar "
        f"({letzter_parse_fehler}). Formuliere die Aufgabe etwas anders und "
        "versuche es noch einmal."
    )


def erzeuge(
    aufgabe: str,
    modell: str,
    api_key: str,
    on_code: Callable[[str], None] | None = None,
    abbrechen: Callable[[], bool] | None = None,
) -> Programm:
    """Erzeugt aus einer Aufgabenbeschreibung ein Python-Programm."""
    if not aufgabe.strip():
        raise ApiFehler("Beschreibe zuerst, was das Programm tun soll.")
    nachrichten = [{"role": "user", "content": f"Aufgabe:\n{aufgabe.strip()}"}]
    return _frage(nachrichten, modell, api_key, on_code, abbrechen)


def verbessere(
    code: str,
    wunsch: str,
    modell: str,
    api_key: str,
    on_code: Callable[[str], None] | None = None,
    abbrechen: Callable[[], bool] | None = None,
) -> Programm:
    """Ändert ein bestehendes Programm gemäss dem Änderungswunsch."""
    if not code.strip():
        raise ApiFehler("Es gibt noch keinen Code, der geändert werden könnte.")
    if not wunsch.strip():
        raise ApiFehler("Beschreibe zuerst, was am Programm anders sein soll.")
    nachrichten = [
        {
            "role": "user",
            "content": (
                "Hier ist ein bestehendes Python-Programm:\n\n"
                f"{code.strip()}\n\n"
                f"Änderungswunsch:\n{wunsch.strip()}\n\n"
                "Gib das vollständige geänderte Programm zurück, nicht nur "
                "den geänderten Teil."
            ),
        }
    ]
    return _frage(nachrichten, modell, api_key, on_code, abbrechen)


def teste_verbindung(api_key: str) -> None:
    """Prüft Key und Erreichbarkeit, ohne Token zu verbrauchen.

    Wirft bei Problemen einen ApiFehler mit verständlichem Text.
    """
    client = _client(api_key)
    try:
        client.models.list(limit=1)
    except Exception as fehler:
        raise _uebersetze(fehler, api_key) from fehler
