from sqlmodel import Session

from api.models import AuditLog


def write_audit(session: Session, *, tenant_id: int | None, actor: str, action: str) -> None:
    """Caller owns the commit — audit rows ride the same transaction as the
    change they describe."""
    session.add(AuditLog(tenant_id=tenant_id, actor=actor, action=action))
