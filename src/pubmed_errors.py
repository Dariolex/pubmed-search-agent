"""
pubmed_errors.py

Gerarchia di eccezioni condivisa da pubmed_models.py e pubmed_client.py.

Vive in un modulo proprio perché il parser (pubmed_models) deve poter sollevare
PubMedParseError e il client importa il parser: definirle nel client creerebbe un
import circolare.
"""


class PubMedError(Exception):
    """Base di tutti gli errori del client PubMed."""


class PubMedConfigError(PubMedError):
    """Variabili d'ambiente mancanti o non valide. Sollevata all'avvio."""


class PubMedAPIError(PubMedError):
    """NCBI ha risposto HTTP 200 con un <ERROR> nel corpo (tipicamente query malformata).

    Non è ritentabile: ripetere la stessa query produce lo stesso errore.
    """


class PubMedHTTPError(PubMedError):
    """Errore di trasporto non recuperato dopo tutti i tentativi.

    Il messaggio non contiene mai l'URL: per le richieste GET includerebbe api_key.
    """


class PubMedParseError(PubMedError):
    """XML sintatticamente valido ma con una struttura inattesa."""
