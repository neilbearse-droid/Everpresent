"""Report export (M5): CSV for the data people, a one-page PDF for the
inbox. Everything reads Postgres rollups — no provider calls."""

import csv
import io
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from fpdf import FPDF
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, func, select

from api import dashboards_service
from api.dashboards_service import overview, personas
from api.models import (
    Citation,
    Mention,
    QueryClassification,
    Result,
    ResultVariant,
    Run,
    Tenant,
    VisibilityDaily,
)

# The built-in PDF fonts only cover Latin-1. Map the common typographic
# characters that appear in names ("Macy’s", "X — Y") to plain equivalents,
# and replace anything else, so a report never fails on a name.
_TYPOGRAPHIC = str.maketrans({
    "\u2014": "-", "\u2013": "-", "\u2012": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2026": "...", "\u00a0": " ", "\u2022": "-", "\u2192": "->", "\u00b7": "-",
})


def _latin1(text: str) -> str:
    return str(text).translate(_TYPOGRAPHIC).encode("latin-1", "replace").decode("latin-1")


class _LatinPDF(FPDF):
    """FPDF whose text calls are made Latin-1 safe."""

    def cell(self, w=None, h=None, text="", *args, **kwargs):  # type: ignore[override]
        return super().cell(w, h, _latin1(text), *args, **kwargs)

    def multi_cell(self, w, h=None, text="", *args, **kwargs):  # type: ignore[override]
        return super().multi_cell(w, h, _latin1(text), *args, **kwargs)


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: object) -> object:
    """Neutralize spreadsheet formula injection: a text cell starting with
    = + - @ (or tab/CR) is prefixed with ' so Excel/Sheets shows it as text.
    Numbers pass through untouched, so negative scores stay numeric."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


class _SafeCsvWriter:
    def __init__(self, out: io.StringIO) -> None:
        self._writer = csv.writer(out)

    def writerow(self, row: list) -> None:
        self._writer.writerow([_csv_cell(v) for v in row])


def build_results_csv(session: Session, tenant_id: int, run_id: int | None = None) -> str:
    """Per-result rows; scoped to one run when run_id is given."""
    scope: list[Any] = [Result.tenant_id == tenant_id, Result.variant == ResultVariant.search]
    if run_id is not None:
        scope.append(Result.run_id == run_id)
    # Plain column rows, not ORM objects: a full-history export is tens of
    # thousands of rows and full objects cost hundreds of MB per request.
    # (sqlalchemy's select: sqlmodel's typed overloads stop at four columns.)
    results = list(session.execute(
        sa_select(
            col(Result.run_id), col(Result.id), col(Result.created_at), col(Result.surface),
            col(Result.mode), col(Result.status), col(Result.query_text),
            col(Result.persona_name), col(Result.persona_segment), col(Result.latency_ms),
        ).where(*scope).order_by(col(Result.run_id), col(Result.id))
    ).all())

    # result_id -> (rank, sentiment) of its best-ranked brand mention.
    brand_mentions: dict[int, tuple[int | None, str | None]] = {}
    citation_counts: dict[int, int] = {}
    if results:
        # Joined/aggregated in the database: an IN list of every result id
        # (tens of thousands after a few months) is slow and memory-heavy.
        for result_id, rank, sentiment in session.exec(
            select(col(Mention.result_id), col(Mention.rank), col(Mention.sentiment))
            .join(Result, col(Result.id) == col(Mention.result_id))
            .where(*scope, Mention.entity_type == "brand")
        ).all():
            # Keep the BEST-ranked brand mention per result (lowest rank),
            # matching kpi_scorecard's min(...key=rank); setdefault kept the
            # first row the DB happened to return, which could be a lower
            # slot and disagree with the dashboard.
            current = brand_mentions.get(result_id)
            if current is None or (rank or 999) < (current[0] or 999):
                brand_mentions[result_id] = (rank, sentiment)
        citation_counts = {
            rid: int(n)
            for rid, n in session.exec(
                select(col(Citation.result_id), func.count())
                .join(Result, col(Result.id) == col(Citation.result_id))
                .where(*scope)
                .group_by(col(Citation.result_id))
            ).all()
        }

    out = io.StringIO()
    writer = _SafeCsvWriter(out)
    writer.writerow(
        [
            "run_id", "result_id", "created_at", "surface", "mode", "status",
            "query", "persona", "segment", "brand_mentioned", "brand_rank",
            "brand_sentiment", "citations", "latency_ms",
        ]
    )
    for r in results:
        mention = brand_mentions.get(r.id or -1)
        writer.writerow(
            [
                r.run_id, r.id, r.created_at.isoformat(), r.surface, r.mode, r.status,
                r.query_text, r.persona_name, r.persona_segment,
                bool(mention), mention[0] if mention else "",
                mention[1] if mention else "",
                citation_counts.get(r.id or -1, 0), r.latency_ms,
            ]
        )
    return out.getvalue()


def build_visibility_csv(session: Session, tenant_id: int) -> str:
    rows = session.exec(
        select(VisibilityDaily).where(VisibilityDaily.tenant_id == tenant_id)
    ).all()
    competitor_names = sorted({n for row in rows for n in row.competitor_scores})
    out = io.StringIO()
    writer = _SafeCsvWriter(out)
    writer.writerow(
        ["date", "surface", "segment", "brand_score", "mention_rate", "citation_rate",
         "result_count", *competitor_names]
    )
    for row in sorted(rows, key=lambda r: (r.date, str(r.surface), r.persona_segment)):
        writer.writerow(
            [
                row.date, row.surface, row.persona_segment, row.brand_score,
                row.extras.get("mention_rate", ""), row.extras.get("citation_rate", ""),
                row.extras.get("result_count", ""),
                *[row.competitor_scores.get(n, "") for n in competitor_names],
            ]
        )
    return out.getvalue()


def build_summary_pdf(session: Session, tenant: Tenant, run: Run | None = None) -> bytes:
    """One-page visibility summary: headline scores, share of voice, movers,
    per-segment table, query buckets."""
    assert tenant.id is not None
    ov = overview(session, tenant.id)
    pe = personas(session, tenant.id)
    classifications = session.exec(
        select(QueryClassification).where(QueryClassification.tenant_id == tenant.id)
    ).all()
    # Classifications are per (query, engine); the corpus counts QUERIES, so
    # each query lands in the bucket most of its engines agree on.
    per_query: dict[str, Counter[str]] = {}
    for c in classifications:
        if c.web_search_likelihood:
            per_query.setdefault(c.query_text, Counter())[c.web_search_likelihood] += 1
    buckets: dict[str, int] = {}
    for votes in per_query.values():
        label = votes.most_common(1)[0][0]
        buckets[label] = buckets.get(label, 0) + 1

    pdf = _LatinPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 10, f"EverPresent - {tenant.name}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    scope = f"run #{run.id}" if run is not None else "all data"
    pdf.cell(0, 6, f"Generated {stamp} - {scope}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("helvetica", "B", 13)
    pdf.cell(0, 8, "Headline", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 11)
    latest = ov.get("latest")
    if latest:
        pdf.cell(
            0, 6,
            f"Brand visibility {latest['brand_score']}/100 on {latest['date']}",
            new_x="LMARGIN", new_y="NEXT",
        )
    sov = ov.get("share_of_voice", {})
    brand_sov = sov.get(ov.get("brand_name", ""), None)
    if brand_sov is not None:
        pdf.cell(0, 6, f"Share of voice ({dashboards_service.SOV_DAYS}d): {brand_sov}%",
                 new_x="LMARGIN", new_y="NEXT")
    if not latest and brand_sov is None:
        pdf.cell(0, 6, "No measurement data yet.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if sov:
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 8, "Share of voice", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        for name, pct in sorted(sov.items(), key=lambda kv: -kv[1]):
            pdf.cell(0, 5.5, f"  {name}: {pct}%", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    if ov.get("movers"):
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 8, "Biggest movers", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        moved = [m for m in ov["movers"] if m["delta"] != 0]
        if not moved:
            pdf.cell(0, 5.5, "  No change since the previous measurement.",
                     new_x="LMARGIN", new_y="NEXT")
        for mover in moved[:6]:
            sign = "+" if mover["delta"] >= 0 else ""
            change = f"({mover['before']} -> {mover['after']})"
            pdf.cell(
                0, 5.5,
                f"  {mover['label']}: {sign}{mover['delta']} {change}",
                new_x="LMARGIN", new_y="NEXT",
            )
        pdf.ln(3)

    if pe.get("segments"):
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 8, f"Persona segments ({pe['date']})", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        for seg in pe["segments"]:
            top = sorted(seg["competitor_scores"].items(), key=lambda kv: -kv[1])[:1]
            top_txt = f"; strongest competitor {top[0][0]} at {top[0][1]}" if top else ""
            pdf.cell(
                0, 5.5,
                f"  {seg['segment']}: brand {seg['brand_score']}"
                f" (mentioned {round(seg['mention_rate'] * 100)}%){top_txt}",
                new_x="LMARGIN", new_y="NEXT",
            )
        pdf.ln(3)

    if buckets:
        pdf.set_font("helvetica", "B", 13)
        pdf.cell(0, 8, "Query corpus - web-search likelihood", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        for bucket in ("very_likely", "likely", "possible", "unlikely"):
            if bucket in buckets:
                pdf.cell(
                    0, 5.5, f"  {bucket.replace('_', ' ')}: {buckets[bucket]} queries",
                    new_x="LMARGIN", new_y="NEXT",
                )

    return bytes(pdf.output())
