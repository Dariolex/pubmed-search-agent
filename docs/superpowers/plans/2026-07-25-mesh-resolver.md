# MeSH Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Risolvere in modo autoritativo un termine libero verso il descriptor MeSH ufficiale di NCBI (con i suoi sinonimi controllati), a sostituzione del giudizio estemporaneo di Claude nella skill `/pubmed-search`.

**Architecture:** Un nuovo metodo `PubMedClient.resolve_mesh()` (in `pubmed_client.py`) interroga `db=mesh` con un campo di match esatto sull'intestazione (`term={termine}[MeSH Terms:noexp]`), verificato dal vivo in fase di brainstorming: NCBI stesso arbitra il match (Count 0 o 1), nessuna euristica di somiglianza necessaria. Il parsing della risposta ESummary vive in `pubmed_models.py` (nuova dataclass `MeshMatch`). Una CLI sottile `mesh_resolver.py` espone il tutto alla skill, stesso pattern di `nl_query_translator`/`run_search`.

**Tech Stack:** Python 3.10+, stdlib (`argparse`, `json`, `dataclasses`), `pytest`, `responses` (già presenti). Riusa `pubmed_client.py`/`pubmed_models.py`/`pubmed_errors.py` esistenti, incluso `parse_esearch_xml` (generico sul formato ESearch, non specifico a PubMed).

## Global Constraints

