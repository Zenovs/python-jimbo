"""Tests für api.py – das Anthropic-SDK wird dabei durch eine Attrappe ersetzt."""

from __future__ import annotations

import json

import anthropic
import httpx2
import pytest

from jimbo import api

MODELL = "claude-sonnet-5"
KEY = "sk-ant-test-0123456789abcdef"


# --------------------------------------------------------------------------
# Attrappe für das SDK
# --------------------------------------------------------------------------

class _StreamAttrappe:
    def __init__(self, stuecke, fehler=None):
        self._stuecke = stuecke
        self._fehler = fehler

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    @property
    def text_stream(self):
        if self._fehler is not None:
            raise self._fehler
        yield from self._stuecke


class _MessagesAttrappe:
    def __init__(self, antworten, fehler=None):
        self._antworten = list(antworten)
        self._fehler = fehler
        self.aufrufe: list[dict] = []

    def stream(self, **kwargs):
        self.aufrufe.append(kwargs)
        if self._fehler is not None:
            return _StreamAttrappe([], self._fehler)
        antwort = self._antworten.pop(0) if self._antworten else ""
        return _StreamAttrappe([antwort])


class _ClientAttrappe:
    def __init__(self, antworten=(), fehler=None):
        self.messages = _MessagesAttrappe(antworten, fehler)
        self.models = self


def _setze_client(monkeypatch, client):
    monkeypatch.setattr(api.anthropic, "Anthropic", lambda **_: client)
    return client


def _antwort(code="print('hallo')", filename="test.py", explanation="Gibt etwas aus."):
    return json.dumps(
        {"filename": filename, "code": code, "explanation": explanation}
    )


# --------------------------------------------------------------------------
# Antwort auswerten
# --------------------------------------------------------------------------

def test_json_aus_codeblock():
    text = '```json\n{"code": "x = 1"}\n```'
    assert api.json_objekt(text) == {"code": "x = 1"}


def test_json_mit_geplauder_davor_und_danach():
    text = 'Klar, hier ist es:\n{"code": "x = 1"}\nViel Spass!'
    assert api.json_objekt(text) == {"code": "x = 1"}


def test_json_mit_geschweiften_klammern_im_code():
    innen = 'd = {"a": 1}\nprint(f"{d}")'
    text = json.dumps({"code": innen})
    assert api.json_objekt(text)["code"] == innen


def test_json_ohne_objekt_meldet_fehler():
    with pytest.raises(ValueError):
        api.json_objekt("Tut mir leid, das kann ich nicht.")


def test_json_unvollstaendig_meldet_fehler():
    with pytest.raises(ValueError):
        api.json_objekt('{"code": "x = 1"')


def test_teilcode_waehrend_des_streams():
    puffer = '{"filename": "a.py", "code": "print(1)\\nprint('
    assert api.teilcode(puffer) == "print(1)\nprint("


def test_teilcode_bricht_unvollstaendige_maskierung_ab():
    assert api.teilcode('{"code": "zeile\\') == "zeile"
    assert api.teilcode('{"code": "A\\u00e4') == "Aä"
    assert api.teilcode('{"code": "A\\u00') == "A"


def test_teilcode_ohne_code_feld():
    assert api.teilcode('{"filename": "a.py"') == ""


@pytest.mark.parametrize(
    "vorschlag, erwartet",
    [
        ("zahlen.py", "zahlen.py"),
        ("zahlen", "zahlen.py"),
        ("../../etc/passwd", "passwd.py"),
        ("C:\\Windows\\böse.py", "b_se.py"),
        ("", "programm.py"),
        ("   ", "programm.py"),
    ],
)
def test_sicherer_dateiname(vorschlag, erwartet):
    assert api.sicherer_dateiname(vorschlag) == erwartet


# --------------------------------------------------------------------------
# Erzeugen und Nachbessern
# --------------------------------------------------------------------------

def test_erzeuge_liefert_programm(monkeypatch):
    client = _setze_client(monkeypatch, _ClientAttrappe([_antwort()]))
    programm = api.erzeuge("Gib hallo aus", MODELL, KEY)

    assert programm.code == "print('hallo')"
    assert programm.filename == "test.py"
    assert programm.explanation == "Gibt etwas aus."
    assert client.messages.aufrufe[0]["model"] == MODELL
    assert "JSON-Objekt" in client.messages.aufrufe[0]["system"]


def test_erzeuge_meldet_teilcode_waehrend_des_streams(monkeypatch):
    _setze_client(monkeypatch, _ClientAttrappe([_antwort(code="a\nb")]))
    gesehen: list[str] = []
    api.erzeuge("Aufgabe", MODELL, KEY, on_code=gesehen.append)
    assert gesehen and gesehen[-1] == "a\nb"


def test_erzeuge_ohne_aufgabe():
    with pytest.raises(api.ApiFehler, match="Beschreibe zuerst"):
        api.erzeuge("   ", MODELL, KEY)


def test_erzeuge_ohne_key():
    with pytest.raises(api.ApiFehler, match="kein API-Key"):
        api.erzeuge("Aufgabe", MODELL, "")


