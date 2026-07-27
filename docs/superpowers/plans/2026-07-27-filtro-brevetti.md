# Filtro brevetti `[cois]` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettere all'utente di chiedere articoli i cui autori dichiarano un brevetto, restringendo la ricerca al Conflict of Interest Statement (`[cois]`) ed esponendo il testo della dichiarazione così che il filtro semantico possa scartare le dichiarazioni negative.

**Architecture:** Due componenti inscindibili. (A) Un nuovo filtro booleano `filtri.brevetto` in `nl_query_translator.py` che serializza in ` AND "patent*"[cois]`, riusando l'helper `_frase` esistente. (B) Un nuovo campo `Article.coi_statement` popolato da `<CoiStatement>` in `parse_efetch_xml` (`pubmed_models.py`), che fluisce automaticamente nel JSON di `run_search` e nel payload del tool MCP perché entrambi usano `dataclasses.asdict`. La skill `/pubmed-search` collega le due: imposta il filtro e poi usa `coi_statement` per scartare i falsi positivi.

**Tech Stack:** Python 3.10+, stdlib (`dataclasses`, `xml.etree.ElementTree`), `pytest` (già presenti). Nessuna nuova dipendenza.

## Global Constraints

- **Python 3.10+** — annotazioni `str | None`.
- **Codice e commenti in italiano**, coerentemente con i moduli esistenti.
- **`nl_query_translator.py` resta una funzione pura**: nessuna chiamata di rete, nessuna logica NL. Testabile offline con JSON fissi.
- **`pubmed_models.py` non ha dipendenze di rete**: parsing puro, testato passando stringhe XML.
- **`coi_statement` vale `None` quando l'elemento manca, mai stringa vuota** — stessa convenzione già adottata per `abstract` e `doi`: distingue «assente» da «vuoto».
- **`coi_statement` ha default `None`** e va in **coda** ai campi di `Article`: i campi precedenti non hanno default, e il default evita di rompere i due unici punti che costruiscono `Article` (`src/pubmed_models.py`, `tests/test_mcp_server.py`).
- **Nessuna modifica a `run_search.py` né a `mcp_server.py`**: entrambi usano `dataclasses.asdict`, quindi il nuovo campo compare automaticamente. Se un task sembra richiederlo, è un errore: fermarsi e segnalarlo.
- **Nessuna regressione**: senza `filtri.brevetto`, la query prodotta deve essere identica a quella di oggi.
- **Le virgolette non disattivano la troncatura in `[cois]`** — verificato dal vivo: `patent*[cois]` e `"patent*"[cois]` restituiscono lo stesso conteggio (145.878). Quindi si riusa `_frase("patent*", "cois")` senza casi speciali, **non** si costruisce la stringa a mano.
- **`pytest` senza argomenti resta interamente offline**; i test live sono marcati `@pytest.mark.live` ed esclusi da `pytest.ini`.

## API dei moduli esistenti (da consumare, non modificare)

- `_frase(termine: str, tag: str) -> str` in `nl_query_translator.py` — restituisce `'"<termine>"[<tag>]'`, ripulendo virgolette interne e spazi.
- `_rendi_filtri(filtri: dict) -> str` in `nl_query_translator.py` — accumula segmenti in una lista `parti` nell'ordine canonico (date, tipi di studio, lingua) e restituisce `""` se vuota, altrimenti `" AND " + " AND ".join(parti)`.
- `serialize(intermedio: dict) -> str` — concatena concetti, poi `_rendi_filtri`, poi le esclusioni `NOT`.
- `parse_efetch_xml(xml: str) -> list[Article]` in `pubmed_models.py` — costruisce gli `Article`; la variabile `citazione` (il nodo `<MedlineCitation>`) è **già in scope** ed è usata per estrarre i `mesh_terms`.
- `_text(node: ET.Element | None) -> str` in `pubmed_models.py` — testo di un nodo, `""` se il nodo è `None`.
- `Article(pmid, title, abstract, authors, journal, pub_date, pub_types, mesh_terms, doi)` — dataclass frozen.

## Fatti verificati dal vivo (non supposizioni)

