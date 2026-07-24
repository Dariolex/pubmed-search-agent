# Design — `nl_query_translator.py` + skill `/pubmed-search` (step 2-4 della roadmap)

**Data:** 2026-07-24
**Stato:** approvato in brainstorming, da implementare
**Ambito:** traduzione NL → sintassi PubMed (fase deterministica) e skill Claude Code che
orchestra l'intero flusso NL → query → PMID → abstract → filtro di rilevanza.

---

## 1. Obiettivo

Permettere a un utente di Claude Code di cercare su PubMed in linguaggio naturale, senza
configurare alcuna API key oltre a quella NCBI già presente, senza scrivere codice.

L'intelligenza (comprensione del linguaggio, estrazione dei concetti, giudizio di
rilevanza) vive in Claude, guidato da una skill. La parte meccanica e fragile (sintassi
PubMed: tag di campo, parentesi, booleani, date) vive in un modulo Python deterministico e
testato. Questa divisione è ciò che rende il sistema usabile da tutti *e* affidabile.

Copre gli step 2 (traduzione), 3 (integrazione end-to-end) e 4 (filtro di rilevanza) della
roadmap in `CLAUDE.md` sezione 8, in un unico incremento.

**Fuori ambito:** `mesh_resolver.py` (mappatura MeSH controllata — resta step futuro; qui i
termini MeSH sono a giudizio di Claude), `mcp_server.py` (esposizione come tool MCP),
`elink.fcgi`.

---

## 2. Decisioni di design

| # | Decisione | Motivazione |
|---|---|---|
| D1 | La **fase 1 (estrazione NL → JSON) la fa Claude**, non un'API Anthropic separata | L'utente non deve configurare una seconda API key: parla solo in linguaggio naturale con Claude. Sistema usabile da tutti, non solo da chi sa impostare le API. |
| D2 | La **fase 2 (serializzazione JSON → query) è un modulo Python deterministico** | La sintassi PubMed deve essere identica a parità di input e testabile offline con `pytest` (CLAUDE.md sezione 5). Il giudizio di Claude non garantisce riproducibilità. |
| D3 | Interfaccia utente = **skill Claude Code** `/pubmed-search` | Un file `SKILL.md` che guida Claude nel flusso completo. Nessun codice da scrivere per l'utente, nessuna chiave aggiuntiva. |
| D4 | **CLI** per il traduttore: JSON da stdin, query su stdout | Claude invoca un comando fisso via Bash, senza costruire snippet Python ad-hoc ogni volta. |
| D5 | Schema JSON **esteso con provenienza** | Ogni concetto porta una nota sul perché è stato estratto: serve al debug quando la query non produce i risultati attesi (CLAUDE.md sezione 5). La provenienza non entra mai nella query. |
| D6 | **`mesh` opzionale per concetto**, a giudizio di Claude | La roadmap rinvia `mesh_resolver.py`, ma includere termini MeSH ovvi migliora subito la qualità. Quando Claude non è sicuro, `mesh: null` → solo `[tiab]`. |
| D7 | Più `tipi_studio` uniti in **OR** | "trial randomizzati o meta-analisi" è la lettura naturale: allarga, non restringe. |
| D8 | Nuovo entry-point **`src/run_search.py`** attorno a `pubmed_client` | La skill esegue la ricerca con un comando CLI fisso invece di snippet `pubmed_client` ad-hoc, coerente con D4 e testabile. |
| D9 | Filtro di rilevanza **inline nella skill** (Claude), non modulo dedicato | Anticipa lo step 4 senza costruire subito `relevance_filter.py`: Claude legge gli abstract e valuta la pertinenza rispetto all'intento originale. |

### Deviazioni / aggiunte rispetto a `CLAUDE.md`

- **Sezione 3 (albero file):** nuovo `src/run_search.py` e directory `.claude/skills/pubmed-search/`. Da riportare in CLAUDE.md all'implementazione.
- **Sezione 8 (roadmap):** questo incremento assorbe gli step 2, 3 e 4 insieme; `mesh_resolver.py` (5) e `mcp_server.py` (6) restano futuri.

---

## 3. Componenti

### A. `src/nl_query_translator.py` — serializzazione deterministica

Funzione pura più interfaccia CLI. Nessuna chiamata a Claude, nessuna chiamata HTTP.

