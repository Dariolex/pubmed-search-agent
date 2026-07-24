"""Test di parsing puro: nessuna rete, nessun mock, solo stringhe XML."""

import pytest
from pathlib import Path

from pubmed_errors import PubMedParseError
from pubmed_models import (
    Article,
    SearchResult,
    MeshMatch,
    find_api_error,
    parse_efetch_xml,
    parse_esearch_xml,
    parse_mesh_esummary_xml,
)

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


def test_articolo_senza_medline_citation_solleva_parse_error():
    xml = "<PubmedArticleSet><PubmedArticle></PubmedArticle></PubmedArticleSet>"
    with pytest.raises(PubMedParseError, match="MedlineCitation"):
        parse_efetch_xml(xml)


EFETCH_CASI_LIMITE = """<?xml version="1.0" encoding="UTF-8" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">30000001</PMID>
    <Article>
      <Journal>
        <JournalIssue><PubDate><Year>2019</Year><Month>07</Month></PubDate></JournalIssue>
        <Title>Journal of Structured Abstracts</Title>
      </Journal>
      <ArticleTitle>Trial con abstract strutturato.</ArticleTitle>
      <Abstract>
        <AbstractText Label="BACKGROUND">Il melanoma metastatico ha prognosi infausta.</AbstractText>
        <AbstractText Label="METHODS">Abbiamo randomizzato 300 pazienti.</AbstractText>
        <AbstractText Label="RESULTS">La sopravvivenza è aumentata.</AbstractText>
      </Abstract>
      <AuthorList>
        <Author><CollectiveName>The CheckMate Study Group</CollectiveName></Author>
        <Author><LastName>Verdi</LastName><ForeName>Anna</ForeName></Author>
      </AuthorList>
    </Article>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">30000001</ArticleId>
      <ArticleId IdType="doi">10.9999/fallback.doi</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">30000002</PMID>
    <Article>
      <Journal>
        <JournalIssue><PubDate><Year>1975</Year></PubDate></JournalIssue>
        <Title>Old Journal</Title>
      </Journal>
      <ArticleTitle>Articolo senza abstract né autori.</ArticleTitle>
    </Article>
  </MedlineCitation>
</PubmedArticle>
<PubmedArticle>
  <MedlineCitation>
    <PMID Version="1">30000003</PMID>
    <Article>
      <Journal>
        <JournalIssue><PubDate><MedlineDate>1998 Mar-Apr</MedlineDate></PubDate></JournalIssue>
        <Title>Seasonal Journal</Title>
      </Journal>
      <ArticleTitle>Data in formato MedlineDate.</ArticleTitle>
      <Abstract><AbstractText Label="AIM"></AbstractText></Abstract>
    </Article>
  </MedlineCitation>
</PubmedArticle>
</PubmedArticleSet>
"""


@pytest.fixture
def casi_limite():
    return {a.pmid: a for a in parse_efetch_xml(EFETCH_CASI_LIMITE)}


def test_abstract_strutturato_conserva_le_etichette(casi_limite):
    abstract = casi_limite["30000001"].abstract
    assert abstract == (
        "BACKGROUND: Il melanoma metastatico ha prognosi infausta.\n\n"
        "METHODS: Abbiamo randomizzato 300 pazienti.\n\n"
        "RESULTS: La sopravvivenza è aumentata."
    )


def test_nome_collettivo_diventa_un_autore(casi_limite):
    assert casi_limite["30000001"].authors == ["The CheckMate Study Group", "Anna Verdi"]


def test_doi_di_riserva_da_article_id_list(casi_limite):
    assert casi_limite["30000001"].doi == "10.9999/fallback.doi"


def test_data_parziale_anno_mese(casi_limite):
    assert casi_limite["30000001"].pub_date == "2019-07"


def test_abstract_assente_e_none_non_stringa_vuota(casi_limite):
    assert casi_limite["30000002"].abstract is None


def test_autori_assenti_danno_lista_vuota(casi_limite):
    assert casi_limite["30000002"].authors == []


def test_doi_assente_e_none(casi_limite):
    assert casi_limite["30000002"].doi is None


def test_data_solo_anno(casi_limite):
    assert casi_limite["30000002"].pub_date == "1975"


def test_medline_date_riduce_all_anno(casi_limite):
    assert casi_limite["30000003"].pub_date == "1998"


def test_abstract_con_solo_etichette_vuote_e_none(casi_limite):
    assert casi_limite["30000003"].abstract is None


def test_ordine_dei_record_preservato():
    articles = parse_efetch_xml(EFETCH_CASI_LIMITE)
    assert [a.pmid for a in articles] == ["30000001", "30000002", "30000003"]


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(nome: str) -> str:
    percorso = FIXTURES / nome
    if not percorso.exists():
        pytest.skip(f"{nome} non registrata: eseguire python tests/record_fixtures.py")
    return percorso.read_text(encoding="utf-8")


