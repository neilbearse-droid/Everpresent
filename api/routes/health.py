from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlmodel import Session

from api.db import get_session

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness only: Render gates deploys and restarts on this, so it must
    not fail on a Redis or worker problem the API itself can't fix."""
    return {"status": "ok", "service": "everpresent-api"}


@router.get("/health/deep")
def health_deep(session: Annotated[Session, Depends(get_session)]) -> JSONResponse:
    """Database, Redis, workers and scheduler. 503 when any is down, so an
    uptime monitor can alert. Reports pass/fail per component only."""
    from api.health_service import system_checks

    checks = system_checks(session)
    ok = all(c["ok"] for c in checks)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded",
                 "checks": {c["label"]: c["ok"] for c in checks}},
    )