- `<CoiStatement>` è **figlio di `<MedlineCitation>`**, fratello di `<Article>` — verificato su record reale (PMID 40910216).
- PubMed **non indicizza i brevetti**: `patent[si]` → 0 (`PhraseNotFound`), `patents[sb]` → 0. Il campo `[cois]` è l'unico proxy: `patent*[cois]` → ~145.878.
- Il filtro cattura anche **dichiarazioni negative** ("hold no ... patents", "no ... patent licensing") in quota stimata fra ~30% e ~60%, non determinabile per matching testuale. È la ragione d'essere della componente B.

---

## File Structure

| File | Responsabilità |
|---|---|
| `src/pubmed_models.py` | Aggiunge il campo `coi_statement` ad `Article` e ne estrae il valore da `<CoiStatement>` in `parse_efetch_xml`. |
| `tests/test_pubmed_models.py` | Test del parsing di `<CoiStatement>`: presente, assente. |
| `src/nl_query_translator.py` | Aggiunge il filtro `brevetto` in `_rendi_filtri`. |
| `tests/test_nl_query_translator.py` | Test del filtro: attivo, assente/false, combinato con altri filtri ed esclusioni. |
| `tests/test_pubmed_live.py` | Un test live end-to-end del filtro contro l'API reale. |
| `.claude/skills/pubmed-search/SKILL.md` | Schema JSON esteso, linea guida di estrazione, uso di `coi_statement` nel filtro di rilevanza. |
| `CLAUDE.md` | Sezione 4: `[cois]` fra i tag di campo, con la nota che PubMed non indicizza i brevetti. |

---

## Task 1: `Article.coi_statement` e parsing di `<CoiStatement>`

**Files:**
- Modify: `src/pubmed_models.py`
- Modify: `tests/test_pubmed_models.py`

**Interfaces:**
- Consumes: `_text`, la variabile `citazione` già in scope in `parse_efetch_xml`.
- Produces: `Article.coi_statement: str | None` (default `None`), popolato da `<CoiStatement>`.

- [ ] **Step 1: Scrivere i test che falliscono**

In `tests/test_pubmed_models.py`, la costante `EFETCH_NOMINALE` contiene un `<MedlineCitation>` che si chiude alla riga ~176, subito dopo `</MeshHeadingList>`. Aggiungere un `<CoiStatement>` fra `</MeshHeadingList>` e `</MedlineCitation>`, così:

```
    </MeshHeadingList>
    <CoiStatement>The authors are co-inventors of a patent on the described method.</CoiStatement>
  </MedlineCitation>
```

Poi aggiungere in fondo al file questi due test:

```python
def test_coi_statement_estratto():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.coi_statement == (
        "The authors are co-inventors of a patent on the described method."
    )


def test_coi_statement_assente_vale_none():
    """Un record senza <CoiStatement> non deve produrre stringa vuota:
    il filtro semantico deve distinguere «nessuna dichiarazione» da «vuota»."""
    xml = """<?xml version="1.0" encoding="UTF-8" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">38000002</PMID>
    <Article><ArticleTitle>Senza dichiarazione COI</ArticleTitle></Article>
  </MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>"""
    art = parse_efetch_xml(xml)[0]
    assert art.coi_statement is None
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `PYTHONPATH=src python -m pytest tests/test_pubmed_models.py -k coi -v`
Expected: FAIL con `AttributeError: 'Article' object has no attribute 'coi_statement'`.

- [ ] **Step 3: Aggiungere il campo alla dataclass**

In `src/pubmed_models.py`, nella dataclass `Article`, aggiungere il campo **in coda**, dopo `doi: str | None`:

```python
    doi: str | None
    coi_statement: str | None = None
```

Aggiungere anche, nella docstring della dataclass, una riga che spieghi il campo:

```
    `coi_statement` è la dichiarazione di conflitto d'interesse (<CoiStatement>),
    None quando l'articolo non ne ha una. È l'unico posto in cui PubMed registra i
    brevetti degli autori, e va letto per distinguere le dichiarazioni positive
    («è co-inventore di un brevetto») da quelle negative («non detiene brevetti»).
