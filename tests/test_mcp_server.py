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
