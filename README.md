# PubMed NL Search Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/Dariolex/pubmed-search-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/Dariolex/pubmed-search-agent/actions/workflows/tests.yml)

Search PubMed with plain-language questions instead of boolean query syntax. This project translates a natural-language request into a real [PubMed](https://pubmed.ncbi.nlm.nih.gov/) advanced-search query, runs it against the official NCBI E-utilities API, and filters the results by **semantic relevance** to what you actually asked — not just keyword overlap.

```
"Find studies from the last 3 years on immunotherapy in metastatic melanoma,
 randomized controlled trials only, excluding case reports"
        │
        ▼  NL → PubMed query translation
("melanoma"[MeSH Terms] OR "melanoma"[tiab]) AND
("immunotherapy"[MeSH Terms] OR "immunotherapy"[tiab]) AND
"metastatic"[tiab] AND "randomized controlled trial"[pt] AND
("2023"[dp] : "2026"[dp])
        │
        ▼  ESearch / EFetch against NCBI E-utilities
        ▼  Semantic relevance filtering
        ▼
Ranked results, with a rationale for each and a link to verify the query yourself
```

> **Note on language:** this README is in English for reach, but the codebase, inline comments, and the Claude skill instructions are in **Italian**. See [Contributing](#contributing) if that's a barrier for you.

---

## Why this exists

A boolean PubMed query is precise but unforgiving — get one field tag wrong and you silently miss half the literature. Free-text search on PubMed's own site is forgiving but noisy. This project tries to get both: a **deterministic, auditable translation step** from natural language to correct PubMed syntax, followed by an LLM reading the actual abstracts to judge relevance — the way a researcher would, not a keyword matcher.

The generated query and a direct PubMed link are always shown to you, so you can verify the interpretation and correct it if needed — this project is a translation and ranking layer on top of PubMed, not a black box.

## Features

- **Natural-language → PubMed query translation** — structured concept extraction, then a deterministic serializer that emits correct field tags (`[tiab]`, `[MeSH Terms]`, `[pt]`, `[dp]`, `[la]`, `[cois]`), boolean operators, and date ranges.
- **Authoritative MeSH resolution** — verifies candidate MeSH terms against NCBI's controlled vocabulary (`db=mesh`) instead of guessing, and pulls in official entry terms (synonyms).
- **Semantic relevance filtering** — an LLM reads titles and abstracts and ranks/discards results against your actual intent, flagging cases where a good article was excluded by an overly strict boolean query.
- **Related articles & citation chains** — given a PMID, find similar articles or everything that cites it, via `elink.fcgi`.
- **Patent / conflict-of-interest filter** — PubMed doesn't index patents directly, so this searches the Conflict of Interest Statement field and exposes the raw disclosure text, so negative declarations ("the authors hold no patents") can be told apart from real positives.
- **MCP server** — exposes search as an MCP tool (`search_pubmed_papers`) usable from Claude Desktop or any MCP-compatible client, with a rate limiter that survives across calls.
- **Rate-limit aware** — an explicit token-bucket limiter respects NCBI's 10 req/s cap (with an API key) and retries on 429/5xx.

## How it's built

Every module is independently testable:

```
src/
├── pubmed_errors.py       # shared exception hierarchy
├── pubmed_models.py       # dataclasses + pure XML parsing (no network)
├── pubmed_client.py       # E-utilities wrapper: rate limiting, retries, esearch/efetch/elink/resolve_mesh
├── run_search.py          # CLI entry-point: query → esearch/efetch → JSON
├── nl_query_translator.py # deterministic serializer: intermediate JSON → PubMed syntax
├── mesh_resolver.py       # CLI: free term → authoritative MeSH descriptor
├── related_search.py      # CLI: PMID → similar articles / citing articles
└── mcp_server.py          # MCP tool exposing the search pipeline
```

`pubmed_client.py` never contains NL-interpretation logic; `nl_query_translator.py` never makes an HTTP call. The natural-language understanding step lives in the Claude skill that drives the pipeline (`.claude/skills/pubmed-search/`), which is a deliberate design choice — it keeps every deterministic step testable offline with fixed JSON/XML fixtures, and keeps the one non-deterministic step (reading and judging text) isolated to where it belongs.

## Getting started

**1. Get a free NCBI API key** — [ncbi.nlm.nih.gov/account](https://www.ncbi.nlm.nih.gov/account/) → *Settings → API Key Management*. Not strictly required, but raises your rate limit from 3 to 10 requests/second.

**2. Configure `.env`** (copy `.env.example`):

```
NCBI_API_KEY=your-key-here
NCBI_TOOL_NAME=pubmed-nl-search-agent
NCBI_EMAIL=you@example.com
```

**3. Install dependencies:**

```bash
pip install -r requirements.txt
```

## Usage

### As a Claude Code skill (recommended)

Open this repository in [Claude Code](https://claude.com/claude-code) and just ask, in plain language:

> *"Find studies from the last 2 years on CAR-T therapy in lymphoma, clinical trials only"*

The `pubmed-search` skill (`.claude/skills/pubmed-search/SKILL.md`) handles NL → query translation, execution, and relevance ranking end to end, always showing you the generated query and a PubMed link before presenting results.

### As an MCP server

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "python",
      "args": ["/absolute/path/to/src/mcp_server.py"]
    }
  }
}
```

This exposes a single fine-grained tool, `search_pubmed_papers(term, retmax)`. `term` must already be valid PubMed syntax — the calling model is responsible for the NL → query translation step, same as any other MCP tool consumer.

### From the command line

```bash
# Run a search (term must be valid PubMed syntax)
PYTHONPATH=src python -m run_search --term '"melanoma"[tiab] AND "immunotherapy"[tiab]' --retmax 30

# Resolve a free term to its official MeSH descriptor
PYTHONPATH=src python -m mesh_resolver --termine "melanoma"

# Find articles similar to / citing a known PMID
PYTHONPATH=src python -m related_search --pmid 33301246 --tipo simili --max 30
PYTHONPATH=src python -m related_search --pmid 33301246 --tipo citazioni --max 30

# Translate a structured JSON request into PubMed syntax (deterministic, no network)
PYTHONPATH=src python -m nl_query_translator --file query.json --link
```

## Testing

```bash
pytest              # offline suite — no network calls, fixtures + fixed XML
pytest -m live       # live suite — real calls against NCBI, needs a valid .env
```

Live-mode fixtures aren't hand-written: `python tests/record_fixtures.py` records authentic NCBI responses into `tests/fixtures/`, stripping the API key before writing to disk — so the parser is always tested against real API output, not an idealized guess at the schema.

## Roadmap status

| Step | Status |
|---|---|
| Core client: ESearch + EFetch, rate limiting, typed parsing | ✅ |
| NL → PubMed query translation | ✅ |
| End-to-end search via the Claude skill | ✅ |
| Semantic relevance filtering | ✅ |
| Authoritative MeSH resolution | ✅ |
| MCP server (`search_pubmed_papers`) | ✅ |
| Related articles & citation chains (`elink`) | ✅ |
| Patent / conflict-of-interest filter | ✅ |

See `CLAUDE.md` (project guide, in Italian) for full architectural detail and design rationale.

## Limitations

- **PubMed only.** No Semantic Scholar, no Google Scholar, no cross-database coverage.
- **No systematic-review workflow.** No PRISMA support, no structured data extraction into tables, no collaborative screening — if that's what you need, look at [Elicit](https://elicit.com), Covidence, or Rayyan instead.
- **No UI.** This is a CLI + a Claude skill + an MCP tool. You need to be comfortable with a terminal (or with Claude Code) to use it directly.
- **The patent filter is a proxy, not ground truth.** PubMed doesn't index patents; the filter searches free-text Conflict of Interest disclosures, which can be incomplete, absent, or phrased ambiguously.

## Contributing

Contributions are welcome — code, documentation, or translation. The existing codebase (comments, docstrings, the `pubmed-search` skill, `CLAUDE.md`) is in **Italian**; new contributions in English are welcome too, but please don't rewrite existing Italian content into English in the same PR as an unrelated change. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and conventions.

## License

[MIT](LICENSE) — do whatever you want with it, including forking, modifying, and redistributing, commercially or not. Attribution appreciated but not required beyond keeping the license notice.

## Acknowledgments

Built against [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/). Developed end-to-end with [Claude Code](https://claude.com/claude-code), using TDD and real API verification at every design step — see the `docs/superpowers/` directory for the design specs and implementation plans behind each feature, if you're curious how it was built.
