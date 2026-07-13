"""BigQuery mirror (§5.3): a nightly job appends new runs, results
(metadata, not raw payloads), mentions, citations, and visibility_daily rows
to the existing warehouse dataset, alongside the v1 tables (v3-suffixed table
names). Internal Looker keeps working; nothing client-facing reads BigQuery.

Implemented against the BigQuery REST API with a service-account JWT grant
(PyJWT) — no Google SDK dependency. Watermarks in mirror_state make the job
idempotent; insertIds make retried inserts deduplicable."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import jwt
import structlog
from sqlmodel import Session, SQLModel, select

from api.config import get_settings
from api.db import get_engine
from api.models import Citation, Mention, MirrorState, Result, Run, VisibilityDaily, utcnow

log = structlog.get_logger()

TOKEN_URL = "https://oauth2.googleapis.com/token"
BQ_BASE = "https://bigquery.googleapis.com/bigquery/v2"
SCOPE = "https://www.googleapis.com/auth/bigquery"
BATCH_SIZE = 500

# model -> (bigquery table, column allowlist). Raw payload URIs stay out of
# the warehouse; so do secrets-adjacent fields.
MIRRORED: list[tuple[type[SQLModel], str, list[str]]] = [
    (
        Run,
        "runs_v3",
        ["id", "tenant_id", "trigger", "status", "surface_set", "mode_set",
         "started_at", "finished_at", "cost_usd", "counts", "error", "created_at"],
    ),
    (
        Result,
        "results_v3",
        ["id", "run_id", "tenant_id", "query_id", "persona_id", "query_text",
         "persona_name", "persona_segment", "surface", "mode", "variant",
         "status", "response_hash", "latency_ms", "created_at"],
    ),
    (
        Mention,
        "mentions_v3",
        ["id", "result_id", "tenant_id", "entity_type", "entity_name",
         "competitor_id", "position", "rank", "sentiment", "detector_version"],
    ),
    (
        Citation,
        "citations_v3",
        ["id", "result_id", "tenant_id", "url", "domain", "source_category"],
    ),
    (
        VisibilityDaily,
        "visibility_daily_v3",
        ["id", "tenant_id", "date", "surface", "persona_segment", "brand_score",
         "competitor_scores", "extras", "scorer_version", "computed_at"],
    ),
]


def _access_token(client: httpx.Client) -> str:
    settings = get_settings()
    key = json.loads(Path(settings.google_service_account_json).read_text(encoding="utf-8"))
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": key["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        key["private_key"],
        algorithm="RS256",
    )
    resp = client.post(
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return value


def _rows_for(table: str, columns: list[str], instances: list[Any]) -> list[dict]:
    rows = []
    for instance in instances:
        data = {c: _serialize(getattr(instance, c)) for c in columns}
        rows.append({"insertId": f"{table}-{instance.id}", "json": data})
    return rows


def _ensure_table(client: httpx.Client, token: str, table: str, columns: list[str]) -> None:
    settings = get_settings()
    url = (
        f"{BQ_BASE}/projects/{settings.bigquery_project}"
        f"/datasets/{settings.bigquery_dataset}/tables"
    )
    headers = {"Authorization": f"Bearer {token}"}
    if client.get(f"{url}/{table}", headers=headers).status_code == 200:
        return
    # Everything as STRING except the obvious numerics — the warehouse is for
    # history and joins, not typed analytics; Looker casts as needed.
    numeric = {"id", "tenant_id", "run_id", "result_id", "query_id", "persona_id",
               "competitor_id", "position", "rank", "latency_ms"}
    floats = {"cost_usd", "brand_score"}
    schema = [
        {
            "name": c,
            "type": "FLOAT" if c in floats else ("INTEGER" if c in numeric else "STRING"),
            "mode": "NULLABLE",
        }
        for c in columns
    ]
    resp = client.post(
        url,
        headers=headers,
        json={
            "tableReference": {
                "projectId": settings.bigquery_project,
                "datasetId": settings.bigquery_dataset,
                "tableId": table,
            },
            "schema": {"fields": schema},
        },
    )
    resp.raise_for_status()
    log.info("mirror.table_created", table=table)


def _insert_all(client: httpx.Client, token: str, table: str, rows: list[dict]) -> None:
    settings = get_settings()
    url = (
        f"{BQ_BASE}/projects/{settings.bigquery_project}"
        f"/datasets/{settings.bigquery_dataset}/tables/{table}/insertAll"
    )
    resp = client.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"rows": rows, "ignoreUnknownValues": False},
    )
    resp.raise_for_status()
    errors = resp.json().get("insertErrors")
    if errors:
        raise RuntimeError(f"BigQuery insertAll errors on {table}: {errors[:3]}")


def mirror_to_bigquery() -> dict[str, int]:
    settings = get_settings()
    if not settings.bigquery_project or not settings.google_service_account_json:
        log.info("mirror.skipped", reason="BigQuery not configured")
        return {}

    mirrored: dict[str, int] = {}
    with httpx.Client(timeout=60) as client, Session(get_engine()) as session:
        token = _access_token(client)
        for model, table, columns in MIRRORED:
            state = session.exec(
                select(MirrorState).where(MirrorState.table_name == table)
            ).first()
            if state is None:
                state = MirrorState(table_name=table)
            new_rows = list(
                session.exec(
                    select(model).where(model.id > state.last_id).order_by(model.id)  # pyright: ignore[reportAttributeAccessIssue, reportArgumentType]
                ).all()
            )
            if not new_rows:
                continue
            _ensure_table(client, token, table, columns)
            for start in range(0, len(new_rows), BATCH_SIZE):
                batch = new_rows[start : start + BATCH_SIZE]
                _insert_all(client, token, table, _rows_for(table, columns, batch))
            state.last_id = max(r.id for r in new_rows if r.id is not None)  # pyright: ignore[reportAttributeAccessIssue, reportGeneralTypeIssues]
            state.updated_at = utcnow()
            session.add(state)
            session.commit()
            mirrored[table] = len(new_rows)
            log.info("mirror.table_done", table=table, rows=len(new_rows))
    return mirrored