```

- [ ] **Step 4: Popolare il campo nel parser**

In `src/pubmed_models.py`, in `parse_efetch_xml`, dentro la costruzione di `Article(...)`, aggiungere come ultimo argomento (dopo `doi=_doi(article, pubmed_article),`):

```python
                coi_statement=_text(citazione.find("CoiStatement")) or None,
```

Nota: `citazione` è il nodo `<MedlineCitation>`, già usato poche righe sopra per i `mesh_terms`. `<CoiStatement>` è suo figlio diretto, non figlio di `<Article>`.

- [ ] **Step 5: Eseguire i test e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_pubmed_models.py -k coi -v`
Expected: PASS entrambi.

- [ ] **Step 6: Verificare l'assenza di regressioni sull'intera suite**

Run: `PYTHONPATH=src python -m pytest`
Expected: PASS, nessun fallimento (il default `None` evita di rompere `tests/test_mcp_server.py`, che costruisce `Article` senza questo campo).

- [ ] **Step 7: Commit**

```bash
git add src/pubmed_models.py tests/test_pubmed_models.py
git commit -m "feat: Article.coi_statement, dichiarazione di conflitto d'interesse"
```

---

## Task 2: Filtro `brevetto` in `nl_query_translator`

**Files:**
- Modify: `src/nl_query_translator.py`
- Modify: `tests/test_nl_query_translator.py`

**Interfaces:**
- Consumes: `_frase(termine, tag)` e la lista `parti` dentro `_rendi_filtri`.
- Produces: il filtro `filtri.brevetto: true` → segmento ` AND "patent*"[cois]`, ultimo nell'ordine canonico.

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_nl_query_translator.py`:

```python
def test_filtro_brevetto():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"brevetto": True},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND "patent*"[cois]'


def test_filtro_brevetto_assente_non_aggiunge_nulla():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {},
    }
    assert serialize(intermedio) == '"melanoma"[tiab]'


def test_filtro_brevetto_false_non_aggiunge_nulla():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"brevetto": False},
    }
    assert serialize(intermedio) == '"melanoma"[tiab]'


def test_filtro_brevetto_ultimo_nell_ordine_canonico():
    """Il brevetto si accoda dopo date, tipi di studio e lingua."""
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {
            "date": {"da": "2023", "a": "2026", "tipo": "dp"},
            "tipi_studio": ["review"],
            "lingua": "english",
            "brevetto": True,
        },
    }
    assert serialize(intermedio) == (
        '"melanoma"[tiab] AND ("2023"[dp] : "2026"[dp]) AND '
        '"review"[pt] AND "english"[la] AND "patent*"[cois]'
    )


def test_filtro_brevetto_precede_le_esclusioni():
    """Le esclusioni NOT restano in coda, dopo tutti i filtri."""
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"brevetto": True},
        "esclusioni": [{"termine": "case reports", "campo": "pt"}],
    }
    assert serialize(intermedio) == (
        '"melanoma"[tiab] AND "patent*"[cois] NOT "case reports"[pt]'
    )
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `PYTHONPATH=src python -m pytest tests/test_nl_query_translator.py -k brevetto -v`
Expected: FAIL sui tre test che attivano il filtro (la query prodotta non contiene `"patent*"[cois]`); i due test "assente"/"false" passano già.

- [ ] **Step 3: Implementare il filtro**

In `src/nl_query_translator.py`, dentro `_rendi_filtri`, **dopo** il blocco che gestisce `lingua` e **prima** di `if not parti:`, aggiungere:

```python
    if filtri.get("brevetto"):
        # PubMed non indicizza i brevetti: il Conflict of Interest Statement è
        # l'unico campo dove compaiono (verificato dal vivo: [si] e [sb] danno 0).
        # In [cois] la troncatura sopravvive alle virgolette, quindi _frase è
        # utilizzabile senza casi speciali.
        parti.append(_frase("patent*", "cois"))
```

Aggiornare anche la docstring di `_rendi_filtri`, che documenta l'ordine canonico:

```
    Ordine canonico: date, tipi di studio, lingua, brevetto.
```