- **Python 3.10+** — annotazioni `str | None`.
- **Codice e commenti in italiano**, coerentemente con i moduli esistenti.
- **`mesh_resolver.py` non fa parsing XML proprio**: delega a `pubmed_models.py`. Non contiene logica NL.
- **Import fra moduli senza prefisso di pacchetto** (`from pubmed_client import ...`), reso possibile da `pythonpath = src` in `pytest.ini` (già configurato).
- **Messaggi di errore su stderr protetti da `UnicodeEncodeError`**: usare `sys.stderr.buffer.write(testo.encode(sys.stderr.encoding or "utf-8", errors="backslashreplace"))`, mai `print(..., file=sys.stderr)` diretto — lezione appresa nel piano precedente (`run_search.py`/`nl_query_translator.py` hanno dovuto essere corretti a posteriori; qui va scritto corretto dall'inizio).
- **Un errore di rete/NCBI durante `resolve_mesh` non deve interrompere il resto del flusso della skill**: la CLI restituisce exit 1 con messaggio chiaro, la skill lo tratta come "nessun match".
- **`pytest` senza argomenti resta interamente offline** — nessuna nuova chiamata di rete nei test automatici.
- **Nessuna nuova dipendenza** in `requirements.txt`.
- **Formato API verificato dal vivo** (non supposizione): `esearch.fcgi?db=mesh&term={termine}[MeSH Terms:noexp]` restituisce `Count=1` con un `<IdList><Id>` quando il termine corrisponde esattamente a un'intestazione MeSH, `Count=0` (con `<ErrorList><PhraseNotFound>`) altrimenti. `esummary.fcgi?db=mesh&id={uid}` restituisce un `<DocSum>` con `<Item Name="DS_MeshTerms" Type="List">`: il **primo** `<Item Name="string">` è il nome ufficiale del descriptor, i successivi sono gli entry term (sinonimi). Esempio reale verificato: UID `68008545` per "melanoma" → `["Melanoma", "Melanomas", "Malignant Melanoma", "Malignant Melanomas", "Melanoma, Malignant", "Melanomas, Malignant"]`.

## API dei moduli esistenti (da consumare, non modificare)

- `PubMedClient._request(endpoint: str, params: dict, *, method: str = "GET") -> str` — trasporto, retry, rate limit già gestiti.
- `parse_esearch_xml(xml: str) -> SearchResult` — **generico sul formato ESearch** (`<Count>`, `<IdList><Id>`, `<ErrorList>`): funziona identico su `db=pubmed` e `db=mesh`, riusato senza modifiche. `SearchResult.pmids` conterrà UID del database MeSH quando usato per una ricerca `db=mesh` — non PMID; va documentato nel punto d'uso, non rinominato (la funzione resta generica).
- `PubMedConfig.from_env()`, `PubMedClient(config)` — costruzione client.
- `PubMedError`, `PubMedParseError`, `PubMedHTTPError`, `PubMedAPIError` — gerarchia eccezioni esistente, da riusare (nessuna nuova eccezione necessaria).
- `_root(xml) -> ET.Element`, `_text(node) -> str` — helper di parsing già in `pubmed_models.py`.

---

## File Structure

| File | Responsabilità |
|---|---|
| `src/pubmed_models.py` | Aggiunge `MeshMatch` (dataclass) e `parse_mesh_esummary_xml` (parsing puro, nessuna rete). |
| `src/pubmed_client.py` | Aggiunge `PubMedClient.resolve_mesh()`, riusando `_request`/`parse_esearch_xml`. |
| `src/mesh_resolver.py` | Nuovo: CLI sottile, stesso pattern di `run_search.py`. |
| `tests/test_pubmed_models.py` | Test di `parse_mesh_esummary_xml` su XML fissi, poi su fixture reali. |
| `tests/test_pubmed_client.py` | Test di `resolve_mesh()` con `responses` mockato. |
| `tests/test_mesh_resolver.py` | Nuovo: test della CLI. |
| `tests/record_fixtures.py` | Estensione: registra 3 nuove fixture reali per il database MeSH. |
| `tests/test_pubmed_live.py` | Estensione: un test live di `resolve_mesh`. |
| `.claude/skills/pubmed-search/SKILL.md` | Aggiornamento: invoca `mesh_resolver` prima della fase 2. |
| `CLAUDE.md` | Aggiornamento: roadmap sezione 8, step 5 completato. |

---

## Task 1: `MeshMatch` e `parse_mesh_esummary_xml`

**Files:**
- Modify: `src/pubmed_models.py`
- Modify: `tests/test_pubmed_models.py`

**Interfaces:**
- Consumes: `_root`, `_text`, `PubMedParseError` (già in `pubmed_models.py`)
- Produces:
  - `MeshMatch(termine_originale: str, descriptor: str, entry_terms: list[str], mesh_ui: str)` — dataclass congelata
  - `parse_mesh_esummary_xml(xml: str, termine_originale: str) -> MeshMatch`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_pubmed_models.py` (e `MeshMatch, parse_mesh_esummary_xml` alla riga di import da `pubmed_models`):

```python
MESH_ESUMMARY_MATCH = """<?xml version="1.0" ?>
<eSummaryResult>
<DocSum>
	<Id>68008545</Id>
	<Item Name="DS_ScopeNote" Type="String">A malignant neoplasm derived from cells capable of forming melanin.</Item>
	<Item Name="DS_MeshTerms" Type="List">
		<Item Name="string" Type="String">Melanoma</Item>
		<Item Name="string" Type="String">Melanomas</Item>
		<Item Name="string" Type="String">Malignant Melanoma</Item>
		<Item Name="string" Type="String">Malignant Melanomas</Item>
		<Item Name="string" Type="String">Melanoma, Malignant</Item>
		<Item Name="string" Type="String">Melanomas, Malignant</Item>
	</Item>
</DocSum>
</eSummaryResult>
"""

MESH_ESUMMARY_UN_SOLO_TERMINE = """<?xml version="1.0" ?>
<eSummaryResult>
<DocSum>
	<Id>68007167</Id>
	<Item Name="DS_MeshTerms" Type="List">
		<Item Name="string" Type="String">Immunotherapy</Item>
	</Item>
</DocSum>
</eSummaryResult>
"""

MESH_ESUMMARY_SENZA_DOCSUM = """<?xml version="1.0" ?>
<eSummaryResult>
</eSummaryResult>
"""

MESH_ESUMMARY_MESHTERMS_VUOTO = """<?xml version="1.0" ?>
<eSummaryResult>
<DocSum>
	<Id>99999999</Id>
	<Item Name="DS_MeshTerms" Type="List">
	</Item>
</DocSum>
</eSummaryResult>
"""


def test_parse_mesh_esummary_descriptor_e_entry_terms():
    match = parse_mesh_esummary_xml(MESH_ESUMMARY_MATCH, "melanoma")
    assert isinstance(match, MeshMatch)
    assert match.termine_originale == "melanoma"
    assert match.descriptor == "Melanoma"
    assert match.entry_terms == [
        "Melanomas",
        "Malignant Melanoma",
        "Malignant Melanomas",
        "Melanoma, Malignant",
        "Melanomas, Malignant",
    ]
    assert match.mesh_ui == "68008545"


def test_parse_mesh_esummary_un_solo_termine_entry_terms_vuoto():
    match = parse_mesh_esummary_xml(MESH_ESUMMARY_UN_SOLO_TERMINE, "immunotherapy")
    assert match.descriptor == "Immunotherapy"
    assert match.entry_terms == []
    assert match.mesh_ui == "68007167"


def test_parse_mesh_esummary_senza_docsum_solleva_parse_error():
    with pytest.raises(PubMedParseError, match="DocSum"):
        parse_mesh_esummary_xml(MESH_ESUMMARY_SENZA_DOCSUM, "x")


def test_parse_mesh_esummary_meshterms_vuoto_solleva_parse_error():
    with pytest.raises(PubMedParseError, match="DS_MeshTerms"):
        parse_mesh_esummary_xml(MESH_ESUMMARY_MESHTERMS_VUOTO, "x")


def test_mesh_match_e_immutabile():
    match = parse_mesh_esummary_xml(MESH_ESUMMARY_MATCH, "melanoma")
    with pytest.raises(Exception):
        match.descriptor = "altro"
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_pubmed_models.py -k mesh_esummary -v`
Expected: FAIL — `ImportError: cannot import name 'MeshMatch' from 'pubmed_models'`

- [ ] **Step 3: Implementare in `src/pubmed_models.py`**

Aggiungere in fondo al file:

```python
@dataclass(frozen=True)
class MeshMatch:
    """Esito di una risoluzione verso il vocabolario MeSH controllato di NCBI.

    `descriptor` è il nome ufficiale dell'intestazione MeSH (il primo elemento di
    <DS_MeshTerms>); `entry_terms` sono i sinonimi ufficiali (gli elementi
    successivi) — non gli stessi sinonimi che Claude estrae nella fase 1, ma quelli
    riconosciuti dal vocabolario controllato.
    """

    termine_originale: str
    descriptor: str
    entry_terms: list[str]
    mesh_ui: str


def parse_mesh_esummary_xml(xml: str, termine_originale: str) -> MeshMatch:
    """Risposta ESummary di db=mesh -> MeshMatch.

    `termine_originale` non compare nella risposta NCBI (è il termine cercato dal
    chiamante): va passato esplicitamente, non estratto dall'XML.
    """
    root = _root(xml)
    docsum = root.find("DocSum")
    if docsum is None:
        raise PubMedParseError("Risposta ESummary priva di <DocSum>")
    mesh_ui = _text(docsum.find("Id"))
    mesh_terms_node = next(
        (item for item in docsum.findall("Item") if item.get("Name") == "DS_MeshTerms"),
        None,
    )
    termini = [
        _text(el)
        for el in (mesh_terms_node.findall("Item") if mesh_terms_node is not None else [])
    ]
    termini = [t for t in termini if t]
    if not termini:
        raise PubMedParseError(f"DS_MeshTerms vuoto o assente per UID {mesh_ui!r}")
    return MeshMatch(
        termine_originale=termine_originale,
        descriptor=termini[0],
        entry_terms=termini[1:],
        mesh_ui=mesh_ui,
    )
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_pubmed_models.py -k mesh_esummary -v`
Expected: PASS — 5 test superati

- [ ] **Step 5: Eseguire l'intera suite del modulo (nessuna regressione)**

Run: `pytest tests/test_pubmed_models.py -v`
Expected: PASS — tutti i test precedenti + i 5 nuovi

- [ ] **Step 6: Commit**

```bash
git add src/pubmed_models.py tests/test_pubmed_models.py
git commit -m "feat: MeshMatch e parsing ESummary del database MeSH"
```

---

## Task 2: `PubMedClient.resolve_mesh()`

**Files:**
- Modify: `src/pubmed_client.py`
- Modify: `tests/test_pubmed_client.py`

**Interfaces:**
- Consumes: `PubMedClient._request` (esistente), `parse_esearch_xml` (esistente, generico), `parse_mesh_esummary_xml`/`MeshMatch` (Task 1)
- Produces: `PubMedClient.resolve_mesh(termine: str) -> MeshMatch | None`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_pubmed_client.py` (e `MeshMatch` alla riga di import da `pubmed_models` se non già presente; il client non deve importare `MeshMatch` direttamente per i test, ma il test file sì per asserire sul tipo):

```python
MESH_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
MESH_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

MESH_ESEARCH_MATCH = """<?xml version="1.0" ?>
<eSearchResult><Count>1</Count><RetMax>1</RetMax><RetStart>0</RetStart>
<IdList><Id>68008545</Id></IdList></eSearchResult>
"""

MESH_ESEARCH_NO_MATCH = """<?xml version="1.0" ?>
<eSearchResult><Count>0</Count><RetMax>0</RetMax><RetStart>0</RetStart>
<IdList/><ErrorList><PhraseNotFound>xyz[MeSH Terms:noexp]</PhraseNotFound></ErrorList>
</eSearchResult>
"""

MESH_ESUMMARY_MELANOMA = """<?xml version="1.0" ?>
<eSummaryResult><DocSum><Id>68008545</Id>
<Item Name="DS_MeshTerms" Type="List">
	<Item Name="string" Type="String">Melanoma</Item>
	<Item Name="string" Type="String">Melanomas</Item>
</Item>
</DocSum></eSummaryResult>
"""


@responses.activate
def test_resolve_mesh_trova_match(client):
    responses.add(responses.GET, MESH_SEARCH_URL, body=MESH_ESEARCH_MATCH, status=200)
    responses.add(responses.GET, MESH_SUMMARY_URL, body=MESH_ESUMMARY_MELANOMA, status=200)
    match = client.resolve_mesh("melanoma")
    assert match is not None
    assert match.descriptor == "Melanoma"
    assert match.entry_terms == ["Melanomas"]
    assert match.mesh_ui == "68008545"
    assert match.termine_originale == "melanoma"


@responses.activate
def test_resolve_mesh_invia_il_tag_di_campo_esatto(client):
    responses.add(responses.GET, MESH_SEARCH_URL, body=MESH_ESEARCH_MATCH, status=200)
    responses.add(responses.GET, MESH_SUMMARY_URL, body=MESH_ESUMMARY_MELANOMA, status=200)
    client.resolve_mesh("melanoma")
    inviata = responses.calls[0].request
    assert "db=mesh" in inviata.url
    assert "MeSH+Terms%3Anoexp" in inviata.url or "MeSH%20Terms%3Anoexp" in inviata.url


@responses.activate
def test_resolve_mesh_nessun_match_restituisce_none_senza_seconda_chiamata(client):
    responses.add(responses.GET, MESH_SEARCH_URL, body=MESH_ESEARCH_NO_MATCH, status=200)
    match = client.resolve_mesh("xyznonesiste")
    assert match is None
    assert len(responses.calls) == 1  # nessuna chiamata a esummary se non c'è UID


@responses.activate
def test_resolve_mesh_propaga_errore_di_rete(client):
    for _ in range(3):
        responses.add(responses.GET, MESH_SEARCH_URL, status=500)
    with pytest.raises(PubMedHTTPError):
        client.resolve_mesh("melanoma")
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_pubmed_client.py -k resolve_mesh -v`
Expected: FAIL — `AttributeError: 'PubMedClient' object has no attribute 'resolve_mesh'`

- [ ] **Step 3: Implementare in `src/pubmed_client.py`**

Modificare la riga di import esistente da `pubmed_models` per includere le nuove funzioni:

```python
from pubmed_models import (
    Article,
    MeshMatch,
    SearchResult,
    find_api_error,
    parse_efetch_xml,
    parse_esearch_xml,
    parse_mesh_esummary_xml,
)
```

Aggiungere come metodo di `PubMedClient`, dopo `efetch`:

```python
    def resolve_mesh(self, termine: str) -> MeshMatch | None:
        """Risolve un termine libero verso il descriptor MeSH ufficiale, se esiste
        un match esatto sull'intestazione.

        Usa `term={termine}[MeSH Terms:noexp]` su db=mesh: verificato dal vivo,
        questo campo restituisce Count=1 con l'UID corretto quando il termine
        corrisponde esattamente a un'intestazione MeSH ufficiale (case-insensitive),
        Count=0 altrimenti — NCBI stesso arbitra il match, nessuna euristica di
        somiglianza necessaria qui.

        `parse_esearch_xml` è generico sul formato ESearch: `SearchResult.pmids`
        conterrà qui UID del database MeSH, non PMID.
        """
        xml_ricerca = self._request(
            "esearch.fcgi",
            {"db": "mesh", "term": f"{termine}[MeSH Terms:noexp]", "retmode": "xml"},
        )
        ricerca = parse_esearch_xml(xml_ricerca)
        if not ricerca.pmids:
            return None
        uid = ricerca.pmids[0]
        xml_dettaglio = self._request(
            "esummary.fcgi", {"db": "mesh", "id": uid, "retmode": "xml"}
        )
        return parse_mesh_esummary_xml(xml_dettaglio, termine)
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_pubmed_client.py -k resolve_mesh -v`
Expected: PASS — 4 test superati

- [ ] **Step 5: Eseguire l'intera suite offline**

Run: `pytest`
Expected: PASS, nessuna regressione, nessuna chiamata di rete

- [ ] **Step 6: Commit**

```bash
git add src/pubmed_client.py tests/test_pubmed_client.py
git commit -m "feat: PubMedClient.resolve_mesh, risoluzione verso il vocabolario MeSH"
```

---

## Task 3: CLI `mesh_resolver.py`

**Files:**
- Create: `src/mesh_resolver.py` (sostituisce il placeholder attuale, solo docstring)
- Create: `tests/test_mesh_resolver.py`

**Interfaces:**
- Consumes: `PubMedClient.resolve_mesh`, `PubMedConfig` (Task 2), `PubMedError` (esistente)
- Produces: `main(argv=None) -> int`

- [ ] **Step 1: Scrivere i test che falliscono**

File `tests/test_mesh_resolver.py`:

```python
"""Test della CLI mesh_resolver: successo, nessun match, errore. HTTP mockato."""

import json

import pytest
import responses

from mesh_resolver import main
from pubmed_client import PubMedClient, PubMedConfig, RateLimiter

MESH_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
MESH_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

MESH_ESEARCH_MATCH = """<?xml version="1.0" ?>
<eSearchResult><Count>1</Count><IdList><Id>68008545</Id></IdList></eSearchResult>
"""
MESH_ESEARCH_NO_MATCH = """<?xml version="1.0" ?>
<eSearchResult><Count>0</Count><IdList/></eSearchResult>
"""
MESH_ESUMMARY_MELANOMA = """<?xml version="1.0" ?>
<eSummaryResult><DocSum><Id>68008545</Id>
<Item Name="DS_MeshTerms" Type="List">
	<Item Name="string" Type="String">Melanoma</Item>
	<Item Name="string" Type="String">Melanomas</Item>
</Item>
</DocSum></eSummaryResult>
"""


class OrologioFinto:
    def __init__(self):
        self.adesso = 0.0

    def time(self):
        return self.adesso

    def sleep(self, secondi):
        self.adesso += secondi


@pytest.fixture
def client_finto(monkeypatch):
    orologio = OrologioFinto()
    client = PubMedClient(
        PubMedConfig(tool="test", email="test@example.org", api_key="chiave-finta"),
        rate_limiter=RateLimiter(clock=orologio.time, sleep=orologio.sleep),
        sleep=orologio.sleep,
    )
    monkeypatch.setattr("mesh_resolver.PubMedConfig.from_env", lambda: client._config)
    monkeypatch.setattr("mesh_resolver.PubMedClient", lambda config: client)
    return client


@responses.activate
def test_main_match_trovato_stampa_json(client_finto, capsys):
    responses.add(responses.GET, MESH_SEARCH_URL, body=MESH_ESEARCH_MATCH, status=200)
    responses.add(responses.GET, MESH_SUMMARY_URL, body=MESH_ESUMMARY_MELANOMA, status=200)
    codice = main(argv=["--termine", "melanoma"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert dati["descriptor"] == "Melanoma"
    assert dati["entry_terms"] == ["Melanomas"]
    assert dati["mesh_ui"] == "68008545"
    assert dati["termine_originale"] == "melanoma"


@responses.activate
def test_main_nessun_match_esce_zero_con_descriptor_null(client_finto, capsys):
    responses.add(responses.GET, MESH_SEARCH_URL, body=MESH_ESEARCH_NO_MATCH, status=200)
    codice = main(argv=["--termine", "xyznonesiste"])
    out = capsys.readouterr()
    assert codice == 0
    dati = json.loads(out.out)
    assert dati["descriptor"] is None
    assert dati["entry_terms"] == []
    assert dati["mesh_ui"] is None
    assert dati["termine_originale"] == "xyznonesiste"


@responses.activate
def test_main_errore_di_rete_esce_uno_su_stderr(client_finto, capsys):
    for _ in range(3):
        responses.add(responses.GET, MESH_SEARCH_URL, status=500)
    codice = main(argv=["--termine", "melanoma"])
    out = capsys.readouterr()
    assert codice == 1
    assert out.out == ""
    assert "Errore" in out.err
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_mesh_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesh_resolver'` (o il modulo esiste solo come docstring placeholder senza `main`)

- [ ] **Step 3: Implementare `src/mesh_resolver.py`**

Sostituire integralmente il contenuto attuale (solo docstring segnaposto):

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
        # Il messaggio puo' incorporare testo grezzo di NCBI: encoding robusto per
        # evitare UnicodeEncodeError su console Windows con encoding restrittivo.
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

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_mesh_resolver.py -v`
Expected: PASS — 3 test superati

- [ ] **Step 5: Eseguire l'intera suite offline**

Run: `pytest`
Expected: PASS, nessuna regressione

- [ ] **Step 6: Verifica manuale della CLI**

Run: `PYTHONPATH=src python -m mesh_resolver --termine "xyznonesiste12345"`
Expected: JSON con `"descriptor": null`, exit 0 (richiede una `.env` valida)

- [ ] **Step 7: Commit**

```bash
git add src/mesh_resolver.py tests/test_mesh_resolver.py
git commit -m "feat: CLI mesh_resolver, risoluzione MeSH per la skill"
```

---

## Task 4: Fixture reali e test contro l'API vera

**Files:**
- Modify: `tests/record_fixtures.py`
- Create: `tests/fixtures/mesh_esearch_match.xml`, `tests/fixtures/mesh_esearch_no_match.xml`, `tests/fixtures/mesh_esummary_match.xml` (generati dallo script)
- Modify: `tests/test_pubmed_models.py`, `tests/test_pubmed_client.py`

**Interfaces:**
- Consumes: `PubMedClient._request`, `PubMedConfig` (esistenti)
- Produces: tre nuove fixture XML, consumate dai test aggiunti in questo task

**Questo task richiede rete e una `.env` valida.**

- [ ] **Step 1: Estendere `tests/record_fixtures.py`**

Aggiungere in fondo alla funzione `main()`, prima di `if not tutto_ok:`:

```python
    print("mesh_esearch_match.xml — match esatto su db=mesh (melanoma)")
    xml = client._request(
        "esearch.fcgi",
        {"db": "mesh", "term": "melanoma[MeSH Terms:noexp]", "retmode": "xml"},
    )
    tutto_ok &= _verifica("mesh_esearch_match", "<Count>1</Count>" in xml, "Count vale 1")
    _scrivi("mesh_esearch_match.xml", xml, chiave)

    print("mesh_esearch_no_match.xml — nessun match su db=mesh")
    xml = client._request(
        "esearch.fcgi",
        {"db": "mesh", "term": "zzzznonesistequestotermine[MeSH Terms:noexp]", "retmode": "xml"},
    )
    tutto_ok &= _verifica("mesh_esearch_no_match", "<Count>0</Count>" in xml, "Count vale 0")
    _scrivi("mesh_esearch_no_match.xml", xml, chiave)

    print("mesh_esummary_match.xml — descriptor + entry term (melanoma, UID 68008545)")
    xml = client._request(
        "esummary.fcgi", {"db": "mesh", "id": "68008545", "retmode": "xml"}
    )
    tutto_ok &= _verifica("mesh_esummary_match", "DS_MeshTerms" in xml, "contiene DS_MeshTerms")
    tutto_ok &= _verifica("mesh_esummary_match", "Melanoma" in xml, "contiene il descriptor atteso")
    _scrivi("mesh_esummary_match.xml", xml, chiave)
```

Nota: l'UID `68008545` per "melanoma" è già stato verificato dal vivo durante il
brainstorming (vedi spec `docs/superpowers/specs/2026-07-25-mesh-resolver-design.md`).
Se nel frattempo NCBI avesse rinumerato l'UID (improbabile ma non impossibile), la
verifica `_verifica("mesh_esummary_match", ...)` fallirebbe e va sostituito con l'UID
restituito dalla chiamata `mesh_esearch_match` appena registrata, seguendo lo stesso
schema già usato per gli altri PMID candidati in cima al file.

- [ ] **Step 2: Eseguire lo script**

Run: `python tests/record_fixtures.py`
Expected: tutte le verifiche `[OK  ]`, incluse le tre nuove, e in chiusura `Tutte le fixture registrate e verificate.`

Se una verifica fallisce, seguire l'istruzione di errore già presente nello script
(sostituire il valore candidato e rieseguire) — stesso comportamento già collaudato
per le fixture PubMed esistenti.

- [ ] **Step 3: Verificare che nessuna fixture contenga la chiave**

Run: `grep -l "$(grep NCBI_API_KEY .env | cut -d= -f2)" tests/fixtures/mesh_*.xml ; echo "exit=$?"`
Expected: `exit=1` (nessun file corrisponde)

- [ ] **Step 4: Scrivere i test contro le fixture reali**

Aggiungere in fondo a `tests/test_pubmed_models.py`:

```python
def test_fixture_mesh_esummary_reale():
    match = parse_mesh_esummary_xml(_fixture("mesh_esummary_match.xml"), "melanoma")
    assert match.descriptor
    assert match.mesh_ui.isdigit()
    # L'entry term "Melanomas" è tra i sinonimi ufficiali attesi per questo descriptor.
    assert any("Melanoma" in t for t in match.entry_terms) or match.descriptor == "Melanoma"
```

Aggiungere in fondo a `tests/test_pubmed_client.py`:

```python
def test_fixture_mesh_esearch_match_reale_ha_count_uno():
    xml = (FIXTURES / "mesh_esearch_match.xml").read_text(encoding="utf-8")
    ricerca = parse_esearch_xml(xml)
    assert ricerca.total_count == 1
    assert len(ricerca.pmids) == 1


def test_fixture_mesh_esearch_no_match_reale_ha_count_zero():
    xml = (FIXTURES / "mesh_esearch_no_match.xml").read_text(encoding="utf-8")
    ricerca = parse_esearch_xml(xml)
    assert ricerca.total_count == 0
    assert ricerca.pmids == []
```

(Se `FIXTURES` non è già definita in `tests/test_pubmed_client.py`, aggiungere in cima
al file: `from pathlib import Path` e `FIXTURES = Path(__file__).parent / "fixtures"`.)

- [ ] **Step 5: Eseguire l'intera suite offline**

Run: `pytest`
Expected: PASS, nessuna chiamata di rete nei test automatici (le fixture sono lette da disco)

- [ ] **Step 6: Commit**

```bash
git add tests/record_fixtures.py tests/fixtures/mesh_esearch_match.xml tests/fixtures/mesh_esearch_no_match.xml tests/fixtures/mesh_esummary_match.xml tests/test_pubmed_models.py tests/test_pubmed_client.py
git commit -m "test: fixture reali del database MeSH e verifica contro dati autentici"
```

---

## Task 5: Test live

**Files:**
- Modify: `tests/test_pubmed_live.py`

**Interfaces:**
- Consumes: `PubMedClient.resolve_mesh` (Task 2)
- Produces: nessuna nuova API

- [ ] **Step 1: Aggiungere il test live**

Aggiungere in fondo a `tests/test_pubmed_live.py` (il file ha già `pytestmark = pytest.mark.live` e una fixture `client` — riusarla):

```python
def test_resolve_mesh_reale_trova_melanoma(client):
    match = client.resolve_mesh("melanoma")
    assert match is not None
    assert match.descriptor == "Melanoma"
    assert len(match.entry_terms) > 0
    assert match.mesh_ui.isdigit()


def test_resolve_mesh_reale_nessun_match_per_termine_inventato(client):
    match = client.resolve_mesh("zzzznonesistequestotermine12345")
    assert match is None
```

- [ ] **Step 2: Eseguire i test live**

Run: `pytest -m live -v`
Expected: PASS — includendo i 2 nuovi test (richiede `.env` valida)

- [ ] **Step 3: Verificare che restino esclusi di default**

Run: `pytest -v`
Expected: i nuovi test risultano deselezionati insieme agli altri test live

- [ ] **Step 4: Commit**

```bash
git add tests/test_pubmed_live.py
git commit -m "test: verifica live di resolve_mesh contro l'API MeSH reale"
```

---

## Task 6: Aggiornare la skill e `CLAUDE.md`

**Files:**
- Modify: `.claude/skills/pubmed-search/SKILL.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `python -m mesh_resolver` (Task 3)
- Produces: nessuna API di codice

- [ ] **Step 1: Aggiornare la sezione "1. Estrai il JSON intermedio" della skill**

In `.claude/skills/pubmed-search/SKILL.md`, sostituire la riga sul campo `mesh` nelle
linee guida per l'estrazione:

```
- **Concetti**: i nuclei clinici/scientifici della richiesta. Aggiungi `sinonimi`
  utili (varianti terminologiche, non traduzioni). Per il campo `mesh`, se hai un
  candidato plausibile (es. `melanoma`), non limitarti al tuo giudizio: verificalo
  con il resolver (vedi sotto) prima di popolarlo nel JSON finale.
```

- [ ] **Step 2: Aggiungere una nuova sotto-sezione dopo "1. Estrai il JSON intermedio dalla richiesta"**

Inserire prima di "### 2. Genera la query PubMed (fase deterministica)":

```markdown
### 1bis. Verifica i termini MeSH candidati (opzionale, per concetto)

Per ogni concetto con un candidato MeSH plausibile, verifica il termine ufficiale
prima di scrivere il JSON finale:

```bash
PYTHONPATH=src python -m mesh_resolver --termine "melanoma"
```

Restituisce JSON con `descriptor` (il nome ufficiale, o `null` se nessun match
esatto) ed `entry_terms` (sinonimi ufficiali del vocabolario MeSH). Se `descriptor`
non è `null`, usalo come valore di `mesh` nel JSON del concetto e valuta se
aggiungere gli `entry_terms` più pertinenti a `sinonimi`. Se `descriptor` è `null`
o il comando esce con errore, lascia `mesh: null` per quel concetto — è lo stesso
comportamento di oggi, nessuna interruzione del flusso.

Questo passo è opzionale ma consigliato quando un concetto ha un candidato MeSH
plausibile: sostituisce il giudizio estemporaneo con una verifica autoritativa
contro il vocabolario controllato di NCBI.
```

- [ ] **Step 3: Verificare che il file resti Markdown valido**

Run: `PYTHONPATH=src python -c "import re; content=open('.claude/skills/pubmed-search/SKILL.md', encoding='utf-8').read(); assert content.count('\`\`\`') % 2 == 0, 'code fence non bilanciato'"`
Expected: nessun errore (i blocchi di codice sono bilanciati)

- [ ] **Step 4: Aggiornare `CLAUDE.md` sezione 8 (roadmap)**

Sostituire il punto 5 con:

```
5. ~~`mesh_resolver.py` — risoluzione autoritativa verso il vocabolario MeSH
   controllato di NCBI (`PubMedClient.resolve_mesh`, `db=mesh`), invocata dalla
   skill `/pubmed-search` prima della serializzazione~~ **(completato)**
```

- [ ] **Step 5: Aggiungere `mesh_resolver.py` all'albero dei file, sezione 3**

Nel blocco `src/`, dopo `run_search.py`, aggiungere:

```
│   ├── mesh_resolver.py       # risoluzione NL -> descriptor MeSH ufficiale (db=mesh)
```

- [ ] **Step 6: Eseguire l'intera suite offline**

Run: `pytest`
Expected: PASS, nessuna regressione

- [ ] **Step 7: Prova d'uso reale end-to-end**

Con una `.env` valida, dalla radice del progetto:

```bash
PYTHONPATH=src python -m mesh_resolver --termine "melanoma"
PYTHONPATH=src python -m mesh_resolver --termine "zzzznonesistequestotermine12345"
```

Expected: il primo comando stampa `"descriptor": "Melanoma"` con gli entry term
attesi; il secondo stampa `"descriptor": null`. Entrambi exit 0.

- [ ] **Step 8: Commit**

```bash
git add .claude/skills/pubmed-search/SKILL.md CLAUDE.md
git commit -m "docs: integra mesh_resolver nella skill, aggiorna roadmap (step 5 completato)"
```

---

## Criteri di completamento

- [ ] `PubMedClient.resolve_mesh("melanoma")` restituisce un `MeshMatch` con
      descriptor `"Melanoma"` ed entry term corretti, verificato contro l'API reale
- [ ] Un termine senza match esatto restituisce `None`, non solleva eccezione, e non
      effettua una seconda chiamata HTTP inutile
- [ ] `python -m mesh_resolver --termine "..."` produce il contratto di output
      descritto (successo/nessun match/errore), con encoding stderr protetto da subito
- [ ] Un errore di rete durante la risoluzione non interrompe il resto della suite
      (verificato con la skill aggiornata tramite prova d'uso reale)
- [ ] `pytest` passa interamente offline; `pytest -m live` passa contro NCBI
- [ ] Le tre nuove fixture sono registrate, versionate e prive di `api_key`
- [ ] `.claude/skills/pubmed-search/SKILL.md` invoca `mesh_resolver` prima della fase 2
- [ ] `CLAUDE.md` riflette `mesh_resolver.py` e la roadmap aggiornata
