"""Google AI Mode as a measured engine (SerpApi engine=google_ai_mode)."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from engine.retrievers.google_ai_mode import capture, parse_ai_mode_payload
from tests.test_runs import job_env  # noqa: F401  (fixture)

FIX = Path(__file__).parent / "fixtures"


def test_parses_text_blocks_and_references():
    out = parse_ai_mode_payload(json.loads((FIX / "serpapi_ai_mode.json").read_text()))
    assert out.text.startswith("For a small business, Wix and GoDaddy")
    assert "GoDaddy Airo builds a site" in out.text  # nested list blocks included
    assert [c.url for c in out.citations] == [
        "https://www.pcmag.com/picks/the-best-website-builders",
        "https://www.godaddy.com/websites/website-builder",
    ]
    assert out.shopping_results == 1 and out.present


def test_capture_sends_ai_mode_engine_and_geo(monkeypatch):
    seen = {}

    async def _get(self, url, params=None, **k):
        seen.update(params or {})
        return httpx.Response(200, json=json.loads((FIX / "serpapi_ai_mode.json").read_text()),
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    out = asyncio.run(capture("best website builder", geo={"gl": "us", "hl": "en"},
                              api_key="k"))
    assert seen["engine"] == "google_ai_mode" and seen["gl"] == "us" and seen["q"]
    assert len(out.citations) == 2


def test_empty_or_errored_capture_is_an_error(monkeypatch):
    async def _get(self, url, params=None, **k):
        return httpx.Response(200, json={"error": "Google hasn't returned any results"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)
    with pytest.raises(RuntimeError, match="SerpApi AI Mode error"):
        asyncio.run(capture("q", geo={}, api_key="k"))
    with pytest.raises(RuntimeError, match="SERPAPI_KEY"):
        asyncio.run(capture("q", geo={}, api_key=""))


def test_ai_mode_runs_per_query_in_mode_b(db_session, job_env, monkeypatch):  # noqa: F811
    from sqlmodel import select

    from api.config import get_settings
    from api.models import Result, Run, RunStatus, SurfaceCode, TenantSurface
    from engine.retrievers.google_ai_mode import AIModeOutcome
    from engine.retrievers.openai_api import ParsedCitation
    from tests.test_runs import _pending_run, make_tenant
    from worker.jobs import run_mode_b

    monkeypatch.setenv("SERPAPI_KEY", "serp-k")
    monkeypatch.setenv("GOOGLE_AI_MODE_RATE_PER_MIN", "100000")
    get_settings.cache_clear()
    calls: list[str] = []

    async def _capture(query_text, *, geo, api_key, timeout_s):
        calls.append(query_text)
        return AIModeOutcome(text="Smith is a strong option.", present=True,
                             citations=[ParsedCitation(url="https://smith.queensu.ca/x")])

    monkeypatch.setattr("engine.retrievers.google_ai_mode.capture", _capture)
    tenant = make_tenant(db_session)  # 2 queries x 2 personas
    tenant.approved_surfaces = ["google_ai_mode"]
    db_session.add(tenant)
    db_session.add(TenantSurface(tenant_id=tenant.id, code=SurfaceCode.google_ai_mode,
                                 enabled=True))
    db_session.commit()
    run_id = _pending_run(db_session, tenant)
    run = db_session.get(Run, run_id)
    run.surface_set = ["google_ai_mode"]
    run.mode_set = ["B"]
    db_session.add(run)
    db_session.commit()

    run_mode_b(run_id)
    db_session.expire_all()
    results = db_session.exec(select(Result).where(Result.run_id == run_id)).all()
    assert len(calls) == 2  # one SERP per query, not per persona
    assert {r.surface for r in results} == {SurfaceCode.google_ai_mode}
    assert all(r.status == "ok" for r in results)
    assert db_session.get(Run, run_id).status == RunStatus.complete
