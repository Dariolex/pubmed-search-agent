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


@responses.activate
def test_main_handles_unicode_in_abstract(client, monkeypatch, capsys):
    """Verifica che main() non crasha su caratteri Unicode non-ASCII in abstract.

    Simula un articolo reale da NCBI con caratteri come U+2009 (thin space),
    accenti, ecc., che causerebbero UnicodeEncodeError con ensure_ascii=False
    su Windows con stdout encoding cp1252. Con ensure_ascii=True, l'output
    deve rimanere pure ASCII (con escape sequences) e parseable come JSON.
    """
    monkeypatch.setattr("run_search.PubMedConfig.from_env", lambda: client._config)
    monkeypatch.setattr("run_search.PubMedClient", lambda config: client)

    # Minimal EFETCH response con un articolo che contiene:
    # - U+2009 (THIN SPACE) — carattere reale riscontrato nei PMID NCBI
    # - accenti (é) — comuni negli abstracts scientifici
    efetch_with_unicode = """<?xml version="1.0" ?>
<PubmedArticleSet>
<PubmedArticle>
<MedlineCitation Status="PubMed" Owner="NLM">
<PMID Version="1">33301246</PMID>
<DateCompleted><Year>2021</Year><Month>02</Month><Day>22</Day></DateCompleted>
<Article PubModel="Print-Electronic">
<Journal><Title>International Journal of Molecular Sciences</Title></Journal>
<ArticleTitle>Test Article with Unicode Characters</ArticleTitle>
<Pagination><StartPage>1</StartPage><EndPage>10</EndPage><MedlinePgn>1-10</MedlinePgn></Pagination>
<Abstract>
<AbstractText Label="BACKGROUND">This abstract contains a thin space here&#x2009;and also accented characters like café and résumé. These should be properly escaped in JSON output.</AbstractText>
</Abstract>
<AuthorList>
<Author><LastName>Smith</LastName><ForeName>John</ForeName></Author>
</AuthorList>
<PublicationTypeList>
<PublicationType>Journal Article</PublicationType>
</PublicationTypeList>
<ArticleDate DateType="Electronic"><Year>2021</Year><Month>01</Month><Day>15</Day></ArticleDate>
</Article>
</MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>"""

    # Sintetico ESearch che ritorna il PMID da efetch_with_unicode
    esearch_response = """<?xml version="1.0" ?>
<eSearchResult>
<Count>1</Count>
<RetMax>1</RetMax>
<RetStart>0</RetStart>
<IdList>
<Id>33301246</Id>
</IdList>
<TranslationSet></TranslationSet>
<QueryTranslation></QueryTranslation>
</eSearchResult>"""

    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=esearch_response,
        status=200,
    )
    responses.add(
        responses.POST,
        EFETCH_URL,
        body=efetch_with_unicode,
        status=200,
    )

    codice = main(argv=["--term", "melanoma", "--retmax", "5"])
    out = capsys.readouterr()

    assert codice == 0, f"main() failed with code {codice}, stderr: {out.err}"

    # Verifica che stdout è puro ASCII (ensure_ascii=True)
    assert out.out.isascii(), "JSON output deve essere puro ASCII"

    # Verifica che il JSON è parseable e contiene i campi attesi
    dati = json.loads(out.out)
    assert "articles" in dati
    assert len(dati["articles"]) == 1
    primo_articolo = dati["articles"][0]
    assert "pmid" in primo_articolo
    assert "abstract" in primo_articolo

    # Verifica che i caratteri Unicode siano stati preservati dopo round-trip
    # (json.dumps escape → json.loads decode)
    abstract = primo_articolo["abstract"]
    assert "café" in abstract, "Accented characters should be decoded from \\uXXXX escapes"
    assert "résumé" in abstract, "Accented characters should be decoded from \\uXXXX escapes"
