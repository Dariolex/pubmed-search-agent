# PubMed NL Search Agent — CLAUDE.md

## 1. Obiettivo del progetto

Costruire un motore di ricerca che permetta di interrogare **PubMed** (via API E-utilities di NCBI) formulando **query in linguaggio naturale**, che vengono tradotte automaticamente nella sintassi di ricerca avanzata di PubMed (tag di campo, operatori booleani, filtri MeSH, date, ecc.), eseguite contro le API reali, e i cui risultati vengono poi **filtrati per rilevanza semantica** rispetto all'intento originale dell'utente — non per semplice matching di parole chiave.

Esempio di flusso:

```
Utente: "Trovami gli studi degli ultimi 3 anni su immunoterapia nel melanoma metastatico,
         solo trial clinici randomizzati, escludendo case report"
   ↓
Traduzione NL → query PubMed:
("melanoma"[MeSH Terms] OR "melanoma"[tiab]) AND
("immunotherapy"[MeSH Terms] OR "immunotherapy"[tiab]) AND
"metastatic"[tiab] AND
"randomized controlled trial"[pt] AND
("2023"[dp] : "2026"[dp])
NOT "case reports"[pt]
   ↓
Esecuzione su ESearch/EFetch (NCBI E-utilities, con api_key)
   ↓
Filtro di rilevanza semantica sui risultati (Claude)
   ↓
Output: elenco ordinato per pertinenza, con motivazione della rilevanza
```

## 2. Stato del progetto

- API key NCBI già generata (E-utilities, non Datasets API — parametro `api_key`, non `api-key`).
- Sviluppo previsto interamente in Claude Code (serve accesso di rete live verso `eutils.ncbi.nlm.nih.gov` per testare le chiamate reali, non disponibile in ambiente chat).
- Questo file è il documento guida iniziale: va raffinato in modalità di pianificazione (plan mode) mano a mano che l'architettura si consolida.

## 3. Architettura

```
pubmed-search-agent/
├── CLAUDE.md
├── .env
├── .env.example
├── pytest.ini
├── requirements.txt
├── docs/superpowers/
│   ├── specs/                 # design approvati in brainstorming
│   └── plans/                 # piani di implementazione
├── src/
│   ├── pubmed_errors.py       # gerarchia di eccezioni condivisa
│   ├── pubmed_models.py       # dataclass + parsing XML puro (nessuna rete)
│   ├── pubmed_client.py       # wrapper E-utilities, rate limiting, retry
│   ├── run_search.py          # entry-point CLI: query -> esearch/efetch -> JSON
│   ├── nl_query_translator.py # NL → sintassi PubMed
│   ├── relevance_filter.py    # filtro di pertinenza semantica
│   ├── mesh_resolver.py       # termini liberi → MeSH controllati
│   └── mcp_server.py          # tool MCP `search_pubmed_papers`
├── tests/
│   ├── test_pubmed_errors.py
│   ├── test_pubmed_models.py
│   ├── test_pubmed_client.py
│   ├── test_pubmed_live.py
│   ├── test_nl_query_translator.py
│   ├── test_run_search.py
│   ├── record_fixtures.py     # registra risposte NCBI reali
│   └── fixtures/              # XML NCBI salvati, senza api_key
└── examples/
    └── sample_queries.md
```

**Principio guida:** ogni modulo deve essere testabile in isolamento. `pubmed_client.py` non deve mai contenere logica di interpretazione NL; `nl_query_translator.py` non deve mai fare chiamate HTTP dirette a NCBI.

Il parsing XML vive in `pubmed_models.py`, che non ha alcuna dipendenza da rete ed è
testabile passandogli stringhe. `pubmed_errors.py` esiste in un modulo proprio perché
sia il parser sia il client devono sollevare eccezioni della stessa gerarchia, e
definirle nel client creerebbe un import circolare.

