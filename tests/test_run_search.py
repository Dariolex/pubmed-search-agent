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

# efetch_batch.xml (fixture genuina, registrata da NCBI) contiene solo i PMID
# 33301246 e 42140479. esearch_basic.xml è una registrazione genuina ma di
# un'altra query, con PMID diversi: la sua intersezione con efetch_batch.xml
# (fatta da PubMedClient.efetch) sarebbe vuota. Per il test che verifica il
# round-trip completo con articoli non vuoti, usiamo un corpo ESearch minimo
# e sintetico (solo Count/IdList, nessun contenuto d'articolo inventato)
# costruito qui inline sui PMID reali di efetch_batch.xml, invece di
# fabbricare un file di fixture con titoli/abstract/rivista finti.
ESEARCH_BODY_PMID_MATCH_EFETCH_BATCH = """<?xml version="1.0" ?>
<eSearchResult>
<Count>2</Count>
<RetMax>2</RetMax>
<RetStart>0</RetStart>
<IdList>
<Id>33301246</Id>
<Id>42140479</Id>
</IdList>
<TranslationSet></TranslationSet>
<QueryTranslation></QueryTranslation>
</eSearchResult>"""


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
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=ESEARCH_BODY_PMID_MATCH_EFETCH_BATCH,
        status=200,
    )
    responses.add(
        responses.POST,
        EFETCH_URL,
        body=(FIXTURES / "efetch_batch.xml").read_text(encoding="utf-8"),
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
        body=(FIXTURES / "efetch_batch.xml").read_text(encoding="utf-8"),
        status=200,
    )
    codice = main(argv=["--term", "melanoma", "--retmax", "5"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert "articles" in dati and "total_count" in dati
