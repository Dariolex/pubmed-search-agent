"""
Registra risposte reali di NCBI in tests/fixtures/.

Le fixture scritte a mano tendono a essere versioni idealizzate della realtà e
perdono proprio i casi limite che rompono il parser. Qui si salva XML autentico:
quando NCBI cambia schema, si rigenera e si guarda il diff.

Uso:
    python tests/record_fixtures.py

Richiede una .env valida. Ogni file viene ripulito dalla api_key prima della
scrittura: tests/fixtures/ finisce in git, .env no.
"""

from __future__ import annotations

import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "src"))

from pubmed_client import PubMedClient, PubMedConfig  # noqa: E402

FIXTURES = RADICE / "tests" / "fixtures"

# PMID candidati per i casi limite. Lo script verifica che abbiano davvero la
# caratteristica richiesta e si ferma se non è così: in quel caso sostituire il
# PMID con uno che la soddisfi.
PMID_ABSTRACT_STRUTTURATO = "33301246"
PMID_SENZA_ABSTRACT = "1"
PMID_AUTORE_COLLETTIVO = "42140479"
PMID_CON_CITAZIONI = "33301246"


def _ripulisci(testo: str, chiave: str) -> str:
    return testo.replace(chiave, "API_KEY_RIMOSSA")


def _scrivi(nome: str, contenuto: str, chiave: str) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    percorso = FIXTURES / nome
    percorso.write_text(_ripulisci(contenuto, chiave), encoding="utf-8")
    print(f"  scritto {percorso.relative_to(RADICE)} ({len(contenuto)} byte)")


def _verifica(nome: str, condizione: bool, descrizione: str) -> bool:
    esito = "OK  " if condizione else "FAIL"
    print(f"  [{esito}] {nome}: {descrizione}")
    return condizione


