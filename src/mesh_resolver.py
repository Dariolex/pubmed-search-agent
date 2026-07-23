"""
mesh_resolver.py

Mappatura di termini liberi (linguaggio naturale) verso termini MeSH controllati.

Responsabilità (vedi CLAUDE.md sezioni 3 e 8):
- Migliorare la traduzione NL -> query PubMed risolvendo i concetti estratti da
  nl_query_translator.py verso i termini MeSH ufficiali, quando disponibile un match
  affidabile, invece di affidarsi esclusivamente al tag [tiab].
- Non gestisce l'esplosione automatica dei termini MeSH (PubMed la applica di default sui
  termini [MeSH Terms]); si occupa solo della risoluzione termine libero -> termine MeSH.

Componente pianificato per una fase successiva del MVP (step 5 della roadmap), da sviluppare
dopo che pubmed_client.py e nl_query_translator.py sono stabili.
"""
