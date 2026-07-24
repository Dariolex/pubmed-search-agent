# NL Query Translator + skill /pubmed-search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tradurre query in linguaggio naturale in sintassi PubMed tramite un modulo Python deterministico, ed esporre l'intero flusso di ricerca (traduzione → esecuzione → filtro di rilevanza) come skill Claude Code, senza che l'utente configuri alcuna API key oltre a quella NCBI.

**Architecture:** `src/nl_query_translator.py` contiene una funzione pura `serialize(dict) -> str` (JSON intermedio → stringa `term=` PubMed) più una CLI. `src/run_search.py` è un entry-point CLI sottile attorno al `pubmed_client` esistente. La skill `.claude/skills/pubmed-search/SKILL.md` guida Claude nella fase 1 (estrazione NL→JSON) e nel filtro di rilevanza inline. La parte deterministica è testata offline; le parti di giudizio vivono in Claude.

**Tech Stack:** Python 3.10+, stdlib (`json`, `argparse`, `sys`, `dataclasses`), `pytest`, `responses` (già presenti). Riusa i moduli `pubmed_client`/`pubmed_models`/`pubmed_errors` già implementati.

## Global Constraints

- **Python 3.10+** — annotazioni `str | None`.
- **Codice e commenti in italiano**, coerentemente con i moduli esistenti.
- **Import fra moduli senza prefisso di pacchetto** (`from pubmed_client import ...`), reso possibile da `pythonpath = src` in `pytest.ini` (già configurato).
- **`nl_query_translator.py` non effettua chiamate HTTP a NCBI** (vincolo CLAUDE.md): l'unica dipendenza da `pubmed_client` è la funzione pura `pubmed_web_url`.
- **Booleani PubMed sempre maiuscoli** (`AND`/`OR`/`NOT`).
- **Ogni termine tra virgolette doppie**; una virgoletta doppia interna al termine va rimossa (PubMed non supporta l'escaping).
- **`serialize` è deterministica**: stesso input → stessa identica stringa (ordine canonico: concetti nell'ordine del JSON, poi date, poi tipi di studio, poi lingua, poi esclusioni).
- **`pytest` senza argomenti resta interamente offline** — nessuna nuova chiamata di rete nei test automatici.
- **Nessuna nuova dipendenza** in `requirements.txt`.

## API dei moduli esistenti (da consumare, non modificare)

- `pubmed_web_url(term: str) -> str` — da `pubmed_client`.
- `PubMedClient(config, *, session=None, rate_limiter=None, max_attempts=3, sleep=time.sleep, timeout=(5.0, 30.0))`.
- `PubMedClient.esearch(term, *, retmax=100, retstart=0, sort=None, mindate=None, maxdate=None, datetype="pdat") -> SearchResult`.
- `PubMedClient.efetch(pmids, *, batch_size=200) -> list[Article]`.
- `PubMedConfig(tool, email, api_key)` e `PubMedConfig.from_env()`.
- `RateLimiter(rate=10.0, capacity=10, clock=time.monotonic, sleep=time.sleep)`.
- `SearchResult(pmids, total_count, translated_query, webenv, query_key, warnings)`.
- `Article(pmid, title, abstract, authors, journal, pub_date, pub_types, mesh_terms, doi)` — dataclass congelata.
- `PubMedError` (base), `PubMedAPIError`, ecc. — da `pubmed_errors`.

---

## File Structure

| File | Responsabilità |
|---|---|
| `src/nl_query_translator.py` | `serialize` (JSON → query PubMed) + CLI. Dipende solo da stdlib e `pubmed_web_url`. |
| `src/run_search.py` | Entry-point CLI: query → esearch/efetch → JSON articoli. Dipende da `pubmed_client`/`pubmed_errors`. |
| `.claude/skills/pubmed-search/SKILL.md` | Skill Claude Code: guida fase 1, fase 2, esecuzione, filtro di rilevanza. |
| `tests/test_nl_query_translator.py` | Test di `serialize` (JSON fissi) e della CLI. Sostituisce il placeholder esistente. |
| `tests/test_run_search.py` | Test di `run_search` con `responses` + fixture NCBI esistenti. |
| `examples/sample_queries.md` | Query di riferimento: NL, JSON, query attesa, giudizio. |
| `CLAUDE.md` | Allineamento sezioni 3 e 8. |

---

## Task 1: `serialize` — concetti e combinazione

**Files:**
- Create: `src/nl_query_translator.py`
- Test: `tests/test_nl_query_translator.py` (sostituisce il placeholder con solo docstring)

**Interfaces:**
- Consumes: nulla (primo task; `pubmed_web_url` serve solo nel Task 3)
- Produces:
  - `serialize(intermedio: dict) -> str` — per ora gestisce concetti + operatore; filtri/esclusioni arrivano nel Task 2
  - Helper interni `_pulisci(str) -> str`, `_frase(termine, tag) -> str`, `_rendi_concetto(dict) -> str`

- [ ] **Step 1: Scrivere i test che falliscono**

Sostituire il contenuto di `tests/test_nl_query_translator.py`:

```python
"""Test di nl_query_translator: serializzazione pura JSON intermedio -> query PubMed."""

import pytest

from nl_query_translator import serialize


def test_concetto_singolo_solo_tiab():
    intermedio = {"concetti": [{"termine": "metastatic", "sinonimi": [], "mesh": None}]}
    assert serialize(intermedio) == '"metastatic"[tiab]'


def test_concetto_singolo_con_mesh():
    intermedio = {"concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": "melanoma"}]}
    assert serialize(intermedio) == '("melanoma"[MeSH Terms] OR "melanoma"[tiab])'


def test_concetto_con_sinonimi_senza_mesh():
    intermedio = {
        "concetti": [
            {"termine": "immunotherapy", "sinonimi": ["immune checkpoint inhibitor"], "mesh": None}
        ]
    }
    assert serialize(intermedio) == (
        '("immunotherapy"[tiab] OR "immune checkpoint inhibitor"[tiab])'
    )


def test_concetto_con_mesh_e_sinonimi():
    intermedio = {
        "concetti": [
            {"termine": "melanoma", "sinonimi": ["malignant melanoma"], "mesh": "melanoma"}
        ]
    }
    assert serialize(intermedio) == (
        '("melanoma"[MeSH Terms] OR "melanoma"[tiab] OR "malignant melanoma"[tiab])'
    )


def test_due_concetti_in_and():
    intermedio = {
        "concetti": [
            {"termine": "melanoma", "sinonimi": [], "mesh": "melanoma"},
            {"termine": "metastatic", "sinonimi": [], "mesh": None},
        ],
        "operatore_tra_concetti": "AND",
    }
    assert serialize(intermedio) == (
        '("melanoma"[MeSH Terms] OR "melanoma"[tiab]) AND "metastatic"[tiab]'
    )


def test_due_concetti_in_or_vengono_racchiusi():
    intermedio = {
        "concetti": [
            {"termine": "melanoma", "sinonimi": [], "mesh": None},
            {"termine": "carcinoma", "sinonimi": [], "mesh": None},
        ],
        "operatore_tra_concetti": "OR",
    }
    assert serialize(intermedio) == '("melanoma"[tiab] OR "carcinoma"[tiab])'


def test_operatore_predefinito_e_and():
    intermedio = {
        "concetti": [
            {"termine": "a", "sinonimi": [], "mesh": None},
            {"termine": "b", "sinonimi": [], "mesh": None},
        ]
    }
    assert serialize(intermedio) == '"a"[tiab] AND "b"[tiab]'


def test_virgolette_interne_rimosse():
    intermedio = {"concetti": [{"termine": 'aberrant "gene"', "sinonimi": [], "mesh": None}]}
    assert serialize(intermedio) == '"aberrant gene"[tiab]'


def test_nessun_concetto_solleva_value_error():
    with pytest.raises(ValueError, match="concetto"):
        serialize({"concetti": []})


def test_concetto_senza_termine_solleva_value_error():
    with pytest.raises(ValueError, match="termine"):
        serialize({"concetti": [{"sinonimi": [], "mesh": None}]})


def test_operatore_ignoto_solleva_value_error():
    intermedio = {
        "concetti": [{"termine": "a", "sinonimi": [], "mesh": None}],
        "operatore_tra_concetti": "XOR",
    }
    with pytest.raises(ValueError, match="AND o OR"):
        serialize(intermedio)
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_nl_query_translator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nl_query_translator'`

- [ ] **Step 3: Implementare `src/nl_query_translator.py`**

Sostituire integralmente il contenuto attuale (solo docstring segnaposto):

```python
"""
nl_query_translator.py

Serializzazione deterministica di un JSON intermedio (prodotto da Claude nella fase 1)
nella sintassi di ricerca avanzata di PubMed.

Questo modulo NON fa chiamate a Claude né a NCBI: è una funzione pura, testabile
offline con JSON fissi. La comprensione del linguaggio naturale vive in Claude,
guidato dalla skill /pubmed-search.
"""

from __future__ import annotations

_OPERATORI_VALIDI = {"AND", "OR"}


def _pulisci(termine: str) -> str:
    """Rimuove le virgolette doppie interne (PubMed non supporta l'escaping) e
    gli spazi ai bordi."""
    return termine.replace('"', "").strip()


def _frase(termine: str, tag: str) -> str:
    """Un termine come frase esatta con tag di campo, es. '\"melanoma\"[tiab]'."""
    return f'"{_pulisci(termine)}"[{tag}]'


def _rendi_concetto(concetto: dict) -> str:
    """Un concetto -> gruppo con MeSH (opzionale), tiab e sinonimi in OR.

    Un solo elemento (nessun mesh, nessun sinonimo) non viene racchiuso tra
    parentesi, per non appesantire la query.
    """
    termine = concetto.get("termine")
    if not termine or not _pulisci(termine):
        raise ValueError("Ogni concetto deve avere un 'termine' non vuoto")
    alternative = []
    mesh = concetto.get("mesh")
    if mesh and _pulisci(mesh):
        alternative.append(_frase(mesh, "MeSH Terms"))
    alternative.append(_frase(termine, "tiab"))
    for sinonimo in concetto.get("sinonimi") or []:
        if _pulisci(sinonimo):
            alternative.append(_frase(sinonimo, "tiab"))
    if len(alternative) == 1:
        return alternative[0]
    return "(" + " OR ".join(alternative) + ")"


def serialize(intermedio: dict) -> str:
    """JSON intermedio -> stringa `term=` PubMed.

    Solleva ValueError se il JSON è semanticamente invalido (nessun concetto,
    concetto senza termine, operatore diverso da AND/OR).
    """
    concetti = intermedio.get("concetti") or []
    if not concetti:
        raise ValueError("Il JSON intermedio deve contenere almeno un concetto")
    operatore = intermedio.get("operatore_tra_concetti", "AND")
    if operatore not in _OPERATORI_VALIDI:
        raise ValueError(
            f"operatore_tra_concetti deve essere AND o OR, non {operatore!r}"
        )
    gruppi = [_rendi_concetto(c) for c in concetti]
    query = f" {operatore} ".join(gruppi)
    # Con operatore OR e più concetti, racchiudo il gruppo così che i filtri/le
    # esclusioni appesi in AND/NOT (Task 2) non alterino la precedenza booleana.
    if len(gruppi) > 1 and operatore == "OR":
        query = "(" + query + ")"
    return query
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_nl_query_translator.py -v`
Expected: PASS — 11 test superati

- [ ] **Step 5: Commit**

```bash
git add src/nl_query_translator.py tests/test_nl_query_translator.py
git commit -m "feat: serialize NL->PubMed, concetti e combinazione booleana"
```

---

## Task 2: `serialize` — filtri, esclusioni, query di riferimento

**Files:**
- Modify: `src/nl_query_translator.py`
- Modify: `tests/test_nl_query_translator.py`

**Interfaces:**
- Consumes: `serialize`, `_frase`, `_pulisci` (Task 1)
- Produces: `serialize` esteso con `filtri` (date, tipi di studio, lingua) ed `esclusioni`; helper `_rendi_filtri(dict) -> str`; costante `_TIPI_DATA_VALIDI`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_nl_query_translator.py`:

```python
def test_filtro_date_intervallo_completo():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"date": {"da": "2023", "a": "2026", "tipo": "dp"}},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND ("2023"[dp] : "2026"[dp])'


def test_filtro_date_solo_da():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"date": {"da": "2023", "tipo": "dp"}},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND ("2023"[dp] : "3000"[dp])'


