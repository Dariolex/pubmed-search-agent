"""Test di parsing puro: nessuna rete, nessun mock, solo stringhe XML."""

import pytest

from pubmed_errors import PubMedParseError
from pubmed_models import SearchResult, find_api_error, parse_esearch_xml

ESEARCH_BASE = """<?xml version="1.0" encoding="UTF-8" ?>
<eSearchResult>
  <Count>1234</Count>
  <RetMax>2</RetMax>
  <RetStart>0</RetStart>
  <QueryKey>1</QueryKey>
  <WebEnv>MCID_abc123def</WebEnv>
  <IdList>
    <Id>38000001</Id>
    <Id>38000002</Id>
  </IdList>
  <QueryTranslation>"melanoma"[MeSH Terms] OR "melanoma"[All Fields]</QueryTranslation>
</eSearchResult>
"""

ESEARCH_ZERO = """<?xml version="1.0" encoding="UTF-8" ?>
<eSearchResult>
  <Count>0</Count>
  <RetMax>0</RetMax>
  <RetStart>0</RetStart>
  <IdList/>
  <QueryTranslation>"zzzznonesiste"[All Fields]</QueryTranslation>
</eSearchResult>
"""

ESEARCH_PHRASE_NOT_FOUND = """<?xml version="1.0" encoding="UTF-8" ?>
<eSearchResult>
  <Count>7</Count>
  <IdList><Id>38000003</Id></IdList>
  <ErrorList>
    <PhraseNotFound>immunoterapia</PhraseNotFound>
    <FieldNotFound>xyz</FieldNotFound>
  </ErrorList>
  <QueryTranslation>melanoma[All Fields]</QueryTranslation>
</eSearchResult>
"""

ESEARCH_HARD_ERROR = """<?xml version="1.0" encoding="UTF-8" ?>
<eSearchResult>
  <ERROR>Can't run executor</ERROR>
</eSearchResult>
"""

EFETCH_ROOT_ERROR = """<?xml version="1.0" encoding="UTF-8" ?>
<ERROR>Empty id list; nothing todo</ERROR>
"""


def test_parsing_nominale():
    result = parse_esearch_xml(ESEARCH_BASE)
    assert isinstance(result, SearchResult)
    assert result.pmids == ["38000001", "38000002"]
    assert result.total_count == 1234
    assert result.webenv == "MCID_abc123def"
    assert result.query_key == "1"
    assert result.translated_query == '"melanoma"[MeSH Terms] OR "melanoma"[All Fields]'
    assert result.warnings == []


def test_zero_risultati_non_e_un_errore():
    result = parse_esearch_xml(ESEARCH_ZERO)
    assert result.total_count == 0
    assert result.pmids == []
    assert result.translated_query == '"zzzznonesiste"[All Fields]'


def test_phrase_not_found_e_un_avviso_non_un_errore():
    result = parse_esearch_xml(ESEARCH_PHRASE_NOT_FOUND)
    assert result.total_count == 7
    assert result.pmids == ["38000003"]
    assert result.warnings == ["PhraseNotFound: immunoterapia", "FieldNotFound: xyz"]


def test_find_api_error_rileva_error_annidato():
    assert find_api_error(ESEARCH_HARD_ERROR) == "Can't run executor"


def test_find_api_error_rileva_error_come_radice():
    assert find_api_error(EFETCH_ROOT_ERROR) == "Empty id list; nothing todo"


def test_find_api_error_ignora_error_list():
    assert find_api_error(ESEARCH_PHRASE_NOT_FOUND) is None


def test_find_api_error_su_risposta_valida():
    assert find_api_error(ESEARCH_BASE) is None


def test_xml_non_valido_solleva_parse_error():
    with pytest.raises(PubMedParseError):
        parse_esearch_xml("<eSearchResult><Count>3</Count>")


def test_esearch_senza_count_solleva_parse_error():
    with pytest.raises(PubMedParseError, match="Count"):
        parse_esearch_xml("<eSearchResult><IdList/></eSearchResult>")


def test_search_result_e_immutabile():
    result = parse_esearch_xml(ESEARCH_BASE)
    with pytest.raises(Exception):
        result.total_count = 99
