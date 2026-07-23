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
