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
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Sequence
from urllib.parse import quote_plus

from dotenv import load_dotenv
import requests

from pubmed_errors import PubMedAPIError, PubMedConfigError, PubMedHTTPError
from pubmed_models import Article, SearchResult, find_api_error, parse_efetch_xml, parse_esearch_xml

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


class RateLimiter:
    """Token bucket per rispettare il limite NCBI di 10 richieste/secondo.

    `clock` e `sleep` sono iniettabili perché i test devono verificare l'attesa
    senza far passare tempo reale.

    Il limite è imposto qui e non delegato alla libreria HTTP, così che anche i
    ritentativi vi passino attraverso (vedi CLAUDE.md sezione 4).
    """

    def __init__(
        self,
        rate: float = 10.0,
        capacity: int = 10,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self._rate = rate
        self._capacity = float(capacity)
        self._token = float(capacity)
        self._clock = clock
        self._sleep = sleep
        self._ultimo = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Consuma un token, bloccando finché non ce n'è uno disponibile."""
        with self._lock:
            while True:
                adesso = self._clock()
                trascorso = max(0.0, adesso - self._ultimo)
                self._token = min(self._capacity, self._token + trascorso * self._rate)
                self._ultimo = adesso
                if self._token >= 1.0 - 1e-10:
                    self._token -= 1.0
                    return
                self._sleep((1.0 - self._token) / self._rate)


def pubmed_web_url(term: str) -> str:
    """Link alla stessa ricerca sull'interfaccia web, da mostrare all'utente."""
    return PUBMED_WEB_BASE + quote_plus(term)


STATUS_RITENTABILI = frozenset({429, 500, 502, 503, 504})


class PubMedClient:
    """Client sincrono per ESearch ed EFetch.

    Le dipendenze (sessione, rate limiter, sleep) sono iniettabili perché i test
    devono poter simulare attese e guasti senza rete né tempo reale.
    """

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def __init__(
        self,
        config: PubMedConfig | None = None,
        *,
        session: "requests.Session | None" = None,
        rate_limiter: RateLimiter | None = None,
        max_attempts: int = 3,
        sleep=time.sleep,
        timeout: tuple[float, float] = (5.0, 30.0),
    ) -> None:
        self._config = config or PubMedConfig.from_env()
        self._session = session or requests.Session()
        self._limiter = rate_limiter or RateLimiter()
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._timeout = timeout

    def _attesa(self, tentativo: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        base = 2.0 ** (tentativo - 1)
        return base + random.uniform(0.0, 0.1 * base)

    def _request(self, endpoint: str, params: dict, *, method: str = "GET") -> str:
        """Esegue una chiamata E-utilities e restituisce il corpo XML.

        Nessun messaggio di errore contiene l'URL: per le GET includerebbe api_key.
        """
        url = self.BASE_URL + endpoint
        payload = {
            **params,
            "tool": self._config.tool,
            "email": self._config.email,
            "api_key": self._config.api_key,
        }
        ultimo_status: int | None = None

        for tentativo in range(1, self._max_attempts + 1):
            self._limiter.acquire()
            try:
                if method == "POST":
                    resp = self._session.post(url, data=payload, timeout=self._timeout)
                else:
                    resp = self._session.get(url, params=payload, timeout=self._timeout)
            except requests.RequestException as exc:
                # str(exc) conterrebbe l'URL completo con api_key: si usa solo il tipo.
                if tentativo == self._max_attempts:
                    raise PubMedHTTPError(
                        f"{endpoint}: errore di rete dopo {tentativo} tentativi "
                        f"({type(exc).__name__})"
                    ) from None
                self._sleep(self._attesa(tentativo, None))
                continue

            if resp.status_code in STATUS_RITENTABILI:
                ultimo_status = resp.status_code
                if tentativo == self._max_attempts:
                    break
                self._sleep(self._attesa(tentativo, resp.headers.get("Retry-After")))
                continue

            if resp.status_code >= 400:
                raise PubMedHTTPError(f"{endpoint}: HTTP {resp.status_code}")

            errore = find_api_error(resp.text)
            if errore:
                raise PubMedAPIError(f"{endpoint}: {errore}")
            return resp.text

        raise PubMedHTTPError(
            f"{endpoint}: HTTP {ultimo_status} dopo {self._max_attempts} tentativi"
        )
