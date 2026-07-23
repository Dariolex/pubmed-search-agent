"""
mcp_server.py

Espone la pipeline di ricerca PubMed come tool MCP `search_pubmed_papers`, utilizzabile da
Claude Desktop/Code.

Responsabilità (vedi CLAUDE.md sezioni 3 e 8):
- Orchestrare l'intero flusso end-to-end: query NL -> traduzione (nl_query_translator.py)
  -> esecuzione su PubMed (pubmed_client.py) -> filtro di rilevanza semantica
  (relevance_filter.py) -> output ordinato per pertinenza.
- Restituire sempre, insieme ai risultati, la query PubMed generata e il link diretto alla
  ricerca su pubmed.ncbi.nlm.nih.gov, cosi' l'utente puo' verificare l'interpretazione.

Componente pianificato per l'ultima fase del MVP (step 6 della roadmap), da sviluppare dopo
che gli altri moduli sono testati singolarmente.
"""
