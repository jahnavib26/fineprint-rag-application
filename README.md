# FinePrint

Ask your lease the questions you never read it for.

A RAG assistant for rental agreements — deposits, subletting, guests, late fees — where
every answer cites the exact clause, and the system refuses when the lease simply doesn't say.

The failure that matters isn't "no answer." It's telling a tenant they *can* sublet when
clause 14(b) says they can't. Everything here is designed backwards from that failure mode.

## What makes it not a tutorial RAG

| | |
|---|---|
| **Clause-aware ingestion** | A clause *tree* (`14` → `14(b)`), not fixed token windows. Splitting a clause from its exceptions retrieves half-truths. |
| **Amendment-aware retrieval** | An addendum signed months later silently overrides the clause retrieval just found. Override edges live in Postgres and retrieval prefers the version that governs. |
| **Grounding gate** | Every claim in a drafted answer is checked back against the clause it cites, semantically. Unsupported answers are downgraded to "not found in your lease" rather than shipped with a correct-looking citation. |
| **Replayable traces** | One row per request: question, retrieved clauses + scores, pre-gate draft, per-claim verdicts, final answer. "It said something weird about my deposit" is a bug report you can actually run. |
| **Refusal evals** | The most valuable cases are the ones whose correct answer is "the lease doesn't say" — plus adversarial cases where an addendum changed the answer and citing the original clause is a wrong answer with a right-looking citation. |

## Status

| Milestone | State |
|---|---|
| **M1 — ingestion core** (PDF → clause tree → fallback chunker) | ✅ done, tests green |
| M2 — Postgres/pgvector storage + retrieval | in progress |
| M3 — synthesis + grounding gate + traces | pending |
| ME — eval suite | pending |
| M4 — frontend (chat + highlighted document pane) | pending |
| M5 — amendment graph | pending |

## Quick start (M1)

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

Regenerate the synthetic leases and their ground truth:

```bash
backend/.venv/bin/python scripts/generate_leases.py
```

Run the tests:

```bash
cd backend && .venv/bin/python -m pytest -q
```

## Layout

```
backend/app/ingestion/   pdf extraction → clause-tree segmenter → fallback chunker
backend/tests/           segmenter tests driven by synthetic ground truth
scripts/                 synthetic lease generator (PDFs + exact ground truth)
data/synthetic/          three generated leases; data/private/ is gitignored
evals/                   case suite + metrics harness
frontend/                Vite + React + TS
```

## The synthetic leases

Generated, not scraped — so eval expectations are exact rather than hand-labelled.

- **maple-court** — clean `ARTICLE` / `14.` / `14(b)` structure, plus two addenda that
  override the deposit and pet clauses. The override cases live here.
- **birch-lane** — `Section 8 –` and dotted `2.1.1` numbering, deeper nesting.
- **messy-loft** — near-unstructured prose that must route to the fallback chunker.

## Prerequisites for M2 onward

- Docker Desktop or OrbStack (Postgres + pgvector), or `brew install postgresql@17 pgvector`
- `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` in `.env` (see `.env.example`)