La skill `/pubmed-search` (`.claude/skills/pubmed-search/SKILL.md`) è l'interfaccia utente:
guida Claude nella fase 1 (estrazione NL → JSON intermedio) e nel filtro di rilevanza
inline, invocando `nl_query_translator` (fase 2, serializzazione deterministica) e
`run_search` (esecuzione). Nessuna API key oltre a quella NCBI.

## 4. API PubMed (NCBI E-utilities) — riferimento tecnico

Base URL: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`

Parametri obbligatori su **ogni** chiamata:
- `tool` — nome applicazione (stringa senza spazi)
- `email` — email di contatto
- `api_key` — la chiave NCBI generata dall'utente

Endpoint principali usati dal progetto:

| Endpoint | Funzione | Note |
|---|---|---|
| `esearch.fcgi?db=pubmed&term=...` | Esegue la query, restituisce PMID | Usare `usehistory=y` per query con molti risultati; supporta `retmax`, `datetype`, `mindate`/`maxdate` |
| `esummary.fcgi?db=pubmed&id=...` | Metadati sintetici (titolo, autori, journal, data) | Fase successiva, non nel MVP: `efetch` restituisce già titolo, autori, journal e data insieme all'abstract |
| `efetch.fcgi?db=pubmed&id=...&rettype=abstract&retmode=xml` | Abstract completo | Necessario per il filtro di rilevanza semantica |
| `elink.fcgi` | Articoli correlati / citazioni | Fase successiva, non nel MVP |

**Rate limiting:** 3 richieste/secondo senza `api_key`, **10 richieste/secondo** con `api_key` valida. `pubmed_client.py` deve implementare un limitatore esplicito (es. token bucket) e gestire i retry su HTTP 429, non affidarsi solo alla libreria HTTP.

**Attenzione — `<ErrorList>` non è un errore fatale.** ESearch restituisce
`<ErrorList><PhraseNotFound>…</PhraseNotFound></ErrorList>` quando un termine non trova
corrispondenze, ma la ricerca è comunque riuscita: quei figli finiscono in
`SearchResult.warnings` e dicono *quale* termine non ha matchato. Solo l'elemento
`<ERROR>` indica un fallimento vero e produce un `PubMedAPIError`.

**Attenzione — un errore può arrivare con HTTP 200.** Una query malformata non produce un
400 ma un `<ERROR>` dentro XML valido con status 200. Controllare solo `status_code`
darebbe una lista vuota indistinguibile da «nessun match».

**Sintassi di ricerca PubMed rilevante da generare in traduzione:**
- Tag di campo: `[tiab]` (title/abstract), `[MeSH Terms]`, `[au]` (autore), `[ta]` (rivista), `[dp]` (data pubblicazione), `[pt]` (tipo di pubblicazione, es. `"randomized controlled trial"[pt]`), `[la]` (lingua)
- Operatori booleani: `AND`, `OR`, `NOT` (maiuscoli, obbligatori)
- Intervalli di date: `("2023"[dp] : "2026"[dp])`
- Esplosione MeSH automatica: PubMed la applica di default sui termini `[MeSH Terms]`; non serve gestirla manualmente
- Frasi esatte tra virgolette per evitare tokenizzazione indesiderata

## 5. Traduzione linguaggio naturale → query PubMed

Componente core (`nl_query_translator.py`). Approccio a due fasi:

1. **Estrazione strutturata** — Claude analizza la query NL e produce un JSON intermedio con: concetti chiave, sinonimi/varianti, filtri (data, tipo di studio, lingua, età/popolazione), esclusioni esplicite, operatori logici impliciti tra i concetti.
2. **Serializzazione in sintassi PubMed** — dal JSON intermedio si genera la stringa `term=` finale, con tag di campo corretti e parentesi per la precedenza booleana.

Separare le due fasi permette di:
- testare la serializzazione senza dover richiamare Claude ogni volta (usando JSON fissi come fixture)
- validare/loggare il JSON intermedio per il debug quando la query risultante non produce i risultati attesi
- riusare `mesh_resolver.py` per mappare i concetti estratti a termini MeSH controllati quando possibile, invece di affidarsi solo a `[tiab]`

**Nota importante:** la traduzione va sempre mostrata all'utente insieme ai risultati (query PubMed generata + link diretto alla ricerca su pubmed.ncbi.nlm.nih.gov), così l'utente può verificare che l'interpretazione sia corretta e, se necessario, correggerla manualmente.

## 6. Filtro di rilevanza semantica

Dopo aver recuperato PMID + abstract via `esummary`/`efetch`, `relevance_filter.py` passa ogni articolo (o un batch) a Claude insieme all'intento originale dell'utente, chiedendo:
- un punteggio o una classificazione di rilevanza
- una breve motivazione (perché è o non è pertinente)
- eventuale segnalazione se l'articolo sembra rilevante ma non ha matchato bene la query booleana (falsi negativi da query troppo restrittiva)

Questo filtro è ciò che distingue il progetto da una semplice interfaccia a ESearch: la query booleana serve a restringere lo spazio di ricerca in modo efficiente, il filtro semantico serve a ordinare/scartare per pertinenza reale.

## 7. Setup ambiente

`.env`:
```
NCBI_API_KEY=...
NCBI_TOOL_NAME=pubmed-nl-search-agent
NCBI_EMAIL=...
```

Nessuna chiave va mai committata o loggata in chiaro; `pubmed_client.py` deve leggerla solo da variabili d'ambiente.

## 8. Roadmap di sviluppo (MVP → oltre)

1. ~~`pubmed_errors.py` + `pubmed_models.py` + `pubmed_client.py` — wrapper ESearch + EFetch
   con rate limiting e parsing tipizzato, testato offline su fixture reali e in modalità live~~
   **(completato)**
2. ~~`nl_query_translator.py` — traduzione NL → sintassi PubMed (solo `[tiab]` + MeSH a
   giudizio di Claude), come modulo deterministico testabile~~ **(completato)**
3. ~~Integrazione end-to-end: query NL → query PubMed → PMID → abstract, tramite
   `run_search.py` e la skill `/pubmed-search`~~ **(completato)**
4. ~~Filtro di rilevanza: implementato inline nella skill `/pubmed-search` (Claude legge
   gli abstract e ordina per pertinenza); `relevance_filter.py` come modulo dedicato resta
   un'evoluzione futura~~ **(completato, inline)**
5. `mesh_resolver.py` — miglioramento della traduzione con termini MeSH controllati
6. `mcp_server.py` — esposizione come tool MCP `search_pubmed_papers`, utilizzabile da Claude Desktop/Code
7. (Successivo) supporto a `elink.fcgi` per articoli correlati e catene di citazioni

## 9. Testing

- I test su `pubmed_client.py` devono poter girare sia in modalità "live" (vera chiamata a NCBI, marcata ed eseguita separatamente per non consumare rate limit nei test automatici) sia in modalità offline usando le fixture XML salvate in `tests/fixtures/`.
- `examples/sample_queries.md` raccoglie query NL reali con la query PubMed attesa e un giudizio manuale sui primi risultati: serve da suite di regressione qualitativa quando si modifica il prompt di traduzione.

I test live sono marcati `@pytest.mark.live` ed esclusi di default da `pytest.ini`
(`addopts = -m "not live"`): `pytest` gira interamente offline, `pytest -m live` esegue le
chiamate reali. Le fixture non si scrivono a mano — `python tests/record_fixtures.py`
registra risposte NCBI autentiche in `tests/fixtures/`, rimuovendo la `api_key` prima di
scrivere su disco.

## 10. Convenzioni di lavoro con Claude Code

- Ogni modifica architetturale rilevante va prima discussa in plan mode e poi riportata in questo file.
- Preferire commit piccoli e mirati per modulo (`pubmed_client`, poi `nl_query_translator`, ecc.) piuttosto che un'unica implementazione monolitica.
- Le chiamate reali verso NCBI vanno sempre testate con query semplici prima di query complesse con molti operatori annidati.
