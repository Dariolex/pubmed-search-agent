"""Test di export_results: conversione JSON -> RIS/BibTeX, interamente offline."""

import json

import pytest

from export_results import esporta, main

ARTICOLO_COMPLETO = {
    "pmid": "33301246",
    "title": "Un titolo di test",
    "abstract": "Un abstract di test.",
    "authors": ["Rossi M", "Bianchi L"],
    "journal": "J Test",
    "pub_date": "2024-03-15",
    "pub_types": ["Journal Article"],
    "mesh_terms": [],
    "doi": "10.1000/test123",
    "coi_statement": None,
}

ARTICOLO_SENZA_DOI_ABSTRACT = {
    "pmid": "1",
    "title": "Senza DOI né abstract",
    "abstract": None,
    "authors": ["Verdi G"],
    "journal": "J Minimal",
    "pub_date": "2023",
    "pub_types": [],
    "mesh_terms": [],
    "doi": None,
    "coi_statement": None,
}

DATI_DUE_ARTICOLI = {
    "total_count": 2,
    "translated_query": None,
    "warnings": [],
    "articles": [ARTICOLO_COMPLETO, ARTICOLO_SENZA_DOI_ABSTRACT],
}


def test_ris_contiene_i_campi_principali():
    out = esporta(DATI_DUE_ARTICOLI, "ris")
    assert "TY  - JOUR" in out
    assert "AU  - Rossi M" in out
    assert "AU  - Bianchi L" in out
    assert "TI  - Un titolo di test" in out
    assert "JO  - J Test" in out
    assert "PY  - 2024" in out
    assert "DO  - 10.1000/test123" in out
    assert "AB  - Un abstract di test." in out
    assert "ID  - 33301246" in out
    assert out.count("ER  -") == 2  # un record per articolo


def test_ris_omette_doi_e_abstract_assenti():
    out = esporta(DATI_DUE_ARTICOLI, "ris")
    # Il secondo record (PMID 1) non deve avere righe DO/AB proprie: verifichiamo
    # che non compaia alcuna riga "DO  - None" o "AB  - None" (bug tipico di
    # una f-string che non gestisce il caso assente).
    assert "DO  - None" not in out
    assert "AB  - None" not in out
    assert "PY  - 2023" in out


def test_bibtex_contiene_i_campi_principali():
    out = esporta(DATI_DUE_ARTICOLI, "bibtex")
    assert "@article{pmid33301246," in out
    assert "author = {Rossi M and Bianchi L}" in out
    assert "title = {Un titolo di test}" in out
    assert "journal = {J Test}" in out
    assert "year = {2024}" in out
    assert "doi = {10.1000/test123}" in out


def test_bibtex_omette_doi_assente():
    out = esporta(DATI_DUE_ARTICOLI, "bibtex")
    assert "@article{pmid1," in out
    # Il record del secondo articolo (senza doi) non deve contenere alcuna riga
    # "doi = ...": né "doi = {None}" né una riga doi vuota.
    inizio_secondo = out.index("@article{pmid1,")
    secondo_record = out[inizio_secondo:]
    assert "doi = " not in secondo_record


def test_formato_ignoto_solleva_value_error():
    with pytest.raises(ValueError):
        esporta(DATI_DUE_ARTICOLI, "csv")


def test_nessun_articolo_produce_stringa_vuota():
    assert esporta({"articles": []}, "ris") == ""
    assert esporta({"articles": []}, "bibtex") == ""


def test_main_legge_da_file_e_stampa_ris(tmp_path, capsys):
    percorso = tmp_path / "risultati.json"
    percorso.write_text(json.dumps(DATI_DUE_ARTICOLI), encoding="utf-8")
    codice = main(argv=["--formato", "ris", "--file", str(percorso)])
    out = capsys.readouterr()
    assert codice == 0
    assert "TY  - JOUR" in out.out


def test_main_legge_da_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(DATI_DUE_ARTICOLI)))
    codice = main(argv=["--formato", "bibtex"])
    out = capsys.readouterr()
    assert codice == 0
    assert "@article{pmid33301246," in out.out


def test_main_json_malformato_esce_con_errore(capsys):
    codice = main(argv=["--formato", "ris", "--file", "/percorso/inesistente.json"])
    out = capsys.readouterr()
    assert codice == 1
    assert "Errore" in out.err
