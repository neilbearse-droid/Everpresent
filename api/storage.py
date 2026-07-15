"""Raw-payload storage (§5.1). Postgres stores only the relative URI in
results.raw_uri; the envelope holds the request, the full provider response,
and the parsed convenience view.

Two backends, chosen by STORAGE_BACKEND:
  "file" (default) — a shared volume on the VPS (infra/docker-compose.yml).
  "db"             — a Postgres table, for managed hosts (Render) where the
                     api and worker can't share a disk.
The URI shape is identical either way, so results.raw_uri is portable."""

import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from api.config import get_settings


def _uri(tenant_slug: str, run_id: int, name: str) -> str:
    return f"{tenant_slug}/run-{run_id}/{name}.json"


def write_raw_envelope(
    tenant_slug: str,
    run_id: int,
    name: str,
    envelope: dict[str, Any],
    session: Session | None = None,
) -> str:
    """Returns the URI stored in results.raw_uri. For the db backend, pass the
    caller's `session` so the write rides the same transaction (avoids a second
    DB connection); it's committed when the caller commits."""
    rel = _uri(tenant_slug, run_id, name)
    if get_settings().storage_backend == "db":
        _db_write(rel, envelope, session)
    else:
        path = Path(get_settings().raw_storage_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return rel


def read_raw_envelope(raw_uri: str, session: Session | None = None) -> dict[str, Any] | None:
    if get_settings().storage_backend == "db":
        return _db_read(raw_uri, session)
    root = Path(get_settings().raw_storage_dir).resolve()
    path = (root / raw_uri).resolve()
    # raw_uri comes from our own DB, but never let a crafted value escape the
    # storage root.
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _db_write(uri: str, envelope: dict[str, Any], session: Session | None) -> None:
    from api.models import RawPayload

    def _do(s: Session) -> None:
        existing = s.exec(select(RawPayload).where(RawPayload.uri == uri)).first()
        if existing is None:
            s.add(RawPayload(uri=uri, envelope=envelope))
        else:
            existing.envelope = envelope
            s.add(existing)

    if session is not None:
        _do(session)  # committed with the caller's transaction
        session.flush()
    else:
        from api.db import get_engine

        with Session(get_engine()) as own:
            _do(own)
            own.commit()


def _db_read(uri: str, session: Session | None) -> dict[str, Any] | None:
    from api.models import RawPayload

    def _do(s: Session) -> dict[str, Any] | None:
        row = s.exec(select(RawPayload).where(RawPayload.uri == uri)).first()
        return row.envelope if row is not None else None

    if session is not None:
        return _do(session)
    from api.db import get_engine

    with Session(get_engine()) as own:
        return _do(own)
