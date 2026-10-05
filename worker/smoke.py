"""Engine smoke test: one cheap live call per enabled engine, end to end
through the same adapters a run uses, with the answer checked for the parts
the dashboards depend on (text, sources, model name). Results land in
engine_checks and show on the admin readiness table.

Cost: one short answer per engine (cents in total), recorded in the spend
ledger so the monthly cap sees it."""

import asyncio
import time
from typing import Any

import structlog
from sqlmodel import Session

from api.config import get_settings
from api.db import get_engine
from api.models import EngineCheck, SpendEntry, Tenant, utcnow
from api.plans import model_for
from api.runs_service import eligible_surfaces
from engine.costs import estimate_mode_b_cost_usd
from engine.retrievers.blocking import BlockedError

log = structlog.get_logger()

# A short, neutral category question: forces a sourced answer without
# depending on any tenant's prompts.
PROBE = "Which companies are well known for domain name registration? Answer in two sentences."
PERSONA = "You are a helpful assistant. Keep answers brief."


def run_engine_smoke(tenant_id: int) -> int:
    return asyncio.run(_run(tenant_id))


async def _run(tenant_id: int) -> int:
    from worker.jobs import A_ADAPTERS, B_ADAPTERS, _base_scrape_env

    settings = get_settings()
    with Session(get_engine()) as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            return 0
        surfaces = eligible_surfaces(session, tenant)
        tier = tenant.plan
        aio_geo = dict(tenant.aio_geo or {})
    from api.plans import limits_for

    model_tier = limits_for(tier).model_tier
    env = _base_scrape_env(settings)
    done = 0
    for surface in surfaces:
        started = time.monotonic()
        row: dict[str, Any] = {"surface": surface}
        try:
            if surface in A_ADAPTERS:
                row |= await _check_api(A_ADAPTERS[surface], surface, settings, model_tier)
            elif surface in B_ADAPTERS:
                row |= await _check_browser(B_ADAPTERS[surface], surface, settings, env, aio_geo)
            else:
                row |= {"status": "failed", "detail": "no adapter for this engine"}
        except BlockedError as exc:
            row |= {"status": "blocked", "detail": f"anti-bot wall: {exc.reason}"[:300]}
        except Exception as exc:  # noqa: BLE001 — the point is to report it
            row |= {"status": "failed", "detail": explain_failure(exc)}
        row.setdefault("latency_ms", int((time.monotonic() - started) * 1000))
        with Session(get_engine()) as session:
            session.add(EngineCheck(tenant_id=tenant_id, checked_at=utcnow(), **row))
            if row.get("cost_usd"):
                session.add(SpendEntry(tenant_id=tenant_id, kind="engine_check",
                                       cost_usd=float(row["cost_usd"])))
            session.commit()
        done += 1
        log.info("engine_check", tenant=tenant_id, surface=surface, status=row.get("status"))
    return done


_HINTS = (
    ("Executable doesn't exist", "The browser isn't installed on this worker. Browser engines "
     "need the worker built from the Playwright image (see render.yaml)."),
    ("ERR_PROXY", "The scrape proxy refused the connection. Check SCRAPE_PROXY_URL."),
    ("407", "The scrape proxy rejected its credentials. Check SCRAPE_PROXY_URL."),
    ("401", "The provider rejected the API key. Check the key on the worker."),
    ("403", "The provider refused the request (key permissions or region)."),
    ("insufficient_quota", "The provider account is out of credits. Add credits or raise "
     "the budget in the provider's billing settings."),
    ("429", "Rate-limited at the provider: too many calls at once. Wait a minute and retry; "
     "if it keeps happening, check the account's rate limits."),
    ("Timeout", "Timed out. The engine or proxy was too slow; try again, then check the proxy."),
)


def explain_failure(exc: BaseException) -> str:
    """The raw error plus, when we recognise it, what to do about it."""
    raw = f"{type(exc).__name__}: {exc}"
    hint = next((h for needle, h in _HINTS if needle in raw), "")
    return (f"{hint} ({raw})" if hint else raw)[:600]


