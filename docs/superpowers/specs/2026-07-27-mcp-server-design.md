# Design — `mcp_server.py` (step 6 della roadmap)

**Data:** 2026-07-27
**Stato:** approvato in brainstorming, da implementare
**Ambito:** esporre la pipeline di ricerca PubMed come tool MCP `search_pubmed_papers`,
utilizzabile da Claude Desktop/Code come server MCP su transport stdio.

---

## 1. Obiettivo

Rendere la ricerca PubMed disponibile come **tool MCP** a un client esterno (es. Claude
Desktop), senza dipendere dalla skill `/pubmed-search`. Copre lo step 6 della roadmap in
`CLAUDE.md` sezione 8.

Il tool è **a grana fine**: accetta una query **già in sintassi PubMed** (`term`) e
restituisce i risultati (PMID + abstract + metadati), esattamente come `run_search.py`.
La traduzione linguaggio-naturale → query e il filtro di rilevanza semantica **restano
compito del modello client** che chiama il tool (Claude Desktop/Code legge gli abstract
restituiti e li valuta), non del server. Il server MCP non fa alcuna chiamata a Claude e
non richiede alcuna API key oltre a quella NCBI già in uso.

**Fuori ambito:**
- Estrazione NL→query e filtro di rilevanza dentro il server (scelta di design: tool a
  grana fine — vedi D1).
- Chiamate all'API Anthropic dal server (nessuna dipendenza/costo aggiuntivo).
- Il filtro brevetti `[cois]` (feature separata, spec propria in `nl_query_translator`).
- Esposizione di `resolve_mesh` o `nl_query_translator` come tool MCP distinti (il client
  costruisce la query da sé; eventuale evoluzione futura).

---

## 2. Decisioni di design

| # | Decisione | Motivazione |
|---|---|---|
| D1 | Tool **a grana fine**: `search_pubmed_papers(term, retmax)`, `term` già in sintassi PubMed | Scelto in brainstorming. Il modello client è già un LLM capace di generare la query e leggere gli abstract; duplicare estrazione/filtro nel server aggiungerebbe una dipendenza dall'API Anthropic e ricalcherebbe logica già nella skill. Stessa interfaccia di `run_search.esegui`. |
| D2 | SDK ufficiale **`mcp` (`FastMCP`)**, transport **stdio** | Standard de facto per tool MCP in Python; decoratori `@mcp.tool()`; stdio è il transport nativo per Claude Desktop/Code. |
| D3 | **Riuso di `run_search.esegui(term, retmax, client)`**, non duplicazione | Evita di riscrivere la logica esearch+efetch+`asdict`. L'accoppiamento a un modulo CLI è accettabile: `esegui` è una funzione pura di orchestrazione, e i suoi write su stdout vivono solo in `main()` (non girano all'import). |
| D4 | **Una sola istanza di `PubMedClient`**, singleton lazy a livello modulo | **Correttezza, non ottimizzazione.** Il server è long-running; il token-bucket che rispetta il limite NCBI di 10 req/s vive *dentro* l'istanza del client (`pubmed_client.py`, classe `RateLimiter`). Creare un client nuovo a ogni chiamata azzererebbe il rate limiter e chiamate ravvicinate potrebbero sforare → HTTP 429. Il client va creato una volta e riusato. |
| D5 | `sys.path.insert(0, dirname(__file__))` in cima al modulo | I moduli `src` usano import piatti (`from pubmed_client import ...`) che presumono `src` sul path. Un client MCP lancia il server via comando in `claude_desktop_config.json`, dove il PYTHONPATH non è garantito. Inserendo la propria cartella in `sys.path`, il server è lanciabile come `python /percorso/assoluto/src/mcp_server.py`. |
| D6 | **`PubMedError` propagata**, non catturata | FastMCP converte l'eccezione in un errore di protocollo MCP (`isError=true`) visibile al client. Coerente con la gerarchia già tipizzata in `pubmed_errors.py`; il client vede il messaggio reale (query malformata, rate limit, ecc.). |
| D7 | **Clamp difensivo di `retmax`** a `1..200` | Un client potrebbe passare un `retmax` assurdo e far esplodere l'efetch. Il clamp evita richieste patologiche senza sollevare (comportamento tollerante). Default 50 come `run_search`. |
| D8 | **Igiene di stdout** come invariante documentato | Il transport stdio usa stdout per il JSON-RPC: un `print` nella catena di import corromperebbe il protocollo. Verificato in brainstorming: `load_dotenv()` è silenzioso e gli unici write su stdout dei moduli `src` sono dentro i rispettivi `main()`. Il modulo annota l'invariante perché non venga introdotto un `print` in futuro. |

---

## 3. Componenti

### A. `src/mcp_server.py` — server MCP

Struttura del modulo:

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # D5

from mcp.server.fastmcp import FastMCP
from pubmed_client import PubMedClient, PubMedConfig
from run_search import esegui                                   # D3

mcp = FastMCP("pubmed-search-agent")

