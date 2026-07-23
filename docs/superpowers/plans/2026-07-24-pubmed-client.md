# PubMed Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire il wrapper E-utilities di NCBI che restituisce dataclass tipizzate, rispetta il limite di 10 richieste/secondo e distingue gli errori NCBI dai risultati vuoti.

**Architecture:** Due moduli. `src/pubmed_models.py` contiene dataclass e funzioni di parsing pure, senza alcuna dipendenza da rete: si testa passando stringhe XML. `src/pubmed_client.py` contiene configurazione, token bucket, retry e trasporto HTTP. `src/pubmed_errors.py` ospita la gerarchia di eccezioni condivisa dai due (vedi Scoperta 1). Il chiamante non vede mai XML.

**Tech Stack:** Python 3.10+, `requests`, `xml.etree.ElementTree` (stdlib), `pytest`, `responses`, `python-dotenv`.

## Scoperte durante la pianificazione

Tre correzioni alla spec `docs/superpowers/specs/2026-07-24-pubmed-client-design.md`, applicate in questo piano:

1. **Serve un terzo modulo `src/pubmed_errors.py`.** La spec colloca la gerarchia di eccezioni in `pubmed_client.py`, ma `pubmed_models.py` deve sollevare `PubMedParseError` e `pubmed_client.py` importa `pubmed_models`: metterle nel client crea un import circolare. Il file è ~25 righe e non dipende da nulla.

2. **`<ErrorList>` NON è un errore fatale — la spec sbagliava.** ESearch restituisce `<ErrorList><PhraseNotFound>...</PhraseNotFound></ErrorList>` quando un termine non trova corrispondenze, ma **la ricerca è comunque riuscita**. Trattarlo come fatale farebbe fallire query legittime. Solo l'elemento `<ERROR>` è un errore vero.

3. **`SearchResult` acquisisce un campo `warnings: list[str]`.** Diretta conseguenza della Scoperta 2: i `PhraseNotFound` dicono *quale* termine non ha trovato nulla, che è esattamente la diagnostica di cui la spec parla a proposito di `Count=0`. Costa ~5 righe. Se vuoi tagliarlo, rimuovi il campo e i due test che lo coprono nel Task 2.

## Global Constraints

- **Python 3.10+** — la sintassi `str | None` nelle annotazioni è usata ovunque.
- **`api_key` solo da variabile d'ambiente.** Mai hardcoded, mai in un log, mai in `__repr__`, mai in un messaggio di eccezione, mai in un file dentro `tests/fixtures/`.
- **Nessuna eccezione di `requests` deve propagare al chiamante.** Le eccezioni di `requests` contengono l'URL completo, che per le GET include `api_key=...`. Ogni `raise` da un blocco `except requests.RequestException` usa `from None` e non interpola mai `str(exc)` né `resp.url`.
- **`pytest` senza argomenti non deve toccare la rete.** I test live sono esclusi di default.
- **Il codice e i commenti sono in italiano**, coerentemente con `CLAUDE.md` e con i docstring già presenti in `src/`.
- **Ogni richiesta a NCBI include `tool`, `email`, `api_key`.**
- **Import fra moduli senza prefisso di pacchetto**: `from pubmed_models import Article`, reso possibile da `pythonpath = src` in `pytest.ini`.

---

## File Structure

| File | Responsabilità |
|---|---|
| `src/pubmed_errors.py` | Gerarchia di eccezioni. Nessuna dipendenza. |
| `src/pubmed_models.py` | Dataclass `SearchResult`/`Article` e parsing XML puro. Dipende solo da `pubmed_errors`. |
| `src/pubmed_client.py` | `PubMedConfig`, `RateLimiter`, `PubMedClient`, `pubmed_web_url`. Dipende da `pubmed_errors`, `pubmed_models`, `requests`. |
| `tests/test_pubmed_models.py` | Parsing su XML inline e su fixture registrate. |
| `tests/test_pubmed_client.py` | Config, rate limiter, retry, errori, batching. Mock via `responses`. |
| `tests/test_pubmed_live.py` | Test marcati `live`, esclusi di default. |
| `tests/record_fixtures.py` | Script che registra risposte NCBI reali in `tests/fixtures/`. |
| `pytest.ini` | `pythonpath`, marker `live`, esclusione di default. |

---

## Task 1: Scaffolding e gerarchia di eccezioni

**Files:**
- Create: `pytest.ini`
- Create: `src/pubmed_errors.py`
- Create: `tests/test_pubmed_errors.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nulla (primo task)
- Produces: `PubMedError`, `PubMedConfigError`, `PubMedAPIError`, `PubMedHTTPError`, `PubMedParseError` — tutte importabili da `pubmed_errors`. Ogni task successivo le importa da qui.

- [ ] **Step 1: Aggiornare `requirements.txt`**

```
requests
python-dotenv
pytest>=7.0
responses
```

(`pytest>=7.0` perché l'opzione `pythonpath` in `pytest.ini` esiste solo da lì. `responses` serve per i mock HTTP.)

- [ ] **Step 2: Creare `pytest.ini`**

```ini
[pytest]
pythonpath = src
testpaths = tests
addopts = -m "not live"
markers =
    live: esegue chiamate reali alle API NCBI; escluso di default, si attiva con `pytest -m live`
```

`pythonpath = src` rende i moduli importabili come `pubmed_errors`, `pubmed_models`, `pubmed_client` senza `__init__.py`. `addopts` viene applicato prima degli argomenti da riga di comando, quindi `pytest -m live` sovrascrive l'esclusione.

- [ ] **Step 3: Scrivere il test che fallisce**

File `tests/test_pubmed_errors.py`:

```python
"""Verifica che la gerarchia di eccezioni permetta di catturare tutto con un solo except."""

import pytest

from pubmed_errors import (
    PubMedAPIError,
    PubMedConfigError,
    PubMedError,
    PubMedHTTPError,
    PubMedParseError,
)


@pytest.mark.parametrize(
    "exc_type",
    [PubMedConfigError, PubMedAPIError, PubMedHTTPError, PubMedParseError],
)
def test_ogni_eccezione_deriva_da_pubmed_error(exc_type):
    assert issubclass(exc_type, PubMedError)


def test_pubmed_error_cattura_le_sottoclassi():
    with pytest.raises(PubMedError):
        raise PubMedAPIError("query malformata")


def test_il_messaggio_e_preservato():
    with pytest.raises(PubMedHTTPError, match="HTTP 503"):
        raise PubMedHTTPError("esearch.fcgi: HTTP 503")
```

- [ ] **Step 4: Eseguire il test e verificare che fallisca**

Run: `pytest tests/test_pubmed_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pubmed_errors'`

- [ ] **Step 5: Implementare `src/pubmed_errors.py`**

```python
"""
pubmed_errors.py

Gerarchia di eccezioni condivisa da pubmed_models.py e pubmed_client.py.

Vive in un modulo proprio perché il parser (pubmed_models) deve poter sollevare
PubMedParseError e il client importa il parser: definirle nel client creerebbe un
import circolare.
"""


class PubMedError(Exception):
    """Base di tutti gli errori del client PubMed."""


class PubMedConfigError(PubMedError):
    """Variabili d'ambiente mancanti o non valide. Sollevata all'avvio."""


class PubMedAPIError(PubMedError):
    """NCBI ha risposto HTTP 200 con un <ERROR> nel corpo (tipicamente query malformata).

    Non è ritentabile: ripetere la stessa query produce lo stesso errore.
    """


class PubMedHTTPError(PubMedError):
    """Errore di trasporto non recuperato dopo tutti i tentativi.

    Il messaggio non contiene mai l'URL: per le richieste GET includerebbe api_key.
    """


class PubMedParseError(PubMedError):
    """XML sintatticamente valido ma con una struttura inattesa."""
```

- [ ] **Step 6: Eseguire il test e verificare che passi**

Run: `pytest tests/test_pubmed_errors.py -v`
Expected: PASS — 6 test superati (4 parametrizzati + 2)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini src/pubmed_errors.py tests/test_pubmed_errors.py
git commit -m "feat: gerarchia eccezioni PubMed e configurazione pytest"
```

---

## Task 2: `SearchResult` e `parse_esearch_xml`

**Files:**
- Create: `src/pubmed_models.py`
- Create: `tests/test_pubmed_models.py`

**Interfaces:**
- Consumes: `PubMedParseError` da `pubmed_errors` (Task 1)
- Produces:
  - `SearchResult(pmids: list[str], total_count: int, translated_query: str | None, webenv: str | None, query_key: str | None, warnings: list[str])` — dataclass congelata
  - `parse_esearch_xml(xml: str) -> SearchResult`
  - `find_api_error(xml: str) -> str | None` — usata dal client nel Task 7

- [ ] **Step 1: Scrivere i test che falliscono**

File `tests/test_pubmed_models.py`:

```python
"""Test di parsing puro: nessuna rete, nessun mock, solo stringhe XML."""

import pytest

from pubmed_errors import PubMedParseError
from pubmed_models import SearchResult, find_api_error, parse_esearch_xml

