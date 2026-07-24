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
