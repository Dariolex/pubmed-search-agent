"""Test di nl_query_translator: serializzazione pura JSON intermedio -> query PubMed."""

import pytest

from nl_query_translator import serialize


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
