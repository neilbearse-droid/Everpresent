"""Regression tests for the bug-audit fixes (C1, H1, H4, H5, worker-4/8)."""


from sqlmodel import select

from api.dashboards_service import citations_intel, engine_scorecard
from api.models import (
    BrandProfile,
    Citation,
    Mention,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunMode,
    RunStatus,
    SurfaceCode,
    Tenant,
    VisibilityDaily,
)
from engine.retrievers.claude_api import parse_claude_payload
from engine.retrievers.gemini_api import parse_gemini_payload
from engine.retrievers.openai_api import parse_responses_payload
from engine.retrievers.perplexity_api import parse_perplexity_payload

# --- H1: parsers must not crash on explicit null values ----------------------

def test_parsers_tolerate_null_values():
    # usage/content/output/choices present but null — .get(k, default) would
    # return None here, which the old code then iterated/attr-accessed.
    assert parse_responses_payload({"output": None, "usage": None}).text == ""
    assert parse_claude_payload({"content": None, "usage": None}).text == ""
    assert parse_gemini_payload({"candidates": None, "usageMetadata": None}).text == ""
    assert parse_perplexity_payload({"choices": None, "usage": None}).text == ""
    # A message with null content array (OpenAI) and null parts (Gemini).
    assert parse_responses_payload(
        {"output": [{"type": "message", "content": None}], "usage": {}}
    ).text == ""
    assert parse_gemini_payload(
        {"candidates": [{"content": None}], "usageMetadata": {}}
    ).text == ""


# --- C1: aio_geo NULL legacy row must not crash the worker -------------------

def test_worker_tolerates_null_aio_geo(db_session):
    from sqlalchemy import text

    from worker.jobs import _tenant_locations

    t = Tenant(name="Legacy", slug="legacy")
    db_session.add(t)
    db_session.commit()
    # Simulate the M6-backfilled NULL that default_factory never repairs on load.
    db_session.exec(text(f"UPDATE tenants SET aio_geo = NULL WHERE id = {t.id}"))
    db_session.commit()
    db_session.expire_all()
    reloaded = db_session.get(Tenant, t.id)
    assert reloaded.aio_geo is None
    # The guard in _run_mode_b turns this into the default; mirror it here.
    aio_geo = dict(reloaded.aio_geo or {"gl": "ca", "hl": "en"})
    locs = _tenant_locations(db_session, t.id, aio_geo, None)
    assert locs == [("", {"gl": "ca", "hl": "en"})]


# --- low: notify_emails NULL legacy row must not crash finalize --------------

def test_notify_emails_null_tolerated(db_session):
    from sqlalchemy import text

    t = Tenant(name="LegacyN", slug="legacyn")
    db_session.add(t)
    db_session.commit()
    # Pre-M5 rows loaded NULL (no server_default, no backfill until M19).
    db_session.exec(text(f"UPDATE tenants SET notify_emails = NULL WHERE id = {t.id}"))
    db_session.commit()
    db_session.expire_all()
    reloaded = db_session.get(Tenant, t.id)
    assert reloaded.notify_emails is None
    # notify_run_complete must treat None as "no recipients", not crash on len().
    from api.notifications import notify_run_complete

    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    assert notify_run_complete(db_session, run, reloaded) is False


# --- shared helpers ----------------------------------------------------------

def _tenant(db):
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.add(Query(tenant_id=t.id, text="best crm"))
    db.commit()
    return t.id


def _result(db, tid, qtext, surface, variant, *, created=None):
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    r = Result(run_id=run.id, tenant_id=tid, query_text=qtext, persona_name="p",
               surface=SurfaceCode(surface), variant=ResultVariant(variant),
               status=ResultStatus.ok)
    if created is not None:
        r.created_at = created
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# --- H4: citations_intel counts the LATEST result only, not every run --------

def test_citations_intel_dedups_across_runs(db_session):
    tid = _tenant(db_session)
    # Same page cited on three separate daily runs for the same (query, surface).
    for _ in range(3):
        r = _result(db_session, tid, "best crm", "openai_api", "search")
        db_session.add(Citation(result_id=r.id, tenant_id=tid,
                                url="https://g2.com/best", domain="g2.com"))
        db_session.commit()

    intel = citations_intel(db_session, tid)
    g2 = next(d for d in intel["domains"] if d["domain"] == "g2.com")
    # Counted once (latest result), not three times (once per run).
    assert g2["count"] == 1


# --- H5: engine_scorecard sees a nosearch twin even if search failed ---------

def test_engine_scorecard_uses_nosearch_when_search_absent(db_session):
    tid = _tenant(db_session)
    # openai search shows a competitor (brand absent in the live answer)...
    s = _result(db_session, tid, "best crm", "openai_api", "search")
    db_session.add(Mention(result_id=s.id, tenant_id=tid, entity_type="competitor",
                           entity_name="Rival", position=0, rank=1))
    # ...but on CLAUDE the search variant FAILED (no ok search row); only its
    # training twin exists, and it knows the brand → this is a content gap.
    ns = _result(db_session, tid, "best crm", "claude_api", "nosearch")
    db_session.add(Mention(result_id=ns.id, tenant_id=tid, entity_type="brand",
                           entity_name="Acme", position=0, rank=1))
    db_session.commit()

    card = engine_scorecard(db_session, tid)
    diag = card["matrix"][0]["diagnosis"]["type"]
    # Before the fix this was "undetermined"/"knowledge_gap" (twin unseen);
    # now the training twin is visible → content_gap.
    assert diag == "content_gap"


# --- worker-8: visibility rollup keeps one row per location ------------------

def test_rollup_keeps_per_location_rows(db_session):
    from api.processing_service import _run_day, rollup_day

    tid = _tenant(db_session)
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    day = _run_day(run)

    # Same (surface, segment), two different locations.
    for loc in ("Toronto", "Vancouver"):
        r = Result(run_id=run.id, tenant_id=tid, query_text="best crm", persona_name="p",
                   surface=SurfaceCode.google_aio, variant=ResultVariant.search,
                   status=ResultStatus.ok, mode=RunMode.B, location_label=loc)
        db_session.add(r)
    db_session.commit()

    rollup_day(db_session, tid, day)
    rows = db_session.exec(
        select(VisibilityDaily).where(VisibilityDaily.tenant_id == tid)
    ).all()
    labels = sorted(r.location_label for r in rows)
    # Two locations → two rows, not one blended row (§audit worker-8).
    assert labels == ["Toronto", "Vancouver"]
