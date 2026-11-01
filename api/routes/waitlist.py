"""Public waitlist signup (m40). No Clerk session: this is the landing-page
form, so it is the one write path open to the internet. Guards: field length
caps in the service, a honeypot field, and a per-address rate limit in Redis
that fails open if Redis is down."""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from api.db import get_session
from api.waitlist_service import INDUSTRIES, WaitlistError, notify_signup, submit

log = structlog.get_logger()

router = APIRouter(prefix="/waitlist")
Db = Annotated[Session, Depends(get_session)]

# Per-IP ceiling. Generous enough for an office behind one address, low enough
# that a script can't fill the table.
RATE_LIMIT = 20
RATE_WINDOW_S = 3600


class WaitlistRequest(BaseModel):
    name: str = ""
    email: str = ""
    title: str = ""
    company: str = ""
    industry: str = ""
    source: str = ""
    utm: dict[str, Any] = Field(default_factory=dict)
    # Honeypot: hidden on the form, so only a bot fills it in.
    website: str = ""


def _rate_limited(request: Request) -> bool:
    client = request.client.host if request.client else ""
    if not client:
        return False
    try:
        from redis import Redis

        from api.config import get_settings

        redis = Redis.from_url(get_settings().redis_url, socket_timeout=1)
        key = f"waitlist:rate:{client}"
        hits = redis.incr(key)
        if hits == 1:
            redis.expire(key, RATE_WINDOW_S)
        return int(hits) > RATE_LIMIT
    except Exception:  # noqa: BLE001 — never lose a signup to a Redis problem
        log.info("waitlist.rate_limit_unavailable")
        return False


@router.get("/industries")
def industries() -> dict[str, list[str]]:
    """The shortlist the form offers. Free text is still accepted."""
    return {"industries": INDUSTRIES}


@router.post("", status_code=201)
def join_waitlist(payload: WaitlistRequest, session: Db, request: Request) -> dict:
    if payload.website.strip():
        # A bot. Answer as if it worked and write nothing.
        log.info("waitlist.honeypot")
        return {"status": "ok", "already_on_list": False}
    if _rate_limited(request):
        raise HTTPException(status_code=429, detail="Too many signups from here. Try again later.")
    try:
        signup, already = submit(
            session,
            name=payload.name,
            email=payload.email,
            title=payload.title,
            company=payload.company,
            industry=payload.industry,
            source=payload.source or "landing",
            utm=payload.utm,
        )
    except WaitlistError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    session.refresh(signup)
    log.info("waitlist.signup", email=signup.email, already=already)
    notify_signup(signup, already_on_list=already)
    return {"status": "ok", "already_on_list": already}
