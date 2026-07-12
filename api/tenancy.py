"""Tenant scoping (§7.3). Every client-facing route resolves its tenant from
the Clerk org context in the session token — never from a client-supplied
parameter — so a member of one tenant cannot address another tenant's data.
The tenancy-isolation tests in tests/test_tenancy.py are a merge blocker."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlmodel import Session, select

from api.auth import AuthedUser, get_current_user
from api.db import get_session
from api.models import Membership, MembershipRole, Tenant


@dataclass
class TenantContext:
    tenant: Tenant
    authed: AuthedUser
    role: MembershipRole

    @property
    def tenant_id(self) -> int:
        assert self.tenant.id is not None
        return self.tenant.id


def _role_from_clerk(org_role: str | None) -> MembershipRole:
    # Clerk encodes org roles as "org:admin" / "org:member".
    if org_role and org_role.endswith("admin"):
        return MembershipRole.owner
    return MembershipRole.member


def get_current_tenant(
    authed: Annotated[AuthedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
) -> TenantContext:
    if not authed.org_id:
        raise HTTPException(status_code=403, detail="No organization context in session")
    tenant = session.exec(select(Tenant).where(Tenant.clerk_org_id == authed.org_id)).first()
    if tenant is None:
        raise HTTPException(status_code=403, detail="Organization is not provisioned as a tenant")

    # Mirror Clerk org membership lazily; Clerk only issues an org_id claim to
    # actual members of that org, so the claim itself is the authorization.
    assert tenant.id is not None and authed.user.id is not None
    role = _role_from_clerk(authed.org_role)
    membership = session.exec(
        select(Membership).where(
            Membership.user_id == authed.user.id, Membership.tenant_id == tenant.id
        )
    ).first()
    if membership is None:
        membership = Membership(user_id=authed.user.id, tenant_id=tenant.id, role=role)
        session.add(membership)
        session.commit()
    elif membership.role != role:
        membership.role = role
        session.add(membership)
        session.commit()

    return TenantContext(tenant=tenant, authed=authed, role=membership.role)
