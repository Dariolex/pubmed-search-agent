"""Test di configurazione, rate limiting e trasporto HTTP. Nessuna rete reale."""

import pytest
import responses

from pubmed_client import PubMedClient, PubMedConfig, RateLimiter, pubmed_web_url
from pubmed_errors import PubMedAPIError, PubMedConfigError, PubMedHTTPError

CHIAVE_FINTA = "chiave-segretissima-0123456789"


@pytest.fixture
def env_completo(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", CHIAVE_FINTA)
    monkeypatch.setenv("NCBI_TOOL_NAME", "pubmed-nl-search-agent")
    monkeypatch.setenv("NCBI_EMAIL", "test@example.org")
    # Isola i test da qualsiasi .env reale su disco: patch load_dotenv a no-op
    monkeypatch.setattr("pubmed_client.load_dotenv", lambda *a, **kw: None)


def test_from_env_legge_le_tre_variabili(env_completo):
    config = PubMedConfig.from_env()
    assert config.tool == "pubmed-nl-search-agent"
    assert config.email == "test@example.org"
    assert config.api_key == CHIAVE_FINTA


def test_variabile_mancante_solleva_config_error(monkeypatch, env_completo):
    monkeypatch.delenv("NCBI_API_KEY")
    with pytest.raises(PubMedConfigError, match="NCBI_API_KEY"):
        PubMedConfig.from_env()


def test_il_messaggio_elenca_tutte_le_variabili_mancanti(monkeypatch, env_completo):
    monkeypatch.delenv("NCBI_API_KEY")
    monkeypatch.delenv("NCBI_EMAIL")
    with pytest.raises(PubMedConfigError) as info:
        PubMedConfig.from_env()
    assert "NCBI_API_KEY" in str(info.value)
    assert "NCBI_EMAIL" in str(info.value)


def test_variabile_vuota_conta_come_mancante(monkeypatch, env_completo):
    monkeypatch.setenv("NCBI_EMAIL", "   ")
    with pytest.raises(PubMedConfigError, match="NCBI_EMAIL"):
        PubMedConfig.from_env()


def test_la_chiave_non_compare_nel_repr(env_completo):
    config = PubMedConfig.from_env()
    assert CHIAVE_FINTA not in repr(config)
    assert "pubmed-nl-search-agent" in repr(config)


def test_config_e_immutabile(env_completo):
    config = PubMedConfig.from_env()
    with pytest.raises(Exception):
        config.api_key = "altro"


def test_pubmed_web_url_codifica_i_caratteri_speciali():
    url = pubmed_web_url('"melanoma"[MeSH Terms] AND immunotherapy')
    assert url.startswith("https://pubmed.ncbi.nlm.nih.gov/?term=")
    assert " " not in url
    assert "%22melanoma%22" in url


class OrologioFinto:
    """Clock e sleep simulati: dormire fa avanzare il tempo, il test è istantaneo.

    Con time.sleep reale questo test durerebbe oltre un secondo e sarebbe
    intermittente in CI.
    """

    def __init__(self):
        self.adesso = 0.0
        self.attese = []

    def time(self) -> float:
        return self.adesso

    def sleep(self, secondi: float) -> None:
        self.attese.append(secondi)
        self.adesso += secondi


@pytest.fixture
def orologio():
    return OrologioFinto()


def test_le_prime_dieci_richieste_non_attendono(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    for _ in range(10):
        limiter.acquire()
    assert orologio.attese == []
    assert orologio.adesso == 0.0


def test_l_undicesima_richiesta_attende_un_decimo_di_secondo(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    for _ in range(11):
        limiter.acquire()
    assert orologio.adesso == pytest.approx(0.1, abs=1e-9)


def test_il_bucket_si_ricarica_col_tempo(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    for _ in range(10):
        limiter.acquire()
    orologio.adesso += 1.0  # un secondo di inattività ricarica il bucket
    for _ in range(10):
        limiter.acquire()
    assert orologio.attese == []


def test_il_bucket_non_supera_la_capacita(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    orologio.adesso += 100.0  # inattività lunghissima
    for _ in range(10):
        limiter.acquire()
    assert orologio.attese == []
    limiter.acquire()  # l'undicesima deve comunque attendere
    assert orologio.attese == [pytest.approx(0.1, abs=1e-9)]


def test_venti_richieste_consecutive_costano_un_secondo(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    for _ in range(20):
        limiter.acquire()
    assert orologio.adesso == pytest.approx(1.0, abs=1e-9)


ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
XML_OK = "<eSearchResult><Count>1</Count><IdList><Id>1</Id></IdList></eSearchResult>"
XML_ERRORE = "<eSearchResult><ERROR>Can't run executor</ERROR></eSearchResult>"


@pytest.fixture
def client(orologio):
    """Client con rate limiter e backoff simulati: nessuna attesa reale."""
    return PubMedClient(
        PubMedConfig(tool="test-tool", email="test@example.org", api_key=CHIAVE_FINTA),
        rate_limiter=RateLimiter(clock=orologio.time, sleep=orologio.sleep),
        sleep=orologio.sleep,
    )


@responses.activate
def test_ogni_richiesta_include_tool_email_e_api_key(client):
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    client._request("esearch.fcgi", {"db": "pubmed", "term": "melanoma"})
    inviata = responses.calls[0].request
    assert "tool=test-tool" in inviata.url
    assert f"api_key={CHIAVE_FINTA}" in inviata.url
    assert "email=test%40example.org" in inviata.url


@responses.activate
def test_ritenta_dopo_un_429_e_riesce(client):
    responses.add(responses.GET, ESEARCH_URL, status=429)
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    assert client._request("esearch.fcgi", {"db": "pubmed"}) == XML_OK
    assert len(responses.calls) == 2


@responses.activate
def test_429_persistente_solleva_dopo_tre_tentativi(client):
    for _ in range(3):
        responses.add(responses.GET, ESEARCH_URL, status=429)
    with pytest.raises(PubMedHTTPError, match="429"):
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert len(responses.calls) == 3


@responses.activate
def test_503_e_ritentabile(client):
    responses.add(responses.GET, ESEARCH_URL, status=503)
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    assert client._request("esearch.fcgi", {"db": "pubmed"}) == XML_OK


@responses.activate
def test_400_non_e_ritentabile(client):
    responses.add(responses.GET, ESEARCH_URL, status=400)
    with pytest.raises(PubMedHTTPError, match="400"):
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert len(responses.calls) == 1


@responses.activate
def test_http_200_con_error_nel_corpo_solleva_api_error_senza_ritentare(client):
    responses.add(responses.GET, ESEARCH_URL, body=XML_ERRORE, status=200)
    with pytest.raises(PubMedAPIError, match="Can't run executor"):
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert len(responses.calls) == 1


@responses.activate
def test_retry_after_determina_l_attesa(client, orologio):
    responses.add(responses.GET, ESEARCH_URL, status=429, headers={"Retry-After": "7"})
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    client._request("esearch.fcgi", {"db": "pubmed"})
    assert 7.0 in orologio.attese


@responses.activate
def test_la_chiave_non_compare_nei_messaggi_di_errore(client):
    responses.add(responses.GET, ESEARCH_URL, status=400)
    with pytest.raises(PubMedHTTPError) as info:
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert CHIAVE_FINTA not in str(info.value)


@responses.activate
def test_errore_di_rete_non_espone_la_chiave(client):
    import requests

    responses.add(responses.GET, ESEARCH_URL, body=requests.ConnectionError("boom"))
    with pytest.raises(PubMedHTTPError) as info:
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert CHIAVE_FINTA not in str(info.value)
    assert CHIAVE_FINTA not in repr(info.value.__cause__)


@responses.activate
def test_il_rate_limiter_viene_interpellato_a_ogni_tentativo(client, orologio):
    """11 tentativi consumano il bucket: l'ultimo deve aver atteso."""
    for _ in range(11):
        responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    for _ in range(11):
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert orologio.adesso == pytest.approx(0.1, abs=1e-9)


@responses.activate
def test_post_invia_i_parametri_nel_corpo(client):
    efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    responses.add(responses.POST, efetch_url, body="<PubmedArticleSet/>", status=200)
    client._request("efetch.fcgi", {"db": "pubmed", "id": "1,2"}, method="POST")
    inviata = responses.calls[0].request
    assert "id=1%2C2" in inviata.body
    assert f"api_key={CHIAVE_FINTA}" in inviata.body
    assert CHIAVE_FINTA not in inviata.url
