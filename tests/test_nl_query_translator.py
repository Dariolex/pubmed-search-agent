"""Test di nl_query_translator: serializzazione pura JSON intermedio -> query PubMed."""

import io
import json
import sys

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


class _BufferFinto:
    """Doppio di test per lo stream binario `sys.stdout.buffer`: accumula i byte
    scritti senza applicare alcuna codifica permissiva (a differenza di
    `capsys`, che sostituisce stdout con uno stream di cattura di fatto UTF-8)."""

    def __init__(self):
        self.chunks: list[bytes] = []

    def write(self, dati: bytes) -> int:
        self.chunks.append(dati)
        return len(dati)


class _StdoutFinto:
    """Simula uno stdout con `encoding` realmente restrittivo (cp1252, come su
    certe console Windows), esponendo `.buffer.write(bytes)` come fa il vero
    `sys.stdout.buffer`."""

    def __init__(self, encoding: str):
        self.encoding = encoding
        self.buffer = _BufferFinto()


def test_cli_con_carattere_non_cp1252_usa_backslashreplace(monkeypatch):
    """Verifica il meccanismo specifico del fix: con stdout.encoding=cp1252 e un
    carattere non rappresentabile in cp1252 (U+2009 THIN SPACE, a differenza di
    "é" che *è* rappresentabile in cp1252 e quindi non discriminerebbe nulla),
    main() non deve crashare (return 0) e i byte scritti, decodificati con
    cp1252, devono contenere la sequenza di escape ASCII prodotta da
    errors="backslashreplace" (`\\u2009`), non il carattere Unicode grezzo
    (che cp1252 non può rappresentare).

    Non usiamo `capsys`: sostituisce sys.stdout con uno stream di cattura
    permissivo (di fatto UTF-8), che non farebbe mai scattare
    UnicodeEncodeError indipendentemente dal fix. Sostituiamo invece
    direttamente `sys.stdout` con un doppio che dichiara `encoding="cp1252"`
    e cattura i byte grezzi scritti su `.buffer`.

    Sul codice pre-fix (`print(query)` anziché
    `sys.stdout.buffer.write(query.encode(..., errors="backslashreplace"))`),
    questo test fallirebbe: `print` scriverebbe tramite `sys.stdout.write`
    (str), che con un TextIOWrapper reale su cp1252 solleverebbe
    UnicodeEncodeError per U+2009; con questo doppio minimale (che non
    implementa `.write()` testuale) fallirebbe comunque, perché il fix
    richiede esplicitamente l'uso di `.buffer.write`.
    """
    termine_con_thin_space = "a b"
    # Conferma che il carattere scelto non è rappresentabile in cp1252
    # (a differenza di "é", usato nella versione tautologica di questo test).
    with pytest.raises(UnicodeEncodeError):
        termine_con_thin_space.encode("cp1252")

    json_con_thin_space = (
        '{"concetti": [{"termine": "a\\u2009b", "sinonimi": [], "mesh": null}]}'
    )
    stdout_finto = _StdoutFinto("cp1252")
    monkeypatch.setattr(sys, "stdout", stdout_finto)

    codice = main(argv=[], stdin=io.StringIO(json_con_thin_space))

    assert codice == 0
    scritto = b"".join(stdout_finto.buffer.chunks)
    # I byte devono essere decodificabili con cp1252 senza sollevare eccezioni:
    # se il fix non applicasse backslashreplace, questo passo fallirebbe con
    # UnicodeEncodeError già in fase di encode dentro main().
    decodificato = scritto.decode("cp1252")
    assert " " not in decodificato, (
        "Il carattere Unicode grezzo non deve comparire: cp1252 non può "
        "rappresentarlo, quindi deve essere stato sostituito dall'escape."
    )
    assert "\\u2009" in decodificato, (
        "Ci si aspetta la sequenza di escape ASCII prodotta da "
        "errors='backslashreplace'."
    )


def test_cli_con_carattere_non_cp1252_e_link_usa_backslashreplace(monkeypatch):
    """Come sopra, ma con --link: anche l'URL generato passa per lo stesso
    percorso di scrittura e deve restare scrivibile su uno stdout cp1252."""
    json_con_thin_space = (
        '{"concetti": [{"termine": "a\\u2009b", "sinonimi": [], "mesh": null}]}'
    )
    stdout_finto = _StdoutFinto("cp1252")
    monkeypatch.setattr(sys, "stdout", stdout_finto)

    codice = main(argv=["--link"], stdin=io.StringIO(json_con_thin_space))

    assert codice == 0
    scritto = b"".join(stdout_finto.buffer.chunks)
    decodificato = scritto.decode("cp1252")
    righe = decodificato.strip().splitlines()
    assert len(righe) >= 2
    assert " " not in righe[0]
    assert "\\u2009" in righe[0]
    assert righe[1].startswith("https://pubmed.ncbi.nlm.nih.gov/?term=")


