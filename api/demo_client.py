"""A fully fictional demo client, built through the real pipeline.

Northpeak (northpeak.example) is a made-up website builder with four
made-up rivals. Everything is on `.example` domains, which can never
resolve, so nothing real is crawled, quoted or accused.

The point is that every action step on the Recommendations page is
legitimate: this module writes raw answers, bot logs, page checks and one
logged fix, then runs the normal processing and playbook. Each play is
derived from data a viewer can open and check. The story the data tells:

- Northpeak cut its Starter plan to $12 a month, but /help/plans still says
  $19, and ChatGPT, Gemini and Perplexity repeat $19 while citing that page.
- "Cheapest domain and website" is a live-search gap: Domainly and Siteforge
  win it, cited from g2.com, smallbizstack.example and Reddit, and engines
  search sub-questions Northpeak never answers.
- "Most reliable builder" is answered from model memory (a long game).
- Google's AI Overview for "website cost" cites rivals, and the cost guide
  that used to be cited dropped out in the latest run (it is also stale and
  erroring for Googlebot).
- No Claude-SearchBot in 30 days of logs, PerplexityBot is refused often, an
  old pricing URL 404s, and the e-commerce page is read but never cited.
- ChatGPT never cites Northpeak's own pages; ChatGPT switched models 10 days ago.
- A comparison page shipped 14 days ago lifted "best domain registrar"
  against a flat control.
- Siteforge buys ads in Google AI Mode; agents pick Siteforge first.

Rebuilding wipes the tenant's data (not its login link) and starts again.
The spend cap is 0, so nobody can launch paid runs on a fictional brand.
"""

import random
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlmodel import Session, SQLModel, col, select

from api.models import (
    AgentTrafficDaily,
    Citation,
    FanoutShard,
    FirstPartyDaily,
    Intervention,
    PagePresence,
    Query,
    QueryClassification,
    RawPayload,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunMode,
    RunStatus,
    SurfaceCode,
    Tenant,
    utcnow,
)
from api.storage import write_raw_envelope
from api.yaml_import import TenantConfigSpec, import_config

SLUG = "demo-client"
NAME = "Demo Client (Northpeak)"
BRAND = "Northpeak"
SITE = "https://northpeak.example"

# Tables a rebuild must keep: the tenant itself, people and the audit trail.
_KEEP = {"tenants", "users", "memberships", "audit_log"}

CONFIG: dict[str, Any] = {
    "brand": {"name": BRAND, "aliases": ["Northpeak Sites"], "domains": ["northpeak.example"]},
    "geo": {"country": "us", "language": "en"},
    "competitors": [
        {"name": "Siteforge", "domains": ["siteforge.example"]},
        {"name": "Pagecraft", "domains": ["pagecraft.example"]},
        {"name": "Hostwell", "domains": ["hostwell.example"]},
        {"name": "Domainly", "domains": ["domainly.example"]},
    ],
    "personas": [
        {"name": "Generic", "segment": "generic", "prompt": ""},
        {"name": "Bakery owner", "segment": "bakery",
         "prompt": "I run a small bakery and need my first website."},
    ],
    "queries": [
        {"text": "Best website builder for a small bakery?", "corpus": "builders",
         "personas": ["bakery"]},
        {"text": "What's the cheapest way to get a domain and a website?", "corpus": "domains"},
        {"text": "Which website builder is most reliable for a small business?",
         "corpus": "builders"},
        {"text": "How much does a small business website cost?", "corpus": "pricing"},
        {"text": "Website builder with online booking for a salon?", "corpus": "builders"},
        {"text": "Best domain registrar for a new business?", "corpus": "domains"},
        {"text": "Is Northpeak's Starter plan worth it?", "corpus": "brand", "branded": True},
        {"text": "Northpeak vs Siteforge: which is better?", "corpus": "brand",
         "branded": True},
        {"text": "Build me a website for my bakery this week. Pick the builder and walk me "
                 "through it.", "corpus": "agent_task"},
        {"text": "Write a script that registers a domain through a registrar's API.",
         "corpus": "agent_code"},
    ],
    "brand_facts": [
        {"label": "Starter plan is $12 a month (since August 2026)",
         "subject": "Starter plan", "aliases": ["Starter"], "expected": "$12",
         "kind": "numeric", "category": "pricing"},
    ],
    "surfaces": ["openai_api", "claude_api", "gemini_api", "perplexity_api",
                 "google_aio", "google_ai_mode"],
}

