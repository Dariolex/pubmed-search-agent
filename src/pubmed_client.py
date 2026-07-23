"""
pubmed_client.py

Wrapper per le API E-utilities di NCBI (ESearch, ESummary, EFetch, ElinK).

Responsabilità:
- Costruire ed eseguire le chiamate HTTP verso https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
  includendo sempre i parametri obbligatori `tool`, `email`, `api_key` (letti da variabili
  d'ambiente, mai hardcoded).
- Implementare un limitatore di velocità esplicito (token bucket) per rispettare il limite
  di 10 richieste/secondo garantito da una api_key valida, con retry/backoff sugli HTTP 429.
- Esporre funzioni pure per: ricerca (esearch), riepiloghi (esummary), abstract completi
  (efetch) e articoli correlati (elink, fase successiva).

Vincolo architetturale: questo modulo non deve mai contenere logica di interpretazione del
linguaggio naturale — quella vive in nl_query_translator.py. Deve essere testabile sia in
modalità "live" contro NCBI, sia offline con le fixture in tests/fixtures/.
"""
