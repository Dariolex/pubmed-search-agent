# Design — `elink`, articoli correlati e citazioni (step 7 della roadmap)

**Data:** 2026-07-27
**Stato:** approvato in brainstorming, da implementare
**Ambito:** dato un PMID, trovare articoli simili e articoli che lo citano, tramite
`elink.fcgi` di NCBI, con lo stesso pattern architetturale di `mesh_resolver.py`.

---

## 1. Obiettivo

Oggi la skill `/pubmed-search` parte sempre da una richiesta in linguaggio naturale che
genera una query booleana. Non c'è modo di chiedere "altri studi come questo" o "chi ha
citato questo lavoro" a partire da un PMID già noto (es. un articolo emerso in una ricerca
precedente). `elink.fcgi` (E-utilities di NCBI) copre esattamente questo caso.

Copre lo step 7 della roadmap in `CLAUDE.md` sezione 8.

**Fuori ambito:**
- `pubmed_pubmed_refs` (riferimenti citati dall'articolo): verificato dal vivo che il dato è
  assente nella maggioranza dei casi (0 su 5 PMID testati in 3 casi, dipende da cosa
  l'editore deposita presso NCBI). Escluso per scelta esplicita in brainstorming — includerlo
  significherebbe mostrare "0 risultati" quasi sempre.
- Catene multi-hop (citazioni di citazioni, correlati dei correlati).
- Un nuovo tool MCP dedicato: il tool esistente resta invariato, questa feature vive in una
  CLI + skill, come `mesh_resolver`.
- Qualsiasi modifica a `mcp_server.py`, `nl_query_translator.py`, `run_search.py`.

---

## 2. Verifiche dal vivo (fatte in brainstorming, non supposizioni)

Tutti i numeri seguenti provengono da chiamate reali all'API NCBI durante il design.

### Tipi di link disponibili e loro affidabilità

Interrogando `elink.fcgi?dbfrom=pubmed&db=pubmed&id=21376230` senza `linkname` (tutti i tipi
insieme): risposta di **1.919.022 byte** per un solo PMID, con questi conteggi:

| `LinkName` | Significato | Link trovati | Nota |
|---|---|---|---|
| `pubmed_pubmed` | Articoli simili | 100 | Tetto fisso, non richiesto esplicitamente |
| `pubmed_pubmed_citedin` | Chi cita l'articolo | 33.929 (su questo PMID) | Volume molto variabile |
| `pubmed_pubmed_refs` | Riferimenti citati dall'articolo | **0, 7, 0, 0, 60** su 5 PMID testati | Inaffidabile, spesso assente |
| `pubmed_pubmed_alsoviewed`, `_combined`, `_five`, `_reviews`, `_reviews_five` | Varianti minori | — | Non richiesti |

Passando **sempre** `linkname` esplicito, la risposta si riduce drasticamente:
`linkname=pubmed_pubmed` → **5 KB**, 101 id totali (100 link + eco della sorgente).
`linkname=pubmed_pubmed_citedin` (con `retmax` — vedi sotto) → 410 KB su un PMID con 8.742
citazioni.

**Conseguenza di design:** il parametro `linkname` è **obbligatorio** in ogni chiamata, non
opzionale — è ciò che riduce la risposta da 1,9 MB a poche decine di KB.

### `retmax` non viene applicato lato NCBI

Testato: `elink.fcgi` con `linkname=pubmed_pubmed_citedin&retmax=10` **non** limita il numero
di `<Id>` restituiti (la risposta contiene comunque tutti gli 8.742 link). Il troncamento va
fatto **lato client**, dopo aver ricevuto la risposta intera.

### Il PMID sorgente compare fra i propri "link"

Verificato due volte:
- Un PMID **valido** (21376230, `linkname=pubmed_pubmed`): il PMID sorgente stesso è il
  **primo** elemento della lista di "articoli simili" restituita (`['21376230',
  '25036871', ...]`).
- Un PMID **inesistente** (999999999, `linkname=pubmed_pubmed`): NCBI non restituisce alcun
  `<ERROR>` — risponde con HTTP 200 e un `<LinkSetDb>` contenente **un solo link: il PMID
  stesso**. Un parser che non escluda la sorgente riporterebbe "1 articolo correlato
  trovato" per un PMID che non esiste.

**Conseguenza di design:** il parser esclude sempre il PMID sorgente dal risultato. Questo
risolve elegantemente entrambi i casi: un PMID inesistente produce lista vuota senza bisogno
di interpretare `<ERROR>` (che qui NCBI non manda).

### Ordine dei risultati

`pubmed_pubmed_citedin`: verificato che gli id **non** sono in ordine numerico crescente
(`ids == sorted(ids)` → `False`); i primi 5 sono PMID 42xxxxxx (2026), gli ultimi 5 sono
32-33xxxxxx (2020-2021). **NCBI ordina dal più recente al più vecchio.** Questo rende il
troncamento lato client (primi N) sensato: si ottengono le citazioni più recenti, non un
sottoinsieme arbitrario.

### `elink` è più fragile degli altri endpoint sotto carico

Durante le verifiche, richieste ripetute che scaricavano risposte da 410 KB–1,9 MB hanno
prodotto **HTTP 500 ripetuti** (falliti dopo i 3 tentativi di retry standard del client). Una
volta introdotto sempre `linkname` (risposte a 5 KB), le richieste sono tornate ad avere
successo in modo affidabile. **Non si aumentano i retry**: la causa era il volume di
risposta, che il design elimina alla radice richiedendo sempre `linkname` esplicito e
limitando lato client.

---

## 3. Decisioni di design

| # | Decisione | Motivazione |
|---|---|---|
| D1 | Due soli `linkname` supportati: `pubmed_pubmed` ("simili") e `pubmed_pubmed_citedin` ("citazioni") | Scelto in brainstorming. Sono gli unici due affidabili; `_refs` è escluso perché il dato è quasi sempre assente. |
| D2 | `linkname` è **sempre** passato esplicitamente, mai omesso | Verificato dal vivo: senza, la risposta è 1,9 MB con tutti i tipi insieme. |
| D3 | Troncamento a `max_links` **lato client**, dopo il parsing | `retmax` non ha effetto su `elink` (verificato). Il default è `30`, coerente con `--retmax 30` già usato da `run_search` nella skill. |
| D4 | Il **PMID sorgente è sempre escluso** dal risultato parsato | Compare come primo elemento anche per un PMID valido, ed è l'unico elemento per un PMID inesistente (nessun `<ERROR>` da NCBI in quel caso). Escluderlo gestisce entrambi i casi senza logica ad hoc. |
| D5 | Nuovo metodo **`PubMedClient.elink()`**, non un client separato | Stesso principio di `resolve_mesh`: riusa `_request`/rate limiter/retry già testati. |
| D6 | Parsing in **`pubmed_models.py`** (`parse_elink_xml`), non nel client | Coerente col principio del progetto: nessun parsing XML in `pubmed_client.py`. |
| D7 | **Nessun aumento dei retry/timeout** per `elink` | La fragilità osservata era proporzionale al volume di risposta (1,9 MB / 410 KB), non un problema strutturale dell'endpoint. Il design lo elimina imponendo `linkname` sempre e troncando lato client; aumentare i retry curerebbe il sintomo invece della causa. |
| D8 | Nuova CLI **`related_search.py`**, output nello stesso formato JSON di `run_search` | Permette alla skill di riusare lo stesso passaggio di filtro di rilevanza semantica già implementato per i risultati di ricerca ordinaria, senza duplicare logica. |
| D9 | La CLI fa **`elink` poi `efetch`**, non restituisce solo PMID nudi | L'utente deve poter valutare la rilevanza (serve titolo/abstract), non solo un elenco di identificativi. |

---

## 4. Componenti

### A. `pubmed_models.py` — `parse_elink_xml`

```python
def parse_elink_xml(xml: str, pmid_sorgente: str) -> list[str]:
    """Estrae i PMID collegati da una risposta elink, escludendo la sorgente.

    Il PMID sorgente compare sempre nel proprio LinkSetDb (verificato dal vivo:
    è il primo elemento per un PMID valido, l'unico per un PMID inesistente,
    dato che NCBI non restituisce <ERROR> in quel caso). Escluderlo qui rende
    "PMID inesistente" e "nessun link trovato" indistinguibili a valle: entrambi
    producono lista vuota, comportamento corretto in entrambi i casi.
    """
```

Implementazione: naviga `<eLinkResult><LinkSet><LinkSetDb><Link><Id>`, filtra `pmid_sorgente`,
preserva l'ordine restituito da NCBI (più recente → più vecchio per `citedin`). Nessuna
dipendenza di rete: testabile passando XML fissi, come gli altri parser del modulo.

### B. `pubmed_client.py` — `PubMedClient.elink()`

```python
def elink(self, pmid: str, linkname: str, *, max_links: int = 30) -> list[str]:
    """Trova PMID collegati a `pmid` secondo `linkname`.

    `linkname` è obbligatorio (non opzionale): senza, NCBI restituisce tutti i
    tipi di link insieme, ~1.9 MB anche per un solo PMID (verificato dal vivo).
    `retmax` non ha effetto su elink (verificato): il troncamento a `max_links`
    avviene qui, lato client, dopo il parsing.

    `linkname` validi in questo progetto: "pubmed_pubmed" (articoli simili),
    "pubmed_pubmed_citedin" (articoli che citano `pmid`).
    """
    xml = self._request(
        "elink.fcgi",
        {"dbfrom": "pubmed", "db": "pubmed", "id": pmid, "linkname": linkname, "retmode": "xml"},
    )
    return parse_elink_xml(xml, pmid)[:max_links]
```

### C. `src/related_search.py` — CLI sottile

```
python -m related_search --pmid 33301246 --tipo simili --max 30
python -m related_search --pmid 33301246 --tipo citazioni --max 30
```

- `--tipo simili` → `linkname="pubmed_pubmed"`
- `--tipo citazioni` → `linkname="pubmed_pubmed_citedin"`

Flusso: `client.elink(pmid, linkname, max_links=max)` → `client.efetch(pmid_collegati)` →
stampa lo **stesso formato JSON di `run_search.esegui`** (`total_count`, `articles`), così la
skill applica il filtro di rilevanza già esistente senza codice nuovo. `total_count` qui è
`len(pmid_collegati)` (non un conteggio NCBI separato, a differenza di `esearch`).

Nessuna logica NL, nessun parsing XML proprio: delega a `pubmed_client`/`pubmed_models`, come
le altre CLI del progetto.

### D. Skill `/pubmed-search` — nuova sezione

Quando l'utente chiede articoli simili o citazioni a partire da un PMID noto (es. "trovami
studi simili a questo articolo, PMID 33301246" o "chi ha citato questo lavoro"), la skill
invoca `python -m related_search --pmid <pmid> --tipo <simili|citazioni> --max 30` e applica
lo stesso passaggio di filtro/ordinamento per rilevanza semantica già usato per i risultati di
`run_search` (fase 5 esistente), rispetto all'intento originale della richiesta.

---

## 5. Testing

- **`tests/test_pubmed_models.py`** (estensione): `parse_elink_xml` su XML fisso — link
  multipli con sorgente esclusa; solo auto-riferimento → lista vuota (copre sia "nessun link"
  sia "PMID inesistente", stesso comportamento per design).
- **`tests/record_fixtures.py`** (estensione): registra `elink_simili.xml` e
  `elink_citazioni.xml` (PMID reale con risultati noti), rimuovendo `api_key`.
- **`tests/test_pubmed_client.py`** (estensione): `elink()` con `responses` mockato —
  `linkname` è sempre passato nella richiesta HTTP; troncamento a `max_links` verificato con
  una fixture che contiene più link del limite.
- **`tests/test_related_search.py`** (nuovo): test della CLI — `--tipo simili`, `--tipo
  citazioni`, formato di output identico a `run_search`, PMID senza link → `articles: []`.
- **`tests/test_pubmed_live.py`** (estensione, `@pytest.mark.live`): una chiamata `elink` reale
  per tipo (simili, citazioni) su un PMID noto, verificando che il PMID sorgente non compaia
  nel risultato.
- `pytest` senza argomenti resta interamente offline.

---

## 6. Dipendenze

Nessuna nuova dipendenza. Riusa `requests`, `responses` (test), l'infrastruttura esistente di
`pubmed_client`/`pubmed_models`/`pubmed_errors`.

---

## 7. Criteri di completamento

- [ ] `PubMedClient.elink(pmid, linkname, max_links=30)` restituisce una lista di PMID
      collegati, sempre esclusa la sorgente, verificato contro l'API reale per entrambi i
      `linkname` supportati
- [ ] Un `linkname` non passato esplicitamente non è possibile (parametro obbligatorio nella
      firma, non ha default)
- [ ] `max_links` tronca lato client (verificato con fixture che eccede il limite)
- [ ] Un PMID inesistente produce lista vuota, non un errore né un falso "1 risultato"
- [ ] `python -m related_search --pmid ... --tipo simili|citazioni --max ...` produce lo
      stesso formato JSON di `run_search` (`total_count`, `articles`)
- [ ] La skill `/pubmed-search` invoca `related_search` per richieste di articoli
      simili/citazioni a partire da un PMID, riusando il filtro di rilevanza esistente
- [ ] `pytest` passa interamente offline; `pytest -m live` passa contro NCBI per entrambi i
      tipi di link
- [ ] `CLAUDE.md` aggiornato (roadmap sezione 8, step 7 completato; nota su `elink` in
      sezione 4 se pertinente)
