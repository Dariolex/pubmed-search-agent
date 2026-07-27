# Design — filtro brevetti `[cois]` + `Article.coi_statement`

**Data:** 2026-07-27
**Stato:** approvato in brainstorming, da implementare
**Ambito:** filtro opzionale per articoli che dichiarano un brevetto, tramite il campo
Conflict of Interest Statement di PubMed, ed esposizione del testo della dichiarazione
negli articoli restituiti.

---

## 1. Obiettivo

Permettere all'utente di chiedere, in linguaggio naturale, **articoli i cui autori
dichiarano un brevetto** ("solo studi che dichiarano un brevetto registrato"), e ottenere
risultati che siano davvero tali.

La feature ha due componenti inscindibili:

- **A. Il filtro** — restringe la ricerca al campo Conflict of Interest Statement
  (`[cois]`), l'unico posto in PubMed dove i brevetti compaiono.
- **B. L'esposizione del testo COI** — rende la dichiarazione leggibile a valle, così che
  il filtro di rilevanza semantica possa scartare le dichiarazioni *negative* che il
  filtro booleano inevitabilmente cattura.

Senza (B), la feature fallirebbe silenziosamente: consegnerebbe una quota rilevante di
articoli che dichiarano di **non** avere brevetti, senza che nessuno a valle possa
accorgersene.

**Fuori ambito:** un filtro `cois` generico su termine arbitrario (YAGNI: si aggiungerà se
servirà); la direzione di esclusione ("senza brevetti"), già ottenibile con il meccanismo
`esclusioni` esistente indicando `campo: "cois"`; qualsiasi modifica a `mcp_server.py`
(il tool è term-based e riceve il nuovo campo automaticamente).

---

## 2. Verifiche dal vivo (fatte in brainstorming, non supposizioni)

Tutti i numeri seguenti provengono da chiamate reali all'API NCBI durante il design. I
conteggi sono fotografie di un indice vivo: `patent*[cois]` è stato misurato 145.879 e, pochi
minuti dopo, 145.878. Le differenze di una manciata di unità fra le tabelle sono deriva reale
dell'indice PubMed, non refusi.

### PubMed non indicizza i brevetti

| Query | Count | Esito |
|---|---|---|
| `patent[si]` (Secondary Source ID) | 0 | ❌ `PhraseNotFound` |
| `patents[sb]` (subset) | 0 | ❌ nessun subset brevetti |
| `patent[cois]` | 103.637 | ✅ |
| `patent*[cois]` | 145.879 | ✅ (cattura patent/patents/patented) |

Non esiste alcun campo strutturato per i brevetti: **`[cois]` è l'unico proxy disponibile**.
Si usa la forma con wildcard `patent*` per il recall maggiore.

### Le virgolette non disattivano la troncatura in `[cois]`

| Query | Count |
|---|---|
| `patent*[cois]` | 145.878 |
| `"patent*"[cois]` | 145.878 |

**Conseguenza di design:** `_frase()` in `nl_query_translator.py` racchiude sempre i termini
fra virgolette, e in questo campo ciò **non** annulla il `*`. Nessun caso speciale nel
serializzatore: si riusa l'helper esistente senza modifiche.

### Il filtro cattura anche dichiarazioni negative

Lettura di 10 `<CoiStatement>` reali estratti da `patent*[cois]`: **5 positive**
(co-inventore, brevetto depositato, royalties da brevetto), **3 negative**, 2 ambigue.
Esempi autentici di falso positivo:

> "The authors have no economic relationship with the manufacturers ... such as employment,
> consulting, shareholding or **patent licensing**."

> "The authors declare that ... they ... hold no employment, financial interests, stocks or
> shares, consultation arrangements, or **patents** relevant [to this work]."

Un'euristica di pattern su 80 record segnala il 62%, ma **sovrastima**: cattura anche gli
enunciati misti, che sono positivi — es. *"The technology described in this manuscript is
covered by a pending Korean patent application (KR 10-2025-0208418). The authors declare no
other competing interests."*

**Il tasso reale sta fra ~30% e ~60% e non è determinabile per matching testuale.** Questa è
esattamente la motivazione della componente B: la classificazione richiede un modello che
legga la dichiarazione, non una regex.

### Posizione di `<CoiStatement>` nell'XML

`<CoiStatement>` è **figlio di `<MedlineCitation>`** (fratello di `<Article>`), verificato su
record reale. In `parse_efetch_xml` la variabile `citazione` (il nodo `MedlineCitation`) è
**già in scope** — è usata per estrarre i `mesh_terms`. L'aggiunta è di una riga.

---

## 3. Decisioni di design