def test_zweiter_versuch_bei_kaputtem_json(monkeypatch):
    client = _setze_client(
        monkeypatch, _ClientAttrappe(["Kein JSON, sorry", _antwort(code="x = 1")])
    )
    programm = api.erzeuge("Aufgabe", MODELL, KEY)

    assert programm.code == "x = 1"
    assert len(client.messages.aufrufe) == 2
    # Der zweite Versuch enthält die Erinnerung an das JSON-Format.
    assert client.messages.aufrufe[1]["messages"][-1]["content"] == api.ERINNERUNG


def test_zweimal_kaputtes_json_meldet_fehler(monkeypatch):
    _setze_client(monkeypatch, _ClientAttrappe(["nein", "immer noch nein"]))
    with pytest.raises(api.ApiFehler, match="zweimal hintereinander"):
        api.erzeuge("Aufgabe", MODELL, KEY)


def test_antwort_ohne_code_gilt_als_kaputt(monkeypatch):
    leer = json.dumps({"filename": "a.py", "explanation": "nix"})
    _setze_client(monkeypatch, _ClientAttrappe([leer, leer]))
    with pytest.raises(api.ApiFehler):
        api.erzeuge("Aufgabe", MODELL, KEY)


def test_verbessere_schickt_alten_code_mit(monkeypatch):
    client = _setze_client(monkeypatch, _ClientAttrappe([_antwort(code="neu = 1")]))
    programm = api.verbessere("alt = 1", "Nenne es neu", MODELL, KEY)

    inhalt = client.messages.aufrufe[0]["messages"][0]["content"]
    assert "alt = 1" in inhalt and "Nenne es neu" in inhalt
    assert programm.code == "neu = 1"


def test_verbessere_ohne_code():
    with pytest.raises(api.ApiFehler, match="noch keinen Code"):
        api.verbessere("", "irgendwas", MODELL, KEY)


def test_verbessere_ohne_wunsch():
    with pytest.raises(api.ApiFehler, match="anders sein soll"):
        api.verbessere("x = 1", "  ", MODELL, KEY)


def test_abbruch_wird_durchgereicht(monkeypatch):
    _setze_client(monkeypatch, _ClientAttrappe([_antwort()]))
    with pytest.raises(api.Abgebrochen):
        api.erzeuge("Aufgabe", MODELL, KEY, abbrechen=lambda: True)


# --------------------------------------------------------------------------
# Fehlermeldungen
# --------------------------------------------------------------------------

def _antwortobjekt(status: int) -> httpx2.Response:
    anfrage = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx2.Response(status, request=anfrage, json={"error": {"message": "nope"}})


@pytest.mark.parametrize(
    "fehler, erwartet",
    [
        (
            anthropic.AuthenticationError("bad key", response=_antwortobjekt(401), body=None),
            "API-Key wurde nicht akzeptiert",
        ),
        (
            anthropic.RateLimitError("slow down", response=_antwortobjekt(429), body=None),
            "Zu viele Anfragen",
        ),
        (
            anthropic.NotFoundError("no model", response=_antwortobjekt(404), body=None),
            "steht deinem Zugang nicht zur Verfügung",
        ),
        (
            anthropic.APIConnectionError(
                request=httpx2.Request("POST", "https://api.anthropic.com")
            ),
            "Keine Verbindung",
        ),
        (
            anthropic.APITimeoutError(
                request=httpx2.Request("POST", "https://api.anthropic.com")
            ),
            "zu lange gedauert",
        ),
        (
            anthropic.InternalServerError("boom", response=_antwortobjekt(500), body=None),
            "Fehler 500",
        ),
    ],
)
def test_fehlermeldungen_sind_verstaendlich(monkeypatch, fehler, erwartet):
    _setze_client(monkeypatch, _ClientAttrappe(fehler=fehler))
    with pytest.raises(api.ApiFehler, match=erwartet):
        api.erzeuge("Aufgabe", MODELL, KEY)


def test_key_taucht_in_keiner_meldung_auf(monkeypatch):
    antwort = httpx2.Response(
        400,
        request=httpx2.Request("POST", "https://api.anthropic.com"),
        json={"error": {"message": f"key {KEY} ist ungueltig"}},
    )
    _setze_client(
        monkeypatch,
        _ClientAttrappe(fehler=anthropic.BadRequestError("x", response=antwort, body=None)),
    )
    with pytest.raises(api.ApiFehler) as info:
        api.erzeuge("Aufgabe", MODELL, KEY)
    assert KEY not in str(info.value)


def test_teste_verbindung_ruft_modelliste(monkeypatch):
    class _Models:
        def __init__(self):
            self.aufgerufen = False

        def list(self, **_):
            self.aufgerufen = True

    client = _ClientAttrappe()
    client.models = _Models()
    _setze_client(monkeypatch, client)

    api.teste_verbindung(KEY)
    assert client.models.aufgerufen


def test_teste_verbindung_ohne_key():
    with pytest.raises(api.ApiFehler, match="kein API-Key"):
        api.teste_verbindung("")
