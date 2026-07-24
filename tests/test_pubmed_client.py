"""Test di configurazione, rate limiting e trasporto HTTP. Nessuna rete reale."""

import pytest

from pubmed_client import PubMedConfig, RateLimiter, pubmed_web_url
from pubmed_errors import PubMedConfigError

CHIAVE_FINTA = "chiave-segretissima-0123456789"


@pytest.fixture
def env_completo(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", CHIAVE_FINTA)
    monkeypatch.setenv("NCBI_TOOL_NAME", "pubmed-nl-search-agent")
    monkeypatch.setenv("NCBI_EMAIL", "test@example.org")


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
