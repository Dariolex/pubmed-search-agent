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


def esegui(term: str, retmax: int, client: PubMedClient, retstart: int = 0) -> dict:
    """Esegue la ricerca e restituisce un dizionario serializzabile in JSON.

    Include `translated_query` e `warnings` di NCBI, utili a Claude per capire
    come PubMed ha reinterpretato la query e quali termini non hanno matchato.
    """
    ricerca = client.esearch(term, retmax=retmax, retstart=retstart)
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
    parser.add_argument(
        "--retstart", type=int, default=0,
        help="Offset per la paginazione (0-based): salta i primi N risultati",
    )
    args = parser.parse_args(argv)

    try:
        client = PubMedClient(PubMedConfig.from_env())
        risultato = esegui(args.term, args.retmax, client, args.retstart)
    except PubMedError as exc:
        # I messaggi di PubMedError possono incorporare il testo grezzo di errore
        # restituito da NCBI: usiamo un encoding robusto per evitare UnicodeEncodeError
        # su console Windows con encoding restrittivo (es. cp1252).
        sys.stderr.buffer.write(
            f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
        )
        return 1

    json.dump(risultato, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
