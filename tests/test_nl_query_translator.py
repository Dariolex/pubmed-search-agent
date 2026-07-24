"""Test di nl_query_translator: serializzazione pura JSON intermedio -> query PubMed."""

import io
import json

import pytest

from nl_query_translator import serialize, main


def test_concetto_singolo_solo_tiab():
    intermedio = {"concetti": [{"termine": "metastatic", "sinonimi": [], "mesh": None}]}
    assert serialize(intermedio) == '"metastatic"[tiab]'


def test_concetto_singolo_con_mesh():
    intermedio = {"concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": "melanoma"}]}
    assert serialize(intermedio) == '("melanoma"[MeSH Terms] OR "melanoma"[tiab])'


def test_concetto_con_sinonimi_senza_mesh():
    intermedio = {
        "concetti": [
            {"termine": "immunotherapy", "sinonimi": ["immune checkpoint inhibitor"], "mesh": None}
        ]
    }
    assert serialize(intermedio) == (
        '("immunotherapy"[tiab] OR "immune checkpoint inhibitor"[tiab])'
    )


def test_concetto_con_mesh_e_sinonimi():
    intermedio = {
        "concetti": [
            {"termine": "melanoma", "sinonimi": ["malignant melanoma"], "mesh": "melanoma"}
        ]
    }
    assert serialize(intermedio) == (
        '("melanoma"[MeSH Terms] OR "melanoma"[tiab] OR "malignant melanoma"[tiab])'
    )


def test_due_concetti_in_and():
    intermedio = {
        "concetti": [
            {"termine": "melanoma", "sinonimi": [], "mesh": "melanoma"},
            {"termine": "metastatic", "sinonimi": [], "mesh": None},
        ],
        "operatore_tra_concetti": "AND",
    }
    assert serialize(intermedio) == (
        '("melanoma"[MeSH Terms] OR "melanoma"[tiab]) AND "metastatic"[tiab]'
    )


def test_due_concetti_in_or_vengono_racchiusi():
    intermedio = {
        "concetti": [
            {"termine": "melanoma", "sinonimi": [], "mesh": None},
            {"termine": "carcinoma", "sinonimi": [], "mesh": None},
        ],
        "operatore_tra_concetti": "OR",
    }
    assert serialize(intermedio) == '("melanoma"[tiab] OR "carcinoma"[tiab])'


def test_operatore_predefinito_e_and():
    intermedio = {
        "concetti": [
            {"termine": "a", "sinonimi": [], "mesh": None},
            {"termine": "b", "sinonimi": [], "mesh": None},
        ]
    }
    assert serialize(intermedio) == '"a"[tiab] AND "b"[tiab]'


def test_virgolette_interne_rimosse():
    intermedio = {"concetti": [{"termine": 'aberrant "gene"', "sinonimi": [], "mesh": None}]}
    assert serialize(intermedio) == '"aberrant gene"[tiab]'


def test_nessun_concetto_solleva_value_error():
    with pytest.raises(ValueError, match="concetto"):
        serialize({"concetti": []})


def test_concetto_senza_termine_solleva_value_error():
    with pytest.raises(ValueError, match="termine"):
        serialize({"concetti": [{"sinonimi": [], "mesh": None}]})


def test_operatore_ignoto_solleva_value_error():
    intermedio = {
        "concetti": [{"termine": "a", "sinonimi": [], "mesh": None}],
        "operatore_tra_concetti": "XOR",
    }
    with pytest.raises(ValueError, match="AND o OR"):
        serialize(intermedio)


def test_filtro_date_intervallo_completo():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"date": {"da": "2023", "a": "2026", "tipo": "dp"}},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND ("2023"[dp] : "2026"[dp])'


def test_filtro_date_solo_da():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"date": {"da": "2023", "tipo": "dp"}},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND ("2023"[dp] : "3000"[dp])'


def test_filtro_date_solo_a():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"date": {"a": "2026", "tipo": "edat"}},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND ("1000"[edat] : "2026"[edat])'


def test_tipo_studio_singolo():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"tipi_studio": ["randomized controlled trial"]},
    }
    assert serialize(intermedio) == (
        '"melanoma"[tiab] AND "randomized controlled trial"[pt]'
    )


def test_tipi_studio_multipli_in_or():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"tipi_studio": ["randomized controlled trial", "meta-analysis"]},
    }
    assert serialize(intermedio) == (
        '"melanoma"[tiab] AND '
        '("randomized controlled trial"[pt] OR "meta-analysis"[pt])'
    )


def test_filtro_lingua():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"lingua": "english"},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND "english"[la]'


def test_esclusioni_in_not():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "esclusioni": [{"termine": "case reports", "campo": "pt"}],
    }
    assert serialize(intermedio) == '"melanoma"[tiab] NOT "case reports"[pt]'


def test_esclusione_campo_predefinito_tiab():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "esclusioni": [{"termine": "pediatric"}],
    }
    assert serialize(intermedio) == '"melanoma"[tiab] NOT "pediatric"[tiab]'