Q_BAKERY, Q_CHEAP, Q_RELIABLE, Q_COST, Q_BOOKING, Q_REGISTRAR, Q_WORTH, Q_VS, Q_TASK, \
    Q_CODE = (q["text"] for q in CONFIG["queries"])

API = [SurfaceCode.openai_api, SurfaceCode.claude_api, SurfaceCode.gemini_api,
       SurfaceCode.perplexity_api]
SERP = [SurfaceCode.google_ai_mode, SurfaceCode.google_aio]
RUN_DAYS_AGO = (27, 24, 20, 17, 13, 10, 6, 3, 1)
SHIP_DAYS_AGO = 14  # the logged fix on the registrar question
MODEL_SWITCH_DAYS_AGO = 10

MODELS = {"claude_api": "claude-sonnet-4-6", "gemini_api": "gemini-3.6-flash",
          "perplexity_api": "sonar-pro"}

# Third-party pages engines cite, per question. Rival sites appear too.
SOURCES = {
    Q_BAKERY: ["https://www.g2.com/categories/website-builders",
               "https://smallbizstack.example/best-builders-for-bakeries",
               "https://www.youtube.com/watch?v=bakery-site-demo",
               "https://siteforge.example/templates/bakery"],
    Q_CHEAP: ["https://www.g2.com/categories/domain-registrars",
              "https://smallbizstack.example/cheapest-domain-and-website",
              "https://www.reddit.com/r/smallbusiness/comments/cheap_site",
              "https://domainly.example/pricing", "https://siteforge.example/pricing"],
    Q_RELIABLE: ["https://en.wikipedia.org/wiki/Website_builder",
                 "https://webbuilderreport.example/uptime-2026",
                 "https://hostwell.example/uptime"],
    Q_COST: ["https://smallbizstack.example/website-costs",
             "https://www.g2.com/articles/website-cost",
             "https://siteforge.example/pricing"],
    Q_BOOKING: ["https://www.capterra.com/booking-software",
                "https://pagecraft.example/booking",
                "https://www.youtube.com/watch?v=salon-booking-setup"],
    Q_REGISTRAR: ["https://webbuilderreport.example/best-registrars",
                  "https://domainly.example/why-domainly",
                  "https://www.reddit.com/r/Entrepreneur/comments/registrar"],
    Q_WORTH: ["https://smallbizstack.example/northpeak-review"],
    Q_VS: ["https://webbuilderreport.example/northpeak-vs-siteforge"],
    Q_TASK: ["https://siteforge.example/start", "https://smallbizstack.example/quick-start"],
    Q_CODE: ["https://domainly.example/docs/api", "https://www.reddit.com/r/webdev/comments/api"],
}

TOPIC = {
    Q_BAKERY: "a small bakery website", Q_CHEAP: "a cheap domain and website",
    Q_RELIABLE: "a reliable small-business site", Q_COST: "small business website costs",
    Q_BOOKING: "salon booking", Q_REGISTRAR: "registering a business domain",
    Q_WORTH: "Northpeak's Starter plan", Q_VS: "Northpeak versus Siteforge",
    Q_TASK: "a bakery website this week", Q_CODE: "registering a domain from code",
}

LINES = {
    BRAND: ["Northpeak is easy for beginners and has good bakery templates, but support "
            "can be slow on weekends.",
            "Northpeak includes online booking on its paid plans.",
            "Northpeak's editor is simple, though its e-commerce features are limited."],
    "Siteforge": ["Siteforge is popular for its low first-year price and large template "
                  "library.", "Siteforge bundles a domain with every annual plan."],
    "Pagecraft": ["Pagecraft has the most flexible design tools, with a steeper learning "
                  "curve.", "Pagecraft's booking add-on is well reviewed by salons."],
    "Hostwell": ["Hostwell is known for reliable uptime and strong support.",
                 "Hostwell costs more but rarely goes down."],
    "Domainly": ["Domainly sells some of the cheapest domains and has a clean API.",
                 "Domainly's renewal prices stay close to the first-year price."],
}

