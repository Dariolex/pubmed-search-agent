---
name: pubmed-search
description: Cerca letteratura scientifica su PubMed a partire da una richiesta in linguaggio naturale. Usare quando l'utente digita /pubmed-search o chiede di trovare studi, articoli, trial o letteratura medica/scientifica su PubMed. Traduce la richiesta in una query PubMed, la esegue via NCBI E-utilities e ordina i risultati per rilevanza semantica.
---

# PubMed NL Search

Trasforma una richiesta in linguaggio naturale in una ricerca PubMed reale, poi
filtra i risultati per pertinenza rispetto all'intento dell'utente.

Eseguire i comandi Python dalla radice del progetto (dove c'è `pytest.ini`), con
`src` sul PYTHONPATH — es. `PYTHONPATH=src python -m nl_query_translator ...`.
Serve un file `.env` valido con `NCBI_API_KEY`, `NCBI_TOOL_NAME`, `NCBI_EMAIL`.

## Flusso

### 1. Estrai il JSON intermedio dalla richiesta

Analizza la richiesta NL e costruisci questo JSON (schema esteso con provenienza):

```json
{
  "intento_originale": "<la richiesta dell'utente, verbatim>",
  "concetti": [
    {"termine": "<concetto>", "sinonimi": ["<variante>"], "mesh": "<termine MeSH o null>", "provenienza": "<perché estratto>"}
  ],
  "operatore_tra_concetti": "AND",
  "esclusioni": [{"termine": "<da escludere>", "campo": "pt", "provenienza": "<perché>"}],
  "filtri": {
    "date": {"da": "<anno>", "a": "<anno>", "tipo": "dp"},
    "tipi_studio": ["<publication type>"],
    "lingua": "<lingua o null>"
  }
}
```

Linee guida per l'estrazione:
- **Concetti**: i nuclei clinici/scientifici della richiesta. Aggiungi `sinonimi`
  utili (varianti terminologiche, non traduzioni). Popola `mesh` solo quando il
  termine MeSH controllato è ovvio (es. `melanoma`, `immunotherapy`); altrimenti `null`.
- **operatore_tra_concetti**: `AND` di norma (l'utente vuole tutti i concetti insieme).
  Usa `OR` solo se la richiesta è esplicitamente alternativa ("melanoma o carcinoma").
- **Esclusioni**: frasi come "escludendo X", "senza X", "non case report" → `NOT`.
  Per i tipi di pubblicazione usa `campo: "pt"`; per termini liberi ometti `campo`.
- **Filtri date**: "ultimi 3 anni" → calcola dalla data odierna (`da` = anno corrente − 3,
  `a` = anno corrente). `tipo`: `dp` (data di pubblicazione) di default.
- **Tipi di studio**: "trial randomizzati" → `randomized controlled trial`; "meta-analisi"
  → `meta-analysis`; "review" → `review`. Più tipi vengono uniti in OR automaticamente.
- **Lingua**: solo se la richiesta la specifica ("in inglese" → `english`).

`provenienza` non entra nella query: serve a te e all'utente per il debug.

### 2. Genera la query PubMed (fase deterministica)

Scrivi il JSON in un file temporaneo e invoca il traduttore:

```bash
PYTHONPATH=src python -m nl_query_translator --file /percorso/query.json --link
```

Stampa due righe: la query PubMed e il link web. **Non costruire la query a mano** —
usa sempre questo comando, così la sintassi è corretta e riproducibile. Se il comando
esce con errore, correggi il JSON e riprova.

### 3. Mostra la traduzione all'utente

Prima dei risultati, mostra la query PubMed generata e il link diretto a
pubmed.ncbi.nlm.nih.gov, così l'utente può verificare l'interpretazione ed
eventualmente correggerla.

### 4. Esegui la ricerca

```bash
PYTHONPATH=src python -m run_search --term "<query generata>" --retmax 30
```

Restituisce JSON con `total_count`, `translated_query` (come NCBI ha reinterpretato
la query — utile se i risultati sorprendono), `warnings` e `articles` (con `title`,
`abstract`, `authors`, `journal`, `pub_date`, `pub_types`, `pmid`).

### 5. Filtra e ordina per rilevanza

Leggi gli abstract e valuta la pertinenza di ciascun articolo rispetto a
`intento_originale`. Scarta o declassa i non pertinenti (un articolo può matchare la
query booleana ma non l'intento reale). Ordina dal più al meno pertinente.

Segnala anche gli articoli che sembrano pertinenti ma che la query booleana potrebbe
aver escluso (falsi negativi da query troppo restrittiva), suggerendo un allargamento.

### 6. Presenta i risultati

Per ogni articolo pertinente: titolo, autori (primi 3), rivista, anno, PMID, e una
breve motivazione della rilevanza. In testa: la query PubMed generata e il link web.
Se `total_count` è 0, segnala che la query è troppo restrittiva e proponi come allargarla.
