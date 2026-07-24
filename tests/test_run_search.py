"""Test di run_search: esecuzione end-to-end con HTTP mockato (nessuna rete reale)."""

import json
from pathlib import Path

import pytest
import responses

from pubmed_client import PubMedClient, PubMedConfig, RateLimiter
from run_search import esegui, main

FIXTURES = Path(__file__).parent / "fixtures"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class OrologioFinto:
    def __init__(self):
        self.adesso = 0.0

    def time(self):
        return self.adesso

    def sleep(self, secondi):
        self.adesso += secondi


@pytest.fixture
def client():
    orologio = OrologioFinto()
    return PubMedClient(
        PubMedConfig(tool="test", email="test@example.org", api_key="chiave-finta"),
        rate_limiter=RateLimiter(clock=orologio.time, sleep=orologio.sleep),
        sleep=orologio.sleep,
    )


@responses.activate
def test_esegui_restituisce_dict_con_articoli(client):
    # efetch_matching_basic.xml contiene i PMID reali di esearch_basic.xml
    # (efetch_batch.xml esiste ma è stato registrato per una query diversa: i
    # suoi PMID non coincidono con quelli di esearch_basic.xml, quindi
    # l'intersezione fatta da PubMedClient.efetch tornerebbe vuota).
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=(FIXTURES / "esearch_basic.xml").read_text(encoding="utf-8"),
        status=200,
    )
    responses.add(
        responses.POST,
        EFETCH_URL,
        body=(FIXTURES / "efetch_matching_basic.xml").read_text(encoding="utf-8"),
        status=200,
    )
    risultato = esegui("melanoma", retmax=5, client=client)
    assert risultato["total_count"] > 0
    assert isinstance(risultato["articles"], list)
    assert risultato["articles"]
    primo = risultato["articles"][0]
    assert "pmid" in primo and "title" in primo and "abstract" in primo


@responses.activate
def test_esegui_propaga_errore_del_client(client):
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=(FIXTURES / "esearch_error.xml").read_text(encoding="utf-8"),
        status=200,
    )
    from pubmed_errors import PubMedAPIError

    with pytest.raises(PubMedAPIError):
        esegui("melanoma AND (", retmax=5, client=client)


@responses.activate
def test_main_stampa_json_su_stdout(client, monkeypatch, capsys):
    monkeypatch.setattr("run_search.PubMedConfig.from_env", lambda: client._config)
    monkeypatch.setattr("run_search.PubMedClient", lambda config: client)
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=(FIXTURES / "esearch_basic.xml").read_text(encoding="utf-8"),
        status=200,
    )
    responses.add(
        responses.POST,
        EFETCH_URL,
        body=(FIXTURES / "efetch_matching_basic.xml").read_text(encoding="utf-8"),
        status=200,
    )
    codice = main(argv=["--term", "melanoma", "--retmax", "5"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert "articles" in dati and "total_count" in dati