def test_filtro_date_solo_a():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"date": {"a": "2026", "tipo": "edat"}},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND ("1000"[edat] : "2026"[edat])'


def test_tipo_studio_singolo():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"tipi_studio": ["randomized controlled trial"]},
    }
    assert serialize(intermedio) == (
        '"melanoma"[tiab] AND "randomized controlled trial"[pt]'
    )


def test_tipi_studio_multipli_in_or():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"tipi_studio": ["randomized controlled trial", "meta-analysis"]},
    }
    assert serialize(intermedio) == (
        '"melanoma"[tiab] AND '
        '("randomized controlled trial"[pt] OR "meta-analysis"[pt])'
    )


def test_filtro_lingua():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"lingua": "english"},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND "english"[la]'


def test_esclusioni_in_not():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "esclusioni": [{"termine": "case reports", "campo": "pt"}],
    }
    assert serialize(intermedio) == '"melanoma"[tiab] NOT "case reports"[pt]'


def test_esclusione_campo_predefinito_tiab():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "esclusioni": [{"termine": "pediatric"}],
    }
    assert serialize(intermedio) == '"melanoma"[tiab] NOT "pediatric"[tiab]'


def test_ordine_canonico_stabile():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {
            "date": {"da": "2023", "a": "2026", "tipo": "dp"},
            "tipi_studio": ["review"],
            "lingua": "english",
        },
        "esclusioni": [{"termine": "case reports", "campo": "pt"}],
    }
    atteso = (
        '"melanoma"[tiab] AND ("2023"[dp] : "2026"[dp]) AND "review"[pt] '
        'AND "english"[la] NOT "case reports"[pt]'
    )
    assert serialize(intermedio) == atteso
    assert serialize(intermedio) == atteso  # stesso input -> stessa stringa


