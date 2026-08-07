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

All six milestones are built and running end to end.

| Milestone | State |
|---|---|
| M1 — ingestion core (PDF → clause tree → fallback chunker) | ✅ |
| M2 — Postgres/pgvector storage + retrieval | ✅ |
| M3 — synthesis + grounding gate + traces | ✅ |
| ME — eval suite (35 cases) | ✅ |
| M4 — frontend (chat + highlighted document pane) | ✅ |
| M5 — amendment graph | ✅ |

## Quick start

```bash
docker compose up -d
```

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev,all-providers]' && .venv/bin/alembic upgrade head
```

Generate the synthetic leases, ingest them, and check retrieval:

```bash
cd backend && .venv/bin/python ../scripts/generate_leases.py && .venv/bin/python scripts/smoke_retrieval.py --reset
```

Run the backend (8001, because 8000 is a crowded default) and the frontend:

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --port 8001
```

```bash
cd frontend && npm install && npm run dev
```

Then open http://localhost:5173. Tests and evals:

```bash
cd backend && .venv/bin/python -m pytest -q && .venv/bin/python ../evals/run_evals.py
```

## Hosting

The deployable artifact is one container — `Dockerfile` builds the UI and
serves it from the same process as the API, so there's no CORS or API-URL
configuration and any host that runs a container works. Postgres with pgvector
is the only external dependency, and migrations run on boot.

```bash
APP_PASSWORD=demo docker compose --profile app up --build   # localhost:8080
```

`render.yaml` is a working blueprint (web service + database). **Set
`APP_PASSWORD` before exposing a public URL** — leases are private legal
documents and there are no user accounts, so without it anyone with the link
can read and upload them. Full guide, including what's deliberately *not*
production-ready: [deploy/README.md](deploy/README.md).

## Providers

Three LLM providers and three embedding providers, chosen independently —
Anthropic has no embeddings endpoint, so they're separate decisions. The
provider is auto-selected from whichever key is present in `.env`, or pinned
with `LLM_PROVIDER` / `EMBEDDING_PROVIDER`.

| | options |
|---|---|
| LLM (classification, synthesis, gate, override detection) | Claude · GPT · Gemini |
| Embeddings | Voyage · OpenAI · Gemini |

**With no keys at all, everything still runs** on deterministic offline
providers — a hashed lexical embedder and a keyword classifier. That's what
lets the eval suite gate a pipeline change in CI without spending money or
sending a lease to a third party. It also bounds what those runs can measure:
see `evals/README.md`.

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
