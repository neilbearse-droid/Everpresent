"""Agent Analytics: which AI bots read the tenant's site, how often, which
pages, with what result — and how that lines up with the pages AI answers
actually cite.

Ingest keeps ONLY AI-bot lines, aggregated per (day, bot, path, status):
human traffic and IP addresses are never stored.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlmodel import Session, col, select

from api.models import AgentTrafficDaily, BrandProfile, Citation
from engine.agents.bots import PURPOSES, Bot, classify_user_agent
from engine.agents.logparse import LogParser
from engine.agents.verify import ip_in, ranges_for

# Distinct paths kept per upload; the long tail folds into one bucket so a
# crawler hitting millions of URLs can't blow up the table.
MAX_PATHS = 20_000
OTHER_PATH = "(other pages)"


def ingest_lines(
    session: Session,
    tenant_id: int,
    lines: Iterable[str],
    *,
    verify: bool = True,
    ranges: Callable[[str], list] = ranges_for,
) -> dict[str, Any]:
    """Parse, classify, aggregate and upsert. Caller owns the commit."""
    parser = LogParser()
    agg: dict[tuple[str, str, str, int], list[int]] = defaultdict(lambda: [0, 0])
    meta: dict[str, Bot] = {}
    paths: set[str] = set()
    n_lines = n_parsed = n_ai = 0
    for line in lines:
        n_lines += 1
        hit = parser.parse(line)
        if hit is None:
            continue
        n_parsed += 1
        bot = classify_user_agent(hit.user_agent)
        if bot is None:
            continue  # human or non-AI crawler: dropped, never stored
        n_ai += 1
        path = hit.path
        if path not in paths:
            if len(paths) >= MAX_PATHS:
                path = OTHER_PATH
            else:
                paths.add(path)
        verified = 0
        if verify and bot.ip_list_url and hit.ip:
            verified = 1 if ip_in(hit.ip, ranges(bot.ip_list_url)) else 0
        cell = agg[(hit.ts.date().isoformat(), bot.name, path, hit.status)]
        cell[0] += 1
        cell[1] += verified
        meta[bot.name] = bot

    dates = {k[0] for k in agg}
    existing: dict[tuple[str, str, str, int], AgentTrafficDaily] = {}
    if dates:
        for row in session.exec(
            select(AgentTrafficDaily).where(
                AgentTrafficDaily.tenant_id == tenant_id,
                col(AgentTrafficDaily.date).in_(dates),
            )
        ).all():
            existing[(row.date, row.bot, row.path, row.status)] = row
    for key, (hits, verified) in agg.items():
        row = existing.get(key)
        if row is None:
            bot = meta[key[1]]
            row = AgentTrafficDaily(
                tenant_id=tenant_id, date=key[0], bot=key[1], company=bot.company,
                purpose=bot.purpose, path=key[2], status=key[3],
            )
        row.hits += hits
        row.verified += verified
        session.add(row)

    by_bot: dict[str, int] = defaultdict(int)
    for (_d, name, _p, _s), (hits, _v) in agg.items():
        by_bot[name] += hits
    return {
        "lines": n_lines,
        "parsed": n_parsed,
        "ai_hits": n_ai,
        "unrecognized_lines": n_lines - n_parsed,
        "bots": dict(sorted(by_bot.items(), key=lambda kv: -kv[1])),
        "days": sorted(dates),
    }


def _owned_paths_cited(session: Session, tenant_id: int, since: datetime) -> dict[str, int]:
    """Paths on the brand's own domains that AI answers cited, with counts."""
    profile = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    domains = {d.lower().removeprefix("www.") for d in (profile.domains if profile else [])}
    if not domains:
        return {}
    from api.models import Result

    out: dict[str, int] = defaultdict(int)
    # Grouped in SQL: a busy tenant has hundreds of thousands of citation rows
    # but only a few thousand distinct URLs.
    for url, domain, n in session.exec(
        select(col(Citation.url), col(Citation.domain), func.count())
        .join(Result, col(Result.id) == col(Citation.result_id))
        .where(Citation.tenant_id == tenant_id, col(Result.created_at) >= since)
        .group_by(col(Citation.url), col(Citation.domain))
    ).all():
        parts = urlsplit(url or "")
        # Judge by the link's own host: Gemini's grounding-redirect links carry
        # the brand's domain as a label but point at vertexaisearch, not the
        # brand's page, so they can't be joined to a crawled path.
        host = (parts.hostname or domain or "").lower().removeprefix("www.")
        if any(host == o or host.endswith("." + o) for o in domains):
            out[(parts.path or "/").rstrip("/") or "/"] += int(n)
    return out