def test_tipo_data_ignoto_solleva_value_error():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"date": {"da": "2023", "a": "2026", "tipo": "xyz"}},
    }
    with pytest.raises(ValueError, match="tipo data"):
        serialize(intermedio)


def test_esclusione_senza_termine_solleva_value_error():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "esclusioni": [{"campo": "pt"}],
    }
    with pytest.raises(ValueError, match="esclusione"):
        serialize(intermedio)


def test_query_di_riferimento_claude_md():
    """La query di esempio del CLAUDE.md sezione 1, forma canonica."""
    intermedio = {
        "intento_originale": "immunoterapia nel melanoma metastatico, RCT, no case report",
        "concetti": [
            {"termine": "melanoma", "sinonimi": [], "mesh": "melanoma"},
            {"termine": "immunotherapy", "sinonimi": [], "mesh": "immunotherapy"},
            {"termine": "metastatic", "sinonimi": [], "mesh": None},
        ],
        "operatore_tra_concetti": "AND",
        "esclusioni": [{"termine": "case reports", "campo": "pt"}],
        "filtri": {
            "date": {"da": "2023", "a": "2026", "tipo": "dp"},
            "tipi_studio": ["randomized controlled trial"],
        },
    }
    atteso = (
        '("melanoma"[MeSH Terms] OR "melanoma"[tiab]) AND '
        '("immunotherapy"[MeSH Terms] OR "immunotherapy"[tiab]) AND '
        '"metastatic"[tiab] AND ("2023"[dp] : "2026"[dp]) AND '
        '"randomized controlled trial"[pt] NOT "case reports"[pt]'
    )
    assert serialize(intermedio) == atteso
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_nl_query_translator.py -k "filtro or tipo or esclusion or ordine or riferimento" -v`
Expected: FAIL — le date/i filtri non sono ancora serializzati (es. `AssertionError`, la query si ferma ai concetti)

- [ ] **Step 3: Estendere `src/nl_query_translator.py`**

Aggiungere la costante accanto a `_OPERATORI_VALIDI`:

```python
_TIPI_DATA_VALIDI = {"dp", "edat", "pdat"}
```

Aggiungere `_rendi_filtri` dopo `_rendi_concetto`:

```python
def _rendi_filtri(filtri: dict) -> str:
    """Filtri opzionali -> segmenti ` AND ...`. Stringa vuota se nessun filtro.

    Ordine canonico: date, tipi di studio, lingua.
    """
    parti = []

    date = filtri.get("date")
    if date:
        tipo = date.get("tipo", "dp")
        if tipo not in _TIPI_DATA_VALIDI:
            raise ValueError(
                f"tipo data non valido: {tipo!r} (ammessi: dp, edat, pdat)"
            )
        da = date.get("da")
        a = date.get("a")
        if da or a:
            # PubMed richiede entrambi gli estremi in un intervallo: si usano
            # anni sentinella per gli intervalli aperti ("dal 2023 in poi").
            estremo_da = da if da else "1000"
            estremo_a = a if a else "3000"
            parti.append(f'("{estremo_da}"[{tipo}] : "{estremo_a}"[{tipo}])')

    tipi_studio = [t for t in (filtri.get("tipi_studio") or []) if _pulisci(t)]
    if len(tipi_studio) == 1:
        parti.append(_frase(tipi_studio[0], "pt"))
    elif len(tipi_studio) > 1:
        parti.append("(" + " OR ".join(_frase(t, "pt") for t in tipi_studio) + ")")

    lingua = filtri.get("lingua")
    if lingua and _pulisci(lingua):
        parti.append(_frase(lingua, "la"))

    if not parti:
        return ""
    return " AND " + " AND ".join(parti)