| # | Decisione | Motivazione |
|---|---|---|
| D1 | Filtro modellato come booleano dedicato **`filtri.brevetto: true`** | Scelto in brainstorming. Mirato alla richiesta reale, nessuna astrazione prematura (un filtro `cois` generico è YAGNI finché non serve un secondo caso d'uso). |
| D2 | Serializza in ` AND "patent*"[cois]` riusando **`_frase("patent*", "cois")`** | Le virgolette non disattivano la troncatura in questo campo (verificato). Nessun caso speciale, nessuna stringa costruita a mano. |
| D3 | Posizione: **ultimo segmento** dei filtri, dopo `lingua` | `_rendi_filtri` ha un ordine canonico documentato (date, tipi di studio, lingua); il brevetto si accoda mantenendo la query deterministica e diffabile. |
| D4 | Nuovo campo **`Article.coi_statement: str \| None`**, con **default `None`** | Rende la dichiarazione leggibile a valle. Il default evita di rompere i due unici punti che costruiscono `Article` (`pubmed_models.py` e `tests/test_mcp_server.py`); il campo va in coda perché i precedenti non hanno default. |
| D5 | `coi_statement` è `None` quando l'elemento manca, **mai stringa vuota** | Coerente con la convenzione già adottata per `abstract` e `doi`: distingue «assente» da «vuoto». |
| D6 | Nessuna modifica a `run_search.py` né a `mcp_server.py` | Entrambi serializzano l'articolo con `dataclasses.asdict`: il nuovo campo compare automaticamente nel JSON della CLI e nel payload del tool MCP. |
| D7 | La skill istruisce Claude a **scartare le dichiarazioni negative** leggendo `coi_statement` | È il punto in cui il ~30-60% di falsi positivi viene effettivamente rimosso. Il filtro booleano restringe, il giudizio semantico raffina — lo stesso principio dell'architettura generale del progetto (CLAUDE.md sezione 6). |
| D8 | Il limite del campo `[cois]` va **dichiarato all'utente**, non nascosto | `[cois]` è testo libero, non un flag strutturato: la skill deve spiegare che il filtro si basa sulle dichiarazioni di conflitto d'interesse e che gli articoli senza dichiarazione COI non sono raggiungibili in alcun modo. |

---

## 4. Componenti

### A. `pubmed_models.py` — campo `coi_statement`

```python
@dataclass(frozen=True)
class Article:
    ...
    doi: str | None
    coi_statement: str | None = None   # dichiarazione di conflitto d'interesse
```

In `parse_efetch_xml`, dentro la costruzione di `Article` (dove `citazione` è già in scope):

```python
coi_statement=_text(citazione.find("CoiStatement")) or None,
```

### B. `nl_query_translator.py` — filtro `brevetto`

In `_rendi_filtri`, dopo il blocco `lingua`:

```python
if filtri.get("brevetto"):
    # PubMed non indicizza i brevetti: il Conflict of Interest Statement è l'unico
    # campo dove compaiono. La troncatura sopravvive alle virgolette in [cois]
    # (verificato dal vivo), quindi _frase è utilizzabile senza casi speciali.
    parti.append(_frase("patent*", "cois"))
```

Schema del JSON intermedio esteso:

```json
"filtri": {
  "date": {...},
  "tipi_studio": [...],
  "lingua": null,
  "brevetto": true
}
```

Assente o `false` → nessun segmento, query identica a oggi.

### C. `.claude/skills/pubmed-search/SKILL.md` — istruzioni

Tre aggiornamenti:

1. **Schema JSON** (fase 1): `filtri` guadagna `"brevetto": <true se richiesto, altrimenti omesso>`.
2. **Linea guida di estrazione:** impostare `brevetto: true` quando la richiesta menziona
   brevetti ("che dichiarano un brevetto", "con brevetto registrato", "autori con brevetti").
3. **Fase 5 (filtro di rilevanza):** quando `brevetto` è attivo, leggere `coi_statement` di
   ogni articolo e **scartare le dichiarazioni negative** (es. "hold no ... patents",
   "no ... patent licensing"), tenendo quelle positive (co-inventore, brevetto depositato o
   pendente, royalties da brevetto) e i casi misti. Nella presentazione, citare la parte
   pertinente della dichiarazione come motivazione. Segnalare all'utente che il filtro si
   basa sul Conflict of Interest Statement, quindi gli articoli privi di dichiarazione COI
   non sono raggiungibili.

---

## 5. Testing

- **`tests/test_nl_query_translator.py`** (estensione, offline):
  - `brevetto: true` → la query contiene ` AND "patent*"[cois]`
  - `brevetto` assente e `brevetto: false` → segmento assente
  - combinazione con date + tipi_studio + lingua → ordine canonico rispettato, brevetto in coda
  - combinazione con `esclusioni` → il segmento `NOT` resta dopo i filtri
- **`tests/test_pubmed_models.py`** (estensione, offline): parsing di `<CoiStatement>` da XML
  con dichiarazione presente; `None` quando l'elemento manca.
- **`tests/test_pubmed_live.py`** (estensione, `@pytest.mark.live`): una ricerca reale con il
  filtro attivo restituisce `total_count > 0` e almeno un articolo con `coi_statement`
  valorizzato.
- `pytest` senza argomenti resta interamente offline.

---

## 6. Dipendenze

Nessuna nuova dipendenza. Modifiche a moduli esistenti più le istruzioni della skill.

---

## 7. Criteri di completamento

- [ ] `serialize` con `filtri.brevetto: true` produce ` AND "patent*"[cois]`; senza il campo
      la query è identica a prima (nessuna regressione)
- [ ] `Article.coi_statement` è popolato dal `<CoiStatement>` reale e vale `None` quando
      l'elemento manca
- [ ] Il campo compare nel JSON di `run_search` e nel payload del tool MCP senza modifiche a
      quei moduli (verificato)
- [ ] La skill imposta `brevetto: true` sulle richieste che menzionano brevetti e usa
      `coi_statement` per scartare le dichiarazioni negative
- [ ] La skill dichiara all'utente il limite del campo `[cois]`
- [ ] `pytest` passa interamente offline; `pytest -m live` passa contro NCBI
- [ ] `CLAUDE.md` aggiornato: `[cois]` fra i tag di campo della sezione 4, con la nota che
      PubMed non indicizza i brevetti e che il campo è un proxy testuale