ESEARCH_BASE = """<?xml version="1.0" encoding="UTF-8" ?>
<eSearchResult>
  <Count>1234</Count>
  <RetMax>2</RetMax>
  <RetStart>0</RetStart>
  <QueryKey>1</QueryKey>
  <WebEnv>MCID_abc123def</WebEnv>
  <IdList>
    <Id>38000001</Id>
    <Id>38000002</Id>
  </IdList>
  <QueryTranslation>"melanoma"[MeSH Terms] OR "melanoma"[All Fields]</QueryTranslation>
</eSearchResult>
"""

ESEARCH_ZERO = """<?xml version="1.0" encoding="UTF-8" ?>
<eSearchResult>
  <Count>0</Count>
  <RetMax>0</RetMax>
  <RetStart>0</RetStart>
  <IdList/>
  <QueryTranslation>"zzzznonesiste"[All Fields]</QueryTranslation>
</eSearchResult>
"""

ESEARCH_PHRASE_NOT_FOUND = """<?xml version="1.0" encoding="UTF-8" ?>
<eSearchResult>
  <Count>7</Count>
  <IdList><Id>38000003</Id></IdList>
  <ErrorList>
    <PhraseNotFound>immunoterapia</PhraseNotFound>
    <FieldNotFound>xyz</FieldNotFound>
  </ErrorList>
  <QueryTranslation>melanoma[All Fields]</QueryTranslation>
</eSearchResult>
"""

ESEARCH_HARD_ERROR = """<?xml version="1.0" encoding="UTF-8" ?>
<eSearchResult>
  <ERROR>Can't run executor</ERROR>
</eSearchResult>
"""

EFETCH_ROOT_ERROR = """<?xml version="1.0" encoding="UTF-8" ?>
<ERROR>Empty id list; nothing todo</ERROR>
"""


def test_parsing_nominale():
    result = parse_esearch_xml(ESEARCH_BASE)
    assert isinstance(result, SearchResult)
    assert result.pmids == ["38000001", "38000002"]
    assert result.total_count == 1234
    assert result.webenv == "MCID_abc123def"
    assert result.query_key == "1"
    assert result.translated_query == '"melanoma"[MeSH Terms] OR "melanoma"[All Fields]'
    assert result.warnings == []


def test_zero_risultati_non_e_un_errore():
    result = parse_esearch_xml(ESEARCH_ZERO)
    assert result.total_count == 0
    assert result.pmids == []
    assert result.translated_query == '"zzzznonesiste"[All Fields]'


def test_phrase_not_found_e_un_avviso_non_un_errore():
    result = parse_esearch_xml(ESEARCH_PHRASE_NOT_FOUND)
    assert result.total_count == 7
    assert result.pmids == ["38000003"]
    assert result.warnings == ["PhraseNotFound: immunoterapia", "FieldNotFound: xyz"]


def test_find_api_error_rileva_error_annidato():
    assert find_api_error(ESEARCH_HARD_ERROR) == "Can't run executor"


def test_find_api_error_rileva_error_come_radice():
    assert find_api_error(EFETCH_ROOT_ERROR) == "Empty id list; nothing todo"


def test_find_api_error_ignora_error_list():
    assert find_api_error(ESEARCH_PHRASE_NOT_FOUND) is None


def test_find_api_error_su_risposta_valida():
    assert find_api_error(ESEARCH_BASE) is None


def test_xml_non_valido_solleva_parse_error():
    with pytest.raises(PubMedParseError):
        parse_esearch_xml("<eSearchResult><Count>3</Count>")


def test_esearch_senza_count_solleva_parse_error():
    with pytest.raises(PubMedParseError, match="Count"):
        parse_esearch_xml("<eSearchResult><IdList/></eSearchResult>")


def test_search_result_e_immutabile():
    result = parse_esearch_xml(ESEARCH_BASE)
    with pytest.raises(Exception):
        result.total_count = 99
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_pubmed_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pubmed_models'`

- [ ] **Step 3: Implementare la parte ESearch di `src/pubmed_models.py`**

```python
"""
pubmed_models.py

Dataclass e parsing delle risposte XML di NCBI E-utilities.

Non effettua alcuna chiamata di rete: ogni funzione riceve una stringa XML e
restituisce dati tipizzati. È il modulo con la maggiore superficie di test del
progetto, ed è testabile senza mock.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from pubmed_errors import PubMedParseError


@dataclass(frozen=True)
class SearchResult:
    """Esito di una ESearch.

    `total_count` è il numero di match reali su PubMed, che può essere molto
    maggiore di `len(pmids)`: quest'ultimo è limitato da `retmax`.

    `translated_query` è il campo <QueryTranslation>: NCBI applica l'automatic
    term mapping, quindi la query eseguita non coincide con quella inviata.

    `warnings` raccoglie i figli di <ErrorList> (PhraseNotFound, FieldNotFound).
    Sono diagnostici, non errori: la ricerca è riuscita comunque.
    """

    pmids: list[str] = field(default_factory=list)
    total_count: int = 0
    translated_query: str | None = None
    webenv: str | None = None
    query_key: str | None = None
    warnings: list[str] = field(default_factory=list)


def _root(xml: str) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as exc:
        raise PubMedParseError(f"Risposta non è XML valido: {exc}") from exc


def _text(node: ET.Element | None) -> str:
    """Testo completo di un nodo, inclusi i figli inline (<i>, <sub>, ...)."""
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def find_api_error(xml: str) -> str | None:
    """Restituisce il messaggio di un <ERROR> di NCBI, o None se non c'è.

    Attenzione: <ErrorList> NON è un errore fatale. Contiene PhraseNotFound e
    FieldNotFound, che segnalano termini senza corrispondenza in una ricerca
    comunque riuscita. Solo <ERROR> indica un fallimento vero.
    """
    root = _root(xml)
    if root.tag == "ERROR":
        return _text(root) or "Errore NCBI senza messaggio"
    node = root.find("ERROR")
    if node is not None:
        return _text(node) or "Errore NCBI senza messaggio"
    return None


def parse_esearch_xml(xml: str) -> SearchResult:
    root = _root(xml)
    count = root.findtext("Count")
    if count is None:
        raise PubMedParseError("Risposta ESearch priva di <Count>")
    return SearchResult(
        pmids=[t for t in (_text(el) for el in root.findall("./IdList/Id")) if t],
        total_count=int(count),
        translated_query=_text(root.find("QueryTranslation")) or None,
        webenv=_text(root.find("WebEnv")) or None,
        query_key=_text(root.find("QueryKey")) or None,
        warnings=[
            f"{child.tag}: {_text(child)}" for child in root.findall("./ErrorList/*")
        ],
    )
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_pubmed_models.py -v`
Expected: PASS — 10 test superati

- [ ] **Step 5: Commit**

```bash
git add src/pubmed_models.py tests/test_pubmed_models.py
git commit -m "feat: SearchResult e parsing ESearch con distinzione ERROR/ErrorList"
```

---

## Task 3: `Article` e `parse_efetch_xml` — caso nominale

**Files:**
- Modify: `src/pubmed_models.py`
- Modify: `tests/test_pubmed_models.py`

