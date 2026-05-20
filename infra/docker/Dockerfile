# Omani Reception — Dockerfile
# Single-stage image; uv copied from the official distroless stage for clean install.
# Python 3.11 slim (bookworm) keeps the image small and matches `requires-python` in pyproject.

FROM python:3.11-slim-bookworm

# Pull the uv binary from the official image — avoids curl|sh and keeps layers reproducible.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Build deps for psycopg / SSL / native wheels. Slim image lacks these by default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
        postgresql-client \
        redis-tools \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. uid 1000 matches typical host users on Linux dev boxes for clean bind-mount perms.
RUN useradd --create-home --uid 1000 --shell /bin/bash app

WORKDIR /app
RUN chown -R app:app /app

# Python runtime hygiene.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH

# ---------- dependency layer (cached) ----------
# Copy only the metadata first so subsequent source edits don't bust the deps layer.
COPY --chown=app:app pyproject.toml /app/
# README is referenced by hatch/pyproject; copy it so `uv sync` doesn't trip.
COPY --chown=app:app README.md /app/

USER app
RUN uv sync --no-dev --no-install-project

# ---------- source layer ----------
USER root
COPY --chown=app:app engine/      /app/engine/
COPY --chown=app:app scripts/     /app/scripts/
COPY --chown=app:app businesses/  /app/businesses/
COPY --chown=app:app infra/docker/entrypoint.sh /app/infra/docker/entrypoint.sh
RUN chmod +x /app/infra/docker/entrypoint.sh

# Install the project itself now that sources are present.
USER app
RUN uv sync --no-dev

ENTRYPOINT ["/app/infra/docker/entrypoint.sh"]
CMD ["python", "-m", "engine.cli", "health"]