SHARDS = ["cheapest website builder with a free domain",
          "domain and website bundle price comparison",
          "website builder renewal prices after year one"]


def _days_ago(n: int, now: datetime) -> datetime:
    return (now - timedelta(days=n)).replace(hour=13, minute=5, second=0, microsecond=0)


def _brand_odds(q: str, surface: str, days_ago: int) -> float:
    if q == Q_REGISTRAR:
        return 0.65 if days_ago < SHIP_DAYS_AGO else 0.15
    return {Q_BAKERY: 0.75, Q_CHEAP: 0.12, Q_RELIABLE: 0.10, Q_COST: 0.40,
            Q_BOOKING: 0.50, Q_WORTH: 1.0, Q_VS: 1.0, Q_TASK: 0.45, Q_CODE: 0.2}[q]


def _rivals(q: str) -> list[str]:
    return {Q_BAKERY: ["Siteforge", "Pagecraft", "Hostwell"],
            Q_CHEAP: ["Domainly", "Siteforge"], Q_RELIABLE: ["Hostwell", "Pagecraft"],
            Q_COST: ["Siteforge", "Pagecraft"], Q_BOOKING: ["Pagecraft", "Siteforge"],
            Q_REGISTRAR: ["Domainly", "Hostwell"], Q_WORTH: ["Siteforge"],
            Q_VS: ["Siteforge"], Q_TASK: ["Siteforge", "Pagecraft"],
            Q_CODE: ["Domainly"]}[q]


def _answer(rng: random.Random, q: str, surface: str, days_ago: int,
            latest: bool) -> tuple[str, list[str], dict]:
    """(answer text, cited urls, extra response payload) for one sample."""
    named = rng.random() < _brand_odds(q, surface, days_ago)
    # Gap questions are gaps on the latest run on every engine but Perplexity,
    # so the playbook's "named on X, missing on Y" line is stable.
    if latest and q in (Q_CHEAP, Q_RELIABLE):
        named = surface == "perplexity_api"
    rivals = _rivals(q)[:]
    rng.shuffle(rivals)
    if q == Q_TASK:  # agents reach for Siteforge first most of the time
        rivals = ["Siteforge"] + [r for r in rivals if r != "Siteforge"]
    if q == Q_CODE:
        rivals = ["Domainly"]
    names = rivals[:]
    if named:
        first = q in (Q_WORTH, Q_VS) or (q == Q_TASK and rng.random() < 0.3) or (
            q in (Q_BAKERY, Q_BOOKING) and rng.random() < 0.5)
        names.insert(0 if first else min(1, len(names)), BRAND)
    lines = [f"For {TOPIC[q]}, the options people usually weigh are {', '.join(names)}."]
    for n in names:
        lines.append(rng.choice(LINES[n]))
    urls = list(SOURCES[q])
    rng.shuffle(urls)
    urls = urls[:3]
    # The pricing story: on questions about Northpeak itself, three engines
    # repeat the stale $19 from /help/plans; Claude cites /pricing and is right.
    if q in (Q_WORTH, Q_VS):
        urls = list(SOURCES[q])
        if surface in ("openai_api", "gemini_api", "perplexity_api"):
            lines.append("Northpeak's Starter plan costs $19 a month, billed annually.")
            urls.append(f"{SITE}/help/plans")
        else:
            lines.append("Northpeak's Starter plan is $12 a month.")
            urls.append(f"{SITE}/pricing")
    # ChatGPT never cites Northpeak's own pages on category questions.
    if named and surface != "openai_api" and q not in (Q_WORTH, Q_VS):
        if q == Q_COST and not latest:
            urls.append(f"{SITE}/blog/website-cost-guide")  # lost in the latest run
        elif q == Q_BAKERY:
            urls.append(f"{SITE}/templates/bakery")
            if surface == "claude_api":
                urls.append(f"{SITE}/")
        elif q == Q_BOOKING:
            urls.append(f"{SITE}/features/online-booking")
        elif q == Q_REGISTRAR and days_ago < SHIP_DAYS_AGO:
            urls.append(f"{SITE}/domains/compare")
    extra: dict = {}
    if surface == "google_ai_mode" and q in (Q_CHEAP, Q_COST, Q_BAKERY) and rng.random() < 0.45:
        extra["sponsored"] = [{
            "title": "Siteforge: your website from $1 a month",
            "url": "https://siteforge.example/offer", "domain": "siteforge.example",
            "text": "Domain included. Cancel any time.", "placement": "serp"}]
    return "\n".join(lines), urls, extra


