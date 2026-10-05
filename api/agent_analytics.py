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
from urllib.parse import unquote, urlsplit

from sqlalchemy import func
from sqlalchemy import select as sa_select
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
    paths: set[str] | None = None,
    parser: LogParser | None = None,
) -> dict[str, Any]:
    """Parse, classify, aggregate and upsert. Caller owns the commit. Pass the
    same `paths` set and `parser` across the batches of one upload so
    MAX_PATHS caps the whole upload and CloudFront's #Fields header carries
    over between batches."""
    parser = parser or LogParser()
    agg: dict[tuple[str, str, str, int], list[int]] = defaultdict(lambda: [0, 0])
    meta: dict[str, Bot] = {}
    seen_paths = paths if paths is not None else set()
    n_lines = n_parsed = n_ai = 0
    for line in lines:
        n_lines += 1
        hits = parser.parse_all(line)
        if hits:
            n_parsed += 1
        for hit in hits:
            n_ai += _count_hit(hit, agg, meta, seen_paths, verify, ranges)

    _upsert_cells(session, tenant_id, agg, meta)

    by_bot: dict[str, int] = defaultdict(int)
    for (_d, name, _p, _s), (hits, _v) in agg.items():
        by_bot[name] += hits
    return {
        "lines": n_lines,
        "parsed": n_parsed,
        "ai_hits": n_ai,
        "unrecognized_lines": n_lines - n_parsed,
        "bots": dict(sorted(by_bot.items(), key=lambda kv: -kv[1])),
        "days": sorted({k[0] for k in agg}),
    }


def _count_hit(
    hit: Any,
    agg: dict[tuple[str, str, str, int], list[int]],
    meta: dict[str, Bot],
    seen_paths: set[str],
    verify: bool,
    ranges: Callable[[str], list],
) -> int:
    """Aggregate one hit; 1 if it was an AI bot, else 0."""
    bot = classify_user_agent(hit.user_agent)
    if bot is None:
        return 0  # human or non-AI crawler: dropped, never stored
    path = hit.path
    if path not in seen_paths:
        if len(seen_paths) >= MAX_PATHS:
            path = OTHER_PATH
        else:
            seen_paths.add(path)
    verified = 0
    if verify and bot.ip_list_url and hit.ip:
        verified = 1 if ip_in(hit.ip, ranges(bot.ip_list_url)) else 0
    cell = agg[(hit.ts.date().isoformat(), bot.name, path, hit.status)]
    cell[0] += 1
    cell[1] += verified
    meta[bot.name] = bot
    return 1


_UPSERT_ROWS = 300  # rows per statement (10 params each; well under SQLite's limit)


def _upsert_cells(
    session: Session,
    tenant_id: int,
    agg: dict[tuple[str, str, str, int], list[int]],
    meta: dict[str, Bot],
) -> None:
    """Add counts to existing cells in one statement per chunk. An atomic
    INSERT ... ON CONFLICT DO UPDATE, so two uploads for the same tenant and
    day (a log drain retrying while a manual upload runs) can't collide on
    the unique cell constraint."""
    if not agg:
        return
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    table = AgentTrafficDaily.__table__  # pyright: ignore[reportAttributeAccessIssue]
    rows = [
        {"tenant_id": tenant_id, "date": d, "bot": name, "company": meta[name].company,
         "purpose": meta[name].purpose, "path": path, "status": status,
         "hits": hits, "verified": verified}
        for (d, name, path, status), (hits, verified) in agg.items()
    ]
    for i in range(0, len(rows), _UPSERT_ROWS):
        stmt = insert(table).values(rows[i : i + _UPSERT_ROWS])
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "date", "bot", "path", "status"],
            set_={"hits": table.c.hits + stmt.excluded.hits,
                  "verified": table.c.verified + stmt.excluded.verified},
        )
        session.execute(stmt)


def _norm_path(path: str) -> str:
    """One key per page: percent-decoded (logs are decoded at parse time) and
    without a trailing slash, so /pricing and /pricing/ are one page."""
    if path == OTHER_PATH:
        return path
    return unquote(path).rstrip("/") or "/"


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
            out[_norm_path(parts.path or "/")] += int(n)
    return out


# Responses that mean the bot was turned away, as opposed to a dead page (404
# and 410 are the page's problem, reported under broken pages).
_BLOCKED = (401, 403, 407, 429)


def _is_blocked(status: int) -> bool:
    return status in _BLOCKED or status >= 500


