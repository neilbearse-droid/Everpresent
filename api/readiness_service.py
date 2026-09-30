"""Engine readiness (admin): for each measured surface, is it switched on for
this tenant, what does the deployment need for it to work, and what did the
last run that included it actually return. Configuration alone can't prove an
engine works (keys live on the worker, proxies get blocked), so the verdict
leans on the latest run's evidence.

Pure reads — no provider calls."""

from collections import Counter

from sqlmodel import Session, select

from api.config import get_settings
from api.models import (
    Result,
    ResultVariant,
    Run,
    RunSchedule,
    RunStatus,
    SurfaceCode,
    Tenant,
    TenantSurface,
)
from api.plans import limits_for
from api.runs_service import DISPATCHABLE_SURFACES, MODE_A_SURFACES, eligible_surfaces

# What each surface needs on the deployment, in plain words. Mode A keys are
# read by the worker (dispatch runs there), so that's where they must be set.
_NEEDS: dict[str, list[str]] = {
    "openai_api": ["OPENAI_API_KEY on everpresent-worker"],
    "claude_api": ["ANTHROPIC_API_KEY on everpresent-worker"],
    "gemini_api": ["GEMINI_API_KEY on everpresent-worker"],
    "perplexity_api": ["PERPLEXITY_API_KEY on everpresent-worker"],
    "chatgpt_web": ["Residential proxy: SCRAPE_PROXY_URL on everpresent-worker"],
    "perplexity_web": ["Residential proxy: SCRAPE_PROXY_URL on everpresent-worker"],
    "copilot_web": ["Residential proxy: SCRAPE_PROXY_URL on everpresent-worker"],
    "google_aio": [
        "SERPAPI_KEY on everpresent-worker",
        "GOOGLE_AIO_PROVIDER=serpapi (already set in render.yaml)",
    ],
    "gemini_web": [],
}

_LABELS = {
    "openai_api": "ChatGPT (API)",
    "claude_api": "Claude (API)",
    "gemini_api": "Gemini (API)",
    "perplexity_api": "Perplexity (API)",
    "chatgpt_web": "ChatGPT (web)",
    "perplexity_web": "Perplexity (web)",
    "copilot_web": "Microsoft Copilot",
    "google_aio": "Google AI Overviews",
    "gemini_web": "Gemini (web)",
}

# Verdict → the next thing to do about it.
_HINTS = {
    "ready": "Working. The last run returned answers.",
    "unavailable": "Not built yet — no adapter for this engine.",
    "off": "Switch it on (this also approves it).",
    "outside_plan": "Over the plan's engine limit. Switch the plan to Command or Custom.",
    "not_run_yet": "Switched on. Trigger a run to verify it end to end.",
    "missing_key": "The last run skipped it: its key isn't set on the worker.",
    "blocked": "Blocked by an anti-bot wall. Set a residential proxy on the worker.",
    "error": "Calls failed. Open the last run to read the error.",
    "withheld": "Withheld by the monthly spend cap. Raise the cap and re-run.",
}


def _mode(code: str) -> str:
    if code in {str(s) for s in MODE_A_SURFACES}:
        return "API"
    if code == "google_aio":
        return "SERP"
    return "Browser"


def engine_readiness(session: Session, tenant: Tenant) -> dict:
    assert tenant.id is not None
    enabled = {
        str(row.code): row.enabled
        for row in session.exec(
            select(TenantSurface).where(TenantSurface.tenant_id == tenant.id)
        ).all()
    }
    approved = set(tenant.approved_surfaces or [])
    will_dispatch = set(eligible_surfaces(session, tenant))
    dispatchable = {str(s) for s in DISPATCHABLE_SURFACES}

    # Latest FINISHED run per surface, newest first. Gated, pending and
    # still-running runs carry no evidence yet and would hide the last real one.
    runs = session.exec(
        select(Run)
        .where(
            Run.tenant_id == tenant.id,
            Run.status.in_(  # pyright: ignore[reportAttributeAccessIssue]
                [RunStatus.complete, RunStatus.capped, RunStatus.failed]
            ),
        )
        .order_by(Run.id.desc())  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
        .limit(30)
    ).all()
    latest_run: dict[str, Run] = {}
    for run in runs:
        for code in run.surface_set or []:
            latest_run.setdefault(code, run)

    engines = []
    for code in (str(c) for c in SurfaceCode):
        is_on = bool(enabled.get(code)) and code in approved
        run = latest_run.get(code)
        evidence: dict = {"run_id": None, "at": None, "ok": 0, "blocked": 0, "error": 0}
        verdict: str
        if code not in dispatchable:
            verdict = "unavailable"
        elif not is_on:
            verdict = "off"
        elif code not in will_dispatch:
            verdict = "outside_plan"
        elif run is None:
            verdict = "not_run_yet"
        else:
            statuses = Counter(
                str(r.status)
                for r in session.exec(
                    select(Result).where(
                        Result.run_id == run.id,
                        Result.surface == code,
                        Result.variant == ResultVariant.search,
                    )
                ).all()
            )
            evidence = {
                "run_id": run.id,
                "at": (run.finished_at or run.created_at).isoformat(),
                "ok": statuses.get("ok", 0),
                "blocked": statuses.get("blocked", 0),
                "error": statuses.get("error", 0),
            }
            counts = run.counts or {}
            if counts.get(f"unconfigured:{code}"):
                verdict = "missing_key"
            elif evidence["ok"] > 0:
                verdict = "ready"
            elif evidence["blocked"] > 0:
                verdict = "blocked"
            elif evidence["error"] > 0:
                verdict = "error"
            elif counts.get("withheld_by_cap"):
                verdict = "withheld"
            else:
                verdict = "not_run_yet"
        engines.append({
            "code": code,
            "label": _LABELS.get(code, code),
            "mode": _mode(code),
            "available": code in dispatchable,
            "on": is_on,
            "needs": _NEEDS.get(code, []),
            "verdict": verdict,
            "hint": _HINTS[verdict],
            "last_run": evidence,
        })

    limits = limits_for(tenant.plan)
    settings = get_settings()
    utility_models = {settings.utility_model_extract, settings.utility_model_draft}
    schedule = session.exec(
        select(RunSchedule).where(RunSchedule.tenant_id == tenant.id)
    ).first()
    checks = [
        {
            "label": "AI processing approved",
            "ok": tenant.ai_processing_approved,
            "hint": "Governance → Approve AI processing. Runs are gated without it.",
        },
        {
            "label": "Plan allows every engine",
            "ok": limits.max_engines is None,
            "hint": f"{limits.label} caps runs at {limits.max_engines} engines. "
            "Use Command or Custom.",
        },
        {
            "label": "Claude features on (Whitespace + corrective content)",
            "ok": tenant.entity_extraction_enabled
            and utility_models <= set(tenant.approved_utility_models or []),
            "hint": "Governance → Turn on Claude features. "
            "Needs ANTHROPIC_API_KEY on api and worker.",
        },
        {
            "label": f"Search country: {str((tenant.aio_geo or {}).get('gl', 'ca')).upper()}",
            "ok": True,
            "hint": "Governance → Search country. Match the client's market (US for GoDaddy).",
        },
        {
            "label": "Daily schedule set",
            "ok": schedule is not None and schedule.enabled,
            "hint": "Run schedule → set a daily cron so trend lines build before the demo.",
        },
    ]
    from api.health_service import system_checks

    return {"engines": engines, "checks": checks, "system": system_checks(session)}