def test_ordine_canonico_stabile():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {
            "date": {"da": "2023", "a": "2026", "tipo": "dp"},
            "tipi_studio": ["review"],
            "lingua": "english",
        },
        "esclusioni": [{"termine": "case reports", "campo": "pt"}],
    }
    atteso = (
        '"melanoma"[tiab] AND ("2023"[dp] : "2026"[dp]) AND "review"[pt] '
        'AND "english"[la] NOT "case reports"[pt]'
    )
    assert serialize(intermedio) == atteso
    assert serialize(intermedio) == atteso  # stesso input -> stessa stringa


def test_tipo_data_ignoto_solleva_value_error():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"date": {"da": "2023", "a": "2026", "tipo": "xyz"}},
    }
    with pytest.raises(ValueError, match="tipo data"):
        serialize(intermedio)


def test_esclusione_senza_termine_solleva_value_error():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "esclusioni": [{"campo": "pt"}],
    }
    with pytest.raises(ValueError, match="esclusione"):
        serialize(intermedio)


def test_query_di_riferimento_claude_md():
    """La query di esempio del CLAUDE.md sezione 1, forma canonica."""
    intermedio = {
        "intento_originale": "immunoterapia nel melanoma metastatico, RCT, no case report",
        "concetti": [
            {"termine": "melanoma", "sinonimi": [], "mesh": "melanoma"},
            {"termine": "immunotherapy", "sinonimi": [], "mesh": "immunotherapy"},
            {"termine": "metastatic", "sinonimi": [], "mesh": None},
        ],
        "operatore_tra_concetti": "AND",
        "esclusioni": [{"termine": "case reports", "campo": "pt"}],
        "filtri": {
            "date": {"da": "2023", "a": "2026", "tipo": "dp"},
            "tipi_studio": ["randomized controlled trial"],
        },
    }
    atteso = (
        '("melanoma"[MeSH Terms] OR "melanoma"[tiab]) AND '
        '("immunotherapy"[MeSH Terms] OR "immunotherapy"[tiab]) AND '
        '"metastatic"[tiab] AND ("2023"[dp] : "2026"[dp]) AND '
        '"randomized controlled trial"[pt] NOT "case reports"[pt]'
    )
    assert serialize(intermedio) == atteso


# ============ CLI tests (Task 3)

_JSON_MELANOMA = '{"concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": null}]}'


def test_cli_legge_da_stdin_e_stampa_query(capsys):
    codice = main(argv=[], stdin=io.StringIO(_JSON_MELANOMA))
    out = capsys.readouterr()
    assert codice == 0
    assert out.out.strip() == '"melanoma"[tiab]'
    assert out.err == ""


def test_cli_opzione_link_aggiunge_url(capsys):
    codice = main(argv=["--link"], stdin=io.StringIO(_JSON_MELANOMA))
    out = capsys.readouterr()
    righe = out.out.strip().splitlines()
    assert codice == 0
    assert righe[0] == '"melanoma"[tiab]'
    assert righe[1].startswith("https://pubmed.ncbi.nlm.nih.gov/?term=")


def test_cli_json_malformato_esce_con_errore(capsys):
    codice = main(argv=[], stdin=io.StringIO("{non-json"))
    out = capsys.readouterr()
    assert codice == 1
    assert out.err.strip() != ""
    assert out.out == ""


def test_cli_json_semanticamente_invalido_esce_con_errore(capsys):
    codice = main(argv=[], stdin=io.StringIO('{"concetti": []}'))
    out = capsys.readouterr()
    assert codice == 1
    assert "concetto" in out.err


def test_cli_legge_da_file(tmp_path, capsys):
    percorso = tmp_path / "query.json"
    percorso.write_text(_JSON_MELANOMA, encoding="utf-8")
    codice = main(argv=["--file", str(percorso)])
    out = capsys.readouterr()
    assert codice == 0
    assert out.out.strip() == '"melanoma"[tiab]'


def test_cli_json_non_dict_esce_con_errore(capsys):
    """JSON valido ma non-dict (numero, array, null, bool) è errore semantico."""
    # Test con numero
    codice = main(argv=[], stdin=io.StringIO("42"))
    out = capsys.readouterr()
    assert codice == 1
    assert "oggetto" in out.err
    assert out.out == ""

    # Test con array
    codice = main(argv=[], stdin=io.StringIO("[1, 2, 3]"))
    out = capsys.readouterr()
    assert codice == 1
    assert "oggetto" in out.err
    assert out.out == ""

    # Test con null
    codice = main(argv=[], stdin=io.StringIO("null"))
    out = capsys.readouterr()
    assert codice == 1
    assert "oggetto" in out.err
    assert out.out == ""

    # Test con bool
    codice = main(argv=[], stdin=io.StringIO("true"))
    out = capsys.readouterr()
    assert codice == 1
    assert "oggetto" in out.err
    assert out.out == ""
