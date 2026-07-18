"""Report export (M5): CSV for the data people, a one-page PDF for the
inbox. Everything reads Postgres rollups — no provider calls."""

import csv
import io
from datetime import UTC, datetime

from fpdf import FPDF
from sqlmodel import Session, select

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


def build_results_csv(session: Session, tenant_id: int, run_id: int | None = None) -> str:
    """Per-result rows; scoped to one run when run_id is given."""
    statement = select(Result).where(
        Result.tenant_id == tenant_id, Result.variant == ResultVariant.search
    )
    if run_id is not None:
        statement = statement.where(Result.run_id == run_id)
    results = list(session.exec(statement).all())
    result_ids = [r.id for r in results if r.id is not None]

    brand_mentions: dict[int, Mention] = {}
    citation_counts: dict[int, int] = {}
    if result_ids:
        for m in session.exec(
            select(Mention).where(Mention.result_id.in_(result_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            if m.entity_type == "brand":
                # Keep the BEST-ranked brand mention per result (lowest rank),
                # matching kpi_scorecard's min(...key=rank); setdefault kept the
                # first row the DB happened to return, which could be a lower
                # slot and disagree with the dashboard.
                current = brand_mentions.get(m.result_id)
                if current is None or (m.rank or 999) < (current.rank or 999):
                    brand_mentions[m.result_id] = m
        for c in session.exec(
            select(Citation).where(Citation.result_id.in_(result_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            citation_counts[c.result_id] = citation_counts.get(c.result_id, 0) + 1

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "run_id", "result_id", "created_at", "surface", "mode", "status",
            "query", "persona", "segment", "brand_mentioned", "brand_rank",
            "brand_sentiment", "citations", "latency_ms",
        ]
    )
    for r in sorted(results, key=lambda r: (r.run_id, r.id or 0)):
        mention = brand_mentions.get(r.id or -1)
        writer.writerow(
            [
                r.run_id, r.id, r.created_at.isoformat(), r.surface, r.mode, r.status,
                r.query_text, r.persona_name, r.persona_segment,
                bool(mention), mention.rank if mention else "",
                mention.sentiment if mention else "",
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
    writer = csv.writer(out)
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
    buckets: dict[str, int] = {}
    for c in classifications:
        buckets[c.web_search_likelihood] = buckets.get(c.web_search_likelihood, 0) + 1

    pdf = FPDF()
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
        for mover in ov["movers"][:6]:
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
