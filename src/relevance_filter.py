"""
relevance_filter.py

Filtro di rilevanza semantica sui risultati PubMed recuperati.

Responsabilità (vedi CLAUDE.md sezione 6):
- Dopo aver recuperato PMID + abstract via esummary/efetch, passare ogni articolo (o un batch)
  a Claude insieme all'intento originale dell'utente.
- Restituire per ciascun articolo un punteggio/classificazione di rilevanza e una breve
  motivazione (perché è o non è pertinente).
- Segnalare eventuali falsi negativi: articoli potenzialmente rilevanti ma esclusi da una
  query booleana troppo restrittiva.

Questo è il componente che distingue il progetto da una semplice interfaccia a ESearch: la
query booleana restringe lo spazio di ricerca in modo efficiente, il filtro semantico ordina
e scarta per pertinenza reale rispetto all'intento dell'utente.
"""