```python
def serialize(intermedio: dict) -> str:
    """JSON intermedio → stringa `term=` PubMed. Solleva ValueError se il JSON è
    semanticamente invalido (nessun concetto, operatore ignoto, termine mancante,
    tipo data ignoto)."""

# CLI: python -m nl_query_translator [--file PATH] [--link]
#   input JSON da stdin (default) o da --file
#   stdout: la query (una riga); con --link anche l'URL pubmed.ncbi.nlm.nih.gov
#   errori: messaggio su stderr, exit code 1
```

Importa `pubmed_web_url` da `pubmed_client` per l'opzione `--link` (dipendenza
`nl_query_translator → pubmed_client` accettabile; il vincolo di CLAUDE.md è l'opposto).

La logica pura (`serialize`) è separata dal wiring CLI (argomenti, stdin, exit code) così i
test chiamano `serialize` senza sottoprocessi.

### B. `src/run_search.py` — entry-point di ricerca

CLI sottile attorno a `pubmed_client`. Prende una query PubMed, esegue `esearch` + `efetch`,
stampa gli articoli come JSON su stdout.

```python
# CLI: python -m run_search --term "..." [--retmax N]
#   stdout: JSON con total_count, translated_query, warnings, articles[]
#   errori del client (PubMedAPIError, ecc.) → stderr, exit code 1
```

Nessuna logica NL, nessun parsing XML (delegato a `pubmed_client`/`pubmed_models`).

### C. `.claude/skills/pubmed-search/SKILL.md` — interfaccia utente

Frontmatter con `name: pubmed-search` e `description` contenente i trigger (`/pubmed-search`
o richieste NL di cercare letteratura/studi su PubMed). Il corpo istruisce Claude sul flusso
della sezione 5.

---

## 4. Schema del JSON intermedio (contratto fase 1 → fase 2)

```json
{
  "intento_originale": "testo NL dell'utente, verbatim",
  "concetti": [
    {
      "termine": "melanoma",
      "sinonimi": ["malignant melanoma"],
      "mesh": "melanoma",
      "provenienza": "concetto clinico centrale"
    },
    {
      "termine": "immunotherapy",
      "sinonimi": ["immune checkpoint inhibitor"],
      "mesh": null,
      "provenienza": "trattamento richiesto"
    }
  ],
  "operatore_tra_concetti": "AND",
  "esclusioni": [
    {"termine": "case reports", "campo": "pt", "provenienza": "utente: 'escludendo case report'"}
  ],
  "filtri": {
    "date": {"da": "2023", "a": "2026", "tipo": "dp"},
    "tipi_studio": ["randomized controlled trial"],
    "lingua": null
  }
}
```

- **`concetti`**: lista non vuota. Ogni concetto ha `termine` (obbligatorio), `sinonimi`
  (lista, può essere vuota), `mesh` (stringa o `null`), `provenienza` (stringa, mai nella query).
- **`operatore_tra_concetti`**: `"AND"` o `"OR"`. Un solo operatore per l'MVP — niente
  annidamenti misti (YAGNI).
- **`esclusioni`**: lista (può essere vuota). Ogni voce ha `termine`, `campo` (tag, es.
  `pt`, `tiab`), `provenienza`.
- **`filtri`**: tutti opzionali. `date` con `da`/`a`/`tipo` (`dp`|`edat`|`pdat`);
  `tipi_studio` lista di stringhe; `lingua` stringa o `null`.

Un campo assente o `null` non compare nella query: `serialize` non inventa filtri.

---

## 5. Regole di serializzazione (fase 2)

**Un concetto** → gruppo con sinonimi in OR:
- con `mesh`: `("melanoma"[MeSH Terms] OR "melanoma"[tiab] OR "malignant melanoma"[tiab])`
- senza `mesh`: `("immunotherapy"[tiab] OR "immune checkpoint inhibitor"[tiab])`
- senza sinonimi né mesh: `"metastatic"[tiab]` (nessuna parentesi superflua)

**Concetti tra loro** → uniti da `operatore_tra_concetti`, ogni gruppo parentesizzato:
`(...) AND (...) AND "metastatic"[tiab]`

**Filtri** → in AND, solo se presenti:
- date: `AND ("2023"[dp] : "2026"[dp])` (il `tipo` sceglie il tag)
- tipi di studio (più di uno → OR tra loro): `AND ("randomized controlled trial"[pt] OR "meta-analysis"[pt])`
- lingua: `AND "english"[la]`

**Esclusioni** → `NOT` in fondo: `NOT "case reports"[pt]`

