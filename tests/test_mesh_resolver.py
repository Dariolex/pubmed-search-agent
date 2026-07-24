"""Test della CLI mesh_resolver: successo, nessun match, errore. HTTP mockato."""

import json

import pytest
import responses

from mesh_resolver import main
from pubmed_client import PubMedClient, PubMedConfig, RateLimiter

MESH_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
MESH_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

MESH_ESEARCH_MATCH = """<?xml version="1.0" ?>
<eSearchResult><Count>1</Count><IdList><Id>68008545</Id></IdList></eSearchResult>
"""
MESH_ESEARCH_NO_MATCH = """<?xml version="1.0" ?>
<eSearchResult><Count>0</Count><IdList/></eSearchResult>
"""
MESH_ESUMMARY_MELANOMA = """<?xml version="1.0" ?>
<eSummaryResult><DocSum><Id>68008545</Id>
<Item Name="DS_MeshTerms" Type="List">
	<Item Name="string" Type="String">Melanoma</Item>
	<Item Name="string" Type="String">Melanomas</Item>
</Item>
</DocSum></eSummaryResult>
"""


class OrologioFinto:
    def __init__(self):
        self.adesso = 0.0

    def time(self):
        return self.adesso

    def sleep(self, secondi):
        self.adesso += secondi


@pytest.fixture
def client_finto(monkeypatch):
    orologio = OrologioFinto()
    client = PubMedClient(
        PubMedConfig(tool="test", email="test@example.org", api_key="chiave-finta"),
        rate_limiter=RateLimiter(clock=orologio.time, sleep=orologio.sleep),
        sleep=orologio.sleep,
    )
    monkeypatch.setattr("mesh_resolver.PubMedConfig.from_env", lambda: client._config)
    monkeypatch.setattr("mesh_resolver.PubMedClient", lambda config: client)
    return client


@responses.activate
def test_main_match_trovato_stampa_json(client_finto, capsys):
    responses.add(responses.GET, MESH_SEARCH_URL, body=MESH_ESEARCH_MATCH, status=200)
    responses.add(responses.GET, MESH_SUMMARY_URL, body=MESH_ESUMMARY_MELANOMA, status=200)
    codice = main(argv=["--termine", "melanoma"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert dati["descriptor"] == "Melanoma"
    assert dati["entry_terms"] == ["Melanomas"]
    assert dati["mesh_ui"] == "68008545"
    assert dati["termine_originale"] == "melanoma"


@responses.activate
def test_main_nessun_match_esce_zero_con_descriptor_null(client_finto, capsys):
    responses.add(responses.GET, MESH_SEARCH_URL, body=MESH_ESEARCH_NO_MATCH, status=200)
    codice = main(argv=["--termine", "xyznonesiste"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert dati["descriptor"] is None
    assert dati["entry_terms"] == []
    assert dati["mesh_ui"] is None
    assert dati["termine_originale"] == "xyznonesiste"


@responses.activate
def test_main_errore_di_rete_esce_uno_su_stderr(client_finto, capsys):
    for _ in range(3):
        responses.add(responses.GET, MESH_SEARCH_URL, status=500)
    codice = main(argv=["--termine", "melanoma"])
    out = capsys.readouterr()
    assert codice == 1
    assert out.out == ""
    assert "Errore" in out.err
