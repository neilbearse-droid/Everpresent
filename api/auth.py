"""Clerk session verification.

The frontend sends the Clerk session JWT as a Bearer token. We verify it
against Clerk's JWKS, then resolve (or create) the local user row. Nothing
outside this module may depend on Clerk-specific claims beyond the user id
and org id (§3: auth must stay swappable)."""

from dataclasses import dataclass
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from api.config import Settings, get_settings
from api.db import get_session
from api.models import User

_jwks_client: PyJWKClient | None = None


def _get_jwks_client(settings: Settings) -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not settings.clerk_jwks_url:
            raise HTTPException(status_code=503, detail="Auth is not configured on this deployment")
        _jwks_client = PyJWKClient(settings.clerk_jwks_url, cache_keys=True)
    return _jwks_client


def _decode_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        signing_key = _get_jwks_client(settings).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid session token") from exc


def _fetch_clerk_email(
    clerk_user_id: str, settings: Settings
) -> tuple[str | None, str | None, bool]:
    """(primary email, display name, email verified) from the Clerk backend
    API. Session tokens don't carry email by default and we don't want to
    require a custom JWT template, so we look the user up once on first sight.
    A Clerk outage degrades to (None, None, False) rather than failing the
    request."""
    if not settings.clerk_secret_key:
        return None, None, False
    try:
        resp = httpx.get(
            f"{settings.clerk_api_base}/users/{clerk_user_id}",
            headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None, None, False
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None, None, False
    email, verified = None, False
    primary_id = data.get("primary_email_address_id")
    for addr in data.get("email_addresses", []):
        if addr.get("id") == primary_id:
            email = addr.get("email_address")
            verified = (addr.get("verification") or {}).get("status") == "verified"
            break
    name = " ".join(p for p in (data.get("first_name"), data.get("last_name")) if p) or None
    return email, name, verified


@dataclass
class AuthedUser:
    user: User
    org_id: str | None
    org_role: str | None = None


def _extract_org(claims: dict[str, Any]) -> tuple[str | None, str | None]:
    """Read the active organization from the session token, tolerating both
    Clerk token shapes: the legacy top-level `org_id`/`org_role` claims, and
    the current default where org data is nested under a compact `o` object
    (`o.id`, `o.rol`). Without this, a modern token carries an active org that
    the server never sees, and every org-scoped route 403s."""
    org_id = claims.get("org_id")
    org_role = claims.get("org_role")
    if not org_id:
        o = claims.get("o")
        if isinstance(o, dict):
            org_id = o.get("id")
            # New tokens store the bare role ("admin"/"member"); the legacy
            # claim was "org:admin". _role_from_clerk matches on the suffix, so
            # either form resolves correctly.
            org_role = o.get("rol") or org_role
    return org_id, org_role


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthedUser:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    claims = _decode_token(auth_header.split(" ", 1)[1], settings)
    clerk_user_id = claims.get("sub")
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Token has no subject")

    user = session.exec(select(User).where(User.clerk_user_id == clerk_user_id)).first()
    if user is None:
        user = _first_sight(session, settings, clerk_user_id)

    org_id, org_role = _extract_org(claims)
    return AuthedUser(user=user, org_id=org_id, org_role=org_role)


def _first_sight(session: Session, settings: Settings, clerk_user_id: str) -> User:
    """Create (or link) the local user row the first time a Clerk user shows up.

    A pre-seeded row (the superadmin seed) is linked by email, compared
    case-insensitively, only when Clerk reports the address VERIFIED and the
    row isn't already linked to another Clerk user. Parallel first requests
    race to insert the same user; the loser re-reads the winner's row."""
    email, name, verified = _fetch_clerk_email(clerk_user_id, settings)
    user = None
    if email and verified:
        user = session.exec(
            select(User).where(
                func.lower(User.email) == email.lower(),
                User.clerk_user_id == None,  # noqa: E711
            )
        ).first()
    if user is None:
        taken = bool(email) and session.exec(
            select(User).where(func.lower(User.email) == (email or "").lower())
        ).first() is not None
        # Never collide with (or silently claim) an existing row's email.
        placeholder = f"{clerk_user_id}@unknown.invalid"
        user = User(email=placeholder if taken or not email else email, display_name=name)
    user.clerk_user_id = clerk_user_id
    if name and not user.display_name:
        user.display_name = name
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        winner = session.exec(select(User).where(User.clerk_user_id == clerk_user_id)).first()
        if winner is None:
            raise
        return winner
    session.refresh(user)
    return user


def require_superadmin(authed: Annotated[AuthedUser, Depends(get_current_user)]) -> AuthedUser:
    if not authed.user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin only")
    return authed
