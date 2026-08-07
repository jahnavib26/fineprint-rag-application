# One image, two stages: build the UI with node, run everything under python.
# The result serves the API and the frontend from a single origin and a single
# process, which is what almost every host wants to deploy.

# --- Stage 1: build the frontend -------------------------------------------
FROM node:20-slim AS web

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build


# --- Stage 2: the runtime ---------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change doesn't reinstall the world.
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir \
      "fastapi>=0.115" "uvicorn[standard]>=0.30" "sqlalchemy[asyncio]>=2.0" \
      "asyncpg>=0.29" "alembic>=1.13" "pgvector>=0.3" "pydantic-settings>=2.4" \
      "pymupdf>=1.24" "python-multipart>=0.0.9" "pyyaml>=6.0" \
      "anthropic>=0.40" "openai>=1.50" "google-genai>=0.3" "voyageai>=0.3"

COPY backend/ ./
COPY --from=web /web/dist ./static

# Run as a non-root user: this process parses untrusted PDFs.
RUN useradd --create-home --uid 10001 fineprint && chown -R fineprint:fineprint /app
USER fineprint

# Hosts inject their own $PORT; 8000 is only the local default.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/api/health').read()"

COPY --chown=fineprint:fineprint deploy/entrypoint.sh /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
