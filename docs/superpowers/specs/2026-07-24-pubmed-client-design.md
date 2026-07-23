# Design — `pubmed_client.py` (step 1 della roadmap)

**Data:** 2026-07-24
**Stato:** approvato in brainstorming, da implementare
**Ambito:** wrapper E-utilities di NCBI con rate limiting e parsing. Nessuna logica di
linguaggio naturale, nessuna chiamata a Claude.

---

## 1. Obiettivo

Fornire l'accesso a PubMed su cui si appoggiano tutti gli altri moduli del progetto.
Il chiamante passa una stringa di query in sintassi PubMed e riceve dataclass tipizzate:
non vede mai XML, non gestisce mai il rate limiting, non conosce l'esistenza delle
E-utilities.

Corrisponde allo step 1 della roadmap in `CLAUDE.md` sezione 8.

**Fuori ambito:** traduzione NL, filtro semantico, risoluzione MeSH, server MCP,
`esummary`, `elink`.

---

## 2. Decisioni di design

| # | Decisione | Motivazione |
|---|---|---|
| D1 | Client **sincrono** con `requests` | Il tetto di 10 req/s rende marginale il guadagno dell'async. Rate limiter bloccante banale da testare. Incapsulabile dietro `asyncio.to_thread` se in futuro `mcp_server.py` avrà bisogno di concorrenza. |
| D2 | Ritorno **tipizzato**, parsing dentro il modulo | I moduli a valle non vedono XML. Il parsing PubMed ha casi limite che meritano test dedicati. |
| D3 | Solo **`esearch` + `efetch`** nell'MVP | `efetch` restituisce già titolo, autori, journal, data e tipi di pubblicazione insieme all'abstract: `esummary` sarebbe un round-trip e un parser in più senza risparmio reale. |
| D4 | `usehistory=y` sempre su `esearch` | Fornisce `WebEnv`/`query_key` per paginare senza rieseguire la query, evitando lo slittamento dei risultati tra pagine. |
| D5 | Split in **`pubmed_client.py` + `pubmed_models.py`** | Il parsing è la parte con più superficie di test e zero dipendenza da HTTP: isolarlo lo rende testabile passando una stringa. |
| D6 | Retry **manuale**, non `urllib3.Retry` | Ogni ritentativo deve ripassare dal token bucket, e `urllib3` non conosce il caso HTTP-200-con-errore. |
| D7 | Fallimento parziale di `efetch` → **solleva** | Risultati silenziosamente incompleti su cui il filtro semantico lavorerebbe inconsapevole sono peggio di un errore esplicito. |

### Deviazioni da `CLAUDE.md` (da riportare nel file al momento dell'implementazione)

- **Sezione 3** — nuovi file `src/pubmed_models.py` e `tests/test_pubmed_models.py` (D5).
- **Sezione 4** — `esummary` scende da "endpoint principale" a fase successiva, accanto a `elink` (D3).

---

## 3. Componenti

### `pubmed_models.py` — dati e parsing (nessuna dipendenza da rete)

```python
@dataclass(frozen=True)
class SearchResult:
    pmids: list[str]
    total_count: int              # match reali, non quanti ne sono stati scaricati
    translated_query: str | None  # <QueryTranslation> restituita da NCBI
    webenv: str | None
    query_key: str | None

@dataclass(frozen=True)
class Article:
    pmid: str
    title: str
    abstract: str | None          # None se assente, mai ""
    authors: list[str]
    journal: str
    pub_date: str                 # ISO parziale: "2024" | "2024-03" | "2024-03-15"
    pub_types: list[str]
    mesh_terms: list[str]
    doi: str | None

def parse_esearch_xml(xml: str) -> SearchResult: ...
def parse_efetch_xml(xml: str) -> list[Article]: ...
```

Regole di parsing:

