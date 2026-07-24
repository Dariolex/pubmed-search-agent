# Design — `mesh_resolver.py` (step 5 della roadmap)

**Data:** 2026-07-25
**Stato:** approvato in brainstorming, da implementare
**Ambito:** risoluzione autoritativa di termini liberi verso il vocabolario MeSH
controllato di NCBI, a sostituzione del giudizio estemporaneo di Claude nella skill
`/pubmed-search`.

---

## 1. Obiettivo

Oggi il campo `mesh` nel JSON intermedio (prodotto da Claude nella fase 1 della skill
`/pubmed-search`) è una stima: Claude popola `mesh: "melanoma"` quando ritiene ovvio il
termine MeSH corrispondente, `null` altrimenti. Nessuna verifica contro il vocabolario
ufficiale.

`mesh_resolver.py` introduce una verifica autoritativa: interroga il database MeSH di
NCBI per confermare (o correggere, o negare) il termine MeSH di un concetto, e recupera
i sinonimi ufficiali (entry term) associati. Migliora la qualità della query PubMed
generata senza cambiare l'architettura esistente (skill → CLI → CLI).

Copre lo step 5 della roadmap in `CLAUDE.md` sezione 8.

**Fuori ambito:** `mcp_server.py` (step 6), disambiguazione complessa fra più candidati
MeSH (si sceglie il primo risultato pertinente o nessuno), gestione dell'esplosione MeSH
automatica (PubMed la applica già di default su `[MeSH Terms]`, non è compito di questo
modulo).

---

## 2. Decisioni di design

