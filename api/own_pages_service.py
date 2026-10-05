"""Your Pages (m33): the brand's own pages that AI answers use, and whether
each one is fit for it. Newer engines check facts on the brand's own site
(2026 vendor studies saw ChatGPT send much of its searching there), so a stale price or an error on
the help center now lands directly in the answer.

One row per own page, joining:
  cited   — how often our sampled answers linked it, by which engines
  crawl   — reachable? when last checked? updated date? newest year named?
  facts   — statements that contradict the brand's fact sheet
  bots    — AI search/user fetches and error responses (Agent Analytics)
  first-party — Google/Bing/Cloudflare numbers the tenant imported
plus pages first-party data shows in AI features that our samples never
saw cited.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from api.agent_analytics import _norm_path
from api.models import (
    AgentTrafficDaily,
    BrandFact,
    BrandProfile,
    Citation,
    PagePresence,
    Result,
)
from engine.processing.citations import domain_is_owned

WINDOW_DAYS = 30
MAX_ROWS = 60


def _owned(session: Session, tenant_id: int) -> list[str]:
    b = session.exec(select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)).first()
    return list(b.domains) if b else []


def _path_of(url: str, owned: list[str]) -> str | None:
    from urllib.parse import urlsplit

    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if not host or not domain_is_owned(host, owned):
        return None
    return _norm_path(parts.path or "/")


def own_pages(session: Session, tenant_id: int, days: int = WINDOW_DAYS) -> dict[str, Any]:
    from api.dashboards_service import _surface_label
    from api.first_party_service import page_metrics

    owned = _owned(session, tenant_id)
    since = datetime.now(UTC) - timedelta(days=days)
    pages: dict[str, dict[str, Any]] = {}

    def row(path: str) -> dict[str, Any]:
        return pages.setdefault(path, {
            "path": path, "url": None, "cited": 0, "inline": 0, "engines": set(),
            "crawl": None, "fact_conflicts": [], "bot_reads": 0, "bot_errors": 0,
            "first_party": {}, "flags": [],
        })

    for url, kind, surface, n in session.execute(
        sa_select(col(Citation.url), col(Citation.link_kind), col(Result.surface), func.count())
        .join(Result, col(Result.id) == col(Citation.result_id))
        .where(col(Citation.tenant_id) == tenant_id, col(Result.created_at) >= since)
        .group_by(col(Citation.url), col(Citation.link_kind), col(Result.surface))
    ).all():
        path = _path_of(url, owned)
        if path is None:
            continue
        r = row(path)
        r["url"] = r["url"] or url
        r["cited"] += int(n)
        r["inline"] += int(n) if kind == "inline" else 0
        r["engines"].add(_surface_label(str(surface)))

    # Active facts, so a conflict shows the rule it broke, and one whose fact
    # was since switched off or deleted disappears without waiting for a
    # re-crawl.
    facts = {f.id: f for f in session.exec(
        select(BrandFact).where(BrandFact.tenant_id == tenant_id,
                                BrandFact.active == True)  # noqa: E712
    ).all()}

    def live_conflicts(raw: list[dict]) -> list[dict]:
        out = []
        for c in raw:
            fact = facts.get(c.get("fact_id"))
            if fact is None:
                continue
            out.append({**c, "kind": fact.kind, "label": fact.label})
        return out

    # Latest crawl per own page.
    for pp in session.exec(select(PagePresence).where(PagePresence.tenant_id == tenant_id)).all():
        path = _path_of(pp.url, owned)
        if path is None:
            continue
        r = row(path)
        r["url"] = r["url"] or pp.url
        f = pp.features or {}
        crawl = {"status": pp.status, "http_status": pp.http_status,
                 "checked": pp.fetched_at.date().isoformat() if pp.fetched_at else None,
                 "has_updated_date": bool(f.get("has_updated_date")),
                 "latest_year": int(f.get("latest_year") or 0),
                 "has_price": bool(f.get("has_price"))}
        if r["crawl"] is None or (crawl["checked"] or "") >= (r["crawl"]["checked"] or ""):
            r["crawl"] = crawl
            r["fact_conflicts"] = live_conflicts(list(f.get("fact_conflicts") or []))

    # AI bot reads and errors per path (search + live user fetches).
    since_day = since.date().isoformat()
    T = AgentTrafficDaily
    has_logs = False
    for path_raw, purpose, status, hits in session.execute(
        sa_select(col(T.path), col(T.purpose), col(T.status), func.sum(T.hits))
        .where(col(T.tenant_id) == tenant_id, col(T.date) >= since_day)
        .group_by(col(T.path), col(T.purpose), col(T.status))
    ).all():
        has_logs = True
        path = _norm_path(path_raw)
        if path not in pages:
            continue
        r = pages[path]
        if purpose in ("search", "user"):
            r["bot_reads"] += int(hits or 0)
        if status >= 400:
            r["bot_errors"] += int(hits or 0)

    # First-party numbers: attach to known pages, and surface pages that
    # Google/Bing say appear in AI features but our samples never saw cited.
    fp = page_metrics(session, tenant_id)
    unseen = []
    for path, metrics in fp.items():
        p = _norm_path(path)
        if p in pages:
            pages[p]["first_party"] = {k: round(v, 2) for k, v in metrics.items()}
        else:
            ai = sum(v for k, v in metrics.items()
                     if k.split(":", 1)[1] in ("impressions", "citations", "ai_impressions"))
            if ai > 0:
                unseen.append({"path": p, "first_party": {k: round(v, 2)
                                                          for k, v in metrics.items()}})
    unseen.sort(key=lambda u: -sum(u["first_party"].values()))

    year = datetime.now(UTC).year
    out = []
    for r in pages.values():
        c = r["crawl"]
        if r["fact_conflicts"]:
            r["flags"].append("facts conflict")
        if c and c["status"] != "ok":
            # Bot protection often turns away our checker while AI bots get
            # through; only call it unreachable when bots don't read it either.
            refused = c["http_status"] in (401, 403, 429)
            r["flags"].append("blocks our checker" if refused and r["bot_reads"] > 0
                              else "unreachable")
        if c and c["status"] == "ok" and not c["has_updated_date"] and c["latest_year"] < year:
            r["flags"].append("stale")
        if has_logs and r["cited"] and r["bot_reads"] == 0:
            r["flags"].append("not read by AI search bots")
        if r["bot_errors"] and r["bot_errors"] >= 0.05 * max(r["bot_reads"], 1):
            r["flags"].append("errors for AI bots")
        if c is None and r["cited"]:
            r["flags"].append("not checked yet")
        r["engines"] = sorted(r["engines"])
        out.append(r)
    severity = {"facts conflict": 0, "unreachable": 1, "errors for AI bots": 2,
                "stale": 3, "not read by AI search bots": 4, "blocks our checker": 5,
                "not checked yet": 6}
    out.sort(key=lambda r: (min((severity[f] for f in r["flags"]), default=9), -r["cited"],
                            r["path"]))
    return {
        "days": days,
        "domains": owned,
        "has_logs": has_logs,
        "has_first_party": bool(fp),
        "pages": out[:MAX_ROWS],
        "pages_total": len(out),
        "flagged": sum(1 for r in out
                       if set(r["flags"]) - {"not checked yet", "blocks our checker"}),
        "in_ai_features_not_sampled": unseen[:15],
    }
