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

from cli_utils import scrivi_errore, scrivi_testo

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

    scrivi_testo(risultato)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
