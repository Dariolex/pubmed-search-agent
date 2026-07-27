"""
mcp_server.py

Espone la ricerca PubMed come tool MCP `search_pubmed_papers` (transport stdio),
utilizzabile da Claude Desktop/Code.

Tool a grana fine: accetta una query GIÀ in sintassi PubMed e restituisce i
risultati (PMID + abstract + metadati). La traduzione linguaggio-naturale -> query
e il filtro di rilevanza semantica restano compito del modello client che chiama il
tool, non del server. Nessuna API key oltre a quella NCBI.

INVARIANTE: nessun write su stdout nella catena di import — il transport stdio usa
stdout per il JSON-RPC MCP. `load_dotenv()` è silenzioso; i moduli importati scrivono
su stdout solo nei rispettivi main(). Non aggiungere print qui né nella catena.

Configurazione client (claude_desktop_config.json):

    {
      "mcpServers": {
        "pubmed-search": {
          "command": "python",
          "args": ["C:\\\\percorso\\\\assoluto\\\\src\\\\mcp_server.py"]
        }
      }
    }

Il .env con NCBI_API_KEY/NCBI_TOOL_NAME/NCBI_EMAIL deve essere raggiungibile
(load_dotenv lo cerca dalla cwd verso l'alto), oppure le variabili vanno passate in
un blocco "env" nella config.
"""

from __future__ import annotations

import os
import sys

# I moduli src usano import piatti (from pubmed_client import ...): quando un client
# MCP lancia il server via path assoluto, il PYTHONPATH non include src. Inserendo la
# propria cartella in sys.path il server parte con `python /percorso/src/mcp_server.py`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from pubmed_client import PubMedClient, PubMedConfig
from run_search import esegui

mcp = FastMCP("pubmed-search-agent")

_client: PubMedClient | None = None


def _get_client() -> PubMedClient:
    """Restituisce l'unica istanza di PubMedClient, creandola alla prima chiamata.

    Un solo client per l'intera vita del server: il token-bucket del rate limiter
    NCBI vive nell'istanza e va preservato tra le chiamate del tool.
    """
    global _client
    if _client is None:
        _client = PubMedClient(PubMedConfig.from_env())
    return _client


@mcp.tool()
def search_pubmed_papers(term: str, retmax: int = 50) -> dict:
    """Esegue una ricerca PubMed e restituisce gli articoli con abstract.

    `term` deve essere GIÀ in sintassi di ricerca PubMed (tag di campo come
    [tiab], [MeSH Terms], [pt], [dp] e operatori AND/OR/NOT), non linguaggio
    naturale: traduci la richiesta dell'utente in questa sintassi prima di
    chiamare il tool.

    `retmax` (default 50) è il numero massimo di articoli da recuperare; viene
    corretto silenziosamente nell'intervallo 1..200 se fuori range.

    Restituisce total_count (match totali su PubMed), translated_query (come NCBI
    ha reinterpretato la query), warnings (es. termini senza corrispondenza) e
    articles (title, abstract, authors, journal, pub_date, pub_types, pmid, ...).
    """
    retmax = max(1, min(retmax, 200))
    return esegui(term, retmax, _get_client())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
