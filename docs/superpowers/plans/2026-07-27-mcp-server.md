# MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Esporre la ricerca PubMed come tool MCP `search_pubmed_papers` (transport stdio), utilizzabile da Claude Desktop/Code, riusando la pipeline esistente senza duplicarla.

**Architecture:** Un modulo `src/mcp_server.py` costruito con l'SDK ufficiale `mcp` (`FastMCP`). Il tool è a grana fine: accetta `term` già in sintassi PubMed e `retmax`, delega a `run_search.esegui(term, retmax, client)` e restituisce il payload JSON (total_count, translated_query, warnings, articles). Una **sola** istanza di `PubMedClient` è tenuta come singleton lazy a livello modulo, così il token-bucket del rate limiter NCBI sopravvive tra le chiamate. `sys.path` viene sistemato in cima al modulo perché il server sia lanciabile con path assoluto senza PYTHONPATH esterno.

**Tech Stack:** Python 3.10+, `mcp[cli]` (nuova dipendenza, SDK FastMCP), `pytest`, `responses` (già presenti). Riusa `pubmed_client.py`, `pubmed_models.py`, `run_search.py` esistenti.

## Global Constraints

- **Python 3.10+** — annotazioni `str | None`, `dict`.
- **Codice e commenti in italiano**, coerentemente con i moduli esistenti.
- **Nessun write su stdout nella catena di import** — il transport stdio usa stdout per il JSON-RPC MCP. Verificato in brainstorming: `load_dotenv()` è silenzioso; gli unici write su stdout dei moduli `src` sono dentro i rispettivi `main()`, che non girano all'import. Non introdurre `print` nel modulo o nella catena importata.
- **Una sola istanza di `PubMedClient`** riusata tra le chiamate (rate limiter preservato) — creare un client nuovo per chiamata azzererebbe il token-bucket e rischierebbe HTTP 429.
- **`term` è sintassi PubMed, non linguaggio naturale** — la docstring del tool deve dirlo esplicitamente (è la descrizione esposta al client MCP). L'estrazione NL e il filtro di rilevanza restano compito del modello client.
- **`retmax` clampato a `1..200`** (default 50), tollerante: si corregge il valore, non si solleva.
- **`PubMedError` propagata**, non catturata in un payload vuoto — FastMCP la converte in errore di protocollo MCP.
- **Import fra moduli senza prefisso di pacchetto** (`from pubmed_client import ...`), reso possibile da `pythonpath = src` in `pytest.ini` (già configurato) per i test, e da `sys.path.insert(0, dirname(__file__))` nel modulo per il lancio esterno.
- **`pytest` senza argomenti resta interamente offline** — nessuna chiamata di rete nei test automatici (si inietta un client fittizio).

## API dei moduli esistenti (da consumare, non modificare)

- `run_search.esegui(term: str, retmax: int, client: PubMedClient) -> dict` — orchestrazione esearch+efetch, restituisce `{"total_count", "translated_query", "warnings", "articles"}` dove `articles` è una lista di `dataclasses.asdict(Article)`. Chiama internamente `client.esearch(term, retmax=retmax)` poi `client.efetch(ricerca.pmids)`.
- `PubMedClient(config)`, `PubMedConfig.from_env()` — costruzione client. `from_env()` legge `.env`/ambiente e solleva `PubMedConfigError` se manca una variabile.
- `PubMedClient.esearch(term, *, retmax=100, ...) -> SearchResult` e `PubMedClient.efetch(pmids) -> list[Article]` — usati da `esegui`.
- `SearchResult(pmids: list[str], total_count: int, translated_query: str | None, webenv, query_key, warnings: list[str])` — dataclass in `pubmed_models.py`.
- `Article(pmid, title, abstract, authors, journal, pub_date, pub_types, mesh_terms, doi)` — dataclass frozen in `pubmed_models.py`.
- `PubMedError` (base), `PubMedAPIError`, `PubMedHTTPError`, `PubMedConfigError` — gerarchia eccezioni in `pubmed_errors.py`.

## FastMCP — API rilevanti (SDK `mcp`)

- `from mcp.server.fastmcp import FastMCP`; `mcp = FastMCP("nome-server")`.
- `@mcp.tool()` registra una funzione come tool e **restituisce la funzione invariata**: si può chiamare direttamente `search_pubmed_papers(...)` nei test.
- `mcp.run()` avvia il server su transport **stdio** di default.
- `await mcp.list_tools()` (coroutine) restituisce una lista di oggetti `Tool` con `.name`, `.description`, `.inputSchema` (dict JSON Schema). Nei test sincroni si invoca con `asyncio.run(mcp.list_tools())`.

---

## File Structure

| File | Responsabilità |
|---|---|
| `requirements.txt` | Aggiunge la dipendenza `mcp[cli]`. |
| `src/mcp_server.py` | Nuovo: server MCP, tool `search_pubmed_papers`, singleton `_get_client`, `main()`. Sostituisce il placeholder attuale. |
| `tests/test_mcp_server.py` | Nuovo: test offline del tool (happy path, registrazione, clamp, propagazione errori, riuso client). |
| `CLAUDE.md` | Aggiornamento: roadmap sezione 8, step 6 completato; nota sullo snippet di config. |

---

## Task 1: Dipendenza, modulo e tool `search_pubmed_papers`