def _verdict(text: str, citations: int, searches: int, needs_sources: bool) -> tuple[str, str]:
    if not text.strip():
        return "parse_problem", "The call succeeded but no answer text was parsed."
    if needs_sources and citations == 0 and searches == 0:
        return "parse_problem", ("Answer text came back but no sources or searches were parsed; "
                                 "the response format may have changed.")
    return "ok", text.strip().replace("\n", " ")[:200]


async def _check_api(adapter: Any, surface: str, settings: Any, tier: str) -> dict[str, Any]:
    key = getattr(settings, adapter.key_attr, "")
    if not key:
        return {"status": "not_configured", "detail": f"{adapter.env_var} is not set on the worker"}
    model = model_for(surface, tier, getattr(settings, adapter.model_attr))
    started = time.monotonic()
    outcome = await asyncio.wait_for(
        adapter.module.retrieve(PERSONA, PROBE, api_key=key, model=model,
                                timeout_s=getattr(settings, adapter.timeout_attr),
                                web_search=True, force_search=True),
        timeout=float(getattr(settings, adapter.timeout_attr)) + 30,
    )
    p = outcome.parsed
    status, detail = _verdict(p.text, len(p.citations), p.web_search_calls, needs_sources=True)
    return {
        "status": status, "detail": detail,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "served_model": (p.model or model)[:120], "text_chars": len(p.text),
        "citations": len(p.citations), "searches": p.web_search_calls,
        "cost_usd": round(adapter.cost_fn(p.model or model, p.input_tokens, p.output_tokens,
                                          p.web_search_calls), 5),
    }


async def _check_browser(adapter: Any, surface: str, settings: Any, env: Any,
                         geo: dict) -> dict[str, Any]:
    from engine.retrievers import google_ai_mode, google_aio

    module, _label, _rate, timeout_attr = adapter
    timeout_s = float(getattr(settings, timeout_attr))
    cost = estimate_mode_b_cost_usd(
        surface, aio_provider=settings.google_aio_provider,
        serpapi_cost_per_search=settings.serpapi_cost_per_search,
        scrape_cost_per_page=settings.scrape_cost_per_page_usd,
    )
    if surface in ("google_aio", "google_ai_mode") and not settings.serpapi_key \
            and (surface == "google_ai_mode" or settings.google_aio_provider == "serpapi"):
        return {"status": "not_configured", "detail": "SERPAPI_KEY is not set on the worker"}
    started = time.monotonic()
    if surface == "google_aio":
        out = await asyncio.wait_for(google_aio.capture(
            PROBE, geo=geo, provider=settings.google_aio_provider,
            serpapi_key=settings.serpapi_key, headless=settings.chatgpt_web_headless,
            timeout_s=settings.google_aio_timeout_s,
            executable_path=settings.playwright_chromium_path or None, env=env,
        ), timeout=timeout_s + 60)
        text, cites = out.aio_text, len(out.citations)
        # Google doesn't show an Overview for every question: a clean capture
        # with no Overview still proves the pipeline works.
        status, detail = ("ok", text[:200] or "Captured; Google showed no AI Overview for "
                          "the probe question (normal for some queries).")
    elif surface == "google_ai_mode":
        out = await asyncio.wait_for(google_ai_mode.capture(
            PROBE, geo=geo, api_key=settings.serpapi_key,
            timeout_s=settings.google_ai_mode_timeout_s,
        ), timeout=timeout_s + 60)
        text, cites = out.text, len(out.citations)
        status, detail = _verdict(text, cites, 1, needs_sources=False)
    else:
        out = await asyncio.wait_for(module.retrieve(
            PERSONA, PROBE, headless=settings.chatgpt_web_headless, timeout_s=timeout_s,
            executable_path=settings.playwright_chromium_path or None, env=env,
        ), timeout=timeout_s + 60)
        text, cites = out.text, len(out.citations)
        status, detail = _verdict(text, cites, 0, needs_sources=False)
    return {"status": status, "detail": detail,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "text_chars": len(text), "citations": cites, "cost_usd": round(cost, 5)}
