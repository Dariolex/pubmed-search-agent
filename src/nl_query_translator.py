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
