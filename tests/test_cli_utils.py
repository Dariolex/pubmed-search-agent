"""Test di cli_utils: scrittura errori/JSON con encoding robusto, in isolamento."""

import json
import sys

import pytest

from cli_utils import scrivi_errore, scrivi_testo, stampa_json


class _BufferFinto:
    """Doppio di test per uno stream binario: accumula i byte scritti."""

    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, dati: bytes) -> int:
        self.chunks.append(dati)
        return len(dati)


class _StderrFinto:
    """Simula uno stderr con encoding realmente restrittivo (cp1252)."""

    def __init__(self, encoding: str):
        self.encoding = encoding
        self.buffer = _BufferFinto()


class _StdoutFinto:
    """Simula uno stdout con encoding realmente restrittivo (cp1252)."""

    def __init__(self, encoding: str):
        self.encoding = encoding
        self.buffer = _BufferFinto()


def test_scrivi_errore_usa_encoding_robusto(monkeypatch):
    """Un messaggio con un carattere non rappresentabile in cp1252 non deve
    sollevare UnicodeEncodeError: deve essere sostituito da backslashreplace."""
    messaggio_con_theta = "Errore NCBI: parametro non valido θ"
    with pytest.raises(UnicodeEncodeError):
        messaggio_con_theta.encode("cp1252")

    stderr_finto = _StderrFinto("cp1252")
    monkeypatch.setattr(sys, "stderr", stderr_finto)

    scrivi_errore(Exception(messaggio_con_theta))

    scritto = b"".join(stderr_finto.buffer.chunks)
    decodificato = scritto.decode("cp1252")
    assert messaggio_con_theta not in decodificato
    assert "\\u03b8" in decodificato
    assert decodificato.startswith("Errore: ")


def test_stampa_json_e_ascii_puro(capsys):
    """ensure_ascii=True: caratteri non-ASCII devono uscire come sequenze di
    escape, mai come byte grezzi (evita UnicodeEncodeError su stdout ristretto)."""
    stampa_json({"titolo": "café résumé"})
    out = capsys.readouterr()
    assert out.out.isascii()
    dati = json.loads(out.out)
    assert dati["titolo"] == "café résumé"


def test_stampa_json_termina_con_newline(capsys):
    stampa_json({"a": 1})
    out = capsys.readouterr()
    assert out.out.endswith("\n")


def test_scrivi_testo_usa_encoding_robusto(monkeypatch):
    """Riproduce dal vivo un bug reale: un abstract NCBI autentico può contenere
    lettere greche (es. "ρ"); su una console Windows con stdout.encoding=cp1252,
    un write testuale diretto solleverebbe UnicodeEncodeError. scrivi_testo deve
    sostituire il carattere non rappresentabile con la sequenza di escape."""
    testo_con_rho = "concentrazione di ρ-actina nel tessuto"
    with pytest.raises(UnicodeEncodeError):
        testo_con_rho.encode("cp1252")

    stdout_finto = _StdoutFinto("cp1252")
    monkeypatch.setattr(sys, "stdout", stdout_finto)

    scrivi_testo(testo_con_rho)

    scritto = b"".join(stdout_finto.buffer.chunks)
    decodificato = scritto.decode("cp1252")
    assert testo_con_rho not in decodificato
    assert "\\u03c1" in decodificato
    assert decodificato.endswith("\n")