```

Modificare `serialize`: sostituire il `return query` finale con la parte filtri + esclusioni:

```python
    query += _rendi_filtri(intermedio.get("filtri") or {})

    for esclusione in intermedio.get("esclusioni") or []:
        termine = esclusione.get("termine")
        if not termine or not _pulisci(termine):
            raise ValueError("Ogni esclusione deve avere un 'termine' non vuoto")
        campo = esclusione.get("campo") or "tiab"
        query += f" NOT {_frase(termine, campo)}"

    return query
```

- [ ] **Step 4: Eseguire l'intera suite del modulo e verificare che passi**

Run: `pytest tests/test_nl_query_translator.py -v`
Expected: PASS — 23 test superati (11 del Task 1 + 12 nuovi)

- [ ] **Step 5: Commit**

```bash
git add src/nl_query_translator.py tests/test_nl_query_translator.py
git commit -m "feat: serialize filtri, esclusioni e query di riferimento"
```

---

## Task 3: CLI di `nl_query_translator`

**Files:**
- Modify: `src/nl_query_translator.py`
- Modify: `tests/test_nl_query_translator.py`

**Interfaces:**
- Consumes: `serialize` (Task 1-2), `pubmed_web_url` da `pubmed_client`
- Produces: `main(argv=None, stdin=None) -> int` — legge JSON da stdin (o `--file`), stampa la query su stdout; con `--link` aggiunge l'URL; errori su stderr, exit code 1

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_nl_query_translator.py` (e `import io`, `import json` in cima al file):

