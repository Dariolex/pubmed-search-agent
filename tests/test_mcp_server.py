"""Test offline del server MCP: si inietta un client fittizio nella global
`_client`, così nessuna chiamata di rete parte durante `pytest`."""
import asyncio

import pytest

import mcp_server
from pubmed_errors import PubMedAPIError
from pubmed_models import Article, SearchResult


@pytest.fixture(autouse=True)
def reset_client():
    """Azzera il singleton prima di ogni test per evitare contaminazione."""
    mcp_server._client = None
    yield
    mcp_server._client = None


class FakeClient:
    """Sostituto di PubMedClient: registra i parametri di esearch e
    restituisce dataclass reali, senza rete."""

    def __init__(self):
        self.esearch_calls = []

    def esearch(self, term, *, retmax=100):
        self.esearch_calls.append((term, retmax))
        return SearchResult(
            pmids=["1"],
            total_count=1,
            translated_query="melanoma[tiab]",
            warnings=[],
        )

    def efetch(self, pmids):
        return [
            Article(
                pmid="1",
                title="Un titolo",
                abstract="Un abstract",
                authors=["Rossi M"],
                journal="J Test",
                pub_date="2024",
                pub_types=["Journal Article"],
                mesh_terms=[],
                doi=None,
            )
        ]


def test_happy_path_restituisce_payload():
    mcp_server._client = FakeClient()
    risultato = mcp_server.search_pubmed_papers("melanoma[tiab]", retmax=10)
    assert risultato["total_count"] == 1
    assert risultato["translated_query"] == "melanoma[tiab]"
    assert risultato["warnings"] == []
    assert risultato["articles"][0]["pmid"] == "1"
    assert risultato["articles"][0]["abstract"] == "Un abstract"


def test_tool_registrato_con_nome_e_schema():
    strumenti = asyncio.run(mcp_server.mcp.list_tools())
    per_nome = {t.name: t for t in strumenti}
    assert "search_pubmed_papers" in per_nome
    tool = per_nome["search_pubmed_papers"]
    assert "PubMed" in (tool.description or "")
    assert "term" in tool.inputSchema["properties"]


def test_retmax_troppo_grande_viene_clampato_a_200():
    fake = FakeClient()
    mcp_server._client = fake
    mcp_server.search_pubmed_papers("melanoma[tiab]", retmax=100000)
    assert fake.esearch_calls[0][1] == 200


def test_retmax_zero_viene_clampato_a_1():
    fake = FakeClient()
    mcp_server._client = fake
    mcp_server.search_pubmed_papers("melanoma[tiab]", retmax=0)
    assert fake.esearch_calls[0][1] == 1


def test_pubmed_error_si_propaga():
    class ClientCheFallisce:
        def esearch(self, term, *, retmax=100):
            raise PubMedAPIError("query malformata")

        def efetch(self, pmids):  # pragma: no cover - non raggiunto
            return []

    mcp_server._client = ClientCheFallisce()
    with pytest.raises(PubMedAPIError):
        mcp_server.search_pubmed_papers("query[[malformata", retmax=10)


def test_client_riusato_tra_chiamate(monkeypatch):
    mcp_server._client = None
    creati = []

    class ClientFinto:
        pass

    class ConfigFinta:
        @staticmethod
        def from_env():
            return "config-finta"

    def costruttore_finto(config):
        creati.append(config)
        return ClientFinto()

    monkeypatch.setattr(mcp_server, "PubMedConfig", ConfigFinta)
    monkeypatch.setattr(mcp_server, "PubMedClient", costruttore_finto)

    primo = mcp_server._get_client()
    secondo = mcp_server._get_client()
    assert primo is secondo
    assert len(creati) == 1  # il client viene costruito una sola volta
