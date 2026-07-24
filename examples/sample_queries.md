# Query di esempio (linguaggio naturale -> PubMed)

Suite di regressione qualitativa: per ogni query NL, la query PubMed attesa e un giudizio
manuale sui primi risultati. Da aggiornare ogni volta che si modifica il prompt di
traduzione in `nl_query_translator.py` (vedi CLAUDE.md sezione 9).

## Formato di ogni voce

```
### Query NL
"..."

### Query PubMed attesa
...

### Note / giudizio manuale sui primi risultati
...
```

---

### Query NL

"Trovami gli studi degli ultimi 3 anni su immunoterapia nel melanoma metastatico,
solo trial clinici randomizzati, escludendo case report"

### JSON intermedio

```json
{
  "intento_originale": "studi ultimi 3 anni su immunoterapia nel melanoma metastatico, solo RCT, no case report",
  "concetti": [
    {"termine": "melanoma", "sinonimi": [], "mesh": "melanoma", "provenienza": "malattia centrale"},
    {"termine": "immunotherapy", "sinonimi": [], "mesh": "immunotherapy", "provenienza": "trattamento richiesto"},
    {"termine": "metastatic", "sinonimi": [], "mesh": null, "provenienza": "stadio specificato"}
  ],
  "operatore_tra_concetti": "AND",
  "esclusioni": [{"termine": "case reports", "campo": "pt", "provenienza": "utente: 'escludendo case report'"}],
  "filtri": {
    "date": {"da": "2023", "a": "2026", "tipo": "dp"},
    "tipi_studio": ["randomized controlled trial"]
  }
}
```

### Query PubMed attesa

```
("melanoma"[MeSH Terms] OR "melanoma"[tiab]) AND ("immunotherapy"[MeSH Terms] OR "immunotherapy"[tiab]) AND "metastatic"[tiab] AND ("2023"[dp] : "2026"[dp]) AND "randomized controlled trial"[pt] NOT "case reports"[pt]
```

### Note / giudizio manuale sui primi risultati

Verificata contro l'API reale: la query restituisce trial di immunoterapia nel melanoma
metastatico degli ultimi anni, coerenti con l'intento. La `translated_query` di NCBI
conferma l'espansione automatica dei termini MeSH.
