"""Scraping v3 (§SCRAPING_V3): block detection, stealth/proxy env resolution,
and the Mode B location fan-out + blocked-status persistence."""

import pytest
from sqlmodel import select

from api.models import Location, Result, ResultStatus, Run, RunStatus, SurfaceCode, TenantSurface
from engine.retrievers.blocking import BlockedError, detect_block
from engine.retrievers.stealth import ScrapeEnv, context_options, resolve_proxy, timezone_for
from tests.test_runs import _pending_run, fake_retrieve, job_env, make_tenant  # noqa: F401
from tests.test_runs_mode_b import add_web_surface

# --- Layer 0: block detection ------------------------------------------------

def test_detect_block_fingerprints():
    assert detect_block(title="Just a moment...").blocked
    assert detect_block(body_text="Checking your browser before accessing").reason == "cloudflare"
    assert detect_block(
        body_text="Our systems have detected unusual traffic from your computer network"
    ).reason == "google_sorry"
    sorry = detect_block(url="https://www.google.com/sorry/index?continue=...")
    assert sorry.reason == "google_sorry"
    # Ambiguous phrases signal a block only as the page TITLE, not mid-answer.
    assert detect_block(title="Verify you are a human").reason == "captcha"
    assert detect_block(title="Access Denied").reason == "access_denied"


def test_detect_block_passes_real_answers():
    # A genuine answer that happens to mention these topics must NOT trip.
    answer = "Smith School of Business is frequently recommended for its MBA program."
    assert not detect_block(title="ChatGPT", body_text=answer).blocked
    # An answer explaining HTTP 429 mentions these phrases in the body — not a block.
    rate = "If you see 'rate limit exceeded' or 'too many requests', back off and retry."
    assert not detect_block(title="ChatGPT", body_text=rate).blocked


def test_blocked_error_carries_reason():
    err = BlockedError("cloudflare", "https://chatgpt.com")
    assert err.reason == "cloudflare"
    assert "cloudflare" in str(err)


# --- Layer 1/2: stealth + proxy resolution -----------------------------------

def test_proxy_selection_prefers_country_then_default():
    env = ScrapeEnv(
        country="gb",
        proxy_url="http://default:pw@gw:7000",
        proxy_map={"gb": "http://uk:pw@gw-uk:7000", "us": "http://us:pw@gw-us:7000"},
    )
    assert resolve_proxy(env) == "http://uk:pw@gw-uk:7000"
    # A country with no map entry falls back to the default URL.
    assert resolve_proxy(ScrapeEnv(country="ca", proxy_url="http://d:pw@gw:7000")) == \
        "http://d:pw@gw:7000"
    # No proxy configured at all.
    assert resolve_proxy(ScrapeEnv(country="ca")) == ""


def test_context_options_localizes_and_proxies():
    env = ScrapeEnv(
        country="us", language="en", latitude=40.7, longitude=-74.0,
        proxy_url="http://user:secret@gateway.example.com:7777",
    )
    opts = context_options(env)
    assert opts["locale"] == "en-US"
    assert opts["timezone_id"] == "America/New_York"
    assert opts["geolocation"] == {"latitude": 40.7, "longitude": -74.0}
    assert "geolocation" in opts["permissions"]
    # Proxy URL is split into Playwright's server/username/password shape.
    assert opts["proxy"]["server"] == "http://gateway.example.com:7777"
    assert opts["proxy"]["username"] == "user"
    assert opts["proxy"]["password"] == "secret"


def test_context_options_no_proxy_is_clean():
    opts = context_options(ScrapeEnv(country="ca"))
    assert "proxy" not in opts
    assert timezone_for("ca") == "America/Toronto"
    assert timezone_for("zz") == "UTC"  # unknown country → safe default


def test_route_blocker_drops_only_heavy_assets():
    import asyncio

    from engine.retrievers.stealth import _route_blocker

    class _Req:
        def __init__(self, rt):
            self.resource_type = rt

    class _Route:
        def __init__(self, rt):
            self.request = _Req(rt)
            self.aborted = False
            self.continued = False

        async def abort(self):
            self.aborted = True

        async def continue_(self):
            self.continued = True

    def check(rt) -> _Route:
        route = _Route(rt)
        asyncio.run(_route_blocker(route))
        return route

    # Images/media/fonts are aborted (never parsed → pure proxy cost saved).
    for rt in ("image", "media", "font"):
        route = check(rt)
        assert route.aborted and not route.continued

    # Document/script/stylesheet/xhr are kept — needed for text + layout.
    for rt in ("document", "script", "stylesheet", "xhr", "fetch"):
        route = check(rt)
        assert route.continued and not route.aborted


# --- Part 2: location fan-out ------------------------------------------------