```python
from nl_query_translator import main

_JSON_MELANOMA = '{"concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": null}]}'


def test_cli_legge_da_stdin_e_stampa_query(capsys):
    codice = main(argv=[], stdin=io.StringIO(_JSON_MELANOMA))
    out = capsys.readouterr()
    assert codice == 0
    assert out.out.strip() == '"melanoma"[tiab]'
    assert out.err == ""


def test_cli_opzione_link_aggiunge_url(capsys):
    codice = main(argv=["--link"], stdin=io.StringIO(_JSON_MELANOMA))
    out = capsys.readouterr()
    righe = out.out.strip().splitlines()
    assert codice == 0
    assert righe[0] == '"melanoma"[tiab]'
    assert righe[1].startswith("https://pubmed.ncbi.nlm.nih.gov/?term=")


def test_cli_json_malformato_esce_con_errore(capsys):
    codice = main(argv=[], stdin=io.StringIO("{non-json"))
    out = capsys.readouterr()
    assert codice == 1
    assert out.err.strip() != ""
    assert out.out == ""


def test_cli_json_semanticamente_invalido_esce_con_errore(capsys):
    codice = main(argv=[], stdin=io.StringIO('{"concetti": []}'))
    out = capsys.readouterr()
    assert codice == 1
    assert "concetto" in out.err


def test_cli_legge_da_file(tmp_path, capsys):
    percorso = tmp_path / "query.json"
    percorso.write_text(_JSON_MELANOMA, encoding="utf-8")
    codice = main(argv=["--file", str(percorso)])
    out = capsys.readouterr()
    assert codice == 0
    assert out.out.strip() == '"melanoma"[tiab]'
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_nl_query_translator.py -k cli -v`
Expected: FAIL — `ImportError: cannot import name 'main' from 'nl_query_translator'`

- [ ] **Step 3: Implementare la CLI in `src/nl_query_translator.py`**

Aggiungere gli import in cima al file (sotto il docstring):

```python
import argparse
import json
import sys

from pubmed_client import pubmed_web_url
```

Aggiungere in fondo al file:

```python
def main(argv=None, stdin=None) -> int:
    """CLI: legge il JSON intermedio da stdin (o --file) e stampa la query PubMed.

    Con --link stampa anche l'URL della stessa ricerca sull'interfaccia web.
    Gli errori (JSON malformato o semanticamente invalido) vanno su stderr con
    codice di uscita 1, così il chiamante sa di dover correggere il JSON.
    """
    parser = argparse.ArgumentParser(
        description="Traduce un JSON intermedio nella sintassi di ricerca PubMed."
    )
    parser.add_argument("--file", help="Legge il JSON da questo file invece che da stdin")
    parser.add_argument(
        "--link", action="store_true", help="Stampa anche l'URL pubmed.ncbi.nlm.nih.gov"
    )
    args = parser.parse_args(argv)

    sorgente = stdin if stdin is not None else sys.stdin
    try:
        testo = open(args.file, encoding="utf-8").read() if args.file else sorgente.read()
        intermedio = json.loads(testo)
        query = serialize(intermedio)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    print(query)
    if args.link:
        print(pubmed_web_url(query))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Eseguire l'intera suite del modulo**

Run: `pytest tests/test_nl_query_translator.py -v`
Expected: PASS — 28 test superati (23 + 5 CLI)

- [ ] **Step 5: Verifica manuale della CLI**

Run: `echo '{"concetti":[{"termine":"melanoma","sinonimi":[],"mesh":"melanoma"}]}' | python -m nl_query_translator --link`
Expected: due righe — la query `("melanoma"[MeSH Terms] OR "melanoma"[tiab])` e l'URL `https://pubmed.ncbi.nlm.nih.gov/?term=...`

- [ ] **Step 6: Commit**

```bash
git add src/nl_query_translator.py tests/test_nl_query_translator.py
git commit -m "feat: CLI nl_query_translator (stdin/--file/--link)"
```

---

## Task 4: `run_search.py` — entry-point di ricerca

**Files:**
- Create: `src/run_search.py`
- Test: `tests/test_run_search.py`

**Interfaces:**
- Consumes: `PubMedClient`, `PubMedConfig`, `RateLimiter` da `pubmed_client`; `PubMedError` da `pubmed_errors`; le fixture in `tests/fixtures/`
- Produces:
  - `esegui(term: str, retmax: int, client: PubMedClient) -> dict` — esegue esearch+efetch, restituisce `{total_count, translated_query, warnings, articles: list[dict]}`
  - `main(argv=None) -> int` — CLI `--term`/`--retmax`

- [ ] **Step 1: Scrivere i test che falliscono**

File `tests/test_run_search.py`:

```python
"""Test di run_search: esecuzione end-to-end con HTTP mockato (nessuna rete reale)."""

import json
from pathlib import Path

import pytest
import responses

from pubmed_client import PubMedClient, PubMedConfig, RateLimiter
from run_search import esegui, main

FIXTURES = Path(__file__).parent / "fixtures"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class OrologioFinto:
    def __init__(self):
        self.adesso = 0.0

    def time(self):
        return self.adesso

    def sleep(self, secondi):
        self.adesso += secondi


@pytest.fixture
def client():
    orologio = OrologioFinto()
    return PubMedClient(
        PubMedConfig(tool="test", email="test@example.org", api_key="chiave-finta"),
        rate_limiter=RateLimiter(clock=orologio.time, sleep=orologio.sleep),
        sleep=orologio.sleep,
    )


@responses.activate
def test_esegui_restituisce_dict_con_articoli(client):
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=(FIXTURES / "esearch_basic.xml").read_text(encoding="utf-8"),
        status=200,
    )
    responses.add(
        responses.POST,
        EFETCH_URL,
        body=(FIXTURES / "efetch_batch.xml").read_text(encoding="utf-8"),
        status=200,
    )
    risultato = esegui("melanoma", retmax=5, client=client)
    assert risultato["total_count"] > 0
    assert isinstance(risultato["articles"], list)
    assert risultato["articles"]
    primo = risultato["articles"][0]
    assert "pmid" in primo and "title" in primo and "abstract" in primo


@responses.activate
def test_esegui_propaga_errore_del_client(client):
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=(FIXTURES / "esearch_error.xml").read_text(encoding="utf-8"),
        status=200,
    )
    from pubmed_errors import PubMedAPIError

    with pytest.raises(PubMedAPIError):
        esegui("melanoma AND (", retmax=5, client=client)


@responses.activate
def test_main_stampa_json_su_stdout(client, monkeypatch, capsys):
    monkeypatch.setattr("run_search.PubMedConfig.from_env", lambda: client._config)
    monkeypatch.setattr("run_search.PubMedClient", lambda config: client)
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=(FIXTURES / "esearch_basic.xml").read_text(encoding="utf-8"),
        status=200,
    )
    responses.add(
        responses.POST,
        EFETCH_URL,
        body=(FIXTURES / "efetch_batch.xml").read_text(encoding="utf-8"),
        status=200,
    )
    codice = main(argv=["--term", "melanoma", "--retmax", "5"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert "articles" in dati and "total_count" in dati
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_run_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'run_search'`

- [ ] **Step 3: Implementare `src/run_search.py`**

```python
"""
run_search.py

Entry-point CLI: prende una query in sintassi PubMed, esegue ESearch + EFetch
tramite pubmed_client e stampa gli articoli come JSON su stdout.

Nessuna logica di linguaggio naturale (quella vive nella skill /pubmed-search e in
nl_query_translator), nessun parsing XML (delegato a pubmed_client/pubmed_models).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from pubmed_client import PubMedClient, PubMedConfig
from pubmed_errors import PubMedError


def esegui(term: str, retmax: int, client: PubMedClient) -> dict:
    """Esegue la ricerca e restituisce un dizionario serializzabile in JSON.

    Include `translated_query` e `warnings` di NCBI, utili a Claude per capire
    come PubMed ha reinterpretato la query e quali termini non hanno matchato.
    """
    ricerca = client.esearch(term, retmax=retmax)
    articoli = client.efetch(ricerca.pmids)
    return {
        "total_count": ricerca.total_count,
        "translated_query": ricerca.translated_query,
        "warnings": ricerca.warnings,
        "articles": [dataclasses.asdict(a) for a in articoli],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Esegue una ricerca PubMed e stampa gli articoli come JSON."
    )
    parser.add_argument("--term", required=True, help="Query in sintassi PubMed")
    parser.add_argument(
        "--retmax", type=int, default=50, help="Numero massimo di articoli da recuperare"
    )
    args = parser.parse_args(argv)

    try:
        client = PubMedClient(PubMedConfig.from_env())
        risultato = esegui(args.term, args.retmax, client)
    except PubMedError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1

    json.dump(risultato, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_run_search.py -v`
Expected: PASS — 3 test superati

- [ ] **Step 5: Eseguire l'intera suite offline**

Run: `pytest`
Expected: PASS — nessuna regressione, nessuna chiamata di rete (i 5 test live restano deselezionati)

- [ ] **Step 6: Commit**

```bash
git add src/run_search.py tests/test_run_search.py
git commit -m "feat: run_search, entry-point CLI per l'esecuzione della ricerca"
```

---

## Task 5: skill `/pubmed-search`

**Files:**
- Create: `.claude/skills/pubmed-search/SKILL.md`

**Interfaces:**
- Consumes: `python -m nl_query_translator` (Task 3), `python -m run_search` (Task 4)
- Produces: nessuna API di codice. È un documento di istruzioni per Claude.

Questo task non ha test automatici (il comportamento vive nel giudizio di Claude). La verifica è la prova d'uso reale al Task 6.

- [ ] **Step 1: Creare `.claude/skills/pubmed-search/SKILL.md`**