- [ ] **Step 4: Eseguire i test e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_nl_query_translator.py -k brevetto -v`
Expected: PASS tutti e cinque.

- [ ] **Step 5: Verificare l'assenza di regressioni**

Run: `PYTHONPATH=src python -m pytest`
Expected: PASS. In particolare i test dei filtri preesistenti devono restare invariati: senza `brevetto` la query è identica a prima.

- [ ] **Step 6: Commit**

```bash
git add src/nl_query_translator.py tests/test_nl_query_translator.py
git commit -m "feat: filtro brevetto, restringe al Conflict of Interest Statement"
```

---

## Task 3: Test live end-to-end

**Files:**
- Modify: `tests/test_pubmed_live.py`

**Interfaces:**
- Consumes: la fixture `client` già presente nel file, `serialize` da `nl_query_translator`, `Article.coi_statement` (Task 1), il filtro `brevetto` (Task 2).
- Produces: nessuna nuova API.

- [ ] **Step 1: Scrivere il test live**

`tests/test_pubmed_live.py` ha già `pytestmark = pytest.mark.live` a livello di modulo (riga 18), quindi il nuovo test è automaticamente escluso da `pytest` senza argomenti — non serve un decoratore aggiuntivo. Aggiungere in fondo al file:

```python
def test_filtro_brevetto_reale_restituisce_dichiarazioni(client):
    """Il filtro [cois] trova articoli reali e il testo della dichiarazione
    arriva fino ad Article.coi_statement, dove il filtro semantico può leggerlo."""
    from nl_query_translator import serialize

    query = serialize(
        {
            "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
            "filtri": {"brevetto": True},
        }
    )
    assert query == '"melanoma"[tiab] AND "patent*"[cois]'

    ricerca = client.esearch(query, retmax=5)
    assert ricerca.total_count > 0
    articoli = client.efetch(ricerca.pmids)
    # Ogni articolo trovato via [cois] ha per definizione una dichiarazione COI,
    # e deve contenere la radice "patent" (in qualsiasi forma flessa).
    assert articoli
    for art in articoli:
        assert art.coi_statement is not None
        assert "patent" in art.coi_statement.lower()
```

- [ ] **Step 2: Verificare che il test resti escluso di default**

Run: `PYTHONPATH=src python -m pytest`
Expected: PASS; il conteggio dei "deselected" aumenta di 1 rispetto a prima (il nuovo test live non gira).

- [ ] **Step 3: Eseguire il test live contro l'API reale**

Run: `PYTHONPATH=src python -m pytest tests/test_pubmed_live.py -m live -k brevetto -v`
Expected: PASS. Serve un `.env` valido con `NCBI_API_KEY`, `NCBI_TOOL_NAME`, `NCBI_EMAIL`.

Se fallisce perché un articolo ha `coi_statement` valorizzato ma senza la stringa "patent" (possibile se NCBI indicizza il termine da un campo diverso da quello restituito), **non allentare l'asserzione in silenzio**: riportare il PMID e il testo ricevuto come concern nel report, così la discrepanza viene esaminata invece di essere nascosta.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pubmed_live.py
git commit -m "test: verifica live del filtro brevetti e di coi_statement"
```

---

## Task 4: Skill `/pubmed-search` e `CLAUDE.md`

**Files:**
- Modify: `.claude/skills/pubmed-search/SKILL.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: il filtro `brevetto` (Task 2) e `Article.coi_statement` (Task 1).
- Produces: nessuna API — solo istruzioni per Claude e documentazione.

- [ ] **Step 1: Estendere lo schema JSON nella skill**

In `.claude/skills/pubmed-search/SKILL.md`, sezione "### 1. Estrai il JSON intermedio dalla richiesta", nel blocco JSON dello schema, il campo `"filtri"` è:

```json
  "filtri": {
    "date": {"da": "<anno>", "a": "<anno>", "tipo": "dp"},
    "tipi_studio": ["<publication type>"],
    "lingua": "<lingua o null>"
  }
```

Sostituirlo con:

```json
  "filtri": {
    "date": {"da": "<anno>", "a": "<anno>", "tipo": "dp"},
    "tipi_studio": ["<publication type>"],
    "lingua": "<lingua o null>",
    "brevetto": "<true solo se la richiesta menziona brevetti, altrimenti ometti>"
  }
