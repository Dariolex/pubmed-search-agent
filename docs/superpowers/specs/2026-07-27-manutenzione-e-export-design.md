# Design — Manutenzione codice + paginazione + export bibliografico

**Data:** 2026-07-27
**Stato:** approvato in brainstorming, da implementare
**Ambito:** quattro interventi indipendenti ma correlati, nati da una review a freddo del
codice dopo il completamento della roadmap MVP: rimozione di codice morto, esposizione della
paginazione già supportata da NCBI ma mai raggiungibile dall'utente, deduplicazione della
gestione errori/output nelle CLI, e un nuovo export bibliografico (RIS/BibTeX).

---

## 1. Obiettivo

Durante l'uso reale della skill in questa sessione sono emersi due limiti concreti (non
teorici): risultati troncati senza modo di vedere il resto (156 match, 30 mostrati; 77 match,
29 mostrati), e nessun modo di portare i risultati fuori dalla conversazione verso un
reference manager. In parallelo, una review del codice ha trovato un modulo mai implementato
ma ancora presente e documentato (`relevance_filter.py`) e una piccola duplicazione fra le
CLI.

**Fuori ambito:** cache locale delle risposte NCBI, `esummary.fcgi` come nuovo endpoint,
formato CSV per l'export (solo RIS+BibTeX), qualsiasi modifica a `mcp_server.py`,
`pubmed_models.py`, `pubmed_client.py.esearch/efetch` (solo `elink` guadagna un parametro),
`nl_query_translator.py` (adotta solo l'helper di stampa errori, nessun'altra modifica).

---

## 2. Verifiche dal vivo (fatte in brainstorming, non supposizioni)

**`retstart` è affidabile per la paginazione**, senza bisogno di propagare `WebEnv`/
`query_key`: interrogata due volte la stessa query con `retstart=5`, i risultati sono
**identici** fra le due chiamate (nessuna instabilità legata a un indice che cambia sotto i
piedi), e non c'è **alcuna sovrapposizione** fra `retstart=0` e `retstart=5` sulla stessa
query. `WebEnv`/`query_key` restano parsati (`SearchResult`) ma inutilizzati anche dopo questo
lavoro — usarli aggiungerebbe stato con scadenza da propagare, senza beneficio misurato.

**`relevance_filter.py` non è importato da nessun modulo**: verificato con una ricerca globale
nel codice sorgente (`.py`), il solo file che lo nomina è se stesso. È referenziato solo in
prosa in `CLAUDE.md` (sezioni 3, 6, roadmap) come se fosse il componente che fa il filtro,
mentre il filtro vive da tempo inline nella skill (step 4 della roadmap, completato "inline").
Cancellazione sicura, nessun impatto su import esistenti.

---

## 3. Decisioni di design