**Interfaces:**
- Consumes: `_root`, `_text`, `PubMedParseError` (Task 2)
- Produces:
  - `Article(pmid: str, title: str, abstract: str | None, authors: list[str], journal: str, pub_date: str, pub_types: list[str], mesh_terms: list[str], doi: str | None)` — dataclass congelata
  - `parse_efetch_xml(xml: str) -> list[Article]`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_pubmed_models.py` (e aggiungere `Article, parse_efetch_xml` alla riga di import da `pubmed_models`):

```python
EFETCH_NOMINALE = """<?xml version="1.0" encoding="UTF-8" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation Status="MEDLINE" Owner="NLM">
    <PMID Version="1">38000001</PMID>
    <Article PubModel="Print">
      <Journal>
        <JournalIssue CitedMedium="Internet">
          <Volume>30</Volume>
          <PubDate>
            <Year>2024</Year>
            <Month>Mar</Month>
            <Day>15</Day>
          </PubDate>
        </JournalIssue>
        <Title>Nature Medicine</Title>
        <ISOAbbreviation>Nat Med</ISOAbbreviation>
      </Journal>
      <ArticleTitle>Immunotherapy in <i>metastatic</i> melanoma.</ArticleTitle>
      <Abstract>
        <AbstractText>Un singolo paragrafo di abstract.</AbstractText>
      </Abstract>
      <AuthorList CompleteYN="Y">
        <Author ValidYN="Y">
          <LastName>Rossi</LastName>
          <ForeName>Maria</ForeName>
          <Initials>M</Initials>
        </Author>
        <Author ValidYN="Y">
          <LastName>Bianchi</LastName>
          <Initials>G</Initials>
        </Author>
      </AuthorList>
      <PublicationTypeList>
        <PublicationType UI="D016449">Randomized Controlled Trial</PublicationType>
        <PublicationType UI="D016428">Journal Article</PublicationType>
      </PublicationTypeList>
      <ELocationID EIdType="doi" ValidYN="Y">10.1038/s41591-024-00001-1</ELocationID>
    </Article>
    <MeshHeadingList>
      <MeshHeading>
        <DescriptorName UI="D008545" MajorTopicYN="N">Melanoma</DescriptorName>
        <QualifierName UI="Q000628" MajorTopicYN="Y">therapy</QualifierName>
      </MeshHeading>
      <MeshHeading>
        <DescriptorName UI="D007167" MajorTopicYN="Y">Immunotherapy</DescriptorName>
      </MeshHeading>
    </MeshHeadingList>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">38000001</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""


def test_efetch_parsing_nominale():
    articles = parse_efetch_xml(EFETCH_NOMINALE)
    assert len(articles) == 1
    art = articles[0]
    assert isinstance(art, Article)
    assert art.pmid == "38000001"
    assert art.journal == "Nature Medicine"
    assert art.pub_date == "2024-03-15"
    assert art.doi == "10.1038/s41591-024-00001-1"


def test_titolo_include_il_markup_inline():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.title == "Immunotherapy in metastatic melanoma."


def test_autori_nome_e_cognome():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.authors == ["Maria Rossi", "G Bianchi"]


def test_tipi_di_pubblicazione():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.pub_types == ["Randomized Controlled Trial", "Journal Article"]


def test_mesh_terms_solo_descrittori():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.mesh_terms == ["Melanoma", "Immunotherapy"]


def test_abstract_semplice():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.abstract == "Un singolo paragrafo di abstract."


def test_set_vuoto_restituisce_lista_vuota():
    assert parse_efetch_xml("<PubmedArticleSet/>") == []


def test_citazione_senza_pmid_solleva_parse_error():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation>
    <Article><ArticleTitle>Senza PMID</ArticleTitle></Article>
    </MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    with pytest.raises(PubMedParseError, match="PMID"):
        parse_efetch_xml(xml)
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_pubmed_models.py -k efetch -v`
Expected: FAIL — `ImportError: cannot import name 'Article' from 'pubmed_models'`

- [ ] **Step 3: Implementare in `src/pubmed_models.py`**

Aggiungere `import re` in cima al file, poi in fondo:

```python
@dataclass(frozen=True)
class Article:
    """Un record PubMed.

    `abstract` è None quando l'articolo non ne ha uno, mai stringa vuota: il
    filtro semantico deve poter distinguere «non posso giudicare» da «vuoto».

    `pub_date` resta una stringa ISO parziale ("2024", "2024-03", "2024-03-15")
    perché PubMed ha date genuinamente incomplete; un oggetto date costringerebbe
    a inventare mese e giorno.
    """

    pmid: str
    title: str
    abstract: str | None
    authors: list[str]
    journal: str
    pub_date: str
    pub_types: list[str]
    mesh_terms: list[str]
    doi: str | None


_MESI = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _mese(valore: str) -> int | None:
    """Accetta sia "Mar" sia "03"; restituisce None se il mese manca o è ignoto."""
    if not valore:
        return None
    if valore.isdigit():
        numero = int(valore)
        return numero if 1 <= numero <= 12 else None
    return _MESI.get(valore[:3].lower())


def _pub_date(node: ET.Element | None) -> str:
    if node is None:
        return ""
    medline = _text(node.find("MedlineDate"))
    if medline:
        # Formati liberi come "2024 Mar-Apr" o "1998 Winter": si tiene solo l'anno.
        trovato = re.search(r"\b(\d{4})\b", medline)
        return trovato.group(1) if trovato else ""
    anno = _text(node.find("Year"))
    if not anno:
        return ""
    mese = _mese(_text(node.find("Month")))
    if mese is None:
        return anno
    giorno = _text(node.find("Day"))
    if not giorno.isdigit():
        return f"{anno}-{mese:02d}"
    return f"{anno}-{mese:02d}-{int(giorno):02d}"


def _abstract(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    parti = []
    for el in node.findall("AbstractText"):
        testo = _text(el)
        if not testo:
            continue
        etichetta = (el.get("Label") or "").strip()
        parti.append(f"{etichetta}: {testo}" if etichetta else testo)
    return "\n\n".join(parti) or None


def _autori(node: ET.Element | None) -> list[str]:
    if node is None:
        return []
    autori = []
    for el in node.findall("Author"):
        collettivo = _text(el.find("CollectiveName"))
        if collettivo:
            autori.append(collettivo)
            continue
        cognome = _text(el.find("LastName"))
        nome = _text(el.find("ForeName")) or _text(el.find("Initials"))
        completo = " ".join(p for p in (nome, cognome) if p)
        if completo:
            autori.append(completo)
    return autori


def _doi(article: ET.Element, pubmed_article: ET.Element) -> str | None:
    for el in article.findall("ELocationID"):
        if el.get("EIdType") == "doi":
            return _text(el) or None
    for el in pubmed_article.findall("./PubmedData/ArticleIdList/ArticleId"):
        if el.get("IdType") == "doi":
            return _text(el) or None
    return None


def parse_efetch_xml(xml: str) -> list[Article]:
    """I record <PubmedBookArticle> (libri) vengono ignorati: fuori ambito per l'MVP."""
    root = _root(xml)
    articoli = []
    for pubmed_article in root.findall(".//PubmedArticle"):
        citazione = pubmed_article.find("MedlineCitation")
        if citazione is None:
            continue
        pmid = _text(citazione.find("PMID"))
        if not pmid:
            raise PubMedParseError("<MedlineCitation> priva di <PMID>")
        article = citazione.find("Article")
        if article is None:
            raise PubMedParseError(f"PMID {pmid}: <Article> mancante")
        articoli.append(
            Article(
                pmid=pmid,
                title=_text(article.find("ArticleTitle")),
                abstract=_abstract(article.find("Abstract")),
                authors=_autori(article.find("AuthorList")),
                journal=_text(article.find("./Journal/Title")),
                pub_date=_pub_date(article.find("./Journal/JournalIssue/PubDate")),
                pub_types=[
                    _text(el)
                    for el in article.findall("./PublicationTypeList/PublicationType")
                ],
                mesh_terms=[
                    _text(el)
                    for el in citazione.findall(
                        "./MeshHeadingList/MeshHeading/DescriptorName"
                    )
                ],
                doi=_doi(article, pubmed_article),
            )
        )
    return articoli
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_pubmed_models.py -v`
Expected: PASS — 18 test superati

- [ ] **Step 5: Commit**

```bash
git add src/pubmed_models.py tests/test_pubmed_models.py
git commit -m "feat: Article e parsing EFetch, caso nominale"
```

---

## Task 4: `parse_efetch_xml` — casi limite

**Files:**
- Modify: `tests/test_pubmed_models.py`
- Modify: `src/pubmed_models.py` (solo se un test rivela un difetto)

**Interfaces:**
- Consumes: `Article`, `parse_efetch_xml` (Task 3)
- Produces: nessuna nuova API. Blinda il comportamento su abstract strutturati, autori collettivi, date parziali e campi mancanti.

Il codice del Task 3 è già scritto per gestire questi casi. Lo scopo del task è verificarlo: se un test fallisce, il difetto va corretto in `pubmed_models.py` prima del commit.

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_pubmed_models.py`:

```python
EFETCH_CASI_LIMITE = """<?xml version="1.0" encoding="UTF-8" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">30000001</PMID>
    <Article>
      <Journal>
        <JournalIssue><PubDate><Year>2019</Year><Month>07</Month></PubDate></JournalIssue>
        <Title>Journal of Structured Abstracts</Title>
      </Journal>
      <ArticleTitle>Trial con abstract strutturato.</ArticleTitle>
      <Abstract>
        <AbstractText Label="BACKGROUND">Il melanoma metastatico ha prognosi infausta.</AbstractText>
        <AbstractText Label="METHODS">Abbiamo randomizzato 300 pazienti.</AbstractText>
        <AbstractText Label="RESULTS">La sopravvivenza è aumentata.</AbstractText>
      </Abstract>
      <AuthorList>
        <Author><CollectiveName>The CheckMate Study Group</CollectiveName></Author>
        <Author><LastName>Verdi</LastName><ForeName>Anna</ForeName></Author>
      </AuthorList>
    </Article>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">30000001</ArticleId>
      <ArticleId IdType="doi">10.9999/fallback.doi</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">30000002</PMID>
    <Article>
      <Journal>
        <JournalIssue><PubDate><Year>1975</Year></PubDate></JournalIssue>
        <Title>Old Journal</Title>
      </Journal>
      <ArticleTitle>Articolo senza abstract né autori.</ArticleTitle>
    </Article>
  </MedlineCitation>
</PubmedArticle>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">30000003</PMID>
    <Article>
      <Journal>
        <JournalIssue><PubDate><MedlineDate>1998 Mar-Apr</MedlineDate></PubDate></JournalIssue>
        <Title>Seasonal Journal</Title>
      </Journal>
      <ArticleTitle>Data in formato MedlineDate.</ArticleTitle>
      <Abstract><AbstractText Label="AIM"></AbstractText></Abstract>
    </Article>
  </MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>
"""


@pytest.fixture
def casi_limite():
    return {a.pmid: a for a in parse_efetch_xml(EFETCH_CASI_LIMITE)}


def test_abstract_strutturato_conserva_le_etichette(casi_limite):
    abstract = casi_limite["30000001"].abstract
    assert abstract == (
        "BACKGROUND: Il melanoma metastatico ha prognosi infausta.\n\n"
        "METHODS: Abbiamo randomizzato 300 pazienti.\n\n"
        "RESULTS: La sopravvivenza è aumentata."
    )


def test_nome_collettivo_diventa_un_autore(casi_limite):
    assert casi_limite["30000001"].authors == ["The CheckMate Study Group", "Anna Verdi"]


def test_doi_di_riserva_da_article_id_list(casi_limite):
    assert casi_limite["30000001"].doi == "10.9999/fallback.doi"


def test_data_parziale_anno_mese(casi_limite):
    assert casi_limite["30000001"].pub_date == "2019-07"


def test_abstract_assente_e_none_non_stringa_vuota(casi_limite):
    assert casi_limite["30000002"].abstract is None


def test_autori_assenti_danno_lista_vuota(casi_limite):
    assert casi_limite["30000002"].authors == []


def test_doi_assente_e_none(casi_limite):
    assert casi_limite["30000002"].doi is None


def test_data_solo_anno(casi_limite):
    assert casi_limite["30000002"].pub_date == "1975"


def test_medline_date_riduce_all_anno(casi_limite):
    assert casi_limite["30000003"].pub_date == "1998"


def test_abstract_con_solo_etichette_vuote_e_none(casi_limite):
    assert casi_limite["30000003"].abstract is None


def test_ordine_dei_record_preservato():
    articles = parse_efetch_xml(EFETCH_CASI_LIMITE)
    assert [a.pmid for a in articles] == ["30000001", "30000002", "30000003"]
```

