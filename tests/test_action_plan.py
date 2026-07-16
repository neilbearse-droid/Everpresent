"""Citation-gap target list + per-gap content briefs (panel #4 + #1), over
hand-built data so the third-party-source filter and brief assembly are
exercised deterministically."""

from api.dashboards_service import action_plan
from api.models import (
    BrandProfile,
    Citation,
    Mention,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)


def _result(db, run_id, tid, qtext, surface, variant):
    r = Result(run_id=run_id, tenant_id=tid, query_text=qtext, persona_name="p",
               surface=SurfaceCode(surface), variant=ResultVariant(variant),
               status=ResultStatus.ok)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_targets_and_brief_for_a_content_gap(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Acme", domains=["acme.com"]))
    db_session.add(Query(tenant_id=tid, text="best crm", corpus_tag="crm"))
    db_session.add(Query(tenant_id=tid, text="crm for startups", corpus_tag="crm"))
    db_session.commit()
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    run_id = run.id

    # Search answer: rival present, brand absent, cites a third-party source + rival site.
    s = _result(db_session, run_id, tid, "best crm", "openai_api", "search")
    db_session.add(Mention(result_id=s.id, tenant_id=tid, entity_type="competitor",
                           entity_name="Globex", position=0, rank=1))
    db_session.add(Citation(result_id=s.id, tenant_id=tid, url="https://g2.com/crm",
                            domain="g2.com", source_category="other"))
    db_session.add(Citation(result_id=s.id, tenant_id=tid, url="https://globex.com",
                            domain="globex.com", source_category="competitor"))
    db_session.add(Citation(result_id=s.id, tenant_id=tid, url="https://acme.com/x",
                            domain="acme.com", source_category="brand"))
    # Training-only twin knows the brand -> content gap (not knowledge gap).
    ns = _result(db_session, run_id, tid, "best crm", "openai_api", "nosearch")
    db_session.add(Mention(result_id=ns.id, tenant_id=tid, entity_type="brand",
                           entity_name="Acme", position=0, rank=1))
    db_session.commit()

    plan = action_plan(db_session, tid)

    # #4 target list: only the pitchable third-party source; rival + owned excluded.
    target_domains = [t["domain"] for t in plan["targets"]]
    assert target_domains == ["g2.com"]
    g2 = plan["targets"][0]
    assert g2["competitor_assoc"] == 1 and g2["already_citing_you"] is False

    # #1 content brief for the gap query.
    assert len(plan["briefs"]) == 1
    brief = plan["briefs"][0]
    assert brief["query"] == "best crm"
    assert brief["diagnosis"]["type"] == "content_gap"
    assert brief["competitors_winning"] == ["Globex"]
    assert brief["target_sources"] == [{"domain": "g2.com", "rivals": ["Globex"]}]
    assert "crm for startups" in brief["subtopics"]  # sibling query in same corpus
    assert any("best crm" in line for line in brief["outline"])
    assert plan["summary"]["content_gap"] == 1