def agent_analytics(session: Session, tenant_id: int, days: int = 30) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    since_day = since.date().isoformat()
    T = AgentTrafficDaily
    window = (col(T.tenant_id) == tenant_id, col(T.date) >= since_day)
    # Aggregated in SQL: per-day rows can number in the hundreds of thousands;
    # the report needs them per (bot, path, status) and per (day, purpose).
    cells = session.execute(
        sa_select(col(T.bot), col(T.company), col(T.purpose), col(T.path), col(T.status),
                  func.sum(T.hits), func.sum(T.verified))
        .where(*window)
        .group_by(col(T.bot), col(T.company), col(T.purpose), col(T.path), col(T.status))
    ).all()
    total = sum(int(c[5] or 0) for c in cells)
    if not total:
        has_older = session.exec(
            select(func.count()).select_from(T).where(T.tenant_id == tenant_id)
        ).one()
        return {"has_data": False, "days": days, "stale": bool(has_older)}

    by_company: dict[str, dict] = {}
    by_purpose: dict[str, int] = defaultdict(int)
    by_bot: dict[str, dict] = {}
    pages: dict[str, dict] = {}
    errors = 0
    verified = 0
    for bot, company, purpose, raw_path, status, hits_, ver_ in cells:
        hits, ver = int(hits_ or 0), int(ver_ or 0)
        by_purpose[purpose] += hits
        c = by_company.setdefault(company, {"company": company, "hits": 0})
        c["hits"] += hits
        b = by_bot.setdefault(bot, {"bot": bot, "company": company, "purpose": purpose,
                                    "hits": 0, "verified": 0, "errors": 0, "blocked": 0})
        b["hits"] += hits
        b["verified"] += ver
        verified += ver
        path = _norm_path(raw_path)
        # A page's "errors" are its own faults (404, 410, 5xx); refusals (401,
        # 403, 407, 429) are an access rule turning a bot away, reported per
        # bot. Mixing them told people to redirect pages that were only blocked.
        p = pages.setdefault(path, {"path": path, "hits": 0, "user": 0, "search": 0,
                                    "training": 0, "agent": 0, "errors": 0, "refused": 0})
        p["hits"] += hits
        p[purpose] = p.get(purpose, 0) + hits
        if status >= 400:
            errors += hits
            b["errors"] += hits
            if status in _BLOCKED:
                p["refused"] += hits
            else:
                p["errors"] += hits
        if _is_blocked(status):
            b["blocked"] += hits

    series_rows = session.exec(
        select(col(T.date), col(T.purpose), func.sum(T.hits))
        .where(*window).group_by(col(T.date), col(T.purpose))
    ).all()
    series: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(PURPOSES, 0))
    for d, purpose, n in series_rows:
        series[d][purpose] = series[d].get(purpose, 0) + int(n or 0)

    cited = _owned_paths_cited(session, tenant_id, since)
    for path, p in pages.items():
        p["cited"] = cited.get(path, 0)

    def _broken(p: dict) -> bool:
        return p["errors"] * 2 > p["hits"]

    # Read by answer engines (search/user fetches) but never cited: the page is
    # being considered and losing — the best content-fix targets.
    read_not_cited = sorted(
        (p for p in pages.values()
         if p["cited"] == 0 and (p["search"] + p["user"]) > 0 and p["path"] != OTHER_PATH
         and not _broken(p)),
        key=lambda p: (-(p["search"] + p["user"]), p["path"]),
    )[:15]
    # Cited in answers but erroring for bots, or not fetched at all lately:
    # the citation is at risk.
    at_risk = []
    for path, n in sorted(cited.items(), key=lambda kv: (-kv[1], kv[0])):
        p = pages.get(path)
        if p is None:
            at_risk.append({"path": path, "cited": n, "reason": "not fetched by AI bots lately"})
        elif p["errors"] > 0 and p["errors"] >= 0.05 * p["hits"]:
            # A real error rate, not the odd timeout on a busy page.
            at_risk.append({"path": path, "cited": n,
                            "reason": f"{p['errors']} error responses to AI bots"})
    # Mostly-erroring pages bots keep requesting: a redirect or fix is owed.
    broken_pages = sorted(
        (p for p in pages.values() if _broken(p) and p["path"] != OTHER_PATH),
        key=lambda p: (-p["errors"], p["path"]),
    )[:15]
    top_pages = sorted(pages.values(), key=lambda p: (-p["hits"], p["path"]))[:25]
    return {
        "has_data": True,
        "days": days,
        "total_hits": total,
        "verified_share": round(100.0 * verified / total, 1),
        "error_rate": round(100.0 * errors / total, 1),
        "by_purpose": {k: by_purpose.get(k, 0) for k in PURPOSES},
        "by_company": sorted(by_company.values(), key=lambda c: -c["hits"]),
        "by_bot": sorted(by_bot.values(), key=lambda b: (-b["hits"], b["bot"])),
        "series": [{"date": d, **v} for d, v in sorted(series.items())],
        "top_pages": top_pages,
        "user_fetch_pages": sorted(
            (p for p in pages.values() if p["user"] > 0), key=lambda p: (-p["user"], p["path"])
        )[:10],
        "read_not_cited": read_not_cited,
        "cited_at_risk": at_risk[:15],
        "broken_pages": broken_pages,
        "pages_tracked": len(pages),
    }


