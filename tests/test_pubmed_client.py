"""
test_pubmed_client.py

Test per pubmed_client.py.

Da implementare:
- Modalità offline: usa le fixture XML/JSON salvate in tests/fixtures/ per verificare
  parsing delle risposte ESearch/ESummary/EFetch senza consumare rate limit NCBI.
- Modalità "live" (marcata separatamente, es. con un marker pytest dedicato): esegue
  chiamate reali contro eutils.ncbi.nlm.nih.gov con query statiche semplici, da eseguire
  a parte per non intasare la CI né consumare inutilmente il rate limit.
- Verifica del rate limiter (token bucket) e della gestione dei retry su HTTP 429.
"""