```markdown
---
name: pubmed-search
description: Cerca letteratura scientifica su PubMed a partire da una richiesta in linguaggio naturale. Usare quando l'utente digita /pubmed-search o chiede di trovare studi, articoli, trial o letteratura medica/scientifica su PubMed. Traduce la richiesta in una query PubMed, la esegue via NCBI E-utilities e ordina i risultati per rilevanza semantica.
---

# PubMed NL Search

Trasforma una richiesta in linguaggio naturale in una ricerca PubMed reale, poi
filtra i risultati per pertinenza rispetto all'intento dell'utente.

Eseguire i comandi Python dalla radice del progetto (dove c'è `pytest.ini`), con
`src` sul PYTHONPATH — es. `PYTHONPATH=src python -m nl_query_translator ...`.
Serve un file `.env` valido con `NCBI_API_KEY`, `NCBI_TOOL_NAME`, `NCBI_EMAIL`.

## Flusso

### 1. Estrai il JSON intermedio dalla richiesta

Analizza la richiesta NL e costruisci questo JSON (schema esteso con provenienza):

```json
{
  "intento_originale": "<la richiesta dell'utente, verbatim>",
  "concetti": [
    {"termine": "<concetto>", "sinonimi": ["<variante>"], "mesh": "<termine MeSH o null>", "provenienza": "<perché estratto>"}
  ],
  "operatore_tra_concetti": "AND",
  "esclusioni": [{"termine": "<da escludere>", "campo": "pt", "provenienza": "<perché>"}],
  "filtri": {
    "date": {"da": "<anno>", "a": "<anno>", "tipo": "dp"},
    "tipi_studio": ["<publication type>"],
    "lingua": "<lingua o null>"
  }
}
```

Linee guida per l'estrazione:
- **Concetti**: i nuclei clinici/scientifici della richiesta. Aggiungi `sinonimi`
  utili (varianti terminologiche, non traduzioni). Popola `mesh` solo quando il
  termine MeSH controllato è ovvio (es. `melanoma`, `immunotherapy`); altrimenti `null`.
- **operatore_tra_concetti**: `AND` di norma (l'utente vuole tutti i concetti insieme).
  Usa `OR` solo se la richiesta è esplicitamente alternativa ("melanoma o carcinoma").
- **Esclusioni**: frasi come "escludendo X", "senza X", "non case report" → `NOT`.
  Per i tipi di pubblicazione usa `campo: "pt"`; per termini liberi ometti `campo`.
- **Filtri date**: "ultimi 3 anni" → calcola dalla data odierna (`da` = anno corrente − 3,
  `a` = anno corrente). `tipo`: `dp` (data di pubblicazione) di default.
- **Tipi di studio**: "trial randomizzati" → `randomized controlled trial`; "meta-analisi"
  → `meta-analysis`; "review" → `review`. Più tipi vengono uniti in OR automaticamente.
- **Lingua**: solo se la richiesta la specifica ("in inglese" → `english`).

`provenienza` non entra nella query: serve a te e all'utente per il debug.

### 2. Genera la query PubMed (fase deterministica)

Scrivi il JSON in un file temporaneo e invoca il traduttore:

```bash
PYTHONPATH=src python -m nl_query_translator --file /percorso/query.json --link
```

Stampa due righe: la query PubMed e il link web. **Non costruire la query a mano** —
usa sempre questo comando, così la sintassi è corretta e riproducibile. Se il comando
esce con errore, correggi il JSON e riprova.

### 3. Mostra la traduzione all'utente

Prima dei risultati, mostra la query PubMed generata e il link diretto a
pubmed.ncbi.nlm.nih.gov, così l'utente può verificare l'interpretazione ed
eventualmente correggerla.

### 4. Esegui la ricerca

```bash
PYTHONPATH=src python -m run_search --term "<query generata>" --retmax 30
```

Restituisce JSON con `total_count`, `translated_query` (come NCBI ha reinterpretato
la query — utile se i risultati sorprendono), `warnings` e `articles` (con `title`,
`abstract`, `authors`, `journal`, `pub_date`, `pub_types`, `pmid`).

### 5. Filtra e ordina per rilevanza

Leggi gli abstract e valuta la pertinenza di ciascun articolo rispetto a
`intento_originale`. Scarta o declassa i non pertinenti (un articolo può matchare la
query booleana ma non l'intento reale). Ordina dal più al meno pertinente.

Segnala anche gli articoli che sembrano pertinenti ma che la query booleana potrebbe
aver escluso (falsi negativi da query troppo restrittiva), suggerendo un allargamento.

### 6. Presenta i risultati

Per ogni articolo pertinente: titolo, autori (primi 3), rivista, anno, PMID, e una
breve motivazione della rilevanza. In testa: la query PubMed generata e il link web.
Se `total_count` è 0, segnala che la query è troppo restrittiva e proponi come allargarla.
```

- [ ] **Step 2: Verificare che la skill sia riconosciuta**

Run: `ls .claude/skills/pubmed-search/SKILL.md`
Expected: il file esiste. (La skill diventa invocabile come `/pubmed-search` in una nuova sessione di Claude Code.)

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pubmed-search/SKILL.md
git commit -m "feat: skill /pubmed-search per la ricerca NL end-to-end"
```

---

## Task 6: `examples/sample_queries.md`, allineamento `CLAUDE.md` e prova d'uso

**Files:**
- Modify: `examples/sample_queries.md`
- Modify: `CLAUDE.md` (sezioni 3 e 8)

**Interfaces:**
- Consumes: tutto il lavoro dei Task 1-5
- Produces: nessuna API. Documentazione e regressione qualitativa.

- [ ] **Step 1: Popolare `examples/sample_queries.md`**

Sostituire il segnaposto "(da popolare durante lo sviluppo)" in fondo al file con:

```markdown
### Query NL

"Trovami gli studi degli ultimi 3 anni su immunoterapia nel melanoma metastatico,
solo trial clinici randomizzati, escludendo case report"

### JSON intermedio

