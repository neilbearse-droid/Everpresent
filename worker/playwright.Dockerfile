# Mode B scraping worker (§3, §6.2): the only container with browsers.
# Build context is the repo root (see infra/docker-compose.yml).
FROM python:3.11-slim

WORKDIR /srv
# Pango for the branded PDF report (WeasyPrint); DejaVu as the fallback font
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md alembic.ini ./
COPY api ./api
COPY engine ./engine
COPY worker ./worker
COPY alembic ./alembic
COPY seeds ./seeds
RUN pip install --no-cache-dir ".[scrape]" \
    && playwright install --with-deps chromium

ENV WORKER_QUEUES=scrape
CMD ["python", "-m", "worker.main"]