| # | Decisione | Motivazione |
|---|---|---|
| D1 | Fonte autoritativa: **API NCBI, database MeSH** (`db=mesh`) | Vocabolario sempre aggiornato, stessa infrastruttura (api_key, rate limit) già in uso. Evita di scaricare/mantenere un file MeSH locale. |
| D2 | Nuova **CLI** `mesh_resolver.py`, invocata dalla skill **prima** della fase 2 (serializzazione) | Coerente col pattern già stabilito (`nl_query_translator`, `run_search` sono CLI invocate dalla skill). Mantiene `nl_query_translator.py` puro e senza rete. |
| D3 | Nessun match affidabile → `descriptor: null`, fallback su `[tiab]` | Comportamento identico a oggi quando Claude non è sicuro. Nessuna interruzione del flusso, nessuna disambiguazione complessa. |
| D4 | Restituisce anche gli **entry term** ufficiali (sinonimi MeSH) | Arricchisce il campo `sinonimi` del concetto con informazione autoritativa, non solo il tag `[MeSH Terms]`. |
| D5 | Nuovo metodo **`PubMedClient.resolve_mesh()`**, non un client separato | Riusa `_request`/`RateLimiter`/retry già testati in `pubmed_client.py`, invece di duplicare la logica di trasporto. |
| D6 | ESearch con **`term={termine}[MeSH Terms:noexp]`** (match esatto sull'intestazione MeSH), non una ricerca libera | **Verificato dal vivo contro l'API reale in fase di brainstorming.** Questo campo restituisce `Count=1` con l'UID corretto quando il termine corrisponde esattamente a un'intestazione MeSH ufficiale (case-insensitive), e `Count=0` (con `<ErrorList><PhraseNotFound>`) quando non c'è alcuna corrispondenza. Elimina la necessità di euristiche di somiglianza: NCBI stesso fa da arbitro del match esatto, senza falsi positivi possibili. Una ricerca libera su `term={termine}` (senza il tag di campo) restituisce invece risultati per rilevanza testuale generica e può anteporre voci correlate ma non pertinenti (verificato: "melanoma" senza tag restituiva come primo risultato un antigene di superficie cellulare, non la malattia). |
| D7 | Un errore di rete/NCBI durante la risoluzione **non interrompe la traduzione** | Il resolver è un arricchimento opzionale. La skill tratta un errore come "nessun match" e prosegue con `[tiab]`. |

### Formato della risposta, verificato dal vivo

Il rischio originariamente segnalato (formato ESummary di `db=mesh` non verificato) è
stato chiuso durante il brainstorming con chiamate reali all'API:

- **ESearch** (`term={termine}[MeSH Terms:noexp]&db=mesh`): stesso schema XML di
  `esearch` su `db=pubmed` (`<Count>`, `<IdList><Id>`), ma il conteggio è sempre 0 o 1
  con questo tag di campo — non serve gestire liste di candidati multipli.
- **ESummary** (`db=mesh&id={uid}`): un `<DocSum>` con vari `<Item Name="DS_*">`. Il
  campo rilevante è `<Item Name="DS_MeshTerms" Type="List">`, una lista di
  `<Item Name="string">`: **il primo elemento è il nome ufficiale del descriptor**, gli
  elementi successivi sono gli entry term (sinonimi). Esempio reale per "melanoma"
  (UID `68008545`): `["Melanoma", "Melanomas", "Malignant Melanoma", "Malignant Melanomas", "Melanoma, Malignant", "Melanomas, Malignant"]` → descriptor `"Melanoma"`, entry term il resto della lista.

---

## 3. Componenti

### A. `PubMedClient.resolve_mesh()` — nuovo metodo in `pubmed_client.py`

```python
def resolve_mesh(self, termine: str) -> "MeshMatch | None":
    """Risolve un termine libero verso il descriptor MeSH ufficiale, se esiste
    un match esatto.

    Flusso a due chiamate (stesso pattern di esearch+efetch):
    1. esearch.fcgi?db=mesh&term={termine}[MeSH Terms:noexp] -> 0 o 1 UID
       (match esatto sull'intestazione, verificato dal vivo — D6)
    2. esummary.fcgi?db=mesh&id={uid} -> DS_MeshTerms: [descriptor, *entry_term]

    Restituisce None se Count=0 (nessuna intestazione MeSH corrisponde esattamente
    al termine).
    """
```

### B. `MeshMatch` — nuova dataclass in `pubmed_models.py`

```python
@dataclass(frozen=True)
class MeshMatch:
    termine_originale: str
    descriptor: str              # nome ufficiale del termine MeSH
    entry_terms: list[str]       # sinonimi ufficiali del vocabolario MeSH
    mesh_ui: str                 # identificativo univoco NCBI (debug)
```

Il parsing della risposta ESummary di `db=mesh` vive in `pubmed_models.py` (funzione
`parse_mesh_esummary_xml` o simile), coerente col principio che il parsing XML non
appartiene mai a `pubmed_client.py`.

### C. `src/mesh_resolver.py` — CLI sottile

```
python -m mesh_resolver --termine "melanoma"
```

- **Successo (match trovato)** — stdout, JSON su una riga, exit 0:
  `{"termine_originale": "melanoma", "descriptor": "Melanoma", "entry_terms": ["Melanomas", "Malignant Melanoma"], "mesh_ui": "D008545"}`
- **Nessun match affidabile** — stdout, exit 0 (esito valido, non un errore):
  `{"termine_originale": "xyz123", "descriptor": null, "entry_terms": [], "mesh_ui": null}`
- **Errore reale** (rete, NCBI down) — messaggio su stderr, exit 1

Nessuna logica NL, nessun parsing XML proprio: delega tutto a `pubmed_client`/`pubmed_models`.

### D. Skill `/pubmed-search` — aggiornamento minimo

Per ogni concetto dove Claude non è certo del termine MeSH, la skill invoca
`python -m mesh_resolver --termine "..."` prima di passare il JSON a
`nl_query_translator`, e usa il risultato per popolare `mesh` e arricchire `sinonimi`
con gli entry term ufficiali. Un errore (exit 1) o un match assente vengono trattati
allo stesso modo: si prosegue senza MeSH per quel concetto.

---

## 4. Testing

- **`tests/test_pubmed_client.py`** (estensione): `resolve_mesh()` con `responses`
  mockato — match trovato, nessun match (lista vuota), match scartato per bassa
  somiglianza, propagazione di errori di rete/NCBI.
- **`tests/test_pubmed_models.py`** (estensione): parsing di `MeshMatch` da XML
  ESummary reale registrato.
- **`tests/record_fixtures.py`** (estensione): registra `mesh_esearch_match.xml` e
  `mesh_esummary_match.xml` (termine con match certo, es. "melanoma"), verificando dal
  vivo il formato esatto della risposta prima di scrivere il parser definitivo.
- **`tests/test_mesh_resolver.py`** (nuovo): test della CLI — successo, nessun match,
  errore → stderr/exit 1.
- **Live test** (`@pytest.mark.live`, escluso di default): una risoluzione reale di un
  termine noto, end-to-end contro la vera API MeSH.

---

## 5. Dipendenze

Nessuna nuova dipendenza Python. Riusa `requests`, `responses` (test), e l'infrastruttura
esistente di `pubmed_client`/`pubmed_models`/`pubmed_errors`.

---

## 6. Criteri di completamento

- [ ] `PubMedClient.resolve_mesh("melanoma")` restituisce un `MeshMatch` con descriptor
      ed entry term corretti, verificato contro l'API reale
- [ ] Un termine senza match affidabile restituisce `None`, non solleva eccezione
- [ ] `python -m mesh_resolver --termine "..."` produce il contratto di output descritto
      (successo/nessun match/errore)
- [ ] Un errore di rete durante la risoluzione non interrompe il resto del flusso della
      skill (verificato con la skill aggiornata)
- [ ] `pytest` passa interamente offline (nessuna nuova chiamata di rete nei test
      automatici); `pytest -m live` passa contro NCBI
- [ ] `.claude/skills/pubmed-search/SKILL.md` aggiornata per invocare `mesh_resolver`
- [ ] `CLAUDE.md` aggiornato (roadmap sezione 8, step 5 completato)
