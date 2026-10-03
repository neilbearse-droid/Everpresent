"""Machine-to-machine ingest (no Clerk session): log drains push access logs
here with the tenant's Agent Analytics token."""

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session, col, select

from api.db import get_session
from api.models import Tenant, TenantStatus

router = APIRouter(prefix="/ingest")
Db = Annotated[Session, Depends(get_session)]


def hash_token(token: str) -> str:
    """Tokens are stored as SHA-256 digests: a leaked database row can't be
    replayed against the ingest endpoint."""
    return hashlib.sha256(token.encode()).hexdigest()


def _tenant_for_token(session: Session, token: str) -> Tenant:
    if len(token) < 24:
        raise HTTPException(status_code=401, detail="Invalid ingest token")
    digest = hash_token(token)
    tenant = session.exec(
        select(Tenant).where(col(Tenant.agent_log_token) == digest)
    ).first()
    if tenant is None or not hmac.compare_digest(tenant.agent_log_token or "", digest):
        raise HTTPException(status_code=401, detail="Invalid ingest token")
    if tenant.status == TenantStatus.archived:
        raise HTTPException(status_code=403, detail="This account is archived")
    return tenant


@router.post("/agent-logs")
async def push_agent_logs(
    request: Request,
    session: Db,
    authorization: Annotated[str, Header()] = "",
) -> dict:
    from api.agent_analytics import ingest_stream

    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer":
        token = ""
    token = token.strip()
    tenant = _tenant_for_token(session, token)
    assert tenant.id is not None
    from api.agent_analytics import UploadError

    try:
        summary = await ingest_stream(session, tenant.id, request.stream())
    except UploadError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    session.commit()
    return {"ai_hits": summary["ai_hits"], "lines": summary["lines"]}
