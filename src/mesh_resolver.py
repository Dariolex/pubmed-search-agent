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
