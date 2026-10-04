"""First-party AI visibility data (m33): the reports Google, Bing, Cloudflare
and GA4 now give site owners, imported as CSV exports and reconciled with
what EverPresent measures.

Formats differ by source and change often, so the importer maps columns by
name instead of by position: a date column, a page/URL column, a query-like
text column, and every numeric column as a metric. Re-importing the same
cells replaces them (exports are snapshots, not increments)."""

import csv
import io
import re
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session, col

from api.models import FirstPartyDaily

SOURCES = {
    "gsc": "Google Search Console (AI features)",
    "bing": "Bing Webmaster Tools (AI Performance)",
    "merchant": "Google Merchant Center (AI insights)",
    "cloudflare": "Cloudflare AI Crawl Control",
    "ga4": "GA4 (AI assistant referrals)",
    "other": "Other export",
}
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000

_DATE_COLS = ("date", "day", "time", "timestamp", "period", "month")
_PAGE_COLS = ("page", "url", "landing page", "top pages", "page path", "address",
              "cited url", "path", "page url", "landing page + query string")
_TEXT_COLS = ("query", "top queries", "search query", "grounding query", "prompt",
              "crawler", "bot", "user agent", "operator", "intent", "topic",
              "session source", "source", "product", "item")
_NUM = re.compile(r"^-?[\d,]*\.?\d+%?$")
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d, %Y",
                 "%d %b %Y", "%Y%m%d", "%Y-%m")


class ImportError_(ValueError):  # noqa: N801 — avoid shadowing the builtin
    pass


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower().lstrip("﻿"))


def _parse_date(v: str) -> str | None:
    v = v.strip()
    if not v:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v[:30], fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _page(v: str) -> str:
    v = v.strip()
    if not v:
        return ""
    path = urlsplit(v).path if "://" in v else v.split("?", 1)[0]
    return (unquote(path).rstrip("/") or "/")[:500]


def _number(v: str) -> float | None:
    v = v.strip().replace(" ", "")
    if not v or not _NUM.match(v):
        return None
    pct = v.endswith("%")
    n = float(v.rstrip("%").replace(",", ""))
    return n / 100 if pct else n


def parse_export(data: bytes) -> list[dict[str, Any]]:
    """CSV/TSV export → cells {date, page, query, metric, value}."""
    if len(data) > MAX_BYTES:
        raise ImportError_("export too large (max 20 MB); export a shorter date range")
    text = data.decode("utf-8-sig", "replace")
    # Some exports put a title or notes above the header row: start at the
    # first line that has at least two delimited cells.
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines[:20])
                  if ln.count(",") >= 1 or ln.count("\t") >= 1), 0)
    body = "\n".join(lines[start:])
    first = body.split("\n", 1)[0]
    dialect = "excel-tab" if first.count("\t") > first.count(",") else "excel"
    reader = csv.reader(io.StringIO(body), dialect=dialect)
    header = next(reader, None)
    if not header:
        raise ImportError_("the file is empty")
    names = [_norm(h) for h in header]
    date_i = next((i for i, n in enumerate(names) if n in _DATE_COLS), None)
    page_i = next((i for i, n in enumerate(names) if n in _PAGE_COLS), None)
    text_i = next((i for i, n in enumerate(names) if n in _TEXT_COLS and i != page_i), None)
    dims = {i for i in (date_i, page_i, text_i) if i is not None}
    rows = list(reader)[:MAX_ROWS]
    metric_cols = [
        i for i, _n in enumerate(names)
        if i not in dims and any(_number(r[i]) is not None for r in rows[:50] if i < len(r))
    ]
    if not metric_cols:
        raise ImportError_("no numeric columns found; is this the right export?")
    cells: list[dict[str, Any]] = []
    for r in rows:
        if not any(c.strip() for c in r):
            continue
        day = _parse_date(r[date_i]) if date_i is not None and date_i < len(r) else ""
        if day is None:
            continue  # a totals/footer row
        page = _page(r[page_i]) if page_i is not None and page_i < len(r) else ""
        query = r[text_i].strip()[:300] if text_i is not None and text_i < len(r) else ""
        for i in metric_cols:
            if i >= len(r):
                continue
            n = _number(r[i])
            if n is None:
                continue
            metric = re.sub(r"[^a-z0-9]+", "_", names[i]).strip("_")[:60] or f"col{i}"
            cells.append({"date": day, "page": page, "query": query, "metric": metric,
                          "value": n})
    if not cells:
        raise ImportError_("no data rows found")
    return cells


def import_export(session: Session, tenant_id: int, source: str, data: bytes) -> dict[str, Any]:
    if source not in SOURCES:
        raise ImportError_(f"unknown source {source!r}")
    cells = parse_export(data)
    # Aggregate duplicate keys inside one file (e.g. split by device) by sum.
    agg: dict[tuple[str, str, str, str], float] = {}
    for c in cells:
        k = (c["date"], c["page"], c["query"], c["metric"])
        agg[k] = agg.get(k, 0.0) + c["value"]
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    table = FirstPartyDaily.__table__  # pyright: ignore[reportAttributeAccessIssue]
    from api.models import utcnow

    rows = [{"tenant_id": tenant_id, "source": source, "date": d, "page": p, "query": q,
             "metric": m, "value": v, "imported_at": utcnow()}
            for (d, p, q, m), v in agg.items()]
    for i in range(0, len(rows), 300):
        stmt = insert(table).values(rows[i:i + 300])
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "source", "date", "page", "query", "metric"],
            set_={"value": stmt.excluded.value, "imported_at": stmt.excluded.imported_at},
        )
        session.execute(stmt)
    days = sorted({d for d, *_ in agg if d})
    return {
        "source": source,
        "cells": len(rows),
        "metrics": sorted({m for *_x, m in agg}),
        "pages": len({p for _d, p, _q, _m in agg if p}),
        "from": days[0] if days else None,
        "to": days[-1] if days else None,
    }


def first_party_summary(session: Session, tenant_id: int) -> dict[str, Any]:
    T = FirstPartyDaily
    out = []
    for source, metric, total, lo, hi, n in session.execute(
        sa_select(col(T.source), col(T.metric), func.sum(T.value), func.min(T.date),
                  func.max(T.date), func.count())
        .where(col(T.tenant_id) == tenant_id)
        .group_by(col(T.source), col(T.metric))
    ).all():
        out.append({"source": source, "label": SOURCES.get(source, source), "metric": metric,
                    "total": round(float(total or 0), 2), "from": lo or None, "to": hi or None,
                    "rows": int(n)})
    return {"sources": sorted(out, key=lambda r: (r["source"], r["metric"]))}


def page_metrics(session: Session, tenant_id: int) -> dict[str, dict[str, float]]:
    """{page path: {"gsc:impressions": n, "bing:citations": n, …}} summed."""
    T = FirstPartyDaily
    out: dict[str, dict[str, float]] = {}
    for source, page, metric, total in session.execute(
        sa_select(col(T.source), col(T.page), col(T.metric), func.sum(T.value))
        .where(col(T.tenant_id) == tenant_id, col(T.page) != "")
        .group_by(col(T.source), col(T.page), col(T.metric))
    ).all():
        out.setdefault(page, {})[f"{source}:{metric}"] = float(total or 0)
    return out
