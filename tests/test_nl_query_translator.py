"""
test_nl_query_translator.py

Test per nl_query_translator.py.

Da implementare:
- Test della fase di serializzazione (JSON intermedio -> stringa `term=` PubMed) usando
  fixture JSON fisse, senza richiamare Claude ad ogni esecuzione.
- Test di regressione sulla generazione dei tag di campo corretti ([tiab], [MeSH Terms],
  [pt], [dp], ecc.) e della precedenza booleana (parentesi, AND/OR/NOT maiuscoli).
- Eventuali test end-to-end sulla fase di estrazione strutturata, marcati separatamente
  se richiedono una chiamata reale a Claude.
"""
