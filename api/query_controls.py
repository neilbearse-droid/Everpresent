"""What a client can change about its own questions: pause one, and choose
which personas it runs against.

A paused question leaves the next run's plan and the competitive numbers
from the day it is paused; its history stays on the Queries page under
"Paused" with the date and who paused it. Personas are capped by plan (the
worker runs the first `max_personas` by id), so a persona outside the plan
is shown but can't be chosen, with the plan that unlocks it named.
"""

from typing import Any

from sqlmodel import Session, select

from api.models import Persona, Query, Tenant, utcnow
from api.plans import PLANS, limits_for

GENERIC_SEGMENT = "generic"


class QueryControlError(ValueError):
    """A change the rules refuse; the message is for the person."""


def persona_access(session: Session, tenant: Tenant) -> dict[str, Any]:
    """The tenant's personas with whether the plan runs each, plus the
    cheapest plan that would run them all."""
    personas = list(session.exec(
        select(Persona).where(Persona.tenant_id == tenant.id)
        .order_by(Persona.id)  # pyright: ignore[reportArgumentType]
    ).all())
    cap = limits_for(tenant.plan).max_personas
    selective = any(p.segment_tag == GENERIC_SEGMENT for p in personas)
    rows = []
    for i, p in enumerate(personas):
        if p.segment_tag == GENERIC_SEGMENT:
            continue  # the baseline runs on every question; nothing to choose
        rows.append({
            "segment": p.segment_tag, "name": p.name,
            "in_plan": cap is None or i < cap,
        })
    needed = len(personas)
    unlock = next((p.label for key, p in PLANS.items()
                   if key != "custom" and (p.max_personas is None or p.max_personas >= needed)
                   and (cap is not None and (p.max_personas is None or p.max_personas > cap))),
                  None)
    return {
        "selective": selective,
        "plan": limits_for(tenant.plan).label,
        "personas": rows,
        "unlock_plan": unlock if any(not r["in_plan"] for r in rows) else None,
    }


def set_query_active(session: Session, tenant: Tenant, query: Query, active: bool,
                     by: str) -> Query:
    """Pause or resume a question. The last active competitive question can't
    be paused: the headline needs a denominator."""
    if query.active == active:
        return query
    if not active:
        others = [q for q in session.exec(
            select(Query).where(Query.tenant_id == tenant.id, Query.active == True)  # noqa: E712
        ).all() if q.id != query.id and not q.branded]
        if not others and not query.branded:
            raise QueryControlError("Keep at least one active competitive question; add "
                                    "another before pausing this one.")
    query.active = active
    query.paused_at = None if active else utcnow()
    query.paused_by = None if active else by
    session.add(query)
    return query


def set_query_personas(session: Session, tenant: Tenant, query: Query,
                       segments: list[str]) -> Query:
    """Choose which personas a question runs against (besides the baseline).
    Segments must be the tenant's and inside the plan; overlays already set
    on a kept segment are preserved."""
    access = persona_access(session, tenant)
    if not access["selective"]:
        raise QueryControlError("This account runs every persona on every question "
                                "(no generic baseline persona); per-question personas "
                                "need a baseline persona in the config.")
    known = {r["segment"]: r for r in access["personas"]}
    wanted = [s for s in dict.fromkeys(segments) if s and s != GENERIC_SEGMENT]
    unknown = [s for s in wanted if s not in known]
    if unknown:
        raise QueryControlError(f"Unknown persona: {', '.join(unknown)}")
    locked = [known[s]["name"] for s in wanted if not known[s]["in_plan"]]
    if locked:
        plan = access["unlock_plan"] or "a higher plan"
        raise QueryControlError(f"{', '.join(locked)} {'is' if len(locked) == 1 else 'are'} "
                                f"not on the {access['plan']} plan; available on {plan}.")
    overlays = {r.get("segment"): r.get("overlay", "") for r in (query.persona_runs or [])}
    query.persona_runs = [{"segment": s, "overlay": overlays.get(s, "")} for s in wanted]
    session.add(query)
    return query