- **`translated_query`** cattura `<QueryTranslation>`. NCBI applica l'*automatic term
  mapping*: la query inviata non è quella eseguita. Questo campo è ciò che spiega i
  risultati sorprendenti quando la traduzione NL sembrava corretta, e alimenta il
  requisito di `CLAUDE.md` sezione 5 (mostrare la traduzione all'utente).
- **`pub_date` resta stringa.** PubMed ha date genuinamente parziali. Forzare un `date`
  significherebbe inventare mese e giorno che poi verrebbero usati per ordinare o filtrare.
- **Abstract strutturati** (`<AbstractText Label="METHODS">`) uniti conservando le etichette.
- **`abstract is None`** quando manca, così il filtro semantico distingue "non posso
  giudicare" da "abstract vuoto".
- **`<CollectiveName>`** (consorzi, gruppi di studio) confluisce in `authors`.

### `pubmed_client.py` — configurazione, rate limiting, trasporto

```python
@dataclass(frozen=True)
class PubMedConfig:
    tool: str
    email: str
    api_key: str

    @classmethod
    def from_env(cls) -> "PubMedConfig": ...   # fallisce subito se manca una variabile
    def __repr__(self) -> str: ...             # api_key redatta

class RateLimiter:
    """Token bucket: capacità 10, ricarica 10 token/s. `acquire()` è bloccante.
    `clock` e `sleep` iniettati (default time.monotonic / time.sleep) per i test."""

class PubMedClient:
    def esearch(self, term: str, *, retmax: int = 100, retstart: int = 0,
                sort: str | None = None, mindate: str | None = None,
                maxdate: str | None = None, datetype: str = "pdat") -> SearchResult: ...
    def efetch(self, pmids: Sequence[str], *, batch_size: int = 200) -> list[Article]: ...

def pubmed_web_url(term: str) -> str: ...   # link a pubmed.ncbi.nlm.nih.gov
```

- `tool`, `email`, `api_key` aggiunti a **ogni** richiesta.
- `requests.Session` per riusare le connessioni.
- `efetch` usa **POST** a blocchi di 200 PMID: con GET l'URL sfora oltre quella soglia.
- `efetch` **riordina secondo i PMID in input**, preservando il ranking di `esearch`.
  Ricevere meno articoli di quanti richiesti (record ritirati o rimossi) non è un errore.

---

## 4. Flusso dati

```
term (sintassi PubMed)
  → RateLimiter.acquire()
  → GET esearch.fcgi?db=pubmed&term=...&usehistory=y&retmax=N
  → controllo <ERROR> nel body
  → parse_esearch_xml → SearchResult(pmids, total_count, translated_query, ...)
  → chunk(pmids, 200)
  → per ogni blocco: RateLimiter.acquire() → POST efetch.fcgi (rettype=abstract, retmode=xml)
  → controllo <ERROR> nel body
  → parse_efetch_xml → list[Article]
  → riordino secondo i pmid in input
```

Il taglio del volume è **esplicito e a carico del chiamante** via `retmax`: una query può
produrre decine di migliaia di PMID, ma il filtro semantico ne processa qualche decina.
`total_count` riporta comunque il numero reale di match.

---

## 5. Gestione errori

### Il caso insidioso: HTTP 200 con errore nel body

Una query malformata (parentesi sbilanciate, tag di campo inesistente) non produce un 400
ma un `<ERROR>` dentro XML valido con status 200. Controllando solo `status_code` si
otterrebbe una lista vuota indistinguibile da "nessun match". Con query generate
automaticamente da un LLM questo è il modo di fallire più probabile.

**Ogni risposta viene ispezionata per `<ERROR>`/`<ErrorList>` prima del parsing.**

`Count=0` **non** è un errore: è un `SearchResult` legittimo con zero PMID, e per questo
progetto è un segnale diagnostico (query troppo restrittiva).

### Gerarchia delle eccezioni

```
PubMedError
├── PubMedConfigError   # variabili d'ambiente mancanti (fallisce all'avvio)
├── PubMedAPIError      # HTTP 200 + <ERROR> nel body, con il messaggio NCBI
├── PubMedHTTPError     # status non recuperabile dopo i retry
└── PubMedParseError    # XML valido ma struttura inattesa
```

### Politica di retry

- **Ritentabili:** 429, 500, 502, 503, 504, timeout, errori di connessione
- **Non ritentabili:** 400 e `PubMedAPIError` — riprovare una query malformata dà lo
  stesso risultato
- 3 tentativi, backoff esponenziale con jitter (~1s, 2s, 4s), `Retry-After` rispettato
  quando presente
- **Ogni ritentativo ripassa dal token bucket**
- Timeout: 5s connessione, 30s lettura (una `efetch` da 200 abstract è lenta)

### Sicurezza della chiave

`api_key` letta solo da variabile d'ambiente, mai hardcoded, mai loggata, assente da
`__repr__` e dai messaggi delle eccezioni. `record_fixtures.py` la **rimuove prima di
scrivere su disco**: `tests/fixtures/` finisce in git, `.env` no.

---

## 6. Testing

### File

- `tests/test_pubmed_models.py` — parsing puro, nessun mock, nessuna rete
- `tests/test_pubmed_client.py` — HTTP, rate limiter, retry, errori (`responses`)
- `tests/record_fixtures.py` — script che registra query reali in `tests/fixtures/`

### Fixture

Scelte per coprire i modi di rompersi, non per fare volume:

| Fixture | Copre |
|---|---|
| `esearch_basic.xml` | caso nominale + `<QueryTranslation>` |
| `esearch_zero_results.xml` | `Count=0` come risultato valido |
| `esearch_error.xml` | HTTP 200 con `<ERROR>` |
| `efetch_batch.xml` | più articoli, uno con abstract strutturato |
| `efetch_no_abstract.xml` | `abstract is None` |
| `efetch_collective_author.xml` | `<CollectiveName>` |

### Casi di test

**`pubmed_models`** — parsing di ogni fixture; date parziali (solo anno, anno-mese);
abstract strutturato con etichette conservate; abstract assente → `None`; `CollectiveName`
→ `authors`; estrazione di MeSH, tipi di pubblicazione, DOI.

**`pubmed_client`** — 11 richieste consecutive con `clock`/`sleep` finti: l'undicesima
attende (con `time.sleep` reale il test durerebbe oltre un secondo e sarebbe
intermittente); 429 poi 200 → successo in 2 chiamate; 429 ripetuto → `PubMedHTTPError`
dopo 3 tentativi; 400 → nessun retry; HTTP 200 + `<ERROR>` → `PubMedAPIError` senza retry;
250 PMID → 2 POST; riordino secondo l'input; batch fallito → solleva; `api_key` assente da
`repr` e dai messaggi di errore.

**Live** (`@pytest.mark.live`, esclusi di default via `addopts = -m "not live"` in
`pytest.ini`) — una `esearch` nota con `total_count > 0`; una `efetch` su un PMID stabile;
15 richieste rapide senza 429. Asseriscono sulla **struttura** (titolo non vuoto, PMID
corrispondente), non sul contenuto esatto: PubMed corregge i propri metadati e un
confronto di stringhe letterali si romperebbe da solo.

---

## 7. Dipendenze

Da aggiungere a `requirements.txt`: `responses` (mock HTTP nei test).
Già presenti: `requests`, `python-dotenv`, `pytest`.

---

## 8. Criteri di completamento

- [ ] `pytest` (senza argomenti) passa interamente offline, senza toccare la rete
- [ ] `pytest -m live` passa contro NCBI
- [ ] Le sei fixture sono registrate e prive di `api_key`
- [ ] `esearch` di una query nota restituisce `total_count`, PMID e `translated_query`
- [ ] `efetch` su quei PMID restituisce `Article` con abstract, nell'ordine di input
- [ ] Una query malformata solleva `PubMedAPIError`, non una lista vuota
- [ ] `CLAUDE.md` aggiornato con le deviazioni della sezione 2
