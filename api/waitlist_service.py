"""Landing-page waitlist (m40).

Public, unauthenticated writes, so everything here is defensive: fields are
trimmed and length-capped before they reach the database, the email is the
identity (lowercased, unique), and a resubmission updates the details without
resetting the status someone already moved the row to.
"""

import re
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlmodel import Session, col, func, select

from api.config import get_settings
from api.models import WaitlistSignup, WaitlistStatus

log = structlog.get_logger()

# Deliberately permissive: one @, a dot in the domain, no spaces. Address
# validity is settled by the invitation email actually arriving, not by a
# regex that rejects someone's real address.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

MAX_LEN = {
    "name": 120,
    "email": 254,
    "title": 120,
    "company": 160,
    "industry": 80,
    "source": 120,
}

# The industries offered on the form. Free text is still accepted (the form
# has an "Other" box), so this is the shortlist, not a constraint.
INDUSTRIES = [
    "Higher education",
    "Financial services",
    "Insurance",
    "Healthcare",
    "SaaS / software",
    "Professional services",
    "Retail / ecommerce",
    "Travel / hospitality",
    "Real estate",
    "Manufacturing / industrial",
    "Nonprofit / association",
    "Agency / consultancy",
    "Media / publishing",
    "Other",
]

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref")


class WaitlistError(ValueError):
    """Rejected submission. The message is shown to the person on the form."""


def _clean(value: Any, field: str) -> str:
    text = " ".join(str(value or "").split())
    return text[: MAX_LEN[field]]


def clean_utm(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key in UTM_KEYS:
        value = raw.get(key)
        if value:
            out[key] = " ".join(str(value).split())[:120]
    return out


def submit(
    session: Session,
    *,
    name: str,
    email: str,
    title: str = "",
    company: str = "",
    industry: str = "",
    source: str = "",
    utm: Any = None,
) -> tuple[WaitlistSignup, bool]:
    """Record a signup. Returns the row and whether this email was already on
    the list. The caller owns the commit."""

    name = _clean(name, "name")
    email = _clean(email, "email").lower()
    if not name:
        raise WaitlistError("Please add your name.")
    if not email or not EMAIL_RE.match(email):
        raise WaitlistError("Please check the email address.")

    existing = session.exec(
        select(WaitlistSignup).where(col(WaitlistSignup.email) == email)
    ).first()
    now = datetime.now(UTC)
    fields = {
        "name": name,
        "title": _clean(title, "title"),
        "company": _clean(company, "company"),
        "industry": _clean(industry, "industry"),
        "source": _clean(source, "source"),
    }
    if existing is not None:
        # Keep the status (someone may already have invited them) and keep any
        # earlier answer a blank resubmission would otherwise wipe out.
        for key, value in fields.items():
            if value:
                setattr(existing, key, value)
        merged = {**(existing.utm or {}), **clean_utm(utm)}
        existing.utm = merged
        existing.submissions = (existing.submissions or 1) + 1
        existing.updated_at = now
        session.add(existing)
        return existing, True

    signup = WaitlistSignup(
        name=fields["name"],
        email=email,
        title=fields["title"],
        company=fields["company"],
        industry=fields["industry"],
        source=fields["source"],
        status=WaitlistStatus.new,
        utm=clean_utm(utm),
        created_at=now,
        updated_at=now,
    )
    session.add(signup)
    return signup, False


def notify_signup(signup: WaitlistSignup, *, already_on_list: bool = False) -> bool:
    """Tell the operator someone signed up. Best effort: a mail server that is
    unconfigured or down must never fail the form."""
    from api.emailer import send_email, smtp_configured

    settings = get_settings()
    raw = settings.waitlist_notify_emails or settings.superadmin_email
    recipients = [address.strip() for address in raw.split(",") if address.strip()]
    if not recipients or not smtp_configured():
        return False
    lines = [
        f"{signup.name} <{signup.email}> joined the EverPresent waitlist.",
        "",
        f"Title: {signup.title or '—'}",
        f"Company: {signup.company or '—'}",
        f"Industry: {signup.industry or '—'}",
        f"Source: {signup.source or '—'}",
    ]
    if signup.utm:
        lines.append("Campaign: " + ", ".join(f"{k}={v}" for k, v in signup.utm.items()))
    if already_on_list:
        lines += ["", f"They were already on the list (submission {signup.submissions})."]
    subject = f"Waitlist: {signup.name}" + (f" ({signup.company})" if signup.company else "")
    try:
        return send_email(recipients, subject, "\n".join(lines))
    except Exception:  # noqa: BLE001 — the signup is already saved
        log.exception("waitlist.notify_failed", email=signup.email)
        return False


def list_signups(
    session: Session, *, status: str = "", limit: int = 500
) -> list[WaitlistSignup]:
    statement = select(WaitlistSignup).order_by(col(WaitlistSignup.created_at).desc())
    if status:
        statement = statement.where(col(WaitlistSignup.status) == status)
    return list(session.exec(statement.limit(limit)).all())


def status_counts(session: Session) -> dict[str, int]:
    rows = session.exec(
        select(col(WaitlistSignup.status), func.count()).group_by(col(WaitlistSignup.status))
    ).all()
    counts = {status.value: 0 for status in WaitlistStatus}
    for status, count in rows:
        key = status.value if isinstance(status, WaitlistStatus) else str(status)
        counts[key] = int(count)
    counts["total"] = sum(counts[s.value] for s in WaitlistStatus)
    return counts


def signups_csv(session: Session) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "created_at",
            "name",
            "email",
            "title",
            "company",
            "industry",
            "status",
            "source",
            "campaign",
            "submissions",
            "note",
        ]
    )
    for row in list_signups(session, limit=100_000):
        campaign = ", ".join(f"{k}={v}" for k, v in (row.utm or {}).items())
        writer.writerow(
            [
                row.id,
                row.created_at.isoformat(),
                # A leading =, +, - or @ in a cell is a formula to Excel; the
                # export is read by people, so neutralise it (same rule as the
                # report workbook).
                *(_csv_safe(v) for v in (row.name, row.email, row.title, row.company)),
                _csv_safe(row.industry),
                row.status.value if isinstance(row.status, WaitlistStatus) else str(row.status),
                _csv_safe(row.source),
                _csv_safe(campaign),
                row.submissions,
                _csv_safe(row.note),
            ]
        )
    return buffer.getvalue()


def _csv_safe(value: Any) -> str:
    text = str(value or "")
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text
