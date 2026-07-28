# Manutenzione, Paginazione ed Export Bibliografico Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rimuovere codice morto, esporre la paginazione (già supportata da NCBI ma mai raggiungibile), deduplicare la gestione errori/output nelle CLI, e aggiungere un export bibliografico RIS/BibTeX.

**Architecture:** Quattro interventi indipendenti sullo stesso strato di CLI sottili che il progetto usa ovunque (client → CLI → skill). La paginazione riusa `retstart` (già supportato da `esearch`, verificato dal vivo stabile) e aggiunge `offset` a `elink` (slice lato client, coerente col troncamento `max_links` già esistente). `cli_utils.py` centralizza due pattern oggi duplicati in 3-4 CLI. `export_results.py` è una CLI nuova, indipendente, che legge lo stesso formato JSON già prodotto da `run_search`/`related_search`.

**Tech Stack:** Python 3.10+, stdlib (`argparse`, `json`, `dataclasses`, `sys`), `pytest`, `responses` (già presenti). Nessuna nuova dipendenza.

## Global Constraints

- **Python 3.10+** — annotazioni `str | None`.
- **Codice e commenti in italiano**, coerentemente con i moduli esistenti.
- **Nessuna nuova dipendenza** in `requirements.txt`.
- **`pytest` senza argomenti resta interamente offline** — nessuna chiamata di rete nei test automatici.
- **Paginazione via `retstart`/`offset` semplice**, non `WebEnv`/`query_key` — verificato dal vivo in brainstorming che `retstart` è stabile (stessi risultati fra chiamate ripetute) e non sovrappone pagine adiacenti. `WebEnv`/`query_key` restano parsati in `SearchResult` ma inutilizzati anche dopo questo lavoro: introdurli aggiungerebbe stato con scadenza da propagare fra chiamate CLI separate, senza beneficio dimostrato.
- **`elink` non supporta un vero paging lato NCBI** (verificato in un lavoro precedente: `retmax` non ha effetto su `elink.fcgi`) — il nuovo parametro `offset` di `PubMedClient.elink()` è uno slice Python **lato client**, applicato dopo `parse_elink_xml`.
- **`cli_utils.scrivi_errore`/`stampa_json` devono riprodurre byte-per-byte il comportamento attuale delle CLI**: `sys.stderr.buffer.write(f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace"))` per gli errori, `json.dump(dati, sys.stdout, ensure_ascii=True, indent=2)` + newline per l'output. Non è un dettaglio stilistico: `tests/test_run_search.py` e `tests/test_nl_query_translator.py` contengono test di hardening (`test_main_handles_unicode_in_abstract`, `test_main_errore_ncbi_con_carattere_non_cp1252_su_stderr`, `test_cli_con_carattere_non_cp1252_usa_backslashreplace`, `test_cli_errore_con_carattere_non_cp1252_su_stderr_usa_backslashreplace`) che monkeypatchano `sys.stdout`/`sys.stderr` **a livello di modulo `sys` globale** (`monkeypatch.setattr(sys, "stderr", ...)`, non `monkeypatch.setattr("run_search.sys.stderr", ...)` — sono equivalenti perché `sys` è un singleton, ma è la prova che questi test continueranno a intercettare il comportamento anche dopo il refactor, SOLO SE `cli_utils` usa lo stesso `sys.stderr.buffer.write(...encode(...errors="backslashreplace"))`). Questi test sono il test di non regressione più forte per il Task 3: se falliscono, il refactor ha introdotto una differenza di comportamento, non solo di posizione del codice.
- **Formato export non riconosciuto → `ValueError` esplicito**, mai output vuoto o malformato silenzioso.
- **`export_results.py` non fa alcuna chiamata di rete**: legge JSON da stdin o `--file`, nessuna dipendenza da `pubmed_client`.

## API dei moduli esistenti (da consumare, non modificare)

- `PubMedClient.esearch(term, *, retmax=100, retstart=0, sort=None, mindate=None, maxdate=None, datetype="pdat") -> SearchResult` — **`retstart` è già un parametro supportato**, semplicemente mai valorizzato da `run_search.esegui`.
- `PubMedClient.elink(pmid, linkname, *, max_links=30) -> list[str]` — da estendere con `offset` (Task 2).
- `PubMedClient.efetch(pmids) -> list[Article]`.
- `Article(pmid, title, abstract, authors, journal, pub_date, pub_types, mesh_terms, doi, coi_statement=None)` — dataclass frozen in `pubmed_models.py`. `pub_date` è una stringa ISO parziale (`"2024"`, `"2024-03"`, `"2024-03-15"`); l'anno è sempre nei primi 4 caratteri.
- `PubMedError` (base), `PubMedAPIError`, `PubMedHTTPError` — gerarchia eccezioni in `pubmed_errors.py`.
- `run_search.esegui(term, retmax, client) -> dict` — produce `{"total_count", "translated_query", "warnings", "articles"}`, `articles` = lista di `dataclasses.asdict(Article)`.
- `related_search.esegui(pmid, tipo, max_links, client) -> dict` — stesso formato di `run_search.esegui`.

## Contenuto attuale esatto dei file da modificare

Riportato qui perché ogni task lavora su un file alla volta senza vedere gli altri task.

