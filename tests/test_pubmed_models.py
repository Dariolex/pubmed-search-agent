"""Test di parsing puro: nessuna rete, nessun mock, solo stringhe XML."""

import pytest

from pubmed_errors import PubMedParseError
from pubmed_models import Article, SearchResult, find_api_error, parse_efetch_xml, parse_esearch_xml

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


def test_count_non_numerico_solleva_parse_error():
    xml = "<eSearchResult><Count>abc</Count></eSearchResult>"
    with pytest.raises(PubMedParseError, match="Valore di <Count> non numerico"):
        parse_esearch_xml(xml)


EFETCH_NOMINALE = """<?xml version="1.0" encoding="UTF-8" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation Status="MEDLINE" Owner="NLM">
    <PMID Version="1">38000001</PMID>
    <Article PubModel="Print">
      <Journal>
        <JournalIssue CitedMedium="Internet">
          <Volume>30</Volume>
          <PubDate>
            <Year>2024</Year>
            <Month>Mar</Month>
            <Day>15</Day>
          </PubDate>
        </JournalIssue>
        <Title>Nature Medicine</Title>
        <ISOAbbreviation>Nat Med</ISOAbbreviation>
      </Journal>
      <ArticleTitle>Immunotherapy in <i>metastatic</i> melanoma.</ArticleTitle>
      <Abstract>
        <AbstractText>Un singolo paragrafo di abstract.</AbstractText>
      </Abstract>
      <AuthorList CompleteYN="Y">
        <Author ValidYN="Y">
          <LastName>Rossi</LastName>
          <ForeName>Maria</ForeName>
          <Initials>M</Initials>
        </Author>
        <Author ValidYN="Y">
          <LastName>Bianchi</LastName>
          <Initials>G</Initials>
        </Author>
      </AuthorList>
      <PublicationTypeList>
        <PublicationType UI="D016449">Randomized Controlled Trial</PublicationType>
        <PublicationType UI="D016428">Journal Article</PublicationType>
      </PublicationTypeList>
      <ELocationID EIdType="doi" ValidYN="Y">10.1038/s41591-024-00001-1</ELocationID>
    </Article>
    <MeshHeadingList>
      <MeshHeading>
        <DescriptorName UI="D008545" MajorTopicYN="N">Melanoma</DescriptorName>
        <QualifierName UI="Q000628" MajorTopicYN="Y">therapy</QualifierName>
      </MeshHeading>
      <MeshHeading>
        <DescriptorName UI="D007167" MajorTopicYN="Y">Immunotherapy</DescriptorName>
      </MeshHeading>
    </MeshHeadingList>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">38000001</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""


def test_efetch_parsing_nominale():
    articles = parse_efetch_xml(EFETCH_NOMINALE)
    assert len(articles) == 1
    art = articles[0]
    assert isinstance(art, Article)
    assert art.pmid == "38000001"
    assert art.journal == "Nature Medicine"
    assert art.pub_date == "2024-03-15"
    assert art.doi == "10.1038/s41591-024-00001-1"


def test_titolo_include_il_markup_inline():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.title == "Immunotherapy in metastatic melanoma."


def test_autori_nome_e_cognome():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.authors == ["Maria Rossi", "G Bianchi"]


def test_tipi_di_pubblicazione():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.pub_types == ["Randomized Controlled Trial", "Journal Article"]


def test_mesh_terms_solo_descrittori():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.mesh_terms == ["Melanoma", "Immunotherapy"]


def test_abstract_semplice():
    art = parse_efetch_xml(EFETCH_NOMINALE)[0]
    assert art.abstract == "Un singolo paragrafo di abstract."


def test_set_vuoto_restituisce_lista_vuota():
    assert parse_efetch_xml("<PubmedArticleSet/>") == []


def test_citazione_senza_pmid_solleva_parse_error():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation>
    <Article><ArticleTitle>Senza PMID</ArticleTitle></Article>
    </MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    with pytest.raises(PubMedParseError, match="PMID"):
        parse_efetch_xml(xml)