def agent_analytics(session: Session, tenant_id: int, days: int = 30) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    since_day = since.date().isoformat()
    rows = session.exec(
        select(AgentTrafficDaily).where(
            AgentTrafficDaily.tenant_id == tenant_id, AgentTrafficDaily.date >= since_day
        )
    ).all()
    total = sum(r.hits for r in rows)
    if not total:
        return {"has_data": False, "days": days}

    by_company: dict[str, dict] = {}
    by_purpose: dict[str, int] = defaultdict(int)
    by_bot: dict[str, dict] = {}
    series: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(PURPOSES, 0))
    pages: dict[str, dict] = {}
    errors = 0
    verified = 0
    for r in rows:
        by_purpose[r.purpose] += r.hits
        c = by_company.setdefault(r.company, {"company": r.company, "hits": 0})
        c["hits"] += r.hits
        b = by_bot.setdefault(r.bot, {"bot": r.bot, "company": r.company,
                                      "purpose": r.purpose, "hits": 0, "verified": 0,
                                      "errors": 0})
        b["hits"] += r.hits
        b["verified"] += r.verified
        verified += r.verified
        if r.status >= 400:
            errors += r.hits
            b["errors"] += r.hits
        series[r.date][r.purpose] = series[r.date].get(r.purpose, 0) + r.hits
        p = pages.setdefault(r.path, {"path": r.path, "hits": 0, "user": 0, "search": 0,
                                      "training": 0, "agent": 0, "errors": 0})
        p["hits"] += r.hits
        p[r.purpose] = p.get(r.purpose, 0) + r.hits
        if r.status >= 400:
            p["errors"] += r.hits

    cited = _owned_paths_cited(session, tenant_id, since)
    norm = {(k.rstrip("/") or "/"): v for k, v in pages.items()}
    for path, p in pages.items():
        p["cited"] = cited.get(path.rstrip("/") or "/", 0)
    # Read by answer engines (search/user fetches) but never cited: the page is
    # being considered and losing — the best content-fix targets.
    def _broken(p: dict) -> bool:
        return p["errors"] * 2 > p["hits"]

    read_not_cited = sorted(
        (p for p in pages.values()
         if p["cited"] == 0 and (p["search"] + p["user"]) > 0 and p["path"] != OTHER_PATH
         and not _broken(p)),
        key=lambda p: -(p["search"] + p["user"]),
    )[:15]
    # Cited in answers but erroring for bots, or not fetched at all lately:
    # the citation is at risk.
    at_risk = []
    for path, n in sorted(cited.items(), key=lambda kv: -kv[1]):
        p = norm.get(path)
        if p is None:
            at_risk.append({"path": path, "cited": n, "reason": "not fetched by AI bots lately"})
        elif p["errors"] > 0 and p["errors"] >= 0.05 * p["hits"]:
            # A real error rate, not the odd timeout on a busy page.
            at_risk.append({"path": path, "cited": n,
                            "reason": f"{p['errors']} error responses to AI bots"})
    # Mostly-erroring pages bots keep requesting: a redirect or fix is owed.
    broken_pages = sorted(
        (p for p in pages.values() if _broken(p) and p["path"] != OTHER_PATH),
        key=lambda p: -p["errors"],
    )[:15]
    top_pages = sorted(pages.values(), key=lambda p: -p["hits"])[:25]
    return {
        "has_data": True,
        "days": days,
        "total_hits": total,
        "verified_share": round(100.0 * verified / total, 1),
        "error_rate": round(100.0 * errors / total, 1),
        "by_purpose": {k: by_purpose.get(k, 0) for k in PURPOSES},
        "by_company": sorted(by_company.values(), key=lambda c: -c["hits"]),
        "by_bot": sorted(by_bot.values(), key=lambda b: -b["hits"]),
        "series": [{"date": d, **v} for d, v in sorted(series.items())],
        "top_pages": top_pages,
        "user_fetch_pages": sorted(
            (p for p in pages.values() if p["user"] > 0), key=lambda p: -p["user"]
        )[:10],
        "read_not_cited": read_not_cited,
        "cited_at_risk": at_risk[:15],
        "broken_pages": broken_pages,
        "pages_tracked": len(pages),
    }


MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # decompressed
_CHUNK_LINES = 50_000


async def ingest_stream(session: Session, tenant_id: int, chunks: Any) -> dict[str, Any]:
    """Ingest an async byte stream (plain or gzip) in bounded memory, in
    batches of lines. Raises ValueError past MAX_UPLOAD_BYTES."""
    import zlib

    decomp: Any = None
    first = True
    buf = b""
    total = 0
    batch: list[str] = []
    summary: dict[str, Any] = {"lines": 0, "parsed": 0, "ai_hits": 0,
                               "unrecognized_lines": 0, "bots": {}, "days": []}

    def _flush() -> None:
        if not batch:
            return
        part = ingest_lines(session, tenant_id, batch)
        for k in ("lines", "parsed", "ai_hits", "unrecognized_lines"):
            summary[k] += part[k]
        for name, n in part["bots"].items():
            summary["bots"][name] = summary["bots"].get(name, 0) + n
        summary["days"] = sorted(set(summary["days"]) | set(part["days"]))
        session.flush()
        batch.clear()

    async for chunk in chunks:
        if first:
            first = False
            if chunk[:2] == b"\x1f\x8b":
                decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = decomp.decompress(chunk) if decomp else chunk
        total += len(data)
        if total > MAX_UPLOAD_BYTES:
            raise ValueError("log file too large (max 200 MB uncompressed); split it")
        buf += data
        *lines, buf = buf.split(b"\n")
        batch.extend(ln.decode("utf-8", "replace") for ln in lines)
        if len(batch) >= _CHUNK_LINES:
            _flush()
    if decomp:
        buf += decomp.flush()
    if buf:
        batch.append(buf.decode("utf-8", "replace"))
    _flush()
    summary["bots"] = dict(sorted(summary["bots"].items(), key=lambda kv: -kv[1]))
    return summary