### `src/run_search.py` (attuale, integrale)

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
        sys.stderr.buffer.write(
            f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
        )
        return 1

    json.dump(risultato, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Nota per il Task 2**: `esegui` viene chiamato come `esegui("melanoma", retmax=5, client=client)` in `tests/test_run_search.py` (keyword arguments per `retmax` e `client`) — il nuovo parametro `retstart` deve avere un default (`retstart: int = 0`) per non rompere queste chiamate posizionali/keyword esistenti.

### `src/related_search.py` (attuale, integrale)

```python
"""
related_search.py

Entry-point CLI: dato un PMID, trova articoli collegati (simili o che lo citano)
tramite PubMedClient.elink, poi ne recupera titolo/abstract con efetch. Stampa lo
stesso formato JSON di run_search.py, così la skill riusa lo stesso filtro di
rilevanza semantica senza codice nuovo.

Nessuna logica NL, nessun parsing XML proprio: delega a pubmed_client/pubmed_models.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from pubmed_client import PubMedClient, PubMedConfig
from pubmed_errors import PubMedError

_LINKNAME_PER_TIPO = {
    "simili": "pubmed_pubmed",
    "citazioni": "pubmed_pubmed_citedin",
}


def esegui(pmid: str, tipo: str, max_links: int, client: PubMedClient) -> dict:
    """Trova articoli collegati a `pmid` e restituisce un dizionario serializzabile
    in JSON, nello stesso formato di run_search.esegui.

    `tipo` deve essere "simili" o "citazioni". `total_count` qui è il numero di
    PMID collegati trovati (elink non fornisce un conteggio separato come esearch).
    """
    linkname = _LINKNAME_PER_TIPO.get(tipo)
    if linkname is None:
        raise ValueError(
            f"tipo non valido: {tipo!r} (ammessi: {', '.join(_LINKNAME_PER_TIPO)})"
        )
    pmid_collegati = client.elink(pmid, linkname, max_links=max_links)
    articoli = client.efetch(pmid_collegati)
    return {
        "total_count": len(pmid_collegati),
        "translated_query": None,
        "warnings": [],
        "articles": [dataclasses.asdict(a) for a in articoli],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Trova articoli PubMed collegati (simili o che citano) a un PMID."
    )
    parser.add_argument("--pmid", required=True, help="PMID di partenza")
    parser.add_argument(
        "--tipo", required=True, choices=sorted(_LINKNAME_PER_TIPO),
        help="Tipo di collegamento da cercare",
    )
    parser.add_argument(
        "--max", type=int, default=30, dest="max_links",
        help="Numero massimo di articoli collegati da recuperare",
    )
    args = parser.parse_args(argv)

    try:
        client = PubMedClient(PubMedConfig.from_env())
        risultato = esegui(args.pmid, args.tipo, args.max_links, client)
    except PubMedError as exc:
        sys.stderr.buffer.write(
            f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
        )
        return 1

    json.dump(risultato, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Nota per il Task 2**: `esegui` viene chiamato come `esegui("21376230", "simili", 30, client)` (posizionale) in `tests/test_related_search.py` — il nuovo parametro `offset` deve avere un default e andare **dopo** `client` (o essere keyword-only) per non rompere queste chiamate posizionali esistenti.

### `src/mesh_resolver.py` (attuale, integrale — solo per il Task 3, adozione di `cli_utils`)

```python
"""
mesh_resolver.py

Entry-point CLI: risolve un termine libero verso il descriptor MeSH ufficiale di
NCBI (quando esiste un match esatto sull'intestazione), tramite
pubmed_client.PubMedClient.resolve_mesh.

Nessuna logica NL, nessun parsing XML proprio (delegato a pubmed_client/pubmed_models).
Un errore di rete o l'assenza di un match affidabile producono lo stesso esito
pratico per il chiamante (la skill): nessun termine MeSH, fallback su [tiab].
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from pubmed_client import PubMedClient, PubMedConfig
from pubmed_errors import PubMedError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Risolve un termine verso il descriptor MeSH ufficiale di NCBI."
    )
    parser.add_argument("--termine", required=True, help="Termine libero da risolvere")
    args = parser.parse_args(argv)

    try:
        client = PubMedClient(PubMedConfig.from_env())
        match = client.resolve_mesh(args.termine)
    except PubMedError as exc:
        sys.stderr.buffer.write(
            f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
        )
        return 1

    if match is None:
        risultato = {
            "termine_originale": args.termine,
            "descriptor": None,
            "entry_terms": [],
            "mesh_ui": None,
        }
    else:
        risultato = dataclasses.asdict(match)

    json.dump(risultato, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

---

## File Structure

| File | Responsabilità |
|---|---|
| `src/relevance_filter.py` | **Cancellato** (Task 1). Zero import nel codice, verificato in brainstorming. |
| `CLAUDE.md` | Task 1: rimuove il riferimento a `relevance_filter.py`, riscrive la sezione 6. Task 5 (indiretto tramite skill): nessuna modifica aggiuntiva qui. |
| `src/run_search.py` | Task 2: aggiunge `--retstart`/`retstart` a CLI e `esegui`. Task 3: adotta `cli_utils`. |
| `src/related_search.py` | Task 2: aggiunge `--retstart`/`offset` a CLI e `esegui`. Task 3: adotta `cli_utils`. |
| `src/pubmed_client.py` | Task 2: `PubMedClient.elink()` guadagna `offset`. |
| `src/mesh_resolver.py` | Task 3: adotta `cli_utils`. |
| `src/nl_query_translator.py` | Task 3: adotta solo `cli_utils.scrivi_errore` (stampa una query testuale, non JSON). |
| `src/cli_utils.py` | Nuovo (Task 3): `scrivi_errore`, `stampa_json`. |
| `src/export_results.py` | Nuovo (Task 4): CLI di export RIS/BibTeX. |
| `tests/test_pubmed_client.py` | Task 2: estende i test di `elink` con `offset`. |
| `tests/test_run_search.py` | Task 2: nuovo test `--retstart`. Nessuna modifica per Task 3 (i test di hardening esistenti sono la rete di sicurezza). |
| `tests/test_related_search.py` | Task 2: nuovo test `--retstart`/`offset`. |
| `tests/test_cli_utils.py` | Nuovo (Task 3). |
| `tests/test_export_results.py` | Nuovo (Task 4). |
| `.claude/skills/pubmed-search/SKILL.md` | Task 5: menzione di `--retstart` e dell'export bibliografico. |

---

## Task 1: Rimozione codice morto — `relevance_filter.py`

**Files:**
- Delete: `src/relevance_filter.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nulla.
- Produces: nulla (solo rimozione e documentazione).

- [ ] **Step 1: Verificare che nessun modulo importi `relevance_filter`**

Run: `grep -rn "relevance_filter" src/ tests/`
Expected: nessun risultato (il file esiste ma non è mai importato — verificato in brainstorming). Se compare un import, FERMARSI e segnalarlo: il piano assume che la rimozione sia sicura.

- [ ] **Step 2: Cancellare il file**

```bash
git rm src/relevance_filter.py
```

- [ ] **Step 3: Aggiornare l'albero directory in `CLAUDE.md` (sezione 3)**

Cercare la riga:

```
│   ├── relevance_filter.py    # filtro di pertinenza semantica
```

e rimuoverla dall'albero.

- [ ] **Step 4: Riscrivere la sezione 6 di `CLAUDE.md`**

Sostituire l'intera sezione (da `## 6. Filtro di rilevanza semantica` fino alla riga prima di `## 7. Setup ambiente`) con:

```markdown
## 6. Filtro di rilevanza semantica

Il filtro di rilevanza vive **inline nella skill** `/pubmed-search`
(`.claude/skills/pubmed-search/SKILL.md`, fase 5), non in un modulo Python dedicato:
dopo aver recuperato PMID + abstract via `run_search`/`related_search`, Claude legge
titolo e abstract di ogni articolo insieme all'intento originale dell'utente e:
- scarta o declassa gli articoli non pertinenti, anche se hanno matchato la query booleana
- segnala eventuali falsi negativi (articoli che sembrano rilevanti ma che la query
  booleana potrebbe aver escluso, per una restrizione troppo aggressiva)
- quando il filtro brevetti è attivo, legge anche `coi_statement` per scartare le
  dichiarazioni negative (vedi sezione 4, tag `[cois]`)

Questo filtro è ciò che distingue il progetto da una semplice interfaccia a ESearch: la
query booleana serve a restringere lo spazio di ricerca in modo efficiente, il filtro
semantico serve a ordinare/scartare per pertinenza reale.
```

- [ ] **Step 5: Aggiornare la roadmap (step 4) in `CLAUDE.md`**

Cercare il testo dello step 4, che contiene una frase simile a:

```
4. ~~Filtro di rilevanza: implementato inline nella skill `/pubmed-search` (Claude legge
   gli abstract e ordina per pertinenza); `relevance_filter.py` come modulo dedicato resta
   un'evoluzione futura~~ **(completato, inline)**
```

Sostituire con (rimuove il riferimento al file ora cancellato):

```
4. ~~Filtro di rilevanza: implementato inline nella skill `/pubmed-search` (Claude legge
   gli abstract e ordina per pertinenza rispetto all'intento originale)~~
   **(completato, inline)**
```

- [ ] **Step 6: Verificare l'intera suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS, stesso conteggio di prima (nessun test referenziava `relevance_filter.py`, verificato allo Step 1).

- [ ] **Step 7: Commit**

```bash
git add -A CLAUDE.md
git commit -m "chore: rimuove relevance_filter.py (mai implementato, mai importato)"
```

---

## Task 2: Paginazione — `retstart` su `run_search`, `offset` su `elink`/`related_search`

**Files:**
- Modify: `src/pubmed_client.py`
- Modify: `src/run_search.py`
- Modify: `src/related_search.py`
- Modify: `tests/test_pubmed_client.py`
- Modify: `tests/test_run_search.py`
- Modify: `tests/test_related_search.py`

**Interfaces:**
- Consumes: `PubMedClient.esearch(..., retstart=0)` (già esistente), `parse_elink_xml` (già esistente).
- Produces:
  - `PubMedClient.elink(self, pmid: str, linkname: str, *, max_links: int = 30, offset: int = 0) -> list[str]`
  - `run_search.esegui(term: str, retmax: int, client: PubMedClient, retstart: int = 0) -> dict`
  - `related_search.esegui(pmid: str, tipo: str, max_links: int, client: PubMedClient, offset: int = 0) -> dict`

- [ ] **Step 1: Scrivere il test che fallisce per `elink` con `offset`**

In `tests/test_pubmed_client.py`, la fixture `ELINK_TRE_LINK` (già presente, usata dai test `test_elink_*`) contiene 3 link oltre alla sorgente: `111`, `222`, `333`. Aggiungere in fondo al blocco dei test `elink` (dopo `test_elink_propaga_errore_di_rete`):

```python
@responses.activate
def test_elink_offset_salta_i_primi_link(client):
    responses.add(responses.GET, ELINK_URL, body=ELINK_TRE_LINK, status=200)
    risultato = client.elink("21376230", "pubmed_pubmed", max_links=2, offset=1)
    assert risultato == ["222", "333"]
```

- [ ] **Step 2: Eseguire il test e verificarne il fallimento**

Run: `PYTHONPATH=src python -m pytest tests/test_pubmed_client.py -k offset -v`
Expected: FAIL con `TypeError: elink() got an unexpected keyword argument 'offset'`.

- [ ] **Step 3: Implementare `offset` in `PubMedClient.elink()`**

In `src/pubmed_client.py`, la firma attuale è:

```python
    def elink(self, pmid: str, linkname: str, *, max_links: int = 30) -> list[str]:
```

Sostituire con:

```python
    def elink(self, pmid: str, linkname: str, *, max_links: int = 30, offset: int = 0) -> list[str]:
```

e l'ultima riga del metodo, che oggi è:

```python
        return parse_elink_xml(xml, pmid)[:max_links]
```

con:

```python
        return parse_elink_xml(xml, pmid)[offset : offset + max_links]
```

Non toccare il resto del metodo (docstring, costruzione della richiesta) — solo firma e riga di ritorno. Aggiungere alla docstring, dopo il paragrafo su `retmax`/`max_links`, una riga:

```
        `offset` sposta la finestra di troncamento (paginazione lato client, dato che
        elink non supporta un vero retstart/paging lato NCBI).
```

- [ ] **Step 4: Eseguire il test e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_pubmed_client.py -k offset -v`
Expected: PASS.

- [ ] **Step 5: Scrivere il test che fallisce per `run_search --retstart`**

Aggiungere in fondo a `tests/test_run_search.py`:

```python
@responses.activate
def test_esegui_passa_retstart_a_esearch(client):
    """Verifica che retstart viaggi fino alla richiesta HTTP inviata a NCBI."""
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=ESEARCH_BODY_PMID_MATCH_EFETCH_BATCH,
        status=200,
    )
    responses.add(
        responses.POST,
        EFETCH_URL,
        body=(FIXTURES / "efetch_batch.xml").read_text(encoding="utf-8"),
        status=200,
    )
    esegui("melanoma", retmax=5, client=client, retstart=10)
    inviata = responses.calls[0].request
    assert "retstart=10" in inviata.url


@responses.activate
def test_main_accetta_flag_retstart(client, monkeypatch, capsys):
    monkeypatch.setattr("run_search.PubMedConfig.from_env", lambda: client._config)
    monkeypatch.setattr("run_search.PubMedClient", lambda config: client)
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body=ESEARCH_BODY_PMID_MATCH_EFETCH_BATCH,
        status=200,
    )
    responses.add(
        responses.POST,
        EFETCH_URL,
        body=(FIXTURES / "efetch_batch.xml").read_text(encoding="utf-8"),
        status=200,
    )
    codice = main(argv=["--term", "melanoma", "--retmax", "5", "--retstart", "10"])
    out = capsys.readouterr()
    assert codice == 0
    inviata = responses.calls[0].request
    assert "retstart=10" in inviata.url
```

- [ ] **Step 6: Eseguire i test e verificarne il fallimento**

Run: `PYTHONPATH=src python -m pytest tests/test_run_search.py -k retstart -v`
Expected: FAIL — `test_esegui_passa_retstart_a_esearch` con `TypeError: esegui() got an unexpected keyword argument 'retstart'`; `test_main_accetta_flag_retstart` con `SystemExit`/errore di parsing per `--retstart` non riconosciuto (`argparse` esce con codice 2 su un flag ignoto).

- [ ] **Step 7: Implementare `--retstart` in `run_search.py`**

In `src/run_search.py`, la firma di `esegui` è oggi:

```python
def esegui(term: str, retmax: int, client: PubMedClient) -> dict:
```

Sostituire con:

```python
def esegui(term: str, retmax: int, client: PubMedClient, retstart: int = 0) -> dict:
```

e la riga:

```python
    ricerca = client.esearch(term, retmax=retmax)
```

con:

```python
    ricerca = client.esearch(term, retmax=retmax, retstart=retstart)
```

In `main()`, dopo l'argomento `--retmax` esistente, aggiungere:

```python
    parser.add_argument(
        "--retstart", type=int, default=0,
        help="Offset per la paginazione (0-based): salta i primi N risultati",
    )
```

e la riga:

```python
        risultato = esegui(args.term, args.retmax, client)
```

con:

```python
        risultato = esegui(args.term, args.retmax, client, args.retstart)
```

- [ ] **Step 8: Eseguire i test e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_run_search.py -v`
Expected: PASS tutti (compresi i test di hardening preesistenti, invariati).

- [ ] **Step 9: Scrivere i test che falliscono per `related_search --retstart`**

Aggiungere in fondo a `tests/test_related_search.py`:

```python
ELINK_TRE_LINK = """<?xml version="1.0" ?>
<eLinkResult>
  <LinkSet>
    <DbFrom>pubmed</DbFrom>
    <IdList><Id>21376230</Id></IdList>
    <LinkSetDb>
      <DbTo>pubmed</DbTo>
      <LinkName>pubmed_pubmed</LinkName>
      <Link><Id>21376230</Id></Link>
      <Link><Id>111</Id></Link>
      <Link><Id>222</Id></Link>
    </LinkSetDb>
  </LinkSet>
</eLinkResult>
"""


@responses.activate
def test_esegui_offset_salta_i_primi_link(client):
    responses.add(responses.GET, ELINK_URL, body=ELINK_TRE_LINK, status=200)
    responses.add(responses.POST, EFETCH_URL, body=_efetch_xml("222"), status=200)
    risultato = esegui("21376230", "simili", 1, client, offset=1)
    assert risultato["articles"][0]["pmid"] == "222"


@responses.activate
def test_main_accetta_flag_retstart(monkeypatch, capsys):
    monkeypatch.setattr(
        "related_search.PubMedConfig.from_env",
        lambda: PubMedConfig(tool="t", email="e@example.org", api_key="k"),
    )
    responses.add(responses.GET, ELINK_URL, body=ELINK_TRE_LINK, status=200)
    responses.add(responses.POST, EFETCH_URL, body=_efetch_xml("222"), status=200)
    codice = main(argv=["--pmid", "21376230", "--tipo", "simili", "--max", "1", "--retstart", "1"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert dati["articles"][0]["pmid"] == "222"
```

- [ ] **Step 10: Eseguire i test e verificarne il fallimento**

Run: `PYTHONPATH=src python -m pytest tests/test_related_search.py -k retstart_o_offset -v` (oppure `-k "offset or retstart"`)
Expected: FAIL — `esegui()` non accetta `offset`, `--retstart` non riconosciuto da `main()`.

- [ ] **Step 11: Implementare `--retstart`/`offset` in `related_search.py`**

In `src/related_search.py`, la firma di `esegui` è oggi:

```python
def esegui(pmid: str, tipo: str, max_links: int, client: PubMedClient) -> dict:
```

Sostituire con:

```python
def esegui(pmid: str, tipo: str, max_links: int, client: PubMedClient, offset: int = 0) -> dict:
```

e la riga:

```python
    pmid_collegati = client.elink(pmid, linkname, max_links=max_links)
```

con:

```python
    pmid_collegati = client.elink(pmid, linkname, max_links=max_links, offset=offset)
```

In `main()`, dopo l'argomento `--max` esistente, aggiungere:

```python
    parser.add_argument(
        "--retstart", type=int, default=0, dest="offset",
        help="Offset per la paginazione (0-based): salta i primi N collegamenti",
    )
```

e la riga:

```python
        risultato = esegui(args.pmid, args.tipo, args.max_links, client)
```

con:

```python
        risultato = esegui(args.pmid, args.tipo, args.max_links, client, args.offset)
```

- [ ] **Step 12: Eseguire i test e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_related_search.py -v`
Expected: PASS tutti.

- [ ] **Step 13: Verificare l'intera suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS, nessuna regressione.

- [ ] **Step 14: Commit**

```bash
git add src/pubmed_client.py src/run_search.py src/related_search.py tests/test_pubmed_client.py tests/test_run_search.py tests/test_related_search.py
git commit -m "feat: paginazione, --retstart su run_search e related_search"
```

---

## Task 3: `cli_utils.py` — deduplica errore/output nelle CLI

**Files:**
- Create: `src/cli_utils.py`
- Create: `tests/test_cli_utils.py`
- Modify: `src/run_search.py`
- Modify: `src/mesh_resolver.py`
- Modify: `src/related_search.py`
- Modify: `src/nl_query_translator.py`

**Interfaces:**
- Consumes: nulla di nuovo.
- Produces:
  - `cli_utils.scrivi_errore(exc: Exception) -> None`
  - `cli_utils.stampa_json(dati: dict) -> None`

**Vincolo critico di questo task** (ripetuto dai Global Constraints, perché qui è dove conta davvero): i test di hardening già presenti in `tests/test_run_search.py` (`test_main_handles_unicode_in_abstract`, `test_main_errore_ncbi_con_carattere_non_cp1252_su_stderr`) e in `tests/test_nl_query_translator.py` (`test_cli_con_carattere_non_cp1252_usa_backslashreplace`, `test_cli_con_carattere_non_cp1252_e_link_usa_backslashreplace`, `test_cli_errore_con_carattere_non_cp1252_su_stderr_usa_backslashreplace`) **non vanno modificati**: sono la prova che il refactor non ha cambiato comportamento. Se uno di questi fallisce dopo l'adozione di `cli_utils`, il bug è nel nuovo `cli_utils.py`, non nel test.

- [ ] **Step 1: Scrivere i test che falliscono per `cli_utils`**

Creare `tests/test_cli_utils.py`:

```python
"""Test di cli_utils: scrittura errori/JSON con encoding robusto, in isolamento."""

import json
import sys

import pytest

from cli_utils import scrivi_errore, stampa_json


class _BufferFinto:
    """Doppio di test per uno stream binario: accumula i byte scritti."""

    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, dati: bytes) -> int:
        self.chunks.append(dati)
        return len(dati)


class _StderrFinto:
    """Simula uno stderr con encoding realmente restrittivo (cp1252)."""

    def __init__(self, encoding: str):
        self.encoding = encoding
        self.buffer = _BufferFinto()


def test_scrivi_errore_usa_encoding_robusto(monkeypatch):
    """Un messaggio con un carattere non rappresentabile in cp1252 non deve
    sollevare UnicodeEncodeError: deve essere sostituito da backslashreplace."""
    messaggio_con_theta = "Errore NCBI: parametro non valido θ"
    with pytest.raises(UnicodeEncodeError):
        messaggio_con_theta.encode("cp1252")

    stderr_finto = _StderrFinto("cp1252")
    monkeypatch.setattr(sys, "stderr", stderr_finto)

    scrivi_errore(Exception(messaggio_con_theta))

    scritto = b"".join(stderr_finto.buffer.chunks)
    decodificato = scritto.decode("cp1252")
    assert messaggio_con_theta not in decodificato
    assert "\\u03b8" in decodificato
    assert decodificato.startswith("Errore: ")


def test_stampa_json_e_ascii_puro(capsys):
    """ensure_ascii=True: caratteri non-ASCII devono uscire come sequenze di
    escape, mai come byte grezzi (evita UnicodeEncodeError su stdout ristretto)."""
    stampa_json({"titolo": "café résumé"})
    out = capsys.readouterr()
    assert out.out.isascii()
    dati = json.loads(out.out)
    assert dati["titolo"] == "café résumé"


def test_stampa_json_termina_con_newline(capsys):
    stampa_json({"a": 1})
    out = capsys.readouterr()
    assert out.out.endswith("\n")
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `PYTHONPATH=src python -m pytest tests/test_cli_utils.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'cli_utils'`.

- [ ] **Step 3: Scrivere `src/cli_utils.py`**

```python
"""
cli_utils.py

Helper condivisi dalle CLI del progetto (run_search, mesh_resolver, related_search,
nl_query_translator): scrittura di errori e output JSON con encoding robusto,
per evitare UnicodeEncodeError su console Windows con encoding ristretto (es. cp1252)
quando un messaggio o un campo contiene caratteri non rappresentabili.

Nessuna logica di dominio: solo I/O.
"""

from __future__ import annotations

import json
import sys


def scrivi_errore(exc: Exception) -> None:
    """Scrive un'eccezione su stderr con encoding robusto.

    Usa `sys.stderr.buffer.write` (non `print`) perché il messaggio può contenere
    testo grezzo arbitrario (es. il corpo di un <ERROR> di NCBI), e `errors=
    "backslashreplace"` evita UnicodeEncodeError quando l'encoding di stderr non
    può rappresentare un carattere.
    """
    sys.stderr.buffer.write(
        f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
    )


def stampa_json(dati: dict) -> None:
    """Stampa un dizionario come JSON su stdout, stesso formato in tutte le CLI.

    `ensure_ascii=True` mantiene l'output puro ASCII (con sequenze di escape per
    i caratteri non-ASCII), evitando UnicodeEncodeError su stdout con encoding
    ristretto.
    """
    json.dump(dati, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
```

- [ ] **Step 4: Eseguire i test e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_cli_utils.py -v`
Expected: PASS tutti e tre.

- [ ] **Step 5: Adottare `cli_utils` in `run_search.py`**

In `src/run_search.py`:
- Aggiungere `from cli_utils import scrivi_errore, stampa_json` (rimuovere `import json` se non più usato altrove nel file — verificare con una ricerca: non lo è).
- Sostituire il blocco:

```python
    except PubMedError as exc:
        sys.stderr.buffer.write(
            f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
        )
        return 1

    json.dump(risultato, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0
```

con:

```python
    except PubMedError as exc:
        scrivi_errore(exc)
        return 1

    stampa_json(risultato)
    return 0
```

- Rimuovere `import json` e `import sys` dalle importazioni **solo se** non più referenziati altrove nel file dopo questa modifica (verificare con `grep -n "sys\.\|json\." src/run_search.py`: se non compaiono altri usi, rimuovere entrambe le righe di import).

- [ ] **Step 6: Eseguire i test di `run_search` e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_run_search.py -v`
Expected: PASS **tutti**, inclusi i test di hardening preesistenti (`test_main_handles_unicode_in_abstract`, `test_main_errore_ncbi_con_carattere_non_cp1252_su_stderr`) senza averli modificati.

- [ ] **Step 7: Adottare `cli_utils` in `mesh_resolver.py`**

In `src/mesh_resolver.py` (contenuto integrale riportato più sopra in questo piano),
aggiungere `from cli_utils import scrivi_errore, stampa_json` alle importazioni. Sostituire
il blocco:

```python
    except PubMedError as exc:
        sys.stderr.buffer.write(
            f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
        )
        return 1
```

con:

```python
    except PubMedError as exc:
        scrivi_errore(exc)
        return 1
```

e le due righe finali:

```python
    json.dump(risultato, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
```

con:

```python
    stampa_json(risultato)
```

`dataclasses` resta importato (usato per `dataclasses.asdict(match)`, non va rimosso).
Rimuovere `import json` e `import sys` **solo se**, dopo questa modifica, non compaiono più
altri usi nel file (verificare con `grep -n "sys\.\|json\." src/mesh_resolver.py`).

- [ ] **Step 8: Eseguire i test di `mesh_resolver` e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_mesh_resolver.py -v`
Expected: PASS tutti, incluso `test_main_errore_di_rete_esce_uno_su_stderr`.

- [ ] **Step 9: Adottare `cli_utils` in `related_search.py`**

A questo punto `src/related_search.py` ha già le modifiche del Task 2 (`--retstart`/`offset`):
il blocco di gestione errori e le righe di stampa JSON restano però invariate rispetto al
contenuto originale riportato più sopra in questo piano. Aggiungere `from cli_utils import
scrivi_errore, stampa_json` alle importazioni. Sostituire il blocco:

```python
    except PubMedError as exc:
        sys.stderr.buffer.write(
            f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
        )
        return 1
```

con:

```python
    except PubMedError as exc:
        scrivi_errore(exc)
        return 1
```

e le due righe finali:

```python
    json.dump(risultato, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
```

con:

```python
    stampa_json(risultato)
```

`dataclasses` resta importato (usato per `dataclasses.asdict(a)` sugli articoli). Rimuovere
`import json` e `import sys` **solo se**, dopo questa modifica, non compaiono più altri usi
nel file (verificare con `grep -n "sys\.\|json\." src/related_search.py`).

- [ ] **Step 10: Eseguire i test di `related_search` e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_related_search.py -v`
Expected: PASS tutti.

- [ ] **Step 11: Adottare `cli_utils.scrivi_errore` (solo, non `stampa_json`) in `nl_query_translator.py`**

`nl_query_translator.py` stampa una query testuale, non un JSON — adotta solo `scrivi_errore`. Aggiungere `from cli_utils import scrivi_errore`. Sostituire il blocco:

```python
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        # Stesso motivo del blocco di scrittura stdout sotto: il messaggio d'errore può
        # contenere contenuto arbitrario (repr() di campi del JSON utente), quindi va
        # scritto con lo stesso encoding robusto per evitare UnicodeEncodeError su Windows.
        sys.stderr.buffer.write(
            f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
        )
        return 1
```

con:

```python
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        scrivi_errore(exc)
        return 1
```

Non toccare il blocco di scrittura di `query`/`url` su stdout (righe con `sys.stdout.buffer.write`): quello resta invariato, perché scrive testo con encoding robusto per un motivo diverso da `stampa_json` (non è JSON) e non è nello scope di questo task secondo la spec (D5 riguarda solo la duplicazione dell'errore e della stampa JSON, `nl_query_translator` non stampa JSON). Non rimuovere `import sys`/`import json`: restano usati altrove nel file (`json.loads`, `sys.stdin`, `sys.stdout.buffer.write`).

- [ ] **Step 12: Eseguire i test di `nl_query_translator` e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_nl_query_translator.py -v`
Expected: PASS **tutti**, inclusi i quattro test di hardening preesistenti, senza averli modificati.

- [ ] **Step 13: Verificare l'intera suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS, stesso numero di test di prima più i 3 nuovi di `test_cli_utils.py`.

- [ ] **Step 14: Commit**

```bash
git add src/cli_utils.py tests/test_cli_utils.py src/run_search.py src/mesh_resolver.py src/related_search.py src/nl_query_translator.py
git commit -m "refactor: cli_utils, deduplica scrittura errori/JSON in 4 CLI"
```

---

## Task 4: `export_results.py` — export bibliografico RIS/BibTeX

**Files:**
- Create: `src/export_results.py`
- Create: `tests/test_export_results.py`

**Interfaces:**
- Consumes: il formato JSON prodotto da `run_search.esegui`/`related_search.esegui` (chiave `"articles"`, lista di dizionari con almeno `title`, `authors`, `journal`, `pub_date`, `pmid`; opzionalmente `doi`, `abstract`).
- Produces:
  - `esporta(dati: dict, formato: str) -> str`
  - CLI `python -m export_results --formato ris|bibtex [--file FILE]`

- [ ] **Step 1: Scrivere i test che falliscono**

Creare `tests/test_export_results.py`:

```python
"""Test di export_results: conversione JSON -> RIS/BibTeX, interamente offline."""

import json

import pytest

from export_results import esporta, main

ARTICOLO_COMPLETO = {
    "pmid": "33301246",
    "title": "Un titolo di test",
    "abstract": "Un abstract di test.",
    "authors": ["Rossi M", "Bianchi L"],
    "journal": "J Test",
    "pub_date": "2024-03-15",
    "pub_types": ["Journal Article"],
    "mesh_terms": [],
    "doi": "10.1000/test123",
    "coi_statement": None,
}

ARTICOLO_SENZA_DOI_ABSTRACT = {
    "pmid": "1",
    "title": "Senza DOI né abstract",
    "abstract": None,
    "authors": ["Verdi G"],
    "journal": "J Minimal",
    "pub_date": "2023",
    "pub_types": [],
    "mesh_terms": [],
    "doi": None,
    "coi_statement": None,
}

DATI_DUE_ARTICOLI = {
    "total_count": 2,
    "translated_query": None,
    "warnings": [],
    "articles": [ARTICOLO_COMPLETO, ARTICOLO_SENZA_DOI_ABSTRACT],
}


def test_ris_contiene_i_campi_principali():
    out = esporta(DATI_DUE_ARTICOLI, "ris")
    assert "TY  - JOUR" in out
    assert "AU  - Rossi M" in out
    assert "AU  - Bianchi L" in out
    assert "TI  - Un titolo di test" in out
    assert "JO  - J Test" in out
    assert "PY  - 2024" in out
    assert "DO  - 10.1000/test123" in out
    assert "AB  - Un abstract di test." in out
    assert "ID  - 33301246" in out
    assert out.count("ER  -") == 2  # un record per articolo


def test_ris_omette_doi_e_abstract_assenti():
    out = esporta(DATI_DUE_ARTICOLI, "ris")
    # Il secondo record (PMID 1) non deve avere righe DO/AB proprie: verifichiamo
    # che non compaia alcuna riga "DO  - None" o "AB  - None" (bug tipico di
    # una f-string che non gestisce il caso assente).
    assert "DO  - None" not in out
    assert "AB  - None" not in out
    assert "PY  - 2023" in out


def test_bibtex_contiene_i_campi_principali():
    out = esporta(DATI_DUE_ARTICOLI, "bibtex")
    assert "@article{pmid33301246," in out
    assert "author = {Rossi M and Bianchi L}" in out
    assert "title = {Un titolo di test}" in out
    assert "journal = {J Test}" in out
    assert "year = {2024}" in out
    assert "doi = {10.1000/test123}" in out


def test_bibtex_omette_doi_assente():
    out = esporta(DATI_DUE_ARTICOLI, "bibtex")
    assert "@article{pmid1," in out
    # Il record del secondo articolo (senza doi) non deve contenere alcuna riga
    # "doi = ...": né "doi = {None}" né una riga doi vuota.
    inizio_secondo = out.index("@article{pmid1,")
    secondo_record = out[inizio_secondo:]
    assert "doi = " not in secondo_record


def test_formato_ignoto_solleva_value_error():
    with pytest.raises(ValueError):
        esporta(DATI_DUE_ARTICOLI, "csv")


def test_nessun_articolo_produce_stringa_vuota():
    assert esporta({"articles": []}, "ris") == ""
    assert esporta({"articles": []}, "bibtex") == ""


def test_main_legge_da_file_e_stampa_ris(tmp_path, capsys):
    percorso = tmp_path / "risultati.json"
    percorso.write_text(json.dumps(DATI_DUE_ARTICOLI), encoding="utf-8")
    codice = main(argv=["--formato", "ris", "--file", str(percorso)])
    out = capsys.readouterr()
    assert codice == 0
    assert "TY  - JOUR" in out.out


def test_main_legge_da_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(DATI_DUE_ARTICOLI)))
    codice = main(argv=["--formato", "bibtex"])
    out = capsys.readouterr()
    assert codice == 0
    assert "@article{pmid33301246," in out.out


def test_main_json_malformato_esce_con_errore(capsys):
    codice = main(argv=["--formato", "ris", "--file", "/percorso/inesistente.json"])
    out = capsys.readouterr()
    assert codice == 1
    assert "Errore" in out.err
```

- [ ] **Step 2: Eseguire i test e verificarne il fallimento**

Run: `PYTHONPATH=src python -m pytest tests/test_export_results.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'export_results'`.

- [ ] **Step 3: Scrivere `src/export_results.py`**

```python
"""
export_results.py