@pytest.fixture()
def fake_web_by_location(monkeypatch):
    """A fake ChatGPT-web adapter that echoes the request geo, so a test can
    assert each location produced its own result."""
    from engine.retrievers.chatgpt_web import WebRetrievalOutcome

    async def _fake(persona_prompt, query_text, *, headless, timeout_s,
                    executable_path=None, env=None):
        country = env.country if env else "?"
        return WebRetrievalOutcome(
            text=f"answer from {country}", citations=[], html_fragment="<div/>",
            latency_ms=10,
        )

    monkeypatch.setattr("engine.retrievers.chatgpt_web.retrieve", _fake)
    monkeypatch.setenv("CHATGPT_WEB_RATE_PER_MIN", "100000")
    from api.config import get_settings

    get_settings.cache_clear()


def _b_only(db_session, tenant):
    """Disable the API surface so the run is Mode B only."""
    api_surface = db_session.exec(
        select(TenantSurface).where(
            TenantSurface.tenant_id == tenant.id,
            TenantSurface.code == SurfaceCode.openai_api,
        )
    ).one()
    api_surface.enabled = False
    db_session.add(api_surface)
    db_session.commit()


def test_mode_b_fans_out_over_locations(
    db_session, job_env, fake_retrieve, fake_web_by_location  # noqa: F811
):
    from worker.jobs import run_mode_b

    tenant = make_tenant(db_session, queries=2, personas=1)
    tenant.plan = "custom"  # uncapped locations
    add_web_surface(db_session, tenant)
    _b_only(db_session, tenant)
    db_session.add_all([
        Location(tenant_id=tenant.id, label="Toronto", country="ca"),
        Location(tenant_id=tenant.id, label="New York", country="us"),
    ])
    db_session.commit()

    run_id = _pending_run(db_session, tenant)
    run_mode_b(run_id)

    results = db_session.exec(
        select(Result).where(Result.run_id == run_id, Result.mode == "B")
    ).all()
    # 2 queries × 2 locations = 4 scrapes, each stamped with its location.
    assert len(results) == 4
    assert {r.location_label for r in results} == {"Toronto", "New York"}
    assert all(r.status == ResultStatus.ok for r in results)


def test_location_cap_truncates_by_plan(
    db_session, job_env, fake_retrieve, fake_web_by_location  # noqa: F811
):
    from worker.jobs import run_mode_b

    tenant = make_tenant(db_session, queries=1, personas=1)
    tenant.plan = "diagnose"  # max_locations = 1
    add_web_surface(db_session, tenant)
    _b_only(db_session, tenant)
    db_session.add_all([
        Location(tenant_id=tenant.id, label="Toronto", country="ca"),
        Location(tenant_id=tenant.id, label="New York", country="us"),
    ])
    db_session.commit()

    run_id = _pending_run(db_session, tenant)
    run_mode_b(run_id)

    results = db_session.exec(
        select(Result).where(Result.run_id == run_id, Result.mode == "B")
    ).all()
    # Only the first active location survives the plan cap.
    assert len(results) == 1
    assert results[0].location_label == "Toronto"


def test_no_locations_uses_tenant_default(
    db_session, job_env, fake_retrieve, fake_web_by_location  # noqa: F811
):
    from worker.jobs import run_mode_b

    tenant = make_tenant(db_session, queries=1, personas=1)
    add_web_surface(db_session, tenant)
    _b_only(db_session, tenant)
    run_id = _pending_run(db_session, tenant)
    run_mode_b(run_id)

    results = db_session.exec(
        select(Result).where(Result.run_id == run_id, Result.mode == "B")
    ).all()
    assert len(results) == 1
    assert results[0].location_label == ""  # implicit default location


# --- Layer 0 end-to-end: a block is data, not "absent" -----------------------

def test_blocked_scrape_records_blocked_status(
    db_session, job_env, fake_retrieve, monkeypatch  # noqa: F811
):
    from worker.jobs import run_mode_b

    async def _blocked(persona_prompt, query_text, *, headless, timeout_s,
                       executable_path=None, env=None):
        raise BlockedError("cloudflare", "https://chatgpt.com")

    monkeypatch.setattr("engine.retrievers.chatgpt_web.retrieve", _blocked)
    monkeypatch.setenv("CHATGPT_WEB_RATE_PER_MIN", "100000")
    from api.config import get_settings

    get_settings.cache_clear()

    tenant = make_tenant(db_session, queries=1, personas=1)
    add_web_surface(db_session, tenant)
    _b_only(db_session, tenant)
    run_id = _pending_run(db_session, tenant)
    run_mode_b(run_id)

    run = db_session.get(Run, run_id)
    assert run is not None
    result = db_session.exec(select(Result).where(Result.run_id == run_id)).one()
    # Distinct 'blocked' status, counted separately — never an "error"/"ok".
    assert result.status == ResultStatus.blocked
    assert "cloudflare" in (result.error or "")
    assert run.counts.get("blocked") == 1
    assert run.counts.get("completed", 0) == 0
    # An all-blocked run fails loudly with the residential-proxy hint.
    assert run.status == RunStatus.failed
    assert "residential proxy" in (run.error or "")