class UploadError(ValueError):
    """A log upload the API refuses; `status` is the HTTP status to return."""

    status = 400


class UploadTooLarge(UploadError):
    status = 413


MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # decompressed, and on the wire
MAX_LINE_BYTES = 16 * 1024  # longer "lines" are junk: skipped, never buffered
_CHUNK_LINES = 50_000
_INFLATE_STEP = 1 << 20  # inflate at most 1 MB at a time (bounded memory)


async def ingest_stream(session: Session, tenant_id: int, chunks: Any) -> dict[str, Any]:
    """Ingest an async byte stream (plain or gzip, including concatenated gzip
    members) in bounded memory and linear time: only new bytes are scanned for
    newlines, an over-long line is skipped without being buffered, inflation
    is capped per step, and the parsing and database work run in a worker
    thread so a big upload never stalls the server's event loop. Raises
    UploadTooLarge past MAX_UPLOAD_BYTES and UploadError on a corrupt gzip.
    `overlap_days` lists days that already had data before this upload:
    uploads add up, so re-sending the same log double-counts it."""
    import zlib

    from starlette.concurrency import run_in_threadpool

    decomp: Any = None
    first = True
    pending = bytearray()  # the current, unfinished line
    skipping = False  # inside an over-long line: drop bytes until its newline
    wire = total = overlong = 0
    batch: list[str] = []
    paths: set[str] = set()
    parser = LogParser()
    head = b""  # the first bytes, until there are enough to sniff gzip
    days_before: set[str] | None = None
    summary: dict[str, Any] = {"lines": 0, "parsed": 0, "ai_hits": 0,
                               "unrecognized_lines": 0, "bots": {}, "days": [],
                               "overlap_days": []}

    def _flush() -> None:
        nonlocal days_before
        if not batch:
            return
        if days_before is None:
            days_before = set(session.exec(
                select(col(AgentTrafficDaily.date))
                .where(AgentTrafficDaily.tenant_id == tenant_id).distinct()
            ).all())
        part = ingest_lines(session, tenant_id, batch, paths=paths, parser=parser)
        for k in ("lines", "parsed", "ai_hits", "unrecognized_lines"):
            summary[k] += part[k]
        for name, n in part["bots"].items():
            summary["bots"][name] = summary["bots"].get(name, 0) + n
        summary["days"] = sorted(set(summary["days"]) | set(part["days"]))
        session.flush()
        batch.clear()

    def _feed(data: bytes) -> None:
        nonlocal skipping, overlong
        start = 0
        while True:
            nl = data.find(b"\n", start)
            piece = data[start:] if nl == -1 else data[start:nl]
            if not skipping:
                if len(pending) + len(piece) > MAX_LINE_BYTES:
                    pending.clear()
                    skipping = True
                    overlong += 1
                else:
                    pending.extend(piece)
            if nl == -1:
                return
            if skipping:
                skipping = False
            else:
                batch.append(pending.decode("utf-8", "replace"))
                pending.clear()
            start = nl + 1

    def _check(n: int) -> None:
        nonlocal total
        total += n
        if total > MAX_UPLOAD_BYTES:
            raise UploadTooLarge("log file too large (max 200 MB uncompressed); split it")

    async for chunk in chunks:
        if not chunk:
            continue
        wire += len(chunk)
        if wire > MAX_UPLOAD_BYTES:
            raise UploadTooLarge("log file too large (max 200 MB uncompressed); split it")
        if first:
            head += chunk
            if len(head) < 2:
                continue  # can't tell gzip from text on one byte
            first = False
            chunk, head = head, b""
            if chunk[:2] == b"\x1f\x8b":
                decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
        if decomp is None:
            _check(len(chunk))
            _feed(chunk)
        else:
            data = chunk
            while data:
                try:
                    out = decomp.decompress(data, _INFLATE_STEP)
                except zlib.error as exc:
                    raise UploadError(f"not a valid gzip file ({exc})") from exc
                _check(len(out))
                _feed(out)
                if decomp.unconsumed_tail:
                    data = decomp.unconsumed_tail
                elif decomp.eof and decomp.unused_data:
                    # Concatenated .gz files (e.g. rotated logs cat'ed together).
                    data = decomp.unused_data
                    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
                else:
                    data = b""
        if len(batch) >= _CHUNK_LINES:
            await run_in_threadpool(_flush)
    if head:  # a one-byte upload
        _check(len(head))
        _feed(head)
    if decomp is not None:
        tail = decomp.flush()
        _check(len(tail))
        _feed(tail)
    if pending and not skipping:
        batch.append(pending.decode("utf-8", "replace"))
    await run_in_threadpool(_flush)
    summary["lines"] += overlong
    summary["unrecognized_lines"] += overlong
    summary["overlap_days"] = sorted(set(summary["days"]) & (days_before or set()))
    summary["bots"] = dict(sorted(summary["bots"].items(), key=lambda kv: -kv[1]))
    return summary
