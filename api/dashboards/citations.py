"""Citations: who gets cited, power pages, consulted-but-not-cited sources."""

from collections import defaultdict

from sqlmodel import Session, col, select

from api.dashboards.common import _date_window, _latest_results_by_variant
from api.dashboards.overview import aio_summary
from api.models import (
    Citation,
    ConsultedSource,
    PagePresence,
    ResultVariant,
)
from engine.processing.citations import classify_source_type

MAX_POWER_PAGES = 30
# The consulted-but-not-cited domains list is a separate ranking; give it its
# own cap so tuning one doesn't silently move the other (§audit low).
MAX_CONSULTED_DOMAINS = 30


def citations_intel(
    session: Session, tenant_id: int, start: str | None = None, end: str | None = None
) -> dict:
    """Citations screen (§7.1 #4): which domains AI answers cite in this
    vertical, and whether the client is among them — plus Power Pages, the
    specific URLs that feed the category's answers. Domains are trivia; pages
    are the battlefield: getting onto (or beating) one high-influence page
    moves every answer it feeds."""
    lo, hi = _date_window(start, end)
    # Count citations from the LATEST result per (query, surface) only (§audit
    # H4) — not every result across every run. Otherwise domain/Power-Page
    # counts scale with run cadence (a page cited once per daily run reads as
    # ~30) instead of reflecting citation reality.
    results_by_id = {
        r.id: r
        for r in _latest_results_by_variant(
            session, tenant_id, ResultVariant.search, lo, hi, scope="competitive"
        ).values()
        if r.id is not None
    }
    latest_ids = set(results_by_id)
    domains: dict[str, dict] = {}
    pages: dict[str, dict] = {}
    # Per-engine source-type mix (§AEO-plan m4): where each engine draws its
    # citations from, so the earned-media playbook can be tailored per engine.
    source_types_by_engine: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for citation in session.exec(
        select(Citation).where(
            Citation.tenant_id == tenant_id,
            col(Citation.result_id).in_(list(latest_ids) or [-1]),
        ).order_by(col(Citation.id))
    ).all():
        _res = results_by_id.get(citation.result_id)
        if _res is not None:
            source_types_by_engine[str(_res.surface)][
                classify_source_type(citation.domain)
            ] += 1
        entry = domains.setdefault(
            citation.domain,
            {"domain": citation.domain, "category": citation.source_category, "count": 0,
             "surfaces": set()},
        )
        entry["count"] += 1
        if citation.source_category:
            entry["category"] = citation.source_category
        result = results_by_id.get(citation.result_id)
        if result is not None:
            entry["surfaces"].add(str(result.surface))

        page = pages.setdefault(
            citation.url,
            {"url": citation.url, "domain": citation.domain,
             "category": citation.source_category or "other",
             "citations": 0, "queries": set(), "surfaces": set()},
        )
        page["citations"] += 1
        if citation.source_category:
            page["category"] = citation.source_category
        if result is not None:
            page["queries"].add(result.query_text)
            page["surfaces"].add(str(result.surface))

    ranked = sorted(domains.values(), key=lambda d: -d["count"])
    # Influence = breadth (distinct queries the page's answers cover) first,
    # then raw citation volume.
    power = sorted(pages.values(), key=lambda p: (-len(p["queries"]), -p["citations"]))

    # On-page presence (§focus-group #2): join the crawl results so each
    # Power Page says whether the brand is actually named on it.
    presence_by_url = {
        row.url: row
        for row in session.exec(
            select(PagePresence).where(PagePresence.tenant_id == tenant_id)
        ).all()
    }

    def _with_presence(p: dict) -> dict:
        row = presence_by_url.get(p["url"])
        crawled = row if row is not None and row.status == "ok" else None
        return {
            **p,
            "queries": len(p["queries"]),
            "surfaces": sorted(p["surfaces"]),
            "on_page": crawled.brand_found if crawled else None,
            "competitors_on_page": crawled.competitors_found if crawled else [],
            "page_features": crawled.features if crawled else None,
        }

    # Consulted-but-not-cited domains (§AEO-plan M6): the engines read these on
    # the way to their answers but didn't cite them — a warm target list, since
    # they're already in the consideration set. Excludes anything already cited.
    cited_domains = set(domains)
    consulted: dict[str, dict] = {}
    for cs in session.exec(
        select(ConsultedSource).where(ConsultedSource.tenant_id == tenant_id)
    ).all():
        if cs.result_id not in latest_ids:  # §audit H4: latest results only
            continue
        src = results_by_id.get(cs.result_id)
        if cs.domain in cited_domains:
            continue
        entry = consulted.setdefault(cs.domain, {"domain": cs.domain, "count": 0, "queries": set()})
        entry["count"] += 1
        if src is not None:
            entry["queries"].add(src.query_text)
    consulted_ranked = sorted(consulted.values(), key=lambda d: -d["count"])[:MAX_CONSULTED_DOMAINS]

    return {
        "domains": [{**d, "surfaces": sorted(d["surfaces"])} for d in ranked],
        "power_pages": [_with_presence(p) for p in power[:MAX_POWER_PAGES]],
        "consulted_domains": [
            {"domain": d["domain"], "count": d["count"], "queries": len(d["queries"])}
            for d in consulted_ranked
        ],
        "source_types_by_engine": {
            surface: dict(sorted(types.items(), key=lambda kv: -kv[1]))
            for surface, types in source_types_by_engine.items()
        },
        "aio": aio_summary(session, tenant_id),
    }