| # | Decisione | Motivazione |
|---|---|---|
| D1 | **Cancellare** `src/relevance_filter.py`, non riscriverne il docstring | Zero funzioni, zero import. Un file che promette un modulo mai esistito è peggiore di nessun file, specialmente ora che il repo è pubblico. La storia git lo conserva se mai servisse recuperarlo. |
| D2 | `CLAUDE.md` sezione 6 riscritta per descrivere il filtro **inline nella skill**, non un modulo dedicato | Allinea la documentazione alla realtà: oggi la sezione 6 descrive un componente (`relevance_filter.py`) che non fa quel lavoro. |
| D3 | Paginazione via **`retstart` semplice**, non `WebEnv`/`query_key` | Verificato dal vivo che è sufficiente e stabile (D2 sopra). Introdurre lo stato di history NCBI aggiungerebbe complessità (scadenza, propagazione fra chiamate CLI separate) senza necessità dimostrata. |
| D4 | `related_search.py`: nuovo parametro **`offset`** su `PubMedClient.elink()`, non su `related_search.esegui` direttamente | `elink` restituisce sempre l'intera lista collegata (non supporta un vero paging lato NCBI, verificato nel lavoro precedente: `retmax` non ha effetto su `elink.fcgi`). Il paging qui è uno slice `[offset : offset+max_links]` lato client, quindi il parametro appartiene al metodo che already fa il troncamento (`elink`), non a un nuovo endpoint. |
| D5 | `cli_utils.py` con **due** helper, non uno solo | La review aveva notato solo la duplicazione dell'errore (4 CLI), ma la stampa JSON è duplicata in 3 CLI (`run_search`, `mesh_resolver`, `related_search`) con lo stesso pattern `json.dump(..., ensure_ascii=True, indent=2)`. Consolidare entrambe evita che il prossimo modulo CLI reintroduca la stessa duplicazione con una sola metà sistemata. |
| D6 | Export come **CLI separata che legge JSON da stdin/file**, non un flag `--export` sulle CLI di ricerca | Scelto in brainstorming: zero duplicazione (funziona identico con l'output di `run_search` e `related_search`, che condividono lo stesso formato), componibile via pipe, testabile offline passando JSON fisso — nessuna nuova dipendenza di rete. |
| D7 | Formati export: **RIS e BibTeX**, non CSV | Scelto in brainstorming: coprono la quasi totalità dei casi d'uso accademici (reference manager e LaTeX); CSV aggiunto solo se emerge un bisogno reale di screening tabellare. |
| D8 | Formato ignoto in `export_results` → **errore esplicito**, non output vuoto | Coerente con l'invariante già in uso nel progetto (es. `nl_query_translator` su JSON semanticamente invalido): un formato non riconosciuto deve fermare il chiamante, non produrre un file silenziosamente vuoto o malformato. |

---

## 4. Componenti

### A. Rimozione codice morto

- `git rm src/relevance_filter.py`.
- `CLAUDE.md`, sezione 3 (albero directory): rimuovere la riga `relevance_filter.py`.
- `CLAUDE.md`, sezione 6: riscrivere per descrivere il filtro come comportamento della skill
  `/pubmed-search` (fase 5, già documentata in `.claude/skills/pubmed-search/SKILL.md`), non
  come modulo Python dedicato.
- `CLAUDE.md`, roadmap (step 4): il testo already dice "inline"; rimuovere solo il riferimento
  al nome file `relevance_filter.py` come "evoluzione futura", visto che non è più presente
  nemmeno come placeholder.

### B. Paginazione — `run_search.py`

```python
parser.add_argument("--retstart", type=int, default=0, help="Offset per la paginazione")
```

`esegui(term, retmax, client, retstart=0)` passa `retstart` a `client.esearch(term,
retmax=retmax, retstart=retstart)` (parametro già supportato dal client, oggi mai
valorizzato da nessun chiamante).

### C. Paginazione — `PubMedClient.elink()` e `related_search.py`

```python
def elink(self, pmid: str, linkname: str, *, max_links: int = 30, offset: int = 0) -> list[str]:
    ...
    return parse_elink_xml(xml, pmid)[offset : offset + max_links]
```

`related_search.py` guadagna `--retstart` (stesso nome CLI di `run_search`, per coerenza),
passato come `offset` a `esegui(pmid, tipo, max_links, client, offset=0)`.

### D. `src/cli_utils.py` — nuovo modulo

```python
def scrivi_errore(exc: Exception) -> None:
    """Scrive un'eccezione su stderr con encoding robusto (evita UnicodeEncodeError
    su console Windows con encoding restrittivo, es. cp1252)."""
    import sys
    sys.stderr.buffer.write(
        f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
    )

def stampa_json(dati: dict) -> None:
    """Stampa un dizionario come JSON su stdout, stesso formato in tutte le CLI del progetto."""
    import sys, json
    json.dump(dati, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
```

Adottato da `run_search.py`, `mesh_resolver.py`, `related_search.py` (entrambi gli helper) e
`nl_query_translator.py` (solo `scrivi_errore`, perché stampa una query testuale non un JSON).

### E. `src/export_results.py` — nuova CLI

```
PYTHONPATH=src python -m run_search --term "..." --retmax 30 | PYTHONPATH=src python -m export_results --formato ris
PYTHONPATH=src python -m export_results --formato bibtex --file risultati.json
```

Funzione pura:

```python
def esporta(dati: dict, formato: str) -> str:
    """Converte il JSON di run_search/related_search (chiave 'articles') in RIS o BibTeX.

    Solleva ValueError se formato non è 'ris' o 'bibtex'.
    """
```

- **RIS**: un record per articolo — `TY  - JOUR`, `AU  - <ogni autore>`, `TI  - <title>`,
  `JO  - <journal>`, `PY  - <anno, primi 4 caratteri di pub_date>`, `DO  - <doi>` (se
  presente), `AB  - <abstract>` (se presente), `ID  - <pmid>` (usato come identificativo,
  campo abbastanza standard per portare il PMID nei reference manager), terminato da `ER  -`.
- **BibTeX**: `@article{pmid<PMID>, author = {<autori separati da " and ">}, title =
  {<title>}, journal = {<journal>}, year = {<anno>}, doi = {<doi>}}` (campo `doi` omesso se
  assente).
- `pub_date` è una stringa ISO parziale (`"2024"`, `"2024-03"`, `"2024-03-15"`, convenzione
  già stabilita in `pubmed_models.Article`): l'anno si estrae con i primi 4 caratteri, non con
  un parsing di data completo.
- Caratteri speciali: BibTeX richiede l'escaping minimo delle graffe nel titolo (`{`/`}` →
  raddoppiate o rimosse se presenti, raro ma possibile in titoli con formule); RIS non
  richiede escaping (è un formato a campi taggati riga per riga).