_client = None
def _get_client() -> PubMedClient:                              # D4: singleton lazy
    global _client
    if _client is None:
        _client = PubMedClient(PubMedConfig.from_env())
    return _client

@mcp.tool()
def search_pubmed_papers(term: str, retmax: int = 50) -> dict:
    """Esegue una ricerca PubMed. `term` deve essere GIÀ in sintassi PubMed
    (tag [tiab], [MeSH Terms], [pt], [dp], operatori AND/OR/NOT).
    Restituisce total_count, translated_query, warnings e articles con abstract."""
    retmax = max(1, min(retmax, 200))                           # D7
    return esegui(term, retmax, _get_client())                  # D6: PubMedError propaga

def main() -> None:
    mcp.run()                                                   # stdio di default

if __name__ == "__main__":
    main()
```

**Nota sulla docstring del tool:** FastMCP la usa come descrizione del tool esposta al
client. Deve dire esplicitamente che `term` è sintassi PubMed (non linguaggio naturale),
così il modello client sa di dover tradurre *prima* di chiamare.

### B. Payload di ritorno

Identico a `run_search.esegui`:

```json
{
  "total_count": 1234,
  "translated_query": "come NCBI ha reinterpretato la query",
  "warnings": ["PhraseNotFound: ..."],
  "articles": [
    {"title": "...", "abstract": "...", "authors": ["..."],
     "journal": "...", "pub_date": "...", "pub_types": ["..."], "pmid": "..."}
  ]
}
```

`translated_query` e `warnings` restano nel payload: dicono al client come PubMed ha
reinterpretato la query e quali termini non hanno matchato.

### C. Configurazione client (documentazione)

Snippet per `claude_desktop_config.json`, incluso nel design per l'utente finale:

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

Il `.env` con `NCBI_API_KEY`/`NCBI_TOOL_NAME`/`NCBI_EMAIL` deve essere raggiungibile
(`load_dotenv()` lo cerca dalla cwd verso l'alto; in alternativa le variabili possono
essere passate nell'ambiente del processo tramite un blocco `"env"` nella config).

---

## 4. Testing

Il seam per i test è `_get_client()` con la global `_client` monkeypatchabile: i test
iniettano un client reale ma con l'HTTP mockato via `responses` (stesso approccio di
`test_pubmed_client.py`), oppure sostituiscono direttamente `_client`.

- **`tests/test_mcp_server.py`** (nuovo, offline):
  - Il tool è registrato con nome `search_pubmed_papers` e schema corretto (introspezione
    via l'API di FastMCP, es. `await mcp.list_tools()`).
  - **Happy path:** con esearch+efetch mockati (`responses`), la chiamata al tool
    restituisce il payload atteso (`total_count`, `articles`, ecc.).
  - **`retmax` fuori range** viene clampato (es. `retmax=100000` → l'esearch mockato
    riceve `retmax=200`; `retmax=0` → 1).
  - **Propagazione errori:** un `<ERROR>` di NCBI (o un 400) fa sì che il tool sollevi
    `PubMedError`, non che restituisca un payload vuoto.
  - **Riuso del client:** due chiamate consecutive usano la stessa istanza (`_get_client`
    non ricrea il client) — verifica il contratto di D4.
- **`pytest` gira interamente offline**; nessuna nuova chiamata di rete nei test
  automatici.
- Nessun test `@pytest.mark.live` dedicato è strettamente necessario (il percorso
  esearch+efetch è già coperto live da `test_pubmed_live.py`); se ne aggiunge uno solo se
  il costo dell'avvio del server MCP end-to-end si rivela utile a coprire un rischio reale.

---

## 5. Dipendenze

Nuova dipendenza Python: **`mcp[cli]`** (SDK ufficiale MCP con `FastMCP`), aggiunta a
`requirements.txt`. Nessun'altra: riusa `requests`, `python-dotenv`, `responses` (test) e
l'infrastruttura `pubmed_client`/`pubmed_models`/`run_search`.

---

## 6. Criteri di completamento

- [ ] `mcp[cli]` in `requirements.txt`; il modulo importa `FastMCP` senza errori
- [ ] `search_pubmed_papers` registrato come tool MCP con docstring che specifica che
      `term` è sintassi PubMed
- [ ] Il tool riusa `run_search.esegui` e una **sola** istanza di `PubMedClient`
      (rate limiter preservato tra le chiamate) — verificato in test
- [ ] `retmax` clampato a `1..200`
- [ ] `PubMedError` propagata come errore MCP, non catturata in un payload vuoto
- [ ] `sys.path` sistemato così che `python /percorso/src/mcp_server.py` parta senza
      PYTHONPATH esterno
- [ ] Nessun write su stdout nella catena di import (invariante annotato nel modulo)
- [ ] `tests/test_mcp_server.py` passa offline; `pytest` interamente offline resta verde
- [ ] `CLAUDE.md` aggiornato (roadmap sezione 8, step 6 completato)
- [ ] Snippet `claude_desktop_config.json` documentato (nel modulo o nel README/CLAUDE.md)
