# Multi-stage build for the Original API

# Stage 1: Builder — install dependencies in isolation
FROM python:3.11-slim AS builder

WORKDIR /install

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix /install -r requirements.txt

# Download the spaCy English model (required for Tier 5 POS features).
# The model is installed as a regular Python package so it lands in /install
# and is copied to the runtime image automatically by the COPY below.
# For air-gapped environments: set SPACY_DISABLE=1 at runtime instead of
# downloading here (Tier 5 will return neutral defaults gracefully).
RUN pip install --no-cache-dir --prefix /install \
    "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl" \
    || echo "[WARNING] spaCy model download failed — Tier 5 features will use neutral defaults."


# Stage 2: Runtime — lean image, non-root user
FROM python:3.11-slim

WORKDIR /app

# Create a non-root user; running as root in production is a hard fail on most audits
RUN useradd -m -u 1000 original

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Set permissions; make the entrypoint executable
RUN chown -R original:original /app \
    && chmod +x /app/docker-entrypoint.sh

USER original

EXPOSE 8000

# Give the DB and migrations time to complete before the first health probe
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# Entrypoint runs `alembic upgrade head` then starts uvicorn
ENTRYPOINT ["/app/docker-entrypoint.sh"]
