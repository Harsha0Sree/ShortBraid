# =============================================================
# Multi-stage Dockerfile
#   Stage 1: builder  — installs deps into a venv (has compiler)
#   Stage 2: runtime  — slim, copies venv only (no compilers)
#   Stage 3: dev      — runtime + dev deps + bash (for --reload)
# Goal: shrink final image from ~1.2GB → ~180MB
# =============================================================

# ---------- Stage 1: builder ----------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps: gcc + headers needed by asyncpg, pgvector, bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install only production deps into a venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
COPY shortbraid/__init__.py ./shortbraid/__init__.py
RUN pip install --upgrade pip && pip install .

# ---------- Stage 2: runtime (production) ----------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Runtime libs only (no compiler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "shortbraid.server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ---------- Stage 3: dev (used by docker-compose.yml) ----------
FROM runtime AS dev

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    make \
    && pip install --no-cache-dir \
       pytest pytest-asyncio flake8 black mypy httpx locust \
    && rm -rf /var/lib/apt/lists/*

USER appuser

# Override command in compose for --reload
CMD ["uvicorn", "shortbraid.server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
