"""
cli_utils.py

Helper condivisi dalle CLI del progetto (run_search, mesh_resolver, related_search,
nl_query_translator, export_results): scrittura di errori e output JSON/testo con
encoding robusto,
per evitare UnicodeEncodeError su console Windows con encoding ristretto (es. cp1252)
quando un messaggio o un campo contiene caratteri non rappresentabili.

Nessuna logica di dominio: solo I/O.
"""

from __future__ import annotations

import json
import sys


def scrivi_errore(exc: Exception) -> None:
    """Scrive un'eccezione su stderr con encoding robusto.

    Usa `sys.stderr.buffer.write` (non `print`) perché il messaggio può contenere
    testo grezzo arbitrario (es. il corpo di un <ERROR> di NCBI), e `errors=
    "backslashreplace"` evita UnicodeEncodeError quando l'encoding di stderr non
    può rappresentare un carattere.
    """
    sys.stderr.buffer.write(
        f"Errore: {exc}\n".encode(sys.stderr.encoding or "utf-8", errors="backslashreplace")
    )


def stampa_json(dati: dict) -> None:
    """Stampa un dizionario come JSON su stdout, stesso formato in tutte le CLI.

    `ensure_ascii=True` mantiene l'output puro ASCII (con sequenze di escape per
    i caratteri non-ASCII), evitando UnicodeEncodeError su stdout con encoding
    ristretto.
    """
    json.dump(dati, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")


def scrivi_testo(testo: str) -> None:
    """Scrive testo libero su stdout con encoding robusto.

    A differenza di `stampa_json` non c'è `ensure_ascii` a proteggere l'output:
    per testo non-JSON (query PubMed, record bibliografici RIS/BibTeX, che
    possono contenere caratteri reali degli abstract NCBI, es. lettere greche)
    si usa `sys.stdout.buffer.write` con `errors="backslashreplace"`, stesso
    pattern già in uso per `scrivi_errore`.
    """
    sys.stdout.buffer.write(
        (testo + "\n").encode(sys.stdout.encoding or "utf-8", errors="backslashreplace")
    )