CLI:

```python
parser.add_argument("--formato", required=True, choices=["ris", "bibtex"])
parser.add_argument("--file", help="Legge il JSON da questo file invece che da stdin")
```

Legge JSON da `--file` o stdin, chiama `esporta`, stampa il risultato su stdout (così è
ridirigibile con `>` verso un file `.ris`/`.bib`).

---

## 5. Testing

- **`tests/test_pubmed_client.py`** (estensione): `elink()` con `offset` — verifica lo slice
  corretto con `responses` mockato (fixture con più link del necessario, `offset=2,
  max_links=2` restituisce esattamente gli elementi attesi).
- **`tests/test_run_search.py`** (estensione): `esegui(..., retstart=10)` passa `retstart` a
  `client.esearch` (verificato ispezionando la chiamata, come già fatto per `retmax` in
  `test_mcp_server.py`).
- **`tests/test_related_search.py`** (estensione): `esegui(..., offset=N)` propaga
  correttamente a `client.elink(..., offset=N)`.
- **`tests/test_cli_utils.py`** (nuovo): `scrivi_errore` e `stampa_json` testati in isolamento
  (cattura di stdout/stderr via `capsys`), poi verifica che `run_search`/`mesh_resolver`/
  `related_search`/`nl_query_translator` producano lo stesso output di prima dopo
  l'adozione (nessuna regressione sui test CLI esistenti, che restano il test di non
  regressione più forte).
- **`tests/test_export_results.py`** (nuovo, offline): `esporta` con un JSON fisso a 1-2
  articoli → confronto stringa esatta per RIS e per BibTeX; formato ignoto → `ValueError`;
  articolo senza `doi`/`abstract` → campo omesso, non stringa `"None"` letterale; CLI con
  `--file` e con stdin.
- Nessun test live nuovo necessario: export e paginazione sono deterministici una volta che i
  dati sono arrivati; il comportamento di NCBI su `retstart` è già coperto dai test live
  esistenti di `esearch`.
- `pytest` senza argomenti resta interamente offline.

---

## 6. Dipendenze

Nessuna nuova dipendenza. RIS e BibTeX sono formati testuali semplici, generabili con
f-string; nessuna libreria di terze parti necessaria per un serializzatore di questa
semplicità.

---

## 7. Criteri di completamento

- [ ] `src/relevance_filter.py` cancellato; `CLAUDE.md` non lo nomina più come modulo, sezione
      6 descrive il filtro come comportamento della skill
- [ ] `run_search --retstart N` restituisce la pagina corretta, verificato che due chiamate
      con `retstart` diversi non si sovrappongano (già verificato dal vivo in brainstorming;
      il test automatico verifica solo la propagazione del parametro, non rifà la verifica di
      rete)
- [ ] `related_search --retstart N` restituisce lo slice corretto della lista di link
- [ ] `cli_utils.scrivi_errore`/`stampa_json` adottati da tutte e 4 le CLI esistenti, nessuna
      regressione nei test CLI già presenti
- [ ] `export_results --formato ris` e `--formato bibtex` producono output corretto da un
      JSON fisso, leggibile sia da stdin sia da `--file`
- [ ] Formato non riconosciuto solleva errore esplicito (CLI: stderr + exit 1)
- [ ] `pytest` passa interamente offline
- [ ] `.claude/skills/pubmed-search/SKILL.md` aggiornata: menzione di `--retstart` per
      proporre "vuoi vedere altri risultati?" quando `total_count` supera quelli mostrati, e
      dell'export bibliografico come opzione dopo aver presentato i risultati
