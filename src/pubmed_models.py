"""
pubmed_models.py

Dataclass e parsing delle risposte XML di NCBI E-utilities.

Non effettua alcuna chiamata di rete: ogni funzione riceve una stringa XML e
restituisce dati tipizzati. È il modulo con la maggiore superficie di test del
progetto, ed è testabile senza mock.
"""

from __future__ import annotations

import re
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
    try:
        total_count = int(count)
    except ValueError as exc:
        raise PubMedParseError(f"Valore di <Count> non numerico: {count!r}") from exc
    return SearchResult(
        pmids=[t for t in (_text(el) for el in root.findall("./IdList/Id")) if t],
        total_count=total_count,
        translated_query=_text(root.find("QueryTranslation")) or None,
        webenv=_text(root.find("WebEnv")) or None,
        query_key=_text(root.find("QueryKey")) or None,
        warnings=[
            f"{child.tag}: {_text(child)}" for child in root.findall("./ErrorList/*")
        ],
    )


@dataclass(frozen=True)
class Article:
    """Un record PubMed.

    `abstract` è None quando l'articolo non ne ha uno, mai stringa vuota: il
    filtro semantico deve poter distinguere «non posso giudicare» da «vuoto».

    `pub_date` resta una stringa ISO parziale ("2024", "2024-03", "2024-03-15")
    perché PubMed ha date genuinamente incomplete; un oggetto date costringerebbe
    a inventare mese e giorno.

    `coi_statement` è la dichiarazione di conflitto d'interesse (<CoiStatement>),
    None quando l'articolo non ne ha una. È l'unico posto in cui PubMed registra i
    brevetti degli autori, e va letto per distinguere le dichiarazioni positive
    («è co-inventore di un brevetto») da quelle negative («non detiene brevetti»).
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
    coi_statement: str | None = None


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
            raise PubMedParseError("<PubmedArticle> privo di <MedlineCitation>")
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
                coi_statement=_text(citazione.find("CoiStatement")) or None,
            )
        )
    return articoli


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


def parse_elink_xml(xml: str, pmid_sorgente: str) -> list[str]:
    """Estrae i PMID collegati da una risposta elink, escludendo la sorgente.

    Il PMID sorgente compare sempre nel proprio LinkSetDb (verificato dal vivo:
    è il primo elemento per un PMID valido, l'unico elemento per un PMID
    inesistente — NCBI non restituisce <ERROR> in quel caso, risponde HTTP 200
    con un LinkSetDb che contiene solo la sorgente). Escluderla qui rende "PMID
    inesistente" e "nessun link trovato" indistinguibili a valle: entrambi
    producono lista vuota, comportamento corretto in entrambi i casi.

    Preserva l'ordine restituito da NCBI (per pubmed_pubmed_citedin è dal più
    recente al più vecchio, verificato dal vivo): non riordina né deduplica
    oltre a escludere la sorgente.
    """
    root = _root(xml)
    return [
        pmid
        for pmid in (
            _text(el) for el in root.findall("./LinkSet/LinkSetDb/Link/Id")
        )
        if pmid and pmid != pmid_sorgente
    ]