**Regole trasversali:**
- Booleani sempre maiuscoli (`AND`/`OR`/`NOT`).
- Ogni termine tra virgolette doppie; una virgoletta doppia interna al termine viene rimossa
  (PubMed non supporta l'escaping).
- Ordine canonico e stabile: concetti nell'ordine del JSON, poi date, poi tipi di studio,
  poi lingua, poi esclusioni. Stesso input → stessa identica stringa.
- JSON senza concetti → `ValueError`, mai una stringa vuota.

**Contratto di errore CLI:** `serialize` solleva `ValueError` su JSON semanticamente invalido
(concetto senza `termine`, operatore ≠ AND/OR, `tipo` data ignoto, nessun concetto). La CLI
cattura, stampa su stderr, esce con codice 1 — così Claude corregge il JSON invece di
eseguire una query rotta.

---

## 6. Flusso della skill `/pubmed-search`

1. **Estrazione (fase 1).** Da NL → JSON intermedio esteso. Linee guida nella skill:
   esclusioni ("escludendo X" → `NOT`), tipi di studio ("solo RCT" → `pt`), finestre
   temporali ("ultimi 3 anni" → date relative alla data corrente), quando popolare `mesh`.
2. **Serializzazione (fase 2).** `python -m nl_query_translator --link` via Bash, JSON in
   pipe. Ottiene query + URL. **Non costruisce la query a mano.**
3. **Mostra la traduzione** (query + link) all'utente prima/insieme ai risultati
   (CLAUDE.md sezione 5).
4. **Esecuzione.** `python -m run_search --term "..."` → JSON di articoli.
5. **Filtro di rilevanza (inline).** Claude legge gli abstract, valuta la pertinenza
   rispetto a `intento_originale`, scarta/declassa i non pertinenti, ordina, motiva.
6. **Output finale.** Elenco ordinato (titolo, autori, rivista, anno, PMID, motivazione);
   in testa query PubMed e link.

Passi 1 e 5 vivono nel giudizio di Claude guidato dalla skill: non coperti da `pytest`,
verificati con prova d'uso reale e regressione qualitativa (`sample_queries.md`).

---

## 7. Testing

### `tests/test_nl_query_translator.py` (offline, `serialize` su JSON fissi)

- Concetto singolo con `mesh` → gruppo MeSH+tiab+sinonimi
- Concetto singolo senza `mesh` → solo `[tiab]`
- Concetto senza sinonimi né mesh → `"X"[tiab]` senza parentesi superflue
- Più concetti in AND; più concetti in OR
- Filtro date (`dp`, `edat`, `pdat`); tipi di studio multipli in OR; lingua
- Esclusioni multiple in NOT
- Ordine canonico stabile: stesso JSON → stessa stringa (anti-regressione)
- Virgolette interne rimosse; booleani sempre maiuscoli
- Errori → `ValueError`: nessun concetto, operatore ignoto, concetto senza `termine`, tipo data ignoto
- **Query di riferimento del CLAUDE.md** (immunoterapia/melanoma/RCT/date/NOT case report)
  → confronto con la stringa attesa
- CLI: stdin→stdout exit 0; JSON malformato→stderr exit 1; `--link` aggiunge URL; `--file`

### `tests/test_run_search.py` (offline, `responses` + fixture NCBI esistenti)

- Query valida → JSON articoli su stdout
- Errore del client (es. `PubMedAPIError`) → stderr, exit 1

### `examples/sample_queries.md`

Popolato con almeno la query di riferimento del CLAUDE.md: NL, JSON intermedio, query
PubMed attesa, giudizio manuale sui primi risultati. Suite di regressione qualitativa
(CLAUDE.md sezione 9).

---

## 8. Dipendenze

Nessuna nuova dipendenza Python. `nl_query_translator` e `run_search` usano solo stdlib +
il `pubmed_client`/`pubmed_models` esistenti. `responses` (già presente) per i test di
`run_search`.

---

## 9. Criteri di completamento

- [ ] `serialize` produce la query di riferimento del CLAUDE.md esattamente
- [ ] `python -m nl_query_translator --link` legge JSON da stdin, stampa query + URL
- [ ] JSON invalido → exit code 1 con messaggio su stderr
- [ ] `python -m run_search --term "..."` esegue la ricerca e stampa articoli JSON
- [ ] `pytest` passa interamente offline (nessuna nuova chiamata di rete nei test automatici)
- [ ] La skill `/pubmed-search` è invocabile e guida il flusso completo, verificato con una
      prova d'uso reale end-to-end
- [ ] `examples/sample_queries.md` contiene almeno la query di riferimento
- [ ] `CLAUDE.md` aggiornato con `run_search.py` e la skill
