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
