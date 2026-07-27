"""
Test contro le API NCBI reali.

Esclusi di default da pytest.ini. Si eseguono con:
    pytest -m live -v

Richiedono una .env valida. Asseriscono sulla struttura e non sul contenuto
esatto, perché PubMed corregge i propri metadati nel tempo.
"""

import time

import pytest

from pubmed_client import PubMedClient, PubMedConfig
from pubmed_errors import PubMedAPIError

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client():
    try:
        config = PubMedConfig.from_env()
    except Exception as exc:
        pytest.skip(f"configurazione NCBI assente: {exc}")
    return PubMedClient(config)


def test_esearch_reale_trova_risultati(client):
    risultato = client.esearch('"melanoma"[MeSH Terms]', retmax=5)
    assert risultato.total_count > 1000
    assert len(risultato.pmids) == 5
    assert all(p.isdigit() for p in risultato.pmids)
    assert risultato.translated_query
    assert risultato.webenv


def test_esearch_reale_senza_risultati(client):
    risultato = client.esearch('"zzzzqwertynonesiste12345"[tiab]')
    assert risultato.total_count == 0
    assert risultato.pmids == []


def test_query_malformata_solleva_api_error(client):
    # NCBI ignora silenziosamente le parentesi sbilanciate (le riporta solo in
    # WarningList, senza <ERROR>): "melanoma AND (" non fa quindi fallire la
    # richiesta. Un termine vuoto invece produce un vero <ERROR> lato NCBI
    # ("Empty term and query_key - nothing todo"), verificato manualmente
    # contro l'endpoint reale: è questo il caso che esercita davvero il
    # percorso find_api_error/PubMedAPIError del client.
    with pytest.raises(PubMedAPIError):
        client.esearch("")


def test_efetch_reale_restituisce_abstract(client):
    ricerca = client.esearch('"melanoma"[MeSH Terms] AND hasabstract', retmax=3)
    articoli = client.efetch(ricerca.pmids)
    assert [a.pmid for a in articoli] == ricerca.pmids
    for art in articoli:
        assert art.title
        assert art.journal
        assert art.pub_date[:4].isdigit()
        assert art.abstract


def test_quindici_richieste_rapide_non_producono_429(client):
    """Verifica che il token bucket tenga sotto il limite reale di NCBI."""
    inizio = time.monotonic()
    for _ in range(15):
        client.esearch("melanoma", retmax=1)
    trascorso = time.monotonic() - inizio
    assert trascorso >= 0.4, "15 richieste non possono essere istantanee a 10 req/s"


def test_resolve_mesh_reale_trova_melanoma(client):
    match = client.resolve_mesh("melanoma")
    assert match is not None
    assert match.descriptor == "Melanoma"
    assert len(match.entry_terms) > 0
    assert match.mesh_ui.isdigit()


def test_resolve_mesh_reale_nessun_match_per_termine_inventato(client):
    match = client.resolve_mesh("zzzznonesistequestotermine12345")
    assert match is None


def test_filtro_brevetto_reale_restituisce_dichiarazioni(client):
    """Il filtro [cois] trova articoli reali e il testo della dichiarazione
    arriva fino ad Article.coi_statement, dove il filtro semantico può leggerlo."""
    from nl_query_translator import serialize

    query = serialize(
        {
            "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
            "filtri": {"brevetto": True},
        }
    )
    assert query == '"melanoma"[tiab] AND "patent*"[cois]'

    ricerca = client.esearch(query, retmax=5)
    assert ricerca.total_count > 0
    articoli = client.efetch(ricerca.pmids)
    # Ogni articolo trovato via [cois] ha per definizione una dichiarazione COI,
    # e deve contenere la radice "patent" (in qualsiasi forma flessa).
    assert articoli
    for art in articoli:
        assert art.coi_statement is not None
        assert "patent" in art.coi_statement.lower()
