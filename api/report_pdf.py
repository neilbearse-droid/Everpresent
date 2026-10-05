"""The client report PDF: a branded, multi-page HTML report rendered with
WeasyPrint. Every number comes from the same services the dashboard uses,
so the PDF never disagrees with the app. Each section is built on its own;
one failing section shows "not available" instead of breaking the report."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from sqlmodel import Session, col, select

from api.dashboards.common import _surface_label
from api.models import Recommendation, RecommendationStatus, Run, Tenant

log = logging.getLogger(__name__)

ASSETS = Path(__file__).parent / "report_assets"

ORANGE = "#ff5a1f"
INK = "#0b1220"
RIVAL_GREYS = ("#8a95a9", "#c3cad7")
GRID = "#e7e9ee"
MUTED = "#636c7c"

_env = Environment(
    loader=FileSystemLoader(ASSETS),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=ChainableUndefined,
)


def _section(name: str, fn, *args) -> Any:
    try:
        return fn(*args)
    except Exception:  # one broken section must not cost the whole report
        log.exception("report section failed: %s", name)
        return None


def _fmt_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime("%b %-d, %Y")
    except ValueError:
        return str(value)


def _short_date(value: str) -> str:
    try:
        return datetime.fromisoformat(str(value)[:10]).strftime("%b %-d")
    except ValueError:
        return str(value)


def change_pill(change: dict | None) -> dict:
    """Brand change as a status pill: orange for good news, ink for bad,
    neutral when the change didn't pass the test."""
    if not change:
        return {"cls": "", "text": "No baseline yet"}
    verdict, delta = change.get("verdict"), change.get("delta") or 0
    if verdict == "up":
        return {"cls": "pill-good", "text": f"Up {abs(delta):.1f} pts"}
    if verdict == "down":
        return {"cls": "pill-bad", "text": f"Down {abs(delta):.1f} pts"}
    return {"cls": "", "text": "No real change"}


# --- Charts (inline SVG; static, since this is print) --------------------