**Files:**
- Modify: `requirements.txt`
- Create: `src/mcp_server.py` (sostituisce il placeholder)
- Create: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `run_search.esegui`, `PubMedClient`, `PubMedConfig` (esistenti); `mcp.server.fastmcp.FastMCP`.
- Produces:
  - modulo `mcp_server` con:
    - `mcp: FastMCP` — istanza a livello modulo
    - `_get_client() -> PubMedClient` — singleton lazy sulla global `_client`
    - `search_pubmed_papers(term: str, retmax: int = 50) -> dict` — tool MCP
    - `main() -> None` — avvia `mcp.run()`

- [ ] **Step 1: Aggiungere la dipendenza e installarla**

Aggiungere a `requirements.txt` (dopo `responses`):

```
mcp[cli]
```

Installare nell'ambiente:

Run: `pip install "mcp[cli]"`
Expected: installazione completata; `python -c "from mcp.server.fastmcp import FastMCP"` esce senza errori.

- [ ] **Step 2: Scrivere i test che falliscono**

Creare `tests/test_mcp_server.py`:

```python
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
```

- [ ] **Step 3: Eseguire i test e verificarne il fallimento**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL in raccolta/collezione — `mcp_server` non ha ancora `mcp`, `_client`, `search_pubmed_papers` (AttributeError o ImportError), oppure il placeholder attuale non definisce nulla.

- [ ] **Step 4: Scrivere l'implementazione**

Sostituire **interamente** il contenuto di `src/mcp_server.py`:

```python
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
```

- [ ] **Step 5: Eseguire i test e verificarne il successo**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS entrambi (`test_happy_path_restituisce_payload`, `test_tool_registrato_con_nome_e_schema`).

- [ ] **Step 6: Verificare che l'intera suite resti verde e offline**

Run: `pytest`
Expected: PASS, nessuna chiamata di rete (i test live restano esclusi da `pytest.ini`).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt src/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: mcp_server, tool MCP search_pubmed_papers (step 6)"
```

---

## Task 2: Comportamenti difensivi (clamp, propagazione errori, riuso client)

**Files:**
- Modify: `tests/test_mcp_server.py`
- Modify: `src/mcp_server.py` (solo se un test lo richiede — l'implementazione di Task 1 dovrebbe già soddisfarli; questi test bloccano il contratto)

**Interfaces:**
- Consumes: `mcp_server.search_pubmed_papers`, `mcp_server._get_client`, `mcp_server._client`, `FakeClient` (definita in Task 1), `PubMedAPIError`.
- Produces: nessuna nuova API — verifica il contratto di `search_pubmed_papers` e `_get_client`.

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_mcp_server.py`:

```python
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
```

- [ ] **Step 2: Eseguire i test**

Run: `pytest tests/test_mcp_server.py -v`
Expected: i quattro nuovi test PASSANO già se l'implementazione di Task 1 è corretta (clamp, propagazione, singleton). Se qualcuno FALLISCE, correggere `src/mcp_server.py` nel punto indicato dal test (il clamp `max(1, min(retmax, 200))`, il non-catturare l'eccezione, il `global _client` in `_get_client`) e rieseguire fino al verde.

- [ ] **Step 3: Verificare l'intera suite**

Run: `pytest`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_mcp_server.py src/mcp_server.py
git commit -m "test: mcp_server, clamp retmax, propagazione errori, riuso client"
```

---

## Task 3: Documentazione (roadmap e config)

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nulla.
- Produces: nulla (solo documentazione).

- [ ] **Step 1: Aggiornare la roadmap in `CLAUDE.md`**

Nella sezione 8, sostituire la riga dello step 6:

```
6. `mcp_server.py` — esposizione come tool MCP `search_pubmed_papers`, utilizzabile da Claude Desktop/Code
```

con:

```
6. ~~`mcp_server.py` — esposizione come tool MCP `search_pubmed_papers` (FastMCP,
   transport stdio), tool a grana fine che prende una query in sintassi PubMed e
   restituisce gli articoli con abstract; riusa `run_search.esegui` e un'unica
   istanza di `PubMedClient` (rate limiter preservato). La traduzione NL e il filtro
   di rilevanza restano compito del modello client che chiama il tool.~~
   **(completato)**
```

- [ ] **Step 2: Documentare la configurazione del client MCP in `CLAUDE.md`**

In fondo alla sezione 8 (dopo la lista della roadmap), aggiungere:

```markdown
### Configurazione del server MCP in Claude Desktop/Code

Aggiungere a `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "python",
      "args": ["C:\\percorso\\assoluto\\src\\mcp_server.py"]
    }
  }
}
```

Il `.env` (`NCBI_API_KEY`, `NCBI_TOOL_NAME`, `NCBI_EMAIL`) deve essere raggiungibile dal
processo, oppure le variabili vanno passate in un blocco `"env"` nella stessa config.
Nuova dipendenza: `mcp[cli]` (vedi `requirements.txt`).
```

- [ ] **Step 3: Verifica finale della suite**

Run: `pytest`
Expected: PASS, interamente offline.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mcp_server integrato, roadmap step 6 completato"
```

---

## Note di verifica finale

- Il tool è testato offline iniettando un `FakeClient` nella global `_client`; nessuna chiamata reale a NCBI parte durante `pytest`. Il percorso esearch+efetch reale è già coperto da `tests/test_pubmed_live.py` — non serve un nuovo test live per l'MVP dell'MCP.
- Prova manuale opzionale (fuori dai test automatici): con un `.env` valido, `python src/mcp_server.py` avvia il server in ascolto su stdio; la validazione end-to-end vera avviene collegandolo a Claude Desktop/Code tramite lo snippet di config.
