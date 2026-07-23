"""Verifica che la gerarchia di eccezioni permetta di catturare tutto con un solo except."""

import pytest

from pubmed_errors import (
    PubMedAPIError,
    PubMedConfigError,
    PubMedError,
    PubMedHTTPError,
    PubMedParseError,
)


@pytest.mark.parametrize(
    "exc_type",
    [PubMedConfigError, PubMedAPIError, PubMedHTTPError, PubMedParseError],
)
def test_ogni_eccezione_deriva_da_pubmed_error(exc_type):
    assert issubclass(exc_type, PubMedError)


def test_pubmed_error_cattura_le_sottoclassi():
    with pytest.raises(PubMedError):
        raise PubMedAPIError("query malformata")


def test_il_messaggio_e_preservato():
    with pytest.raises(PubMedHTTPError, match="HTTP 503"):
        raise PubMedHTTPError("esearch.fcgi: HTTP 503")
