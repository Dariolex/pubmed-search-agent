"""Test della CLI related_search: successo, PMID senza link, tipo invalido, errore."""

import json

import pytest
import responses

from related_search import esegui, main
from pubmed_client import PubMedClient, PubMedConfig, RateLimiter
from pubmed_errors import PubMedAPIError

ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

ELINK_UN_LINK = """<?xml version="1.0" ?>
<eLinkResult>
  <LinkSet>
    <DbFrom>pubmed</DbFrom>
    <IdList><Id>21376230</Id></IdList>
    <LinkSetDb>
      <DbTo>pubmed</DbTo>
      <LinkName>pubmed_pubmed</LinkName>
      <Link><Id>21376230</Id></Link>
      <Link><Id>111</Id></Link>
    </LinkSetDb>
  </LinkSet>
</eLinkResult>
"""

ELINK_SOLO_SORGENTE = """<?xml version="1.0" ?>
<eLinkResult>
  <LinkSet>
    <DbFrom>pubmed</DbFrom>
    <IdList><Id>999999999</Id></IdList>
    <LinkSetDb>
      <DbTo>pubmed</DbTo>
      <LinkName>pubmed_pubmed</LinkName>
      <Link><Id>999999999</Id></Link>
    </LinkSetDb>
  </LinkSet>
</eLinkResult>
"""


def _efetch_xml(pmid):
    return f"""<?xml version="1.0" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">{pmid}</PMID>
    <Article PubModel="Print">
      <Journal><JournalIssue CitedMedium="Internet"><PubDate><Year>2024</Year></PubDate></JournalIssue>
      <Title>Rivista Test</Title></Journal>
      <ArticleTitle>Titolo {pmid}</ArticleTitle>
    </Article>
  </MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>"""


@pytest.fixture
def client():
    return PubMedClient(
        PubMedConfig(tool="test", email="test@example.org", api_key="chiave-finta"),
        rate_limiter=RateLimiter(clock=lambda: 0.0, sleep=lambda s: None),
        sleep=lambda s: None,
    )


@responses.activate
def test_esegui_simili_restituisce_stesso_formato_di_run_search(client):
    responses.add(responses.GET, ELINK_URL, body=ELINK_UN_LINK, status=200)
    responses.add(responses.POST, EFETCH_URL, body=_efetch_xml("111"), status=200)
    risultato = esegui("21376230", "simili", 30, client)
    assert risultato["total_count"] == 1
    assert risultato["articles"][0]["pmid"] == "111"
    assert risultato["articles"][0]["title"] == "Titolo 111"


@responses.activate
def test_esegui_nessun_link_restituisce_lista_vuota(client):
    responses.add(responses.GET, ELINK_URL, body=ELINK_SOLO_SORGENTE, status=200)
    risultato = esegui("999999999", "citazioni", 30, client)
    assert risultato["total_count"] == 0
    assert risultato["articles"] == []


def test_esegui_tipo_invalido_solleva_value_error(client):
    with pytest.raises(ValueError):
        esegui("21376230", "tipo-a-caso", 30, client)


@responses.activate
def test_main_stampa_json_su_stdout(monkeypatch, capsys):
    monkeypatch.setattr(
        "related_search.PubMedConfig.from_env",
        lambda: PubMedConfig(tool="t", email="e@example.org", api_key="k"),
    )
    responses.add(responses.GET, ELINK_URL, body=ELINK_UN_LINK, status=200)
    responses.add(responses.POST, EFETCH_URL, body=_efetch_xml("111"), status=200)
    codice = main(argv=["--pmid", "21376230", "--tipo", "simili", "--max", "30"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert dati["articles"][0]["pmid"] == "111"


@responses.activate
def test_main_errore_di_rete_esce_uno_su_stderr(monkeypatch, capsys):
    monkeypatch.setattr(
        "related_search.PubMedConfig.from_env",
        lambda: PubMedConfig(tool="t", email="e@example.org", api_key="k"),
    )
    for _ in range(3):
        responses.add(responses.GET, ELINK_URL, status=500)
    codice = main(argv=["--pmid", "21376230", "--tipo", "simili"])
    out = capsys.readouterr()
    assert codice == 1
    assert out.out == ""
    assert "Errore" in out.err
