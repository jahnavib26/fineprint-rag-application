# Hosting FinePrint

The deployable artifact is **one container**: `Dockerfile` builds the React UI
with node, then runs it and the API from a single Python process on one origin.
That removes CORS and API-base-URL configuration entirely, and means any host
that can run a container and hand it a `$PORT` can run this.

```mermaid
flowchart LR
    B["Browser"] -->|HTTPS| H["Host's TLS + router<br/>Render · Fly · Railway"]
    H -->|"$PORT"| C

    subgraph C["One container"]
      direction TB
      UI["Built React UI<br/>/assets + SPA fallback"]
      API["FastAPI<br/>/api/*"]
    end

    C -->|"asyncpg over TLS"| P[("Managed Postgres<br/>+ pgvector")]
    API -.->|"optional key"| L["LLM provider<br/>Claude · GPT · Gemini"]
    API -.->|"optional key"| E["Embedding provider<br/>Voyage · OpenAI · Gemini"]

    style C fill:#faf9f7,stroke:#7a5c3e
```

The dotted edges are the ones that can be absent: with no provider keys the app
still boots and serves, on offline providers. The solid edges are required.

The only external dependency is **Postgres with pgvector**. Migration `0001`
runs `CREATE EXTENSION IF NOT EXISTS vector` itself, so a managed Postgres that
*offers* pgvector needs no manual setup — Render, Neon, Supabase, and RDS all
qualify. `deploy/entrypoint.sh` runs `alembic upgrade head` before serving, so
there is no separate release step.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | `postgres://`, `postgresql://`, and `?sslmode=…` are all normalised for asyncpg automatically |
| `PORT` | injected by host | Defaults to 8000 |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` | no | Any one enables real synthesis, classification, and the grounding gate |
| `VOYAGE_API_KEY` | no | Or reuse the OpenAI/Gemini key for embeddings |
| `MAX_UPLOAD_MB` | no | Defaults to 25 |
| `CORS_ORIGINS` | only for split deploys | Comma-separated; unnecessary in the single-container setup |

**With no API keys the app still boots and works** on offline providers. That
is a genuine deployment mode for a demo, with a real limit: retrieval is
lexical, so questions phrased differently from the lease's wording will miss,
and answers are extractive quotes rather than written prose. One key changes
that with no code change and no redeploy of the frontend.

## Render (blueprint included)

`render.yaml` declares the web service and the database. Push to GitHub, then
**New → Blueprint**, point it at the repo, and fill in any provider keys as the
sync-disabled values it prompts for.

## Fly.io

```bash
fly launch --no-deploy          # generates fly.toml from the Dockerfile
fly postgres create             # or attach Neon/Supabase instead
fly postgres attach <db-name>   # sets DATABASE_URL
fly secrets set ANTHROPIC_API_KEY=...
fly deploy
```

Set `internal_port = 8000` and a `/api/health` check in `fly.toml`. If Fly's
Postgres image lacks pgvector, point `DATABASE_URL` at Neon or Supabase — both
have it and both have a free tier.

## Anything else (Railway, Cloud Run, ECS, a VPS)

Build and run the image, give it `DATABASE_URL` and `$PORT`:

```bash
docker build -t fineprint .
docker run -p 8080:8000 \
  -e DATABASE_URL='postgresql://user:pass@host/db?sslmode=require' \
  fineprint
```

To run the whole stack locally exactly as it will run deployed:

```bash
docker compose --profile app up --build
```

Then open http://localhost:8080.

## What is not production-ready

Worth being explicit, since "it deploys" and "it's production-ready" get
conflated:

- **No authentication at all.** Every lease lives in one shared corpus keyed by
  a guessable `lease_id`, so anyone who can reach the URL can read and upload.
  Keep the deployment private (an unlisted URL is not privacy — prefer your
  host's built-in access control, a VPN, or simply not deploying real leases).
- **Traces store question text and retrieved clause text indefinitely.** That's
  the point of them for debugging, and it's personal data with no retention
  policy or delete endpoint behind it.
- **No rate limiting.** With a provider key configured, anyone who can reach
  the app can spend money in a loop.
- **Single process, no queue.** Ingestion is synchronous inside the request; a
  60-page lease with a real classifier will hold a worker for a while.
- **Scanned leases are rejected**, not OCR'd.

None of these block a demo or personal use. All of them block real tenants.
