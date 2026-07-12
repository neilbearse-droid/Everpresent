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
from sqlmodel import Session, select

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


def _fetch_clerk_email(clerk_user_id: str, settings: Settings) -> tuple[str | None, str | None]:
    """Primary email + display name from the Clerk backend API. Session tokens
    don't carry email by default and we don't want to require a custom JWT
    template, so we look the user up once on first sight."""
    if not settings.clerk_secret_key:
        return None, None
    resp = httpx.get(
        f"{settings.clerk_api_base}/users/{clerk_user_id}",
        headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return None, None
    data = resp.json()
    email = None
    primary_id = data.get("primary_email_address_id")
    for addr in data.get("email_addresses", []):
        if addr.get("id") == primary_id:
            email = addr.get("email_address")
            break
    name = " ".join(p for p in (data.get("first_name"), data.get("last_name")) if p) or None
    return email, name


@dataclass
class AuthedUser:
    user: User
    org_id: str | None
    org_role: str | None = None


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
        email, name = _fetch_clerk_email(clerk_user_id, settings)
        if email:
            # Link a pre-seeded row (the superadmin seed) by email.
            user = session.exec(select(User).where(User.email == email)).first()
        if user is None:
            user = User(email=email or f"{clerk_user_id}@unknown.invalid", display_name=name)
        user.clerk_user_id = clerk_user_id
        if name and not user.display_name:
            user.display_name = name
        session.add(user)
        session.commit()
        session.refresh(user)

    return AuthedUser(user=user, org_id=claims.get("org_id"), org_role=claims.get("org_role"))


def require_superadmin(authed: Annotated[AuthedUser, Depends(get_current_user)]) -> AuthedUser:
    if not authed.user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin only")
    return authed