def test_fixture_esearch_reale():
    result = parse_esearch_xml(_fixture("esearch_basic.xml"))
    assert result.total_count > 0
    assert len(result.pmids) > 0
    assert all(p.isdigit() for p in result.pmids)
    assert result.translated_query
    assert result.webenv


def test_fixture_esearch_zero_risultati():
    result = parse_esearch_xml(_fixture("esearch_zero_results.xml"))
    assert result.total_count == 0
    assert result.pmids == []


def test_fixture_esearch_error_rilevata():
    assert find_api_error(_fixture("esearch_error.xml")) is not None


def test_fixture_efetch_batch_reale():
    articoli = parse_efetch_xml(_fixture("efetch_batch.xml"))
    assert len(articoli) >= 1
    for art in articoli:
        assert art.pmid.isdigit()
        assert art.title
        assert art.journal
        assert art.pub_date[:4].isdigit()


def test_fixture_abstract_strutturato_reale():
    articoli = parse_efetch_xml(_fixture("efetch_batch.xml"))
    strutturati = [a for a in articoli if a.abstract and ": " in a.abstract]
    assert strutturati, "nessun abstract strutturato nella fixture"


def test_fixture_senza_abstract_reale():
    articoli = parse_efetch_xml(_fixture("efetch_no_abstract.xml"))
    assert len(articoli) == 1
    assert articoli[0].abstract is None
    assert articoli[0].title


def test_fixture_autore_collettivo_reale():
    articoli = parse_efetch_xml(_fixture("efetch_collective_author.xml"))
    assert articoli[0].authors, "nessun autore estratto"


def test_nessuna_fixture_contiene_api_key():
    for percorso in FIXTURES.glob("*.xml"):
        assert "api_key=" not in percorso.read_text(encoding="utf-8")


MESH_ESUMMARY_MATCH = """<?xml version="1.0" ?>
<eSummaryResult>
<DocSum>
	<Id>68008545</Id>
	<Item Name="DS_ScopeNote" Type="String">A malignant neoplasm derived from cells capable of forming melanin.</Item>
	<Item Name="DS_MeshTerms" Type="List">
		<Item Name="string" Type="String">Melanoma</Item>
		<Item Name="string" Type="String">Melanomas</Item>
		<Item Name="string" Type="String">Malignant Melanoma</Item>
		<Item Name="string" Type="String">Malignant Melanomas</Item>
		<Item Name="string" Type="String">Melanoma, Malignant</Item>
		<Item Name="string" Type="String">Melanomas, Malignant</Item>
	</Item>
</DocSum>
</eSummaryResult>
"""

MESH_ESUMMARY_UN_SOLO_TERMINE = """<?xml version="1.0" ?>
<eSummaryResult>
<DocSum>
	<Id>68007167</Id>
	<Item Name="DS_MeshTerms" Type="List">
		<Item Name="string" Type="String">Immunotherapy</Item>
	</Item>
</DocSum>
</eSummaryResult>
"""

MESH_ESUMMARY_SENZA_DOCSUM = """<?xml version="1.0" ?>
<eSummaryResult>
</eSummaryResult>
"""

MESH_ESUMMARY_MESHTERMS_VUOTO = """<?xml version="1.0" ?>
<eSummaryResult>
<DocSum>
	<Id>99999999</Id>
	<Item Name="DS_MeshTerms" Type="List">
	</Item>
</DocSum>
</eSummaryResult>
"""


def test_parse_mesh_esummary_descriptor_e_entry_terms():
    match = parse_mesh_esummary_xml(MESH_ESUMMARY_MATCH, "melanoma")
    assert isinstance(match, MeshMatch)
    assert match.termine_originale == "melanoma"
    assert match.descriptor == "Melanoma"
    assert match.entry_terms == [
        "Melanomas",
        "Malignant Melanoma",
        "Malignant Melanomas",
        "Melanoma, Malignant",
        "Melanomas, Malignant",
    ]
    assert match.mesh_ui == "68008545"


def test_parse_mesh_esummary_un_solo_termine_entry_terms_vuoto():
    match = parse_mesh_esummary_xml(MESH_ESUMMARY_UN_SOLO_TERMINE, "immunotherapy")
    assert match.descriptor == "Immunotherapy"
    assert match.entry_terms == []
    assert match.mesh_ui == "68007167"


def test_parse_mesh_esummary_senza_docsum_solleva_parse_error():
    with pytest.raises(PubMedParseError, match="DocSum"):
        parse_mesh_esummary_xml(MESH_ESUMMARY_SENZA_DOCSUM, "x")


def test_parse_mesh_esummary_meshterms_vuoto_solleva_parse_error():
    with pytest.raises(PubMedParseError, match="DS_MeshTerms"):
        parse_mesh_esummary_xml(MESH_ESUMMARY_MESHTERMS_VUOTO, "x")


def test_mesh_match_e_immutabile():
    match = parse_mesh_esummary_xml(MESH_ESUMMARY_MATCH, "melanoma")
    with pytest.raises(Exception):
        match.descriptor = "altro"