def trend_svg(trend: list[dict], brand: str, width: int = 660, height: int = 210) -> Markup:
    """Brand score over time, with the two strongest rivals for context.
    Brand in orange, rivals in greys; every line labelled at its end."""
    if len(trend) < 2:
        return Markup("")
    left, right, top, bottom = 30, 120, 12, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    n = len(trend)

    def x(i: int) -> float:
        return left + plot_w * i / (n - 1)

    def y(v: float) -> float:
        return top + plot_h * (1 - max(0.0, min(100.0, v)) / 100)

    last = trend[-1].get("competitors", {})
    rivals = sorted(last, key=lambda k: -(last.get(k) or 0))[:2]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" font-family="Inter" font-size="10">']
    for v in (0, 25, 50, 75, 100):
        parts.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y(v):.1f}" y2="{y(v):.1f}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{left - 6}" y="{y(v) + 3:.1f}" text-anchor="end" '
                     f'fill="{MUTED}">{v}</text>')
    for i in sorted({0, n // 2, n - 1}):
        anchor = "start" if i == 0 else "end" if i == n - 1 else "middle"
        parts.append(f'<text x="{x(i):.1f}" y="{height - 8}" text-anchor="{anchor}" '
                     f'fill="{MUTED}">{_short_date(trend[i]["date"])}</text>')

    series = [(name, [p.get("competitors", {}).get(name) for p in trend], RIVAL_GREYS[k], 1.5)
              for k, name in enumerate(rivals)]
    series.append((brand, [p.get("brand_score") for p in trend], ORANGE, 2.5))
    labels: list[list] = []
    for name, values, colour, stroke in series:
        pts = [(x(i), y(v)) for i, v in enumerate(values) if v is not None]
        if not pts:
            continue
        path = " ".join(f"{'M' if j == 0 else 'L'}{px:.1f},{py:.1f}"
                        for j, (px, py) in enumerate(pts))
        parts.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="{stroke}" '
                     'stroke-linejoin="round" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3.5" fill="{colour}" '
                     'stroke="#fff" stroke-width="1.5"/>')
        final = next(v for v in reversed(values) if v is not None)
        labels.append([pts[-1][1], name, final, name == brand])
    # Direct labels at the line ends, nudged apart so they never collide.
    labels.sort(key=lambda lab: lab[0])
    for k in range(1, len(labels)):
        labels[k][0] = max(labels[k][0], labels[k - 1][0] + 13)
    for ly, name, final, is_brand in labels:
        weight = "700" if is_brand else "500"
        fill = INK if is_brand else MUTED
        parts.append(f'<text x="{left + plot_w + 8}" y="{ly + 3.5:.1f}" fill="{fill}" '
                     f'font-weight="{weight}">{_esc(name)} {final:.0f}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


def range_svg(rate: float, low: float, high: float, width: int = 190, height: int = 16) -> Markup:
    """A rate on a 0-100 track with its confidence range."""
    def x(v: float) -> float:
        return 4 + (width - 8) * max(0.0, min(100.0, v)) / 100

    mid = height / 2
    return Markup(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<line x1="4" x2="{width - 4}" y1="{mid}" y2="{mid}" stroke="{GRID}" stroke-width="2" '
        'stroke-linecap="round"/>'
        f'<line x1="{x(low):.1f}" x2="{x(high):.1f}" y1="{mid}" y2="{mid}" stroke="#c3cad7" '
        'stroke-width="6" stroke-linecap="round"/>'
        f'<circle cx="{x(rate):.1f}" cy="{mid}" r="4.5" fill="{ORANGE}" stroke="#fff" '
        'stroke-width="1.5"/></svg>'
    )


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def bars(items: list[tuple[str, float]], highlight: str | None,
         scale: float | None = None) -> list[dict]:
    """Rows for an HTML bar list: the highlighted entity in orange."""
    top = scale or max((v for _, v in items), default=0) or 1
    return [{"name": n, "value": v, "pct": max(1.5, 100 * v / top), "brand": n == highlight}
            for n, v in items]


# --- Sections -------------------------------------------------------------


def _cover_and_scorecard(session: Session, tenant_id: int) -> dict:
    from api.briefing_service import briefing
    from api.dashboards_service import kpi_scorecard, overview

    ov = overview(session, tenant_id)
    kpi = kpi_scorecard(session, tenant_id)
    brief = briefing(session, tenant_id)
    brand = ov.get("brand_name") or brief.get("brand") or ""
    mr = kpi.get("mention_rates", {})
    overall = mr.get("overall") or {}
    sov = ov.get("share_of_voice", {})
    prominence = kpi.get("prominence") or {}
    return {
        "brand": brand,
        "window": mr.get("window") or {},
        "verdict": (brief.get("winning") or {}),
        "focus": brief.get("focus"),
        "overall": overall,
        "overall_pill": change_pill(overall.get("change")),
        "answer_share": kpi.get("answer_share"),
        "sov_bars": bars(sorted(sov.items(), key=lambda kv: -kv[1]), brand),
        "brand_sov": sov.get(brand),
        "prominence": prominence,
        "stability": kpi.get("stability") or {},
        "head_to_head": kpi.get("head_to_head") or [],
        "trend_svg": trend_svg(ov.get("trend") or [], brand),
        "series_notes": ov.get("series_notes") or [],
        "why": brief.get("why") or [],
        "engines": [
            {**e, "pill": change_pill(e.get("change")),
             "svg": range_svg(e.get("rate") or 0, e.get("low") or 0, e.get("high") or 0)}
            for e in sorted(mr.get("engines") or [], key=lambda e: -(e.get("rate") or 0))
        ],
    }


def _citations(session: Session, tenant_id: int) -> dict:
    from api.dashboards_service import citations_intel

    ci = citations_intel(session, tenant_id)
    domains = (ci.get("domains") or [])[:8]
    return {
        "domains": [{**d, "engines": len(d.get("surfaces") or [])} for d in domains],
        "domain_bars": bars([(d["domain"], d["count"]) for d in domains], None),
        "power_pages": (ci.get("power_pages") or [])[:5],
    }


def _drivers(session: Session, tenant_id: int) -> dict:
    from api.agent_picks_service import agent_picks
    from api.dashboards_service import fanout_report
    from api.own_pages_service import own_pages

    pages = own_pages(session, tenant_id)
    conflicts = [
        {"path": p["path"], "cited": p.get("cited", 0), **c}
        for p in pages.get("pages") or [] for c in p.get("fact_conflicts") or []
    ]
    fan = fanout_report(session, tenant_id)
    picks = agent_picks(session, tenant_id)
    return {
        "conflicts": conflicts[:5],
        "fanout": [{**p, "subqueries": (p.get("subqueries") or [])[:5]}
                   for p in (fan.get("prompts") or [])[:3]],
        "fanout_observed": fan.get("observed"),
        "picks": picks if picks.get("has_data") else None,
    }


def _playbook(session: Session, tenant_id: int) -> list[Recommendation]:
    return list(session.exec(
        select(Recommendation)
        .where(Recommendation.tenant_id == tenant_id,
               col(Recommendation.status).in_([RecommendationStatus.open,
                                               RecommendationStatus.in_progress]))
        .order_by(col(Recommendation.priority).desc())
        .limit(6)
    ).all())


def _proof(session: Session, tenant_id: int) -> dict:
    from api.proof_service import intervention_proof

    return intervention_proof(session, tenant_id)


def report_context(session: Session, tenant: Tenant, run: Run | None = None) -> dict:
    assert tenant.id is not None
    tid = tenant.id
    score = _section("scorecard", _cover_and_scorecard, session, tid) or {}
    window = score.get("window") or {}
    return {
        "tenant": tenant,
        "brand": score.get("brand") or tenant.name,
        "generated": datetime.now(UTC).strftime("%b %-d, %Y"),
        "period": (f"{_fmt_date(window.get('start'))} – {_fmt_date(window.get('end'))}"
                   if window else ""),
        "run": run,
        "s": score,
        "c": _section("citations", _citations, session, tid),
        "d": _section("drivers", _drivers, session, tid),
        "plays": _section("playbook", _playbook, session, tid) or [],
        "proof": _section("proof", _proof, session, tid),
        "label": _surface_label,
        "fmt_date": _fmt_date,
    }


def render_report_html(session: Session, tenant: Tenant, run: Run | None = None) -> str:
    return _env.get_template("report.html").render(**report_context(session, tenant, run))


def build_report_pdf(session: Session, tenant: Tenant, run: Run | None = None) -> bytes:
    from weasyprint import HTML

    html = render_report_html(session, tenant, run)
    return HTML(string=html, base_url=str(ASSETS)).write_pdf() or b""