def _wipe(session: Session, tenant_id: int) -> None:
    for table in reversed(SQLModel.metadata.sorted_tables):
        if table.name in _KEEP or "tenant_id" not in table.c:
            continue
        session.execute(sa_delete(table).where(table.c.tenant_id == tenant_id))
    session.execute(sa_delete(RawPayload).where(col(RawPayload.uri).startswith(f"{SLUG}/")))
    session.commit()


def _bot_logs(session: Session, tenant_id: int, now: datetime) -> None:
    from engine.agents.bots import BOTS

    meta = {b.name: b for b in BOTS}
    # (bot, path, status, hits per day[, from day, to day]) over 30 days.
    plan: list[tuple] = [
        ("OAI-SearchBot", "/pricing", 200, 4), ("OAI-SearchBot", "/help/plans", 200, 3),
        ("OAI-SearchBot", "/templates/bakery", 200, 2),
        ("OAI-SearchBot", "/features/ecommerce", 200, 3),
        ("OAI-SearchBot", "/old-pricing", 404, 2), ("OAI-SearchBot", "/", 200, 2),
        ("ChatGPT-User", "/pricing", 200, 2), ("ChatGPT-User", "/help/plans", 200, 1),
        ("GPTBot", "/", 200, 10), ("GPTBot", "/blog/website-cost-guide", 200, 3),
        # Refused on uncited pages, so this reads as one access problem.
        ("PerplexityBot", "/features/online-booking", 200, 1),
        ("PerplexityBot", "/features/online-booking", 403, 2),
        ("PerplexityBot", "/pricing", 403, 1),
        ("Googlebot", "/features/online-booking", 200, 3),
        ("Googlebot", "/", 200, 3), ("Googlebot", "/pricing", 200, 2),
        ("Googlebot", "/blog/website-cost-guide", 200, 2),
        ("Googlebot", "/blog/website-cost-guide", 500, 1),
        ("Googlebot", "/old-pricing", 404, 1), ("Googlebot", "/features/ecommerce", 200, 1),
        ("Bingbot", "/", 200, 3), ("Bingbot", "/pricing", 200, 2),
        ("ClaudeBot", "/", 200, 4),
    ]
    for d in range(30):
        day = (now - timedelta(days=d)).date().isoformat()
        for bot, path, status, hits in plan:
            b = meta[bot]
            session.add(AgentTrafficDaily(tenant_id=tenant_id, date=day, bot=bot,
                                          company=b.company, purpose=b.purpose, path=path,
                                          status=status, hits=hits, verified=hits))
        # The comparison page: read far more after it shipped.
        reads = 4 if d < SHIP_DAYS_AGO else 1
        session.add(AgentTrafficDaily(tenant_id=tenant_id, date=day, bot="OAI-SearchBot",
                                      company="OpenAI", purpose="search",
                                      path="/domains/compare", status=200, hits=reads,
                                      verified=reads))


