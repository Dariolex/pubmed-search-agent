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

from cli_utils import scrivi_errore, stampa_json
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
        scrivi_errore(exc)
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

    stampa_json(risultato)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