def main() -> int:
    config = PubMedConfig.from_env()
    client = PubMedClient(config)
    chiave = config.api_key
    tutto_ok = True

    print("esearch_basic.xml — caso nominale con QueryTranslation")
    xml = client._request(
        "esearch.fcgi",
        {"db": "pubmed", "term": "melanoma immunotherapy", "usehistory": "y",
         "retmax": "5", "retmode": "xml"},
    )
    tutto_ok &= _verifica("esearch_basic", "<QueryTranslation>" in xml, "contiene QueryTranslation")
    _scrivi("esearch_basic.xml", xml, chiave)

    print("esearch_zero_results.xml — Count=0")
    xml = client._request(
        "esearch.fcgi",
        {"db": "pubmed", "term": '"zzzzqwertynonesiste12345"[tiab]',
         "usehistory": "y", "retmax": "5", "retmode": "xml"},
    )
    tutto_ok &= _verifica("esearch_zero", "<Count>0</Count>" in xml, "Count vale 0")
    _scrivi("esearch_zero_results.xml", xml, chiave)

    print("esearch_error.xml — HTTP 200 con <ERROR>")
    # _request solleverebbe PubMedAPIError: qui serve il corpo grezzo.
    import requests

    risposta = requests.get(
        client.BASE_URL + "esearch.fcgi",
        params={"db": "pubmed", "term": "()", "retmode": "xml",
                "tool": config.tool, "email": config.email, "api_key": chiave},
        timeout=(5, 30),
    )
    xml = risposta.text
    tutto_ok &= _verifica("esearch_error", "<ERROR>" in xml, "contiene <ERROR>")
    tutto_ok &= _verifica("esearch_error", risposta.status_code == 200, "status è 200")
    _scrivi("esearch_error.xml", xml, chiave)

    print("efetch_batch.xml — più articoli, uno con abstract strutturato")
    xml = client._request(
        "efetch.fcgi",
        {"db": "pubmed", "id": f"{PMID_ABSTRACT_STRUTTURATO},{PMID_AUTORE_COLLETTIVO}",
         "rettype": "abstract", "retmode": "xml"},
        method="POST",
    )
    tutto_ok &= _verifica("efetch_batch", 'Label="' in xml, "contiene un abstract strutturato")
    _scrivi("efetch_batch.xml", xml, chiave)

    print("efetch_no_abstract.xml — articolo privo di abstract")
    xml = client._request(
        "efetch.fcgi",
        {"db": "pubmed", "id": PMID_SENZA_ABSTRACT, "rettype": "abstract", "retmode": "xml"},
        method="POST",
    )
    tutto_ok &= _verifica("efetch_no_abstract", "<Abstract>" not in xml, "nessun <Abstract>")
    _scrivi("efetch_no_abstract.xml", xml, chiave)

    print("efetch_collective_author.xml — <CollectiveName>")
    xml = client._request(
        "efetch.fcgi",
        {"db": "pubmed", "id": PMID_AUTORE_COLLETTIVO, "rettype": "abstract", "retmode": "xml"},
        method="POST",
    )
    tutto_ok &= _verifica("efetch_collective", "<CollectiveName>" in xml, "contiene CollectiveName")
    _scrivi("efetch_collective_author.xml", xml, chiave)

    print("mesh_esearch_match.xml — match esatto su db=mesh (melanoma)")
    xml = client._request(
        "esearch.fcgi",
        {"db": "mesh", "term": "melanoma[MeSH Terms:noexp]", "retmode": "xml"},
    )
    tutto_ok &= _verifica("mesh_esearch_match", "<Count>1</Count>" in xml, "Count vale 1")
    _scrivi("mesh_esearch_match.xml", xml, chiave)

    print("mesh_esearch_no_match.xml — nessun match su db=mesh")
    xml = client._request(
        "esearch.fcgi",
        {"db": "mesh", "term": "zzzznonesistequestotermine[MeSH Terms:noexp]", "retmode": "xml"},
    )
    tutto_ok &= _verifica("mesh_esearch_no_match", "<Count>0</Count>" in xml, "Count vale 0")
    _scrivi("mesh_esearch_no_match.xml", xml, chiave)

    print("mesh_esummary_match.xml — descriptor + entry term (melanoma, UID 68008545)")
    xml = client._request(
        "esummary.fcgi", {"db": "mesh", "id": "68008545", "retmode": "xml"}
    )
    tutto_ok &= _verifica("mesh_esummary_match", "DS_MeshTerms" in xml, "contiene DS_MeshTerms")
    tutto_ok &= _verifica("mesh_esummary_match", "Melanoma" in xml, "contiene il descriptor atteso")
    _scrivi("mesh_esummary_match.xml", xml, chiave)

    print("elink_simili.xml — articoli simili a un PMID noto")
    xml = client._request(
        "elink.fcgi",
        {"dbfrom": "pubmed", "db": "pubmed", "id": PMID_CON_CITAZIONI,
         "linkname": "pubmed_pubmed", "retmode": "xml"},
    )
    tutto_ok &= _verifica("elink_simili", "<LinkSetDb>" in xml, "contiene LinkSetDb")
    _scrivi("elink_simili.xml", xml, chiave)

    print("elink_citazioni.xml — articoli che citano un PMID noto")
    xml = client._request(
        "elink.fcgi",
        {"dbfrom": "pubmed", "db": "pubmed", "id": PMID_CON_CITAZIONI,
         "linkname": "pubmed_pubmed_citedin", "retmode": "xml"},
    )
    tutto_ok &= _verifica("elink_citazioni", "<LinkSetDb>" in xml, "contiene LinkSetDb")
    _scrivi("elink_citazioni.xml", xml, chiave)

    if not tutto_ok:
        print("\nAlcune verifiche sono fallite: sostituire i PMID candidati in cima")
        print("a questo file con record che soddisfino la caratteristica richiesta,")
        print("poi rieseguire.")
        return 1

    print("\nTutte le fixture registrate e verificate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