Entry-point CLI: converte il JSON prodotto da run_search/related_search (chiave
"articles") in formato bibliografico RIS o BibTeX, per l'import in reference
manager (Zotero, Mendeley, EndNote) o in LaTeX.

Funzione pura, nessuna chiamata di rete: legge JSON da stdin o file, scrive testo
su stdout. Non dipende da pubmed_client: qualunque JSON con la stessa forma
(articles: [{title, authors, journal, pub_date, pmid, doi?, abstract?}, ...])
funziona, non solo l'output diretto delle altre CLI del progetto.
"""

from __future__ import annotations

import argparse
import json
import sys

from cli_utils import scrivi_errore

_FORMATI_VALIDI = {"ris", "bibtex"}


def _anno(pub_date: str | None) -> str:
    """Estrae l'anno da una data ISO parziale ("2024", "2024-03", "2024-03-15").

    pub_date può essere una stringa vuota per articoli con data mancante: in tal
    caso l'anno è una stringa vuota, non un errore (coerente con la convenzione
    già in uso in pubmed_models.Article: dati NCBI genuinamente incompleti).
    """
    return (pub_date or "")[:4]


def _record_ris(articolo: dict) -> str:
    righe = ["TY  - JOUR"]
    for autore in articolo.get("authors") or []:
        righe.append(f"AU  - {autore}")
    righe.append(f"TI  - {articolo.get('title') or ''}")
    righe.append(f"JO  - {articolo.get('journal') or ''}")
    anno = _anno(articolo.get("pub_date"))
    if anno:
        righe.append(f"PY  - {anno}")
    if articolo.get("doi"):
        righe.append(f"DO  - {articolo['doi']}")
    if articolo.get("abstract"):
        righe.append(f"AB  - {articolo['abstract']}")
    if articolo.get("pmid"):
        righe.append(f"ID  - {articolo['pmid']}")
    righe.append("ER  - ")
    return "\n".join(righe)


def _record_bibtex(articolo: dict) -> str:
    chiave = f"pmid{articolo.get('pmid') or 'sconosciuto'}"
    autori = " and ".join(articolo.get("authors") or [])
    campi = [
        f"  author = {{{autori}}}",
        f"  title = {{{articolo.get('title') or ''}}}",
        f"  journal = {{{articolo.get('journal') or ''}}}",
    ]
    anno = _anno(articolo.get("pub_date"))
    if anno:
        campi.append(f"  year = {{{anno}}}")
    if articolo.get("doi"):
        campi.append(f"  doi = {{{articolo['doi']}}}")
    corpo = ",\n".join(campi)
    return f"@article{{{chiave},\n{corpo}\n}}"


def esporta(dati: dict, formato: str) -> str:
    """Converte dati["articles"] nel formato richiesto ("ris" o "bibtex").

    Solleva ValueError se il formato non è riconosciuto. Nessun articolo ->
    stringa vuota (non un errore: è un esito valido di una ricerca a zero risultati).
    """
    if formato not in _FORMATI_VALIDI:
        raise ValueError(
            f"formato non valido: {formato!r} (ammessi: {', '.join(sorted(_FORMATI_VALIDI))})"
        )
    articoli = dati.get("articles") or []
    if formato == "ris":
        record = [_record_ris(a) for a in articoli]
    else:
        record = [_record_bibtex(a) for a in articoli]
    return "\n\n".join(record)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Converte il JSON di run_search/related_search in RIS o BibTeX."
    )
    parser.add_argument("--formato", required=True, choices=sorted(_FORMATI_VALIDI))
    parser.add_argument("--file", help="Legge il JSON da questo file invece che da stdin")
    args = parser.parse_args(argv)

    try:
        testo = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
        dati = json.loads(testo)
        if not isinstance(dati, dict):
            raise ValueError(f"Il JSON deve essere un oggetto, non {type(dati).__name__}")
        risultato = esporta(dati, args.formato)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        scrivi_errore(exc)
        return 1

    sys.stdout.write(risultato + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Eseguire i test e verificarne il successo**

Run: `PYTHONPATH=src python -m pytest tests/test_export_results.py -v`
Expected: PASS tutti.

- [ ] **Step 5: Verificare l'intera suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Prova manuale end-to-end (facoltativa, non bloccante)**

Run:
```bash
PYTHONPATH=src python -m run_search --term '"melanoma"[tiab]' --retmax 3 | PYTHONPATH=src python -m export_results --formato ris
```
Expected: output RIS leggibile per i 3 articoli reali, nessun errore. Se questo comando fallisce mentre i test unitari passano, indica un problema di integrazione fra il formato reale prodotto da `run_search` e quello assunto dai test (es. un campo mancante non coperto dalle fixture di test) — annotarlo come concern nel report del task, non correggere i test per farlo sparire.

- [ ] **Step 7: Commit**

```bash
git add src/export_results.py tests/test_export_results.py
git commit -m "feat: export_results, esportazione RIS/BibTeX dei risultati"
```

---

## Task 5: Skill `/pubmed-search` — paginazione ed export

**Files:**
- Modify: `.claude/skills/pubmed-search/SKILL.md`

**Interfaces:**
- Consumes: `--retstart` (Task 2), `export_results` (Task 4).
- Produces: nessuna API — solo istruzioni per Claude.

- [ ] **Step 1: Aggiungere l'istruzione di paginazione**

In `.claude/skills/pubmed-search/SKILL.md`, nella sezione `### 6. Presenta i risultati`, dopo il paragrafo che gestisce `total_count` pari a 0, aggiungere:

```markdown
Se `total_count` è maggiore del numero di articoli mostrati (limite `retmax`/`max`),
dillo esplicitamente e offri di vedere altri risultati con `--retstart <N>` (dove `N`
è il numero di articoli già mostrati), riusando la stessa query. Esempio:
`PYTHONPATH=src python -m run_search --term "<query>" --retmax 30 --retstart 30` per
la pagina successiva.
```

- [ ] **Step 2: Aggiungere l'istruzione di export**

Nella stessa sezione, subito dopo il paragrafo appena aggiunto, aggiungere:

```markdown
Se l'utente chiede di esportare i risultati (per Zotero, Mendeley, EndNote, o un
documento LaTeX), usa `export_results` sul JSON già ottenuto:

```bash
PYTHONPATH=src python -m run_search --term "<query>" --retmax 30 | PYTHONPATH=src python -m export_results --formato ris > risultati.ris
```

`--formato` accetta `ris` (reference manager) o `bibtex` (LaTeX). Funziona identico
sull'output di `related_search`.
```

- [ ] **Step 3: Verifica finale della suite**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS, interamente offline (questo task tocca solo istruzioni).

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/pubmed-search/SKILL.md
git commit -m "docs: paginazione ed export bibliografico nella skill"
```

---

## Note di verifica finale

- Il vincolo più delicato di questo piano è il Task 3: i test di hardening preesistenti su
  `run_search.py` e `nl_query_translator.py` non vanno modificati, e il loro successo dopo il
  refactor è la prova che `cli_utils` riproduce il comportamento originale byte per byte.
- `export_results.py` è deliberatamente disaccoppiato da `pubmed_client`/`pubmed_models`:
  accetta qualunque JSON con la forma giusta, non solo l'output diretto delle CLI di ricerca
  del progetto. Questo è verificato implicitamente dal fatto che i test costruiscono il JSON a
  mano, non tramite `run_search.esegui`.