- [ ] **Step 2: Eseguire i test**

Run: `pytest tests/test_pubmed_models.py -v`
Expected: PASS su tutti e 29. Se qualcuno fallisce, il difetto è in `pubmed_models.py` — correggerlo e rieseguire finché non passano tutti.

- [ ] **Step 3: Commit**

```bash
git add src/pubmed_models.py tests/test_pubmed_models.py
git commit -m "test: casi limite del parsing EFetch (abstract strutturati, date parziali, autori collettivi)"
```

---

## Task 5: `PubMedConfig` e redazione della chiave

**Files:**
- Create: `src/pubmed_client.py`
- Create: `tests/test_pubmed_client.py`

**Interfaces:**
- Consumes: `PubMedConfigError` da `pubmed_errors` (Task 1)
- Produces:
  - `PubMedConfig(tool: str, email: str, api_key: str)` — dataclass congelata, `api_key` esclusa da `__repr__`
  - `PubMedConfig.from_env() -> PubMedConfig`
  - `pubmed_web_url(term: str) -> str`

- [ ] **Step 1: Scrivere i test che falliscono**

File `tests/test_pubmed_client.py`:

```python
"""Test di configurazione, rate limiting e trasporto HTTP. Nessuna rete reale."""

import pytest

from pubmed_client import PubMedConfig, pubmed_web_url
from pubmed_errors import PubMedConfigError

CHIAVE_FINTA = "chiave-segretissima-0123456789"


@pytest.fixture
def env_completo(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", CHIAVE_FINTA)
    monkeypatch.setenv("NCBI_TOOL_NAME", "pubmed-nl-search-agent")
    monkeypatch.setenv("NCBI_EMAIL", "test@example.org")


def test_from_env_legge_le_tre_variabili(env_completo):
    config = PubMedConfig.from_env()
    assert config.tool == "pubmed-nl-search-agent"
    assert config.email == "test@example.org"
    assert config.api_key == CHIAVE_FINTA


def test_variabile_mancante_solleva_config_error(monkeypatch, env_completo):
    monkeypatch.delenv("NCBI_API_KEY")
    with pytest.raises(PubMedConfigError, match="NCBI_API_KEY"):
        PubMedConfig.from_env()


def test_il_messaggio_elenca_tutte_le_variabili_mancanti(monkeypatch, env_completo):
    monkeypatch.delenv("NCBI_API_KEY")
    monkeypatch.delenv("NCBI_EMAIL")
    with pytest.raises(PubMedConfigError) as info:
        PubMedConfig.from_env()
    assert "NCBI_API_KEY" in str(info.value)
    assert "NCBI_EMAIL" in str(info.value)


def test_variabile_vuota_conta_come_mancante(monkeypatch, env_completo):
    monkeypatch.setenv("NCBI_EMAIL", "   ")
    with pytest.raises(PubMedConfigError, match="NCBI_EMAIL"):
        PubMedConfig.from_env()


def test_la_chiave_non_compare_nel_repr(env_completo):
    config = PubMedConfig.from_env()
    assert CHIAVE_FINTA not in repr(config)
    assert "pubmed-nl-search-agent" in repr(config)


def test_config_e_immutabile(env_completo):
    config = PubMedConfig.from_env()
    with pytest.raises(Exception):
        config.api_key = "altro"


def test_pubmed_web_url_codifica_i_caratteri_speciali():
    url = pubmed_web_url('"melanoma"[MeSH Terms] AND immunotherapy')
    assert url.startswith("https://pubmed.ncbi.nlm.nih.gov/?term=")
    assert " " not in url
    assert "%22melanoma%22" in url
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_pubmed_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pubmed_client'`

- [ ] **Step 3: Implementare l'intestazione di `src/pubmed_client.py`**

Sostituire integralmente il contenuto attuale di `src/pubmed_client.py` (oggi solo un docstring segnaposto):

```python
"""
pubmed_client.py

Wrapper sincrono per le API E-utilities di NCBI (ESearch, EFetch).

Responsabilità:
- Costruire ed eseguire le chiamate HTTP includendo sempre `tool`, `email` e
  `api_key`, letti da variabili d'ambiente.
- Applicare un token bucket esplicito a 10 richieste/secondo, con retry e
  backoff sugli errori transitori. Ogni ritentativo ripassa dal limitatore.
- Riconoscere il caso in cui NCBI risponde HTTP 200 con un <ERROR> nel corpo.

Vincolo architetturale: nessuna logica di interpretazione del linguaggio
naturale. Il parsing XML vive in pubmed_models.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from dotenv import load_dotenv

from pubmed_errors import PubMedConfigError

PUBMED_WEB_BASE = "https://pubmed.ncbi.nlm.nih.gov/?term="

_VARIABILI = {
    "tool": "NCBI_TOOL_NAME",
    "email": "NCBI_EMAIL",
    "api_key": "NCBI_API_KEY",
}


@dataclass(frozen=True)
class PubMedConfig:
    """Credenziali NCBI.

    `api_key` è esclusa da __repr__ perché il repr finisce nei log e nei
    messaggi di debug.
    """

    tool: str
    email: str
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls) -> "PubMedConfig":
        """Legge .env e le variabili d'ambiente, fallendo subito se manca qualcosa.

        Meglio un errore esplicito all'avvio che un HTTP 400 opaco da NCBI.
        """
        load_dotenv()
        valori = {
            campo: (os.environ.get(nome) or "").strip()
            for campo, nome in _VARIABILI.items()
        }
        mancanti = [_VARIABILI[campo] for campo, valore in valori.items() if not valore]
        if mancanti:
            raise PubMedConfigError(
                "Variabili d'ambiente mancanti o vuote: "
                + ", ".join(sorted(mancanti))
                + ". Definirle in .env (vedi .env.example)."
            )
        return cls(**valori)


def pubmed_web_url(term: str) -> str:
    """Link alla stessa ricerca sull'interfaccia web, da mostrare all'utente."""
    return PUBMED_WEB_BASE + quote_plus(term)
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_pubmed_client.py -v`
Expected: PASS — 7 test superati

- [ ] **Step 5: Commit**

```bash
git add src/pubmed_client.py tests/test_pubmed_client.py
git commit -m "feat: PubMedConfig da variabili d'ambiente con chiave redatta"
```

---

## Task 6: `RateLimiter` con clock e sleep iniettati

**Files:**
- Modify: `src/pubmed_client.py`
- Modify: `tests/test_pubmed_client.py`

**Interfaces:**
- Consumes: nulla
- Produces: `RateLimiter(rate: float = 10.0, capacity: int = 10, clock=time.monotonic, sleep=time.sleep)` con metodo `acquire() -> None`. Il Task 7 lo inietta in `PubMedClient`.

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_pubmed_client.py` (e `RateLimiter` alla riga di import da `pubmed_client`):

```python
class OrologioFinto:
    """Clock e sleep simulati: dormire fa avanzare il tempo, il test è istantaneo.

    Con time.sleep reale questo test durerebbe oltre un secondo e sarebbe
    intermittente in CI.
    """

    def __init__(self):
        self.adesso = 0.0
        self.attese = []

    def time(self) -> float:
        return self.adesso

    def sleep(self, secondi: float) -> None:
        self.attese.append(secondi)
        self.adesso += secondi


@pytest.fixture
def orologio():
    return OrologioFinto()