```

- [ ] **Step 2: Aggiungere la linea guida di estrazione**

Nella stessa sezione, l'elenco "Linee guida per l'estrazione" termina con la voce che inizia con `- **Lingua**:`. Subito dopo quella voce, aggiungere:

```markdown
- **Brevetto**: imposta `brevetto: true` quando la richiesta chiede articoli i cui autori
  dichiarano un brevetto ("che dichiarano un brevetto", "con brevetto registrato", "autori
  con brevetti"). Aggiunge ` AND "patent*"[cois]` alla query. **Attenzione**: PubMed non
  indicizza i brevetti — il filtro cerca nel Conflict of Interest Statement, che è testo
  libero. Cattura quindi anche le dichiarazioni *negative* ("gli autori non detengono
  brevetti"): vanno scartate leggendo `coi_statement` nella fase 5.
```

- [ ] **Step 3: Istruire il filtro di rilevanza a usare `coi_statement`**

Nella sezione "### 5. Filtra e ordina per rilevanza", dopo il primo paragrafo (quello che inizia con "Leggi gli abstract e valuta la pertinenza"), aggiungere:

```markdown
**Se hai attivato il filtro `brevetto`**, leggi anche `coi_statement` di ogni articolo (la
dichiarazione di conflitto d'interesse) e **scarta le dichiarazioni negative**: frasi come
"the authors hold no patents", "no ... patent licensing", "declare no competing interests"
riferite ai brevetti indicano che l'articolo NON dichiara alcun brevetto, pur avendo matchato
la query booleana. Tieni invece le dichiarazioni positive ("is co-inventor of a patent",
"filed a patent application", "receives royalties from a patent") e i casi misti, dove almeno
un autore dichiara un brevetto. Nella presentazione dei risultati, cita la parte pertinente
della dichiarazione come motivazione.
```

- [ ] **Step 4: Avvisare l'utente del limite del campo**

Nella sezione "### 6. Presenta i risultati", in fondo, aggiungere:

```markdown
Se hai usato il filtro `brevetto`, dillo all'utente in modo esplicito: la ricerca si basa sul
Conflict of Interest Statement, quindi gli articoli che non pubblicano una dichiarazione di
conflitto d'interesse non sono raggiungibili in alcun modo — non è un limite della query ma
di come PubMed indicizza i dati.
```

- [ ] **Step 5: Documentare il tag `[cois]` in `CLAUDE.md`**

In `CLAUDE.md`, sezione 4, l'elenco "**Sintassi di ricerca PubMed rilevante da generare in traduzione:**" ha come prima voce la riga che inizia con `- Tag di campo:` e termina con `` `[la]` (lingua) ``. Aggiungere in fondo a quella riga, prima del ritorno a capo:

```
, `[cois]` (conflict of interest statement)
```

Poi, come nuova voce in fondo allo stesso elenco puntato, aggiungere:

```markdown
- **Brevetti:** PubMed non li indicizza (nessun campo `[si]` o subset dedicato, verificato
  dal vivo). L'unico proxy è il Conflict of Interest Statement: `"patent*"[cois]`. È testo
  libero, quindi cattura anche le dichiarazioni negative; `Article.coi_statement` espone il
  testo così che il filtro semantico possa scartarle.
```

- [ ] **Step 6: Verifica finale della suite**

Run: `PYTHONPATH=src python -m pytest`
Expected: PASS, interamente offline (le modifiche di questo task sono solo documentazione e istruzioni).

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/pubmed-search/SKILL.md CLAUDE.md
git commit -m "docs: filtro brevetti nella skill e nel riferimento PubMed"
```

---

## Note di verifica finale

- Il criterio "il campo compare nel JSON di `run_search` e nel payload MCP senza modifiche a quei moduli" si verifica per costruzione: entrambi usano `dataclasses.asdict`. Se durante l'implementazione sembra necessario modificarli, è il segnale di un errore — fermarsi e segnalarlo.
- Il tasso di falsi positivi (~30-60%) non è verificabile da un test automatico, perché la classificazione richiede giudizio semantico. Il test live verifica ciò che è oggettivo: che il filtro trovi articoli e che il testo della dichiarazione arrivi fino a `Article.coi_statement`, dove Claude può leggerlo.
