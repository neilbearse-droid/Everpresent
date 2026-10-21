"""Site searches: which websites the engines search *inside* (`site:` in their
sub-searches) while answering your questions, yours against your rivals'.

ChatGPT now sends a share of its sub-searches to one domain, mostly brand
sites, to check facts at the source. If it checks your rivals' sites and not
yours, their pages are the ones answering. Read from the sub-searches we
already store; no extra calls."""

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from api.dashboards.common import _branded_query_texts, _surface_label
from api.models import BrandProfile, Competitor, Result, ResultStatus, ResultVariant

WINDOW_DAYS = 30
MAX_TARGETS = 10
MAX_LOOKED_FOR = 12

_SITE = re.compile(r"\bsite:\s*(?:https?://)?([a-z0-9][a-z0-9.-]*\.[a-z]{2,})[^\s]*",
                   re.IGNORECASE)


def site_targets(query: str) -> tuple[list[str], str]:
    """The domains a sub-search is limited to, and what it looked for there."""
    domains = [d.lower().removeprefix("www.").rstrip(".") for d in _SITE.findall(query or "")]
    words = [w for w in _SITE.sub(" ", query or "").replace('"', " ").split()
             if w.upper() not in ("OR", "AND", "|")]
    # "site:a.com pricing OR site:b.com pricing" repeats the terms per site.
    for size in range(1, len(words) // 2 + 1):
        if len(words) % size == 0 and words == words[:size] * (len(words) // size):
            words = words[:size]
            break
    return domains, " ".join(words)


def _matches(domain: str, owned: str) -> bool:
    owned = owned.lower().removeprefix("www.")
    return domain == owned or domain.endswith("." + owned)


def site_searches(session: Session, tenant_id: int, days: int = WINDOW_DAYS) -> dict[str, Any]:
    brand = session.exec(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)).first()
    brand_name = brand.brand_name if brand else "You"
    brand_domains = list(brand.domains) if brand else []
    rivals = [(c.name, list(c.domains)) for c in session.exec(
        select(Competitor).where(Competitor.tenant_id == tenant_id)).all()]
    # A question that names the brand sends engines to its site by design.
    branded = _branded_query_texts(session, tenant_id)

    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.execute(
        sa_select(col(Result.surface), col(Result.query_text), col(Result.fanout_queries))
        .where(col(Result.tenant_id) == tenant_id, col(Result.status) == ResultStatus.ok,
               col(Result.variant).in_([ResultVariant.search, ResultVariant.natural]),
               col(Result.created_at) >= since)
    ).all()

    total_subs = 0
    targets: dict[str, dict[str, Any]] = {}
    looked_for: dict[str, dict[str, Any]] = {}
    for surface, qtext, subs in rows:
        if qtext in branded or not subs:
            continue
        label = _surface_label(str(getattr(surface, "value", surface)))
        for sub in subs:
            if not isinstance(sub, str):
                continue
            total_subs += 1
            domains, rest = site_targets(sub)
            for domain in dict.fromkeys(domains):  # each site once per sub-search
                if any(_matches(domain, d) for d in brand_domains):
                    key, name, kind = "owned", brand_name, "owned"
                else:
                    rival = next((n for n, ds in rivals if any(_matches(domain, d) for d in ds)),
                                 None)
                    key, name, kind = ((f"rival:{rival}", rival, "competitor") if rival
                                       else (f"other:{domain}", domain, "other"))
                t = targets.setdefault(key, {"name": name, "kind": kind, "domains": set(),
                                             "count": 0, "engines": Counter(),
                                             "asks": Counter()})
                t["count"] += 1
                t["domains"].add(domain)
                t["engines"][label] += 1
                if rest:
                    t["asks"][rest] += 1
                if kind == "owned" and rest:
                    lf = looked_for.setdefault(rest.lower(), {"text": rest, "count": 0,
                                                              "engines": set()})
                    lf["count"] += 1
                    lf["engines"].add(label)

    site_total = sum(t["count"] for t in targets.values())
    owned = targets.get("owned")
    ranked = sorted(targets.values(), key=lambda t: (-t["count"], t["name"]))
    by_kind: dict[str, int] = defaultdict(int)
    for t in targets.values():
        by_kind[t["kind"]] += t["count"]
    return {
        "days": days,
        "brand": brand_name,
        "has_domains": bool(brand_domains),
        "sub_searches": total_subs,
        "site_searches": site_total,
        "owned": by_kind["owned"],
        "rivals": by_kind["competitor"],
        "other": by_kind["other"],
        "owned_share": round(100 * by_kind["owned"] / site_total, 1) if site_total else 0.0,
        "targets": [
            {"name": t["name"], "kind": t["kind"], "domains": sorted(t["domains"]),
             "count": t["count"], "engines": dict(t["engines"].most_common()),
             "top_asks": [a for a, _n in t["asks"].most_common(3)]}
            for t in ranked[:MAX_TARGETS]
        ],
        "owned_engines": dict(owned["engines"].most_common()) if owned else {},
        "looked_for": [
            {"text": v["text"], "count": v["count"], "engines": sorted(v["engines"])}
            for v in sorted(looked_for.values(), key=lambda v: (-v["count"], v["text"]))
        ][:MAX_LOOKED_FOR],
    }