def test_le_prime_dieci_richieste_non_attendono(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    for _ in range(10):
        limiter.acquire()
    assert orologio.attese == []
    assert orologio.adesso == 0.0


def test_l_undicesima_richiesta_attende_un_decimo_di_secondo(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    for _ in range(11):
        limiter.acquire()
    assert orologio.adesso == pytest.approx(0.1, abs=1e-9)


def test_il_bucket_si_ricarica_col_tempo(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    for _ in range(10):
        limiter.acquire()
    orologio.adesso += 1.0  # un secondo di inattività ricarica il bucket
    for _ in range(10):
        limiter.acquire()
    assert orologio.attese == []


def test_il_bucket_non_supera_la_capacita(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    orologio.adesso += 100.0  # inattività lunghissima
    for _ in range(10):
        limiter.acquire()
    assert orologio.attese == []
    limiter.acquire()  # l'undicesima deve comunque attendere
    assert orologio.attese == [pytest.approx(0.1, abs=1e-9)]


def test_venti_richieste_consecutive_costano_un_secondo(orologio):
    limiter = RateLimiter(clock=orologio.time, sleep=orologio.sleep)
    for _ in range(20):
        limiter.acquire()
    assert orologio.adesso == pytest.approx(1.0, abs=1e-9)
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_pubmed_client.py -k rate -v`
Expected: FAIL — `ImportError: cannot import name 'RateLimiter' from 'pubmed_client'`

- [ ] **Step 3: Implementare in `src/pubmed_client.py`**

Aggiungere `import threading` e `import time` agli import, poi inserire dopo `PubMedConfig`:

```python
class RateLimiter:
    """Token bucket per rispettare il limite NCBI di 10 richieste/secondo.

    `clock` e `sleep` sono iniettabili perché i test devono verificare l'attesa
    senza far passare tempo reale.

    Il limite è imposto qui e non delegato alla libreria HTTP, così che anche i
    ritentativi vi passino attraverso (vedi CLAUDE.md sezione 4).
    """

    def __init__(
        self,
        rate: float = 10.0,
        capacity: int = 10,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self._rate = rate
        self._capacity = float(capacity)
        self._token = float(capacity)
        self._clock = clock
        self._sleep = sleep
        self._ultimo = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Consuma un token, bloccando finché non ce n'è uno disponibile."""
        with self._lock:
            while True:
                adesso = self._clock()
                trascorso = max(0.0, adesso - self._ultimo)
                self._token = min(self._capacity, self._token + trascorso * self._rate)
                self._ultimo = adesso
                if self._token >= 1.0:
                    self._token -= 1.0
                    return
                self._sleep((1.0 - self._token) / self._rate)
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_pubmed_client.py -v`
Expected: PASS — 12 test superati

- [ ] **Step 5: Commit**

```bash
git add src/pubmed_client.py tests/test_pubmed_client.py
git commit -m "feat: RateLimiter token bucket con clock iniettabile"
```

---

## Task 7: `PubMedClient._request` — trasporto, retry, errori

**Files:**
- Modify: `src/pubmed_client.py`
- Modify: `tests/test_pubmed_client.py`

**Interfaces:**
- Consumes: `PubMedConfig` (Task 5), `RateLimiter` (Task 6), `find_api_error` (Task 2), `PubMedAPIError`/`PubMedHTTPError` (Task 1)
- Produces:
  - `PubMedClient(config=None, *, session=None, rate_limiter=None, max_attempts=3, sleep=time.sleep, timeout=(5.0, 30.0))`
  - `PubMedClient.BASE_URL == "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"`
  - `PubMedClient._request(endpoint: str, params: dict, *, method: str = "GET") -> str`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_pubmed_client.py` (e `PubMedClient` alla riga di import da `pubmed_client`, più `from pubmed_errors import PubMedAPIError, PubMedHTTPError` e `import responses`):

```python
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
XML_OK = "<eSearchResult><Count>1</Count><IdList><Id>1</Id></IdList></eSearchResult>"
XML_ERRORE = "<eSearchResult><ERROR>Can't run executor</ERROR></eSearchResult>"


@pytest.fixture
def client(orologio):
    """Client con rate limiter e backoff simulati: nessuna attesa reale."""
    return PubMedClient(
        PubMedConfig(tool="test-tool", email="test@example.org", api_key=CHIAVE_FINTA),
        rate_limiter=RateLimiter(clock=orologio.time, sleep=orologio.sleep),
        sleep=orologio.sleep,
    )


@responses.activate
def test_ogni_richiesta_include_tool_email_e_api_key(client):
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    client._request("esearch.fcgi", {"db": "pubmed", "term": "melanoma"})
    inviata = responses.calls[0].request
    assert "tool=test-tool" in inviata.url
    assert f"api_key={CHIAVE_FINTA}" in inviata.url
    assert "email=test%40example.org" in inviata.url


@responses.activate
def test_ritenta_dopo_un_429_e_riesce(client):
    responses.add(responses.GET, ESEARCH_URL, status=429)
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    assert client._request("esearch.fcgi", {"db": "pubmed"}) == XML_OK
    assert len(responses.calls) == 2


@responses.activate
def test_429_persistente_solleva_dopo_tre_tentativi(client):
    for _ in range(3):
        responses.add(responses.GET, ESEARCH_URL, status=429)
    with pytest.raises(PubMedHTTPError, match="429"):
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert len(responses.calls) == 3


@responses.activate
def test_503_e_ritentabile(client):
    responses.add(responses.GET, ESEARCH_URL, status=503)
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    assert client._request("esearch.fcgi", {"db": "pubmed"}) == XML_OK


@responses.activate
def test_400_non_e_ritentabile(client):
    responses.add(responses.GET, ESEARCH_URL, status=400)
    with pytest.raises(PubMedHTTPError, match="400"):
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert len(responses.calls) == 1


@responses.activate
def test_http_200_con_error_nel_corpo_solleva_api_error_senza_ritentare(client):
    responses.add(responses.GET, ESEARCH_URL, body=XML_ERRORE, status=200)
    with pytest.raises(PubMedAPIError, match="Can't run executor"):
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert len(responses.calls) == 1


@responses.activate
def test_retry_after_determina_l_attesa(client, orologio):
    responses.add(responses.GET, ESEARCH_URL, status=429, headers={"Retry-After": "7"})
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    client._request("esearch.fcgi", {"db": "pubmed"})
    assert 7.0 in orologio.attese


@responses.activate
def test_la_chiave_non_compare_nei_messaggi_di_errore(client):
    responses.add(responses.GET, ESEARCH_URL, status=400)
    with pytest.raises(PubMedHTTPError) as info:
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert CHIAVE_FINTA not in str(info.value)


@responses.activate
def test_errore_di_rete_non_espone_la_chiave(client):
    import requests

    responses.add(responses.GET, ESEARCH_URL, body=requests.ConnectionError("boom"))
    with pytest.raises(PubMedHTTPError) as info:
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert CHIAVE_FINTA not in str(info.value)
    assert CHIAVE_FINTA not in repr(info.value.__cause__)


@responses.activate
def test_il_rate_limiter_viene_interpellato_a_ogni_tentativo(client, orologio):
    """11 tentativi consumano il bucket: l'ultimo deve aver atteso."""
    for _ in range(11):
        responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    for _ in range(11):
        client._request("esearch.fcgi", {"db": "pubmed"})
    assert orologio.adesso == pytest.approx(0.1, abs=1e-9)


@responses.activate
def test_post_invia_i_parametri_nel_corpo(client):
    efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    responses.add(responses.POST, efetch_url, body="<PubmedArticleSet/>", status=200)
    client._request("efetch.fcgi", {"db": "pubmed", "id": "1,2"}, method="POST")
    inviata = responses.calls[0].request
    assert "id=1%2C2" in inviata.body
    assert f"api_key={CHIAVE_FINTA}" in inviata.body
    assert CHIAVE_FINTA not in inviata.url
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_pubmed_client.py -k request -v`
Expected: FAIL — `ImportError: cannot import name 'PubMedClient' from 'pubmed_client'`

- [ ] **Step 3: Implementare in `src/pubmed_client.py`**

Aggiungere agli import in cima al file:

```python
import random
from typing import Sequence

import requests

from pubmed_errors import PubMedAPIError, PubMedConfigError, PubMedHTTPError
from pubmed_models import Article, SearchResult, find_api_error, parse_efetch_xml, parse_esearch_xml
```

(la riga `from pubmed_errors import PubMedConfigError` del Task 5 va sostituita da quella qui sopra)

Poi aggiungere in fondo al file:

```python
STATUS_RITENTABILI = frozenset({429, 500, 502, 503, 504})


class PubMedClient:
    """Client sincrono per ESearch ed EFetch.

    Le dipendenze (sessione, rate limiter, sleep) sono iniettabili perché i test
    devono poter simulare attese e guasti senza rete né tempo reale.
    """

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def __init__(
        self,
        config: PubMedConfig | None = None,
        *,
        session: "requests.Session | None" = None,
        rate_limiter: RateLimiter | None = None,
        max_attempts: int = 3,
        sleep=time.sleep,
        timeout: tuple[float, float] = (5.0, 30.0),
    ) -> None:
        self._config = config or PubMedConfig.from_env()
        self._session = session or requests.Session()
        self._limiter = rate_limiter or RateLimiter()
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._timeout = timeout

    def _attesa(self, tentativo: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        base = 2.0 ** (tentativo - 1)
        return base + random.uniform(0.0, 0.1 * base)

    def _request(self, endpoint: str, params: dict, *, method: str = "GET") -> str:
        """Esegue una chiamata E-utilities e restituisce il corpo XML.

        Nessun messaggio di errore contiene l'URL: per le GET includerebbe api_key.
        """
        url = self.BASE_URL + endpoint
        payload = {
            **params,
            "tool": self._config.tool,
            "email": self._config.email,
            "api_key": self._config.api_key,
        }
        ultimo_status: int | None = None

        for tentativo in range(1, self._max_attempts + 1):
            self._limiter.acquire()
            try:
                if method == "POST":
                    resp = self._session.post(url, data=payload, timeout=self._timeout)
                else:
                    resp = self._session.get(url, params=payload, timeout=self._timeout)
            except requests.RequestException as exc:
                # str(exc) conterrebbe l'URL completo con api_key: si usa solo il tipo.
                if tentativo == self._max_attempts:
                    raise PubMedHTTPError(
                        f"{endpoint}: errore di rete dopo {tentativo} tentativi "
                        f"({type(exc).__name__})"
                    ) from None
                self._sleep(self._attesa(tentativo, None))
                continue

            if resp.status_code in STATUS_RITENTABILI:
                ultimo_status = resp.status_code
                if tentativo == self._max_attempts:
                    break
                self._sleep(self._attesa(tentativo, resp.headers.get("Retry-After")))
                continue

            if resp.status_code >= 400:
                raise PubMedHTTPError(f"{endpoint}: HTTP {resp.status_code}")

            errore = find_api_error(resp.text)
            if errore:
                raise PubMedAPIError(f"{endpoint}: {errore}")
            return resp.text

        raise PubMedHTTPError(
            f"{endpoint}: HTTP {ultimo_status} dopo {self._max_attempts} tentativi"
        )
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `pytest tests/test_pubmed_client.py -v`
Expected: PASS — 23 test superati

- [ ] **Step 5: Commit**

```bash
git add src/pubmed_client.py tests/test_pubmed_client.py
git commit -m "feat: trasporto HTTP con retry, rilevamento ERROR nel corpo, chiave non esposta"
```

---

## Task 8: `esearch` ed `efetch`

**Files:**
- Modify: `src/pubmed_client.py`
- Modify: `tests/test_pubmed_client.py`

**Interfaces:**
- Consumes: `PubMedClient._request` (Task 7), `parse_esearch_xml`/`parse_efetch_xml` (Task 2 e 3)
- Produces:
  - `PubMedClient.esearch(term, *, retmax=100, retstart=0, sort=None, mindate=None, maxdate=None, datetype="pdat") -> SearchResult`
  - `PubMedClient.efetch(pmids, *, batch_size=200) -> list[Article]`

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/test_pubmed_client.py`:

```python
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def _articolo_xml(pmid: str) -> str:
    return f"""<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID>
    <Article><Journal><Title>J</Title>
    <JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal>
    <ArticleTitle>Titolo {pmid}</ArticleTitle></Article>
    </MedlineCitation></PubmedArticle>"""


def _set_xml(*pmids: str) -> str:
    return "<PubmedArticleSet>" + "".join(_articolo_xml(p) for p in pmids) + "</PubmedArticleSet>"


@responses.activate
def test_esearch_usa_usehistory_e_restituisce_search_result(client):
    responses.add(
        responses.GET,
        ESEARCH_URL,
        body="""<eSearchResult><Count>42</Count>
        <WebEnv>MCID_x</WebEnv><QueryKey>1</QueryKey>
        <IdList><Id>11</Id><Id>22</Id></IdList>
        <QueryTranslation>melanoma[All Fields]</QueryTranslation></eSearchResult>""",
        status=200,
    )
    risultato = client.esearch("melanoma", retmax=2)
    assert risultato.total_count == 42
    assert risultato.pmids == ["11", "22"]
    assert risultato.translated_query == "melanoma[All Fields]"
    inviata = responses.calls[0].request
    assert "usehistory=y" in inviata.url
    assert "retmax=2" in inviata.url
    assert "db=pubmed" in inviata.url


@responses.activate
def test_esearch_invia_i_filtri_di_data_solo_se_presenti(client):
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    client.esearch("melanoma", mindate="2023", maxdate="2026")
    inviata = responses.calls[0].request
    assert "mindate=2023" in inviata.url
    assert "maxdate=2026" in inviata.url
    assert "datetype=pdat" in inviata.url


@responses.activate
def test_esearch_omette_datetype_senza_filtri_di_data(client):
    responses.add(responses.GET, ESEARCH_URL, body=XML_OK, status=200)
    client.esearch("melanoma")
    assert "datetype" not in responses.calls[0].request.url


@responses.activate
def test_efetch_restituisce_articoli(client):
    responses.add(responses.POST, EFETCH_URL, body=_set_xml("11", "22"), status=200)
    articoli = client.efetch(["11", "22"])
    assert [a.pmid for a in articoli] == ["11", "22"]
    assert articoli[0].title == "Titolo 11"


@responses.activate
def test_efetch_riordina_secondo_i_pmid_in_input(client):
    """NCBI restituisce nel proprio ordine: il ranking di ESearch va preservato."""
    responses.add(responses.POST, EFETCH_URL, body=_set_xml("22", "11", "33"), status=200)
    articoli = client.efetch(["33", "11", "22"])
    assert [a.pmid for a in articoli] == ["33", "11", "22"]


@responses.activate
def test_efetch_tollera_pmid_mancanti(client):
    """Record ritirati o rimossi: meno articoli del richiesto non è un errore."""
    responses.add(responses.POST, EFETCH_URL, body=_set_xml("11"), status=200)
    articoli = client.efetch(["11", "99999999"])
    assert [a.pmid for a in articoli] == ["11"]


@responses.activate
def test_efetch_divide_in_batch_da_duecento(client):
    pmids = [str(n) for n in range(1, 251)]
    responses.add(responses.POST, EFETCH_URL, body=_set_xml(*pmids[:200]), status=200)
    responses.add(responses.POST, EFETCH_URL, body=_set_xml(*pmids[200:]), status=200)
    articoli = client.efetch(pmids)
    assert len(responses.calls) == 2
    assert len(articoli) == 250
    assert [a.pmid for a in articoli] == pmids


@responses.activate
def test_efetch_solleva_se_un_batch_fallisce(client):
    """Fail-fast: risultati silenziosamente incompleti sono peggio di un errore."""
    pmids = [str(n) for n in range(1, 251)]
    responses.add(responses.POST, EFETCH_URL, body=_set_xml(*pmids[:200]), status=200)
    for _ in range(3):
        responses.add(responses.POST, EFETCH_URL, status=500)
    with pytest.raises(PubMedHTTPError):
        client.efetch(pmids)


def test_efetch_con_lista_vuota_non_chiama_la_rete(client):
    assert client.efetch([]) == []


@responses.activate
def test_efetch_accetta_pmid_numerici(client):
    responses.add(responses.POST, EFETCH_URL, body=_set_xml("11"), status=200)
    assert [a.pmid for a in client.efetch([11])] == ["11"]
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest tests/test_pubmed_client.py -k "esearch or efetch" -v`
Expected: FAIL — `AttributeError: 'PubMedClient' object has no attribute 'esearch'`

- [ ] **Step 3: Implementare in `src/pubmed_client.py`**

Aggiungere come metodi di `PubMedClient`, dopo `_request`:

```python
    def esearch(
        self,
        term: str,
        *,
        retmax: int = 100,
        retstart: int = 0,
        sort: str | None = None,
        mindate: str | None = None,
        maxdate: str | None = None,
        datetype: str = "pdat",
    ) -> SearchResult:
        """Esegue una ricerca e restituisce PMID, conteggio e query tradotta da NCBI.

        `retmax` limita quanti PMID vengono restituiti, non quanti ne esistono:
        `SearchResult.total_count` riporta comunque i match reali.

        `usehistory=y` è sempre attivo: fornisce WebEnv e query_key per paginare
        senza rieseguire la query, evitando lo slittamento dei risultati.
        """
        params = {
            "db": "pubmed",
            "term": term,
            "usehistory": "y",
            "retmax": str(retmax),
            "retstart": str(retstart),
            "retmode": "xml",
        }
        if sort:
            params["sort"] = sort
        if mindate or maxdate:
            params["datetype"] = datetype
            if mindate:
                params["mindate"] = mindate
            if maxdate:
                params["maxdate"] = maxdate
        return parse_esearch_xml(self._request("esearch.fcgi", params))

    def efetch(self, pmids: Sequence, *, batch_size: int = 200) -> list[Article]:
        """Scarica gli abstract completi, preservando l'ordine dei PMID in input.

        Usa POST perché oltre ~200 identificatori l'URL di una GET sfora i limiti.

        Se un batch fallisce dopo tutti i tentativi l'eccezione si propaga: meglio
        un errore esplicito che risultati incompleti su cui il filtro semantico
        lavorerebbe senza saperlo.
        """
        ordinati = [str(p) for p in pmids]
        if not ordinati:
            return []
        per_pmid: dict[str, Article] = {}
        for inizio in range(0, len(ordinati), batch_size):
            batch = ordinati[inizio : inizio + batch_size]
            xml = self._request(
                "efetch.fcgi",
                {
                    "db": "pubmed",
                    "id": ",".join(batch),
                    "rettype": "abstract",
                    "retmode": "xml",
                },
                method="POST",
            )
            for articolo in parse_efetch_xml(xml):
                per_pmid[articolo.pmid] = articolo
        return [per_pmid[p] for p in ordinati if p in per_pmid]
```

- [ ] **Step 4: Eseguire l'intera suite offline**

Run: `pytest -v`
Expected: PASS — 68 test superati (6 in `test_pubmed_errors.py`, 29 in `test_pubmed_models.py`, 33 in `test_pubmed_client.py`), nessuna chiamata di rete

- [ ] **Step 5: Commit**

```bash
git add src/pubmed_client.py tests/test_pubmed_client.py
git commit -m "feat: esearch ed efetch con batching, riordino e fail-fast"
```

---

## Task 9: Registrazione delle fixture reali

**Files:**
- Create: `tests/record_fixtures.py`
- Create: `tests/fixtures/*.xml` (sei file, generati)
- Modify: `.gitignore` (verificare che `tests/fixtures/` non sia escluso)

**Interfaces:**
- Consumes: `PubMedClient`, `PubMedConfig` (Task 5-8)
- Produces: sei file XML in `tests/fixtures/`, consumati dal Task 10

**Questo task richiede rete e una `.env` valida.** Le fixture vanno versionate; la `api_key` non deve finirci dentro.

- [ ] **Step 1: Scrivere lo script**

File `tests/record_fixtures.py`:

```python
"""
Registra risposte reali di NCBI in tests/fixtures/.

Le fixture scritte a mano tendono a essere versioni idealizzate della realtà e
perdono proprio i casi limite che rompono il parser. Qui si salva XML autentico:
quando NCBI cambia schema, si rigenera e si guarda il diff.

Uso:
    python tests/record_fixtures.py

Richiede una .env valida. Ogni file viene ripulito dalla api_key prima della
scrittura: tests/fixtures/ finisce in git, .env no.
"""

from __future__ import annotations

import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from pubmed_client import PubMedClient, PubMedConfig  # noqa: E402

FIXTURES = RADICE / "tests" / "fixtures"

# PMID candidati per i casi limite. Lo script verifica che abbiano davvero la
# caratteristica richiesta e si ferma se non è così: in quel caso sostituire il
# PMID con uno che la soddisfi.
PMID_ABSTRACT_STRUTTURATO = "33301246"
PMID_SENZA_ABSTRACT = "1"
PMID_AUTORE_COLLETTIVO = "25891304"


def _ripulisci(testo: str, chiave: str) -> str:
    return testo.replace(chiave, "API_KEY_RIMOSSA")


def _scrivi(nome: str, contenuto: str, chiave: str) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    percorso = FIXTURES / nome
    percorso.write_text(_ripulisci(contenuto, chiave), encoding="utf-8")
    print(f"  scritto {percorso.relative_to(RADICE)} ({len(contenuto)} byte)")


def _verifica(nome: str, condizione: bool, descrizione: str) -> bool:
    esito = "OK  " if condizione else "FAIL"
    print(f"  [{esito}] {nome}: {descrizione}")
    return condizione


def main() -> int:
    config = PubMedConfig.from_env()
    client = PubMedClient(config)
    chiave = config.api_key
    tutto_ok = True

    print("esearch_basic.xml — caso nominale con QueryTranslation")
    xml = client._request(
        "esearch.fcgi",
        {"db": "pubmed", "term": "melanoma immunotherapy", "usehistory": "y",
         "retmax": "5", "retmode": "xml"},
    )
    tutto_ok &= _verifica("esearch_basic", "<QueryTranslation>" in xml, "contiene QueryTranslation")
    _scrivi("esearch_basic.xml", xml, chiave)

    print("esearch_zero_results.xml — Count=0")
    xml = client._request(
        "esearch.fcgi",
        {"db": "pubmed", "term": '"zzzzqwertynonesiste12345"[tiab]',
         "usehistory": "y", "retmax": "5", "retmode": "xml"},
    )
    tutto_ok &= _verifica("esearch_zero", "<Count>0</Count>" in xml, "Count vale 0")
    _scrivi("esearch_zero_results.xml", xml, chiave)

    print("esearch_error.xml — HTTP 200 con <ERROR>")
    # _request solleverebbe PubMedAPIError: qui serve il corpo grezzo.
    import requests

    risposta = requests.get(
        client.BASE_URL + "esearch.fcgi",
        params={"db": "pubmed", "term": "melanoma AND (", "retmode": "xml",
                "tool": config.tool, "email": config.email, "api_key": chiave},
        timeout=(5, 30),
    )
    xml = risposta.text
    tutto_ok &= _verifica("esearch_error", "<ERROR>" in xml, "contiene <ERROR>")
    tutto_ok &= _verifica("esearch_error", risposta.status_code == 200, "status è 200")
    _scrivi("esearch_error.xml", xml, chiave)

    print("efetch_batch.xml — più articoli, uno con abstract strutturato")
    xml = client._request(
        "efetch.fcgi",
        {"db": "pubmed", "id": f"{PMID_ABSTRACT_STRUTTURATO},{PMID_AUTORE_COLLETTIVO}",
         "rettype": "abstract", "retmode": "xml"},
        method="POST",
    )
    tutto_ok &= _verifica("efetch_batch", 'Label="' in xml, "contiene un abstract strutturato")
    _scrivi("efetch_batch.xml", xml, chiave)

    print("efetch_no_abstract.xml — articolo privo di abstract")
    xml = client._request(
        "efetch.fcgi",
        {"db": "pubmed", "id": PMID_SENZA_ABSTRACT, "rettype": "abstract", "retmode": "xml"},
        method="POST",
    )
    tutto_ok &= _verifica("efetch_no_abstract", "<Abstract>" not in xml, "nessun <Abstract>")
    _scrivi("efetch_no_abstract.xml", xml, chiave)

    print("efetch_collective_author.xml — <CollectiveName>")
    xml = client._request(
        "efetch.fcgi",
        {"db": "pubmed", "id": PMID_AUTORE_COLLETTIVO, "rettype": "abstract", "retmode": "xml"},
        method="POST",
    )
    tutto_ok &= _verifica("efetch_collective", "<CollectiveName>" in xml, "contiene CollectiveName")
    _scrivi("efetch_collective_author.xml", xml, chiave)

    if not tutto_ok:
        print("\nAlcune verifiche sono fallite: sostituire i PMID candidati in cima")
        print("a questo file con record che soddisfino la caratteristica richiesta,")
        print("poi rieseguire.")
        return 1

    print("\nTutte le fixture registrate e verificate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verificare che `tests/fixtures/` sia versionabile**

Run: `git check-ignore -v tests/fixtures/ ; echo "exit=$?"`
Expected: `exit=1` (nessuna regola lo esclude). Se invece stampa una regola di `.gitignore`, rimuoverla o aggiungere `!tests/fixtures/`.

- [ ] **Step 3: Eseguire lo script**

Run: `python tests/record_fixtures.py`
Expected: sei righe `scritto tests/fixtures/...`, tutte le verifiche `[OK  ]`, e in chiusura `Tutte le fixture registrate e verificate.`

Se una verifica stampa `[FAIL]`, sostituire il PMID candidato corrispondente in cima allo script e rieseguire. I PMID indicati sono candidati non confermati: vanno validati da questa esecuzione.

- [ ] **Step 4: Verificare che nessuna fixture contenga la chiave**

Run: `grep -rl "$(grep NCBI_API_KEY .env | cut -d= -f2)" tests/fixtures/ ; echo "exit=$?"`
Expected: `exit=1` (nessun file corrisponde). Se un file compare nell'elenco, correggere `_ripulisci` e rigenerare.

- [ ] **Step 5: Commit**

```bash
git add tests/record_fixtures.py tests/fixtures/
git commit -m "test: script di registrazione e sei fixture XML reali da NCBI"
```

---

## Task 10: Test di parsing contro le fixture reali

**Files:**
- Modify: `tests/test_pubmed_models.py`

**Interfaces:**
- Consumes: `parse_esearch_xml`, `parse_efetch_xml`, `find_api_error` (Task 2-3), le fixture del Task 9
- Produces: nessuna nuova API

I test inline dei Task 2-4 verificano il comportamento su XML che ho scritto io. Questi verificano che lo stesso codice regga XML autentico di NCBI, che contiene campi e annidamenti che una fixture scritta a mano non riproduce.

- [ ] **Step 1: Scrivere i test**

Aggiungere in fondo a `tests/test_pubmed_models.py` (e `from pathlib import Path` agli import):

```python
FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(nome: str) -> str:
    percorso = FIXTURES / nome
    if not percorso.exists():
        pytest.skip(f"{nome} non registrata: eseguire python tests/record_fixtures.py")
    return percorso.read_text(encoding="utf-8")


def test_fixture_esearch_reale():
    result = parse_esearch_xml(_fixture("esearch_basic.xml"))
    assert result.total_count > 0
    assert len(result.pmids) > 0
    assert all(p.isdigit() for p in result.pmids)
    assert result.translated_query
    assert result.webenv


def test_fixture_esearch_zero_risultati():
    result = parse_esearch_xml(_fixture("esearch_zero_results.xml"))
    assert result.total_count == 0
    assert result.pmids == []


def test_fixture_esearch_error_rilevata():
    assert find_api_error(_fixture("esearch_error.xml")) is not None


def test_fixture_efetch_batch_reale():
    articoli = parse_efetch_xml(_fixture("efetch_batch.xml"))
    assert len(articoli) >= 1
    for art in articoli:
        assert art.pmid.isdigit()
        assert art.title
        assert art.journal
        assert art.pub_date[:4].isdigit()


def test_fixture_abstract_strutturato_reale():
    articoli = parse_efetch_xml(_fixture("efetch_batch.xml"))
    strutturati = [a for a in articoli if a.abstract and ": " in a.abstract]
    assert strutturati, "nessun abstract strutturato nella fixture"


def test_fixture_senza_abstract_reale():
    articoli = parse_efetch_xml(_fixture("efetch_no_abstract.xml"))
    assert len(articoli) == 1
    assert articoli[0].abstract is None
    assert articoli[0].title


def test_fixture_autore_collettivo_reale():
    articoli = parse_efetch_xml(_fixture("efetch_collective_author.xml"))
    assert articoli[0].authors, "nessun autore estratto"


def test_nessuna_fixture_contiene_api_key():
    for percorso in FIXTURES.glob("*.xml"):
        assert "api_key=" not in percorso.read_text(encoding="utf-8")
```

- [ ] **Step 2: Eseguire i test**

Run: `pytest tests/test_pubmed_models.py -v`
Expected: PASS su tutti. Un fallimento qui è un difetto reale del parser: correggerlo in `pubmed_models.py` e riaggiungere il caso ai test inline del Task 4 perché resti coperto anche senza fixture.

- [ ] **Step 3: Eseguire l'intera suite offline**

Run: `pytest`
Expected: PASS, nessun test `live` eseguito

- [ ] **Step 4: Commit**

```bash
git add tests/test_pubmed_models.py
git commit -m "test: parsing verificato contro fixture NCBI autentiche"
```

---

## Task 11: Test live

**Files:**
- Create: `tests/test_pubmed_live.py`

**Interfaces:**
- Consumes: `PubMedClient`, `PubMedConfig`, `PubMedAPIError` (Task 5-8)
- Produces: nessuna nuova API

Le asserzioni riguardano la **struttura**, non il contenuto: PubMed corregge i propri metadati e un confronto con stringhe letterali si romperebbe da solo.

- [ ] **Step 1: Scrivere i test**

File `tests/test_pubmed_live.py`:

```python
"""
Test contro le API NCBI reali.

Esclusi di default da pytest.ini. Si eseguono con:
    pytest -m live -v

Richiedono una .env valida. Asseriscono sulla struttura e non sul contenuto
esatto, perché PubMed corregge i propri metadati nel tempo.
"""

import time

import pytest

from pubmed_client import PubMedClient, PubMedConfig
from pubmed_errors import PubMedAPIError

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client():
    try:
        config = PubMedConfig.from_env()
    except Exception as exc:
        pytest.skip(f"configurazione NCBI assente: {exc}")
    return PubMedClient(config)


def test_esearch_reale_trova_risultati(client):
    risultato = client.esearch('"melanoma"[MeSH Terms]', retmax=5)
    assert risultato.total_count > 1000
    assert len(risultato.pmids) == 5
    assert all(p.isdigit() for p in risultato.pmids)
    assert risultato.translated_query
    assert risultato.webenv


def test_esearch_reale_senza_risultati(client):
    risultato = client.esearch('"zzzzqwertynonesiste12345"[tiab]')
    assert risultato.total_count == 0
    assert risultato.pmids == []


def test_query_malformata_solleva_api_error(client):
    with pytest.raises(PubMedAPIError):
        client.esearch("melanoma AND (")


def test_efetch_reale_restituisce_abstract(client):
    ricerca = client.esearch('"melanoma"[MeSH Terms] AND hasabstract', retmax=3)
    articoli = client.efetch(ricerca.pmids)
    assert [a.pmid for a in articoli] == ricerca.pmids
    for art in articoli:
        assert art.title
        assert art.journal
        assert art.pub_date[:4].isdigit()
        assert art.abstract


def test_quindici_richieste_rapide_non_producono_429(client):
    """Verifica che il token bucket tenga sotto il limite reale di NCBI."""
    inizio = time.monotonic()
    for _ in range(15):
        client.esearch("melanoma", retmax=1)
    trascorso = time.monotonic() - inizio
    assert trascorso >= 0.4, "15 richieste non possono essere istantanee a 10 req/s"
```

- [ ] **Step 2: Eseguire i test live**

Run: `pytest -m live -v`
Expected: PASS — 5 test superati. Se `total_count > 1000` fallisse, verificare a mano su pubmed.ncbi.nlm.nih.gov prima di abbassare la soglia.

- [ ] **Step 3: Verificare che restino esclusi di default**

Run: `pytest -v`
Expected: i test di `test_pubmed_live.py` risultano deselezionati (`5 deselected` nel riepilogo)

- [ ] **Step 4: Commit**

```bash
git add tests/test_pubmed_live.py
git commit -m "test: suite live contro le API NCBI, esclusa di default"
```

---

## Task 12: Allineare `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (sezioni 3, 4, 8, 9)

**Interfaces:**
- Consumes: nulla
- Produces: nessuna API. Chiude il requisito di `CLAUDE.md` sezione 10 («ogni modifica architetturale rilevante va riportata in questo file»).

- [ ] **Step 1: Aggiornare l'albero della sezione 3**

Sostituire il blocco dell'albero dei file con:

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
│   ├── record_fixtures.py     # registra risposte NCBI reali
│   └── fixtures/              # XML NCBI salvati, senza api_key
└── examples/
    └── sample_queries.md
```

Aggiungere sotto il "Principio guida" esistente:

```
Il parsing XML vive in `pubmed_models.py`, che non ha alcuna dipendenza da rete ed è
testabile passandogli stringhe. `pubmed_errors.py` esiste in un modulo proprio perché
sia il parser sia il client devono sollevare eccezioni della stessa gerarchia, e
definirle nel client creerebbe un import circolare.
```

- [ ] **Step 2: Correggere la tabella degli endpoint nella sezione 4**

Nella riga `esummary.fcgi`, sostituire la colonna "Note" con:

```
Fase successiva, non nel MVP: `efetch` restituisce già titolo, autori, journal e data insieme all'abstract
```

Aggiungere sotto la tabella:

```
**Attenzione — `<ErrorList>` non è un errore fatale.** ESearch restituisce
`<ErrorList><PhraseNotFound>…</PhraseNotFound></ErrorList>` quando un termine non trova
corrispondenze, ma la ricerca è comunque riuscita: quei figli finiscono in
`SearchResult.warnings` e dicono *quale* termine non ha matchato. Solo l'elemento
`<ERROR>` indica un fallimento vero e produce un `PubMedAPIError`.

**Attenzione — un errore può arrivare con HTTP 200.** Una query malformata non produce un
400 ma un `<ERROR>` dentro XML valido con status 200. Controllare solo `status_code`
darebbe una lista vuota indistinguibile da «nessun match».
```

- [ ] **Step 3: Aggiornare la roadmap nella sezione 8**

Sostituire il punto 1 con:

```
1. ~~`pubmed_errors.py` + `pubmed_models.py` + `pubmed_client.py` — wrapper ESearch + EFetch
   con rate limiting e parsing tipizzato, testato offline su fixture reali e in modalità live~~
   **(completato)**
```

- [ ] **Step 4: Aggiornare la sezione 9**

Aggiungere in fondo:

```
I test live sono marcati `@pytest.mark.live` ed esclusi di default da `pytest.ini`
(`addopts = -m "not live"`): `pytest` gira interamente offline, `pytest -m live` esegue le
chiamate reali. Le fixture non si scrivono a mano — `python tests/record_fixtures.py`
registra risposte NCBI autentiche in `tests/fixtures/`, rimuovendo la `api_key` prima di
scrivere su disco.
```

- [ ] **Step 5: Verificare che la suite passi ancora**

Run: `pytest`
Expected: PASS, nessuna regressione

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: allinea CLAUDE.md all'architettura effettiva del client"
```

---

## Criteri di completamento

- [ ] `pytest` passa interamente offline, senza toccare la rete
- [ ] `pytest -m live` passa contro NCBI
- [ ] Le sei fixture sono registrate, versionate e prive di `api_key`
- [ ] `esearch` di una query nota restituisce `total_count`, PMID e `translated_query`
- [ ] `efetch` su quei PMID restituisce `Article` con abstract, nell'ordine di input
- [ ] Una query malformata solleva `PubMedAPIError`, non una lista vuota
- [ ] Un `PhraseNotFound` finisce in `warnings` e non fa fallire la ricerca
- [ ] `CLAUDE.md` riflette l'architettura effettiva
