# Contributing

Thanks for considering a contribution. This is a small, opinionated project — a few conventions keep it that way.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in NCBI_API_KEY, NCBI_TOOL_NAME, NCBI_EMAIL
pytest                 # offline suite — should pass with no .env at all
```

`pytest.ini` sets `pythonpath = src`, so tests import project modules directly (`from pubmed_client import ...`), no package install needed.

## Before opening a PR

- `pytest` must pass fully offline (no network calls in the default suite).
- If you touched anything that talks to NCBI, also run `pytest -m live -v` against a real `.env` and paste the output in your PR description — this project doesn't mock its way past API behavior changes.
- If you're changing XML parsing, prefer adding a fixture recorded from a real NCBI response (`python tests/record_fixtures.py`) over a hand-written XML string. Hand-written fixtures tend to be idealized and miss the edge cases that actually break parsers.
- Keep modules single-purpose: `pubmed_client.py` never contains NL-interpretation logic, `nl_query_translator.py` never makes a network call, `pubmed_models.py` never does either. If you're adding a new E-utilities endpoint, follow the existing pattern (client method → pure parser in `pubmed_models.py` → thin CLI if user-facing).

## A note on language

The existing code, comments, docstrings, `CLAUDE.md`, and the `.claude/skills/pubmed-search/SKILL.md` instructions are written in **Italian** — that was simply the language of the original author and the sessions this was built in. This isn't a requirement for contributions:

- New code/comments in English are fine, including in files that are currently Italian-only, as long as you're not doing a drive-by rewrite of unrelated existing content in the same PR.
- Please don't mix a functional change with a language-only rewrite of a file you didn't otherwise need to touch — it makes the diff impossible to review. Open a separate PR for pure translation work if you want to do it.
- If in doubt, match the language already used in the file you're editing.

## Design docs

Every non-trivial feature has a design spec and an implementation plan under `docs/superpowers/` (in Italian), including the live-API verification that shaped each decision. Worth a read before touching `pubmed_client.py`, `nl_query_translator.py`, or the E-utilities integration in general — several design choices there (e.g. why `elink` always requires an explicit `linkname`, why the patent filter also needs `Article.coi_statement`) look arbitrary until you see what broke without them.

## Reporting issues

Open a GitHub issue. For anything involving real NCBI responses (a parser bug, an unexpected `<ERROR>`, a rate-limit surprise), including the raw XML (with your API key redacted, if present) speeds things up enormously.
