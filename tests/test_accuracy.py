"""Factual-accuracy detection (§AEO-plan M4): the check engine, its processing
integration, the grouped report, and the admin fact-sheet CRUD."""

from sqlmodel import select

from api.dashboards_service import accuracy_report
from api.models import (
    AccuracyFinding,
    BrandFact,
    BrandProfile,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)
from api.processing_service import process_run
from api.storage import write_raw_envelope
from engine.processing.accuracy import FactSpec, check_text
from tests.test_runs import _pending_run, fake_retrieve, job_env, make_tenant  # noqa: F401

# --- engine ------------------------------------------------------------------

def _fact(fid, subject, kind, expected, aliases=None, category="pricing"):
    return FactSpec(id=fid, category=category, label=subject, subject=subject,
                    aliases=aliases or [], kind=kind, expected=expected)


def test_numeric_mismatch_is_flagged():
    facts = [_fact(1, "tuition", "numeric", "$120,000", ["cost to attend"])]
    hits = check_text("The full-time MBA tuition is $95,000 in total.", facts)
    assert len(hits) == 1
    assert hits[0].stated == "$95,000" and hits[0].expected == "$120,000"
    assert hits[0].severity == "high"


def test_correct_number_is_not_flagged():
    facts = [_fact(1, "tuition", "numeric", "$120,000")]
    assert check_text("Tuition runs about $120,000 total.", facts) == []


def test_number_in_unrelated_sentence_is_ignored():
    facts = [_fact(1, "tuition", "numeric", "$120,000")]
    # $500 appears, but not in a sentence about tuition → no false positive.
    assert check_text("The application fee is $500. Classes start in September.", facts) == []


def test_unit_mismatch_does_not_cross_types():
    facts = [_fact(1, "pass rate", "numeric", "92%")]
    # A dollar figure near the subject must not be compared to a percentage.
    assert check_text("The pass rate cohort paid $92 in fees.", facts) == []


def test_disallowed_claim_is_flagged():
    facts = [_fact(1, "accreditation", "disallowed", "not accredited", category="accreditation")]
    hits = check_text("Some say the school is not accredited, which is false.", facts)
    assert len(hits) == 1 and hits[0].category == "accreditation"


def test_no_facts_returns_empty():
    assert check_text("Anything at all, $5, 10%.", []) == []


def test_correct_decimal_value_is_not_flagged():
    # The decimal point must not be read as a sentence terminator (§audit H2).
    facts = [_fact(1, "tuition", "numeric", "$1,000.50")]
    assert check_text("The tuition is $1,000.50 per course.", facts) == []
    # And a genuinely wrong decimal IS still caught.
    hits = check_text("The tuition is $2,000.75 per course.", facts)
    assert len(hits) == 1 and hits[0].stated == "$2,000.75"


def test_blank_alias_does_not_match_everything():
    # A whitespace-only alias must not turn the checker loose on every sentence.
    facts = [_fact(1, "tuition", "numeric", "$120,000", aliases=["   "])]
    assert check_text("Enrollment grew 15% and the campus has 900 students.", facts) == []


# --- processing integration --------------------------------------------------

def test_process_run_writes_accuracy_findings(db_session, job_env):  # noqa: F811
    tenant = make_tenant(db_session, "smith", queries=1, personas=1)
    db_session.add(BrandProfile(tenant_id=tenant.id, brand_name="Smith",
                                domains=["smith.ca"]))
    db_session.add(BrandFact(tenant_id=tenant.id, category="pricing", label="Tuition",
                             subject="tuition", kind="numeric", expected="$120,000"))
    db_session.commit()

    run = Run(tenant_id=tenant.id, trigger="manual", status=RunStatus.running)
    db_session.add(run)
    db_session.commit()
    r = Result(run_id=run.id, tenant_id=tenant.id, query_text="cost?", persona_name="p",
               surface=SurfaceCode.openai_api, variant=ResultVariant.search,
               status=ResultStatus.ok)
    db_session.add(r)
    db_session.commit()
    db_session.refresh(r)
    r.raw_uri = write_raw_envelope(
        "smith", run.id, "r0",
        {"parsed_text": "Smith's MBA tuition is $95,000."}, session=db_session,
    )
    db_session.add(r)
    db_session.commit()

    process_run(db_session, run)

    findings = list(db_session.exec(select(AccuracyFinding)))
    assert len(findings) == 1
    assert findings[0].stated == "$95,000"

    rep = accuracy_report(db_session, tenant.id)
    assert rep["facts_on_file"] == 1
    assert rep["error_count"] == 1
    assert rep["errors"][0]["engines"] == ["ChatGPT"]


def test_accuracy_report_no_facts_on_file(db_session):
    tenant = Tenant(name="Empty", slug="empty")
    db_session.add(tenant)
    db_session.commit()
    rep = accuracy_report(db_session, tenant.id)
    assert rep["facts_on_file"] == 0 and rep["errors"] == []


# --- admin CRUD --------------------------------------------------------------

def test_brand_fact_crud(client, login, db_session):
    from api.models import User

    admin = User(email="a@x.com", clerk_user_id="u_a", is_superadmin=True)
    db_session.add(admin)
    tenant = Tenant(name="Smith", slug="smith")
    db_session.add(tenant)
    db_session.commit()
    login(admin)

    created = client.post("/api/admin/tenants/smith/brand-facts", json={
        "category": "pricing", "label": "Tuition", "subject": "tuition",
        "aliases": ["cost"], "kind": "numeric", "expected": "$120,000",
    })
    assert created.status_code == 201
    fid = created.json()["id"]

    listed = client.get("/api/admin/tenants/smith/brand-facts").json()
    assert len(listed) == 1 and listed[0]["subject"] == "tuition"

    # Validation: bad kind and blank fields are rejected.
    assert client.post("/api/admin/tenants/smith/brand-facts", json={
        "label": "x", "subject": "x", "kind": "vibes", "expected": "1"}).status_code == 422
    assert client.post("/api/admin/tenants/smith/brand-facts", json={
        "label": "", "subject": "x", "kind": "numeric", "expected": "1"}).status_code == 422

    assert client.delete(f"/api/admin/tenants/smith/brand-facts/{fid}").status_code == 204
    assert client.get("/api/admin/tenants/smith/brand-facts").json() == []
