# Build context is the repo root (see infra/docker-compose.yml); this image
# serves the API and, with a different command, runs the RQ worker.
FROM python:3.11-slim

WORKDIR /srv
COPY pyproject.toml README.md alembic.ini ./
COPY api ./api
COPY engine ./engine
COPY worker ./worker
COPY alembic ./alembic
COPY seeds ./seeds
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
