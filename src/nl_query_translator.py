"""
nl_query_translator.py

Traduzione di query in linguaggio naturale nella sintassi di ricerca avanzata di PubMed.

Responsabilità (approccio a due fasi, vedi CLAUDE.md sezione 5):
1. Estrazione strutturata — analizza la query NL (via Claude) e produce un JSON intermedio
   con concetti chiave, sinonimi/varianti, filtri (data, tipo di studio, lingua, popolazione),
   esclusioni esplicite e operatori logici impliciti tra i concetti.
2. Serializzazione in sintassi PubMed — dal JSON intermedio genera la stringa `term=` finale,
   con tag di campo corretti ([tiab], [MeSH Terms], [pt], [dp], [au], [ta], [la]) e parentesi
   per la precedenza booleana (AND/OR/NOT maiuscoli).

Le due fasi sono separate per permettere di testare la serializzazione offline con JSON fissi
come fixture, e per loggare/validare il JSON intermedio quando la query risultante non produce
i risultati attesi.

Vincolo architetturale: questo modulo non deve mai effettuare chiamate HTTP dirette a NCBI —
quella responsabilità appartiene esclusivamente a pubmed_client.py.
"""