def _pages(session: Session, tenant_id: int, fact_id: int | None, now: datetime) -> None:
    year = now.year
    own = [
        ("/pricing", {"has_updated_date": True, "latest_year": year, "has_price": True}),
        ("/help/plans", {"has_updated_date": False, "latest_year": 2024, "has_price": True,
                         "fact_conflicts": [{
                             "fact_id": fact_id, "subject": "Starter plan", "expected": "$12",
                             "stated": "$19", "kind": "numeric",
                             "snippet": "The Starter plan is $19 per month, billed annually, "
                                        "and includes one free domain."}]}),
        ("/blog/website-cost-guide", {"has_updated_date": False, "latest_year": 2023}),
        ("/templates/bakery", {"has_updated_date": True, "latest_year": year}),
        ("/domains/compare", {"has_updated_date": True, "latest_year": year}),
    ]
    for path, features in own:
        session.add(PagePresence(tenant_id=tenant_id, url=f"{SITE}{path}",
                                 domain="northpeak.example", status="ok", http_status=200,
                                 brand_found=True, features={**features, "owned": True},
                                 fetched_at=now - timedelta(hours=20)))
    for url, rivals in [("https://www.g2.com/categories/website-builders",
                         ["Siteforge", "Pagecraft"]),
                        ("https://smallbizstack.example/cheapest-domain-and-website",
                         ["Domainly", "Siteforge"])]:
        session.add(PagePresence(tenant_id=tenant_id, url=url, domain=url.split("/")[2],
                                 status="ok", http_status=200, brand_found=False,
                                 competitors_found=rivals, features={},
                                 fetched_at=now - timedelta(hours=20)))


def _first_party(session: Session, tenant_id: int, now: datetime) -> None:
    for d in range(28):
        day = (now - timedelta(days=d)).date().isoformat()
        for page, before, after in [("/domains/compare", 20, 70), ("/pricing", 140, 150),
                                    ("/help/plans", 60, 58), ("/templates/bakery", 45, 47)]:
            value = after if d < SHIP_DAYS_AGO else before
            session.add(FirstPartyDaily(tenant_id=tenant_id, source="gsc", date=day, page=page,
                                        metric="impressions", value=value))


def _classify(session: Session, tenant_id: int, last_run_id: int) -> None:
    """The web-search classifier needs no-search twin answers, which this demo
    doesn't simulate, so each question gets the class its story needs."""
    session.execute(sa_delete(QueryClassification).where(
        col(QueryClassification.tenant_id) == tenant_id))
    ids = {q.text: q.id for q in session.exec(select(Query).where(Query.tenant_id == tenant_id))}
    classes = {Q_BAKERY: "likely", Q_CHEAP: "very_likely", Q_RELIABLE: "unlikely",
               Q_COST: "likely", Q_BOOKING: "likely", Q_REGISTRAR: "likely",
               Q_WORTH: "likely", Q_VS: "likely", Q_TASK: "possible", Q_CODE: "possible"}
    for text, likelihood in classes.items():
        aio = text == Q_COST
        session.add(QueryClassification(
            tenant_id=tenant_id, query_id=ids.get(text), query_text=text,
            surface=SurfaceCode.openai_api, web_search_likelihood=likelihood,
            signals={"demo": True}, classifier_version="demo", run_id=last_run_id,
            google_aio_triggered=aio, google_aio_confidence=0.9 if aio else 0.0,
            google_aio_source_type="aio_dominant" if aio else "no_aio",
            google_aio_signals={"cited_domains": ["siteforge.example", "smallbizstack.example",
                                                  "g2.com"]} if aio else {}))