class _StderrFinto:
    """Come `_StdoutFinto`, ma per `sys.stderr`: stesso doppio minimale con
    `.encoding` restrittivo e `.buffer.write(bytes)`, usato per verificare
    l'hardening del ramo d'errore (stampa su stderr) invece di quello di
    stampa normale su stdout."""

    def __init__(self, encoding: str):
        self.encoding = encoding
        self.buffer = _BufferFinto()


def test_cli_errore_con_carattere_non_cp1252_su_stderr_usa_backslashreplace(monkeypatch):
    """Verifica l'hardening del ramo d'errore di main() (stampa su stderr).

    `serialize()` solleva ValueError con `repr()` del valore non valido
    incorporato nel messaggio (es. `operatore_tra_concetti deve essere AND o
    OR, non {operatore!r}`). Se quel valore contiene un carattere non
    rappresentabile in cp1252, il ramo `except` deve scrivere il messaggio con
    lo stesso schema robusto usato per stdout (`.buffer.write` con
    `errors="backslashreplace"`), non con `print(..., file=sys.stderr)`.

    Si usa la lettera greca theta (U+03B8) invece di U+2009 THIN SPACE: THIN
    SPACE non e' "printable" per Python (`str.isprintable()` e' False per i
    separatori Unicode diversi dallo spazio ASCII), quindi `repr()` la
    escaperebbe gia' lui stesso in `\\u2009` *prima* che il messaggio arrivi a
    stdout/stderr, rendendo il test tautologico (il messaggio sarebbe gia'
    puro ASCII e non solleverebbe mai UnicodeEncodeError). Theta e' invece
    "printable": `repr()` la lascia come carattere Unicode grezzo dentro le
    virgolette, esattamente come richiesto dallo scenario del reviewer ("un
    operatore... contenente una lettera greca").

    Sul codice pre-fix (`print(f"Errore: {exc}", file=sys.stderr)`), questo
    test fallirebbe: con questo doppio minimale (che espone solo
    `.buffer.write(bytes)`, non un `.write()` testuale) `print` solleverebbe
    AttributeError, perche' tenterebbe di scrivere una str su un oggetto privo
    di quel metodo -- il test discrimina quindi esattamente il fix richiesto
    (uso di `.buffer.write` con encoding robusto), non solo il sintomo.
    """
    operatore_con_theta = "AND" + "\u03b8" + "OR"
    assert operatore_con_theta.isprintable()
    with pytest.raises(UnicodeEncodeError):
        operatore_con_theta.encode("cp1252")
    # repr() lo lascia grezzo (non lo trasforma in \u03b8 ASCII): conferma che
    # il carattere problematico arriva intatto nel messaggio d'errore, non
    # gia' pre-escapato da repr() come accadrebbe con THIN SPACE.
    with pytest.raises(UnicodeEncodeError):
        repr(operatore_con_theta).encode("cp1252")

    json_operatore_invalido = json.dumps(
        {
            "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
            "operatore_tra_concetti": operatore_con_theta,
        }
    )
    stderr_finto = _StderrFinto("cp1252")
    monkeypatch.setattr(sys, "stderr", stderr_finto)

    codice = main(argv=[], stdin=io.StringIO(json_operatore_invalido))

    assert codice == 1
    scritto = b"".join(stderr_finto.buffer.chunks)
    decodificato = scritto.decode("cp1252")
    assert operatore_con_theta not in decodificato, (
        "Il carattere Unicode grezzo non deve comparire: cp1252 non puo' "
        "rappresentarlo, quindi deve essere stato sostituito dall'escape."
    )
    assert "\\u03b8" in decodificato, (
        "Ci si aspetta la sequenza di escape ASCII prodotta da "
        "errors='backslashreplace'."
    )


def test_filtro_brevetto():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"brevetto": True},
    }
    assert serialize(intermedio) == '"melanoma"[tiab] AND "patent*"[cois]'


def test_filtro_brevetto_assente_non_aggiunge_nulla():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {},
    }
    assert serialize(intermedio) == '"melanoma"[tiab]'


def test_filtro_brevetto_false_non_aggiunge_nulla():
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"brevetto": False},
    }
    assert serialize(intermedio) == '"melanoma"[tiab]'


def test_filtro_brevetto_ultimo_nell_ordine_canonico():
    """Il brevetto si accoda dopo date, tipi di studio e lingua."""
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {
            "date": {"da": "2023", "a": "2026", "tipo": "dp"},
            "tipi_studio": ["review"],
            "lingua": "english",
            "brevetto": True,
        },
    }
    assert serialize(intermedio) == (
        '"melanoma"[tiab] AND ("2023"[dp] : "2026"[dp]) AND '
        '"review"[pt] AND "english"[la] AND "patent*"[cois]'
    )


def test_filtro_brevetto_precede_le_esclusioni():
    """Le esclusioni NOT restano in coda, dopo tutti i filtri."""
    intermedio = {
        "concetti": [{"termine": "melanoma", "sinonimi": [], "mesh": None}],
        "filtri": {"brevetto": True},
        "esclusioni": [{"termine": "case reports", "campo": "pt"}],
    }
    assert serialize(intermedio) == (
        '"melanoma"[tiab] AND "patent*"[cois] NOT "case reports"[pt]'
    )