```json
{
  "intento_originale": "studi ultimi 3 anni su immunoterapia nel melanoma metastatico, solo RCT, no case report",
  "concetti": [
    {"termine": "melanoma", "sinonimi": [], "mesh": "melanoma", "provenienza": "malattia centrale"},
    {"termine": "immunotherapy", "sinonimi": [], "mesh": "immunotherapy", "provenienza": "trattamento richiesto"},
    {"termine": "metastatic", "sinonimi": [], "mesh": null, "provenienza": "stadio specificato"}
  ],
  "operatore_tra_concetti": "AND",
  "esclusioni": [{"termine": "case reports", "campo": "pt", "provenienza": "utente: 'escludendo case report'"}],
  "filtri": {
    "date": {"da": "2023", "a": "2026", "tipo": "dp"},
    "tipi_studio": ["randomized controlled trial"]
  }
}
```

### Query PubMed attesa

```
("melanoma"[MeSH Terms] OR "melanoma"[tiab]) AND ("immunotherapy"[MeSH Terms] OR "immunotherapy"[tiab]) AND "metastatic"[tiab] AND ("2023"[dp] : "2026"[dp]) AND "randomized controlled trial"[pt] NOT "case reports"[pt]
```

### Note / giudizio manuale sui primi risultati

Verificata contro l'API reale: la query restituisce trial di immunoterapia nel melanoma
metastatico degli ultimi anni, coerenti con l'intento. La `translated_query` di NCBI
conferma l'espansione automatica dei termini MeSH.
```

- [ ] **Step 2: Aggiornare l'albero dei file in `CLAUDE.md` sezione 3**

Nel blocco `src/`, aggiungere dopo `pubmed_client.py`:

```
│   ├── run_search.py          # entry-point CLI: query -> esearch/efetch -> JSON
```

Nel blocco `tests/`, aggiungere `test_run_search.py`. Aggiungere una voce per la skill,
dopo l'albero:

```
La skill `/pubmed-search` (`.claude/skills/pubmed-search/SKILL.md`) è l'interfaccia utente:
guida Claude nella fase 1 (estrazione NL → JSON intermedio) e nel filtro di rilevanza
inline, invocando `nl_query_translator` (fase 2, serializzazione deterministica) e
`run_search` (esecuzione). Nessuna API key oltre a quella NCBI.
```

- [ ] **Step 3: Aggiornare la roadmap in `CLAUDE.md` sezione 8**

Sostituire i punti 2, 3 e 4 con:

```
2. ~~`nl_query_translator.py` — traduzione NL → sintassi PubMed (solo `[tiab]` + MeSH a
   giudizio di Claude), come modulo deterministico testabile~~ **(completato)**
3. ~~Integrazione end-to-end: query NL → query PubMed → PMID → abstract, tramite
   `run_search.py` e la skill `/pubmed-search`~~ **(completato)**
4. ~~Filtro di rilevanza: implementato inline nella skill `/pubmed-search` (Claude legge
   gli abstract e ordina per pertinenza); `relevance_filter.py` come modulo dedicato resta
   un'evoluzione futura~~ **(completato, inline)**
```

- [ ] **Step 4: Eseguire l'intera suite offline (nessuna regressione)**

Run: `pytest`
Expected: PASS — tutti i test offline passano, 5 live deselezionati

- [ ] **Step 5: Prova d'uso reale end-to-end**

Con una `.env` valida, dalla radice del progetto:

```bash
echo '{"concetti":[{"termine":"melanoma","sinonimi":[],"mesh":"melanoma"},{"termine":"immunotherapy","sinonimi":[],"mesh":"immunotherapy"}],"operatore_tra_concetti":"AND","filtri":{"tipi_studio":["randomized controlled trial"]}}' > /tmp/q.json
PYTHONPATH=src python -m nl_query_translator --file /tmp/q.json --link
PYTHONPATH=src python -m run_search --term "$(PYTHONPATH=src python -m nl_query_translator --file /tmp/q.json)" --retmax 5
```

Expected: la prima invocazione stampa la query + URL; la seconda stampa un JSON con
`total_count > 0` e alcuni articoli con abstract. (Su Windows/PowerShell adattare la
sintassi della variabile.)

- [ ] **Step 6: Commit**

```bash
git add examples/sample_queries.md CLAUDE.md
git commit -m "docs: query di riferimento e allineamento CLAUDE.md (step 2-4 completati)"
```

---

## Criteri di completamento

- [ ] `serialize` produce la query di riferimento del CLAUDE.md esattamente (test `test_query_di_riferimento_claude_md`)
- [ ] `python -m nl_query_translator --link` legge JSON da stdin, stampa query + URL
- [ ] JSON invalido (sintattico o semantico) → exit code 1, messaggio su stderr
- [ ] `python -m run_search --term "..."` esegue la ricerca e stampa articoli JSON
- [ ] `pytest` passa interamente offline (nessuna nuova chiamata di rete nei test automatici)
- [ ] La skill `/pubmed-search` esiste e guida il flusso completo; verificata con prova d'uso reale
- [ ] `examples/sample_queries.md` contiene la query di riferimento
- [ ] `CLAUDE.md` riflette `run_search.py`, la skill e gli step 2-4 completati