def build_demo_client(session: Session, clerk_org_id: str | None = None) -> dict[str, Any]:
    from api.processing_service import process_run
    from api.recommendations_service import generate_recommendations

    now = utcnow()
    tenant = session.exec(select(Tenant).where(Tenant.slug == SLUG)).first()
    if tenant is None:
        tenant = Tenant(name=NAME, slug=SLUG)
        session.add(tenant)
        session.flush()
    assert tenant.id is not None
    tid = tenant.id
    _wipe(session, tid)
    tenant = session.get(Tenant, tid)
    assert tenant is not None
    if clerk_org_id:
        tenant.clerk_org_id = clerk_org_id
    tenant.monthly_spend_cap_usd = 0.0  # fictional brand: no paid runs
    tenant.ai_processing_approved = False  # no LLM calls while processing
    session.add(tenant)
    import_config(session, tenant, TenantConfigSpec.model_validate(CONFIG))
    session.commit()

    from api.models import BrandFact
    fact = session.exec(select(BrandFact).where(BrandFact.tenant_id == tid)).first()
    queries = session.exec(select(Query).where(Query.tenant_id == tid)).all()
    qid = {q.text: q.id for q in queries}

    last_run_id = 0
    total = 0
    for i, days_ago in enumerate(RUN_DAYS_AGO):
        latest = i == len(RUN_DAYS_AGO) - 1
        when = _days_ago(days_ago, now)
        run = Run(tenant_id=tid, trigger="schedule", status=RunStatus.complete,
                  surface_set=[str(s) for s in API + SERP], mode_set=["A", "B"],
                  started_at=when, finished_at=when + timedelta(minutes=18), created_at=when)
        session.add(run)
        session.flush()
        assert run.id is not None
        last_run_id = run.id
        n = 0
        for q in qid:
            for surface in API + SERP:
                samples = 2 if surface in API else 1
                personas = [("Generic", "generic")] * samples
                if q == Q_BAKERY and surface in API:
                    personas.append(("Bakery owner", "bakery"))
                for k, (pname, pseg) in enumerate(personas):
                    rng = random.Random(f"{SLUG}|{days_ago}|{q}|{surface}|{k}")
                    text, urls, extra = _answer(rng, q, str(surface), days_ago, latest)
                    model = ("gpt-6-astra" if days_ago < MODEL_SWITCH_DAYS_AGO else
                             "gpt-5.6-terra") if surface == SurfaceCode.openai_api else \
                        MODELS.get(str(surface), "")
                    r = Result(run_id=run.id, tenant_id=tid, query_id=qid[q], query_text=q,
                               persona_name=pname, persona_segment=pseg, surface=surface,
                               mode=RunMode.A if surface in API else RunMode.B,
                               variant=ResultVariant.search, status=ResultStatus.ok,
                               created_at=when, served_model=model, latency_ms=4200,
                               web_search_calls=1 if surface in API else 0,
                               logged_in=None if surface in API else False,
                               fanout_queries=SHARDS if q == Q_CHEAP and surface in (
                                   SurfaceCode.openai_api, SurfaceCode.gemini_api) else [])
                    r.raw_uri = write_raw_envelope(
                        SLUG, run.id, f"demo-{n:04d}",
                        {"surface": str(surface), "query": q, "persona": pname,
                         "model": model, "demo": True, "response": extra,
                         "parsed_text": text, "cost_usd": 0.0}, session=session)
                    session.add(r)
                    session.flush()
                    assert r.id is not None
                    for u in dict.fromkeys(urls):
                        session.add(Citation(result_id=r.id, tenant_id=tid, url=u,
                                             domain=u.split("/")[2].removeprefix("www.")))
                    n += 1
        for shard in SHARDS:
            session.add(FanoutShard(
                tenant_id=tid, run_id=run.id, parent_query_text=Q_CHEAP, shard_text=shard,
                shard_norm=shard, issuing_surfaces=["openai_api", "gemini_api",
                                                    "google_ai_mode"],
                reach=3, brand_present=False, winners=["Domainly", "Siteforge"],
                source="reprobed", priority="high"))
        run.counts = {"planned": n, "completed": n, "demo": True}
        session.add(run)
        session.commit()
        run.counts = {**run.counts, **process_run(session, run)}
        session.add(run)
        session.commit()
        total += n

    session.add(Intervention(
        tenant_id=tid, query_text=Q_REGISTRAR, url=f"{SITE}/domains/compare",
        description="Published a registrar comparison page with prices and renewal terms",
        shipped_at=_days_ago(SHIP_DAYS_AGO, now), created_by="demo"))
    _bot_logs(session, tid, now)
    _pages(session, tid, fact.id if fact else None, now)
    _first_party(session, tid, now)
    _classify(session, tid, last_run_id)
    session.commit()
    plays = generate_recommendations(session, tenant)
    session.commit()
    return {"tenant": SLUG, "runs": len(RUN_DAYS_AGO), "answers": total, "open_plays": plays}


def build_demo_client_job(clerk_org_id: str | None = None) -> dict[str, Any]:
    """Worker entry point (RQ)."""
    from api.db import get_engine

    with Session(get_engine()) as session:
        return build_demo_client(session, clerk_org_id)

