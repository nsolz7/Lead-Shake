FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests
RUN pip install --upgrade pip && pip install -e ".[test]"

# Run as an unprivileged user so a compromised process does not hold root.
# /data is pre-created and owned here so a fresh named volume inherits the
# ownership. For a volume created before this change, run once:
#   docker compose run --rm -u root api chown -R 10001:10001 /data
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app
USER appuser

EXPOSE 8000
