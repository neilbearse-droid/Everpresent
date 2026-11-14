"""Fixes are experiments: every fix is logged with what it was and what it
predicted, page changes are detected whether or not anyone logs them, and
every fix is scored the same way and its outcome stored."""

from datetime import UTC, date, datetime, timedelta

from sqlmodel import select

from api.models import (
    AccuracyFinding,
    BrandProfile,
    Citation,
    FixOutcome,
    Intervention,
    Mention,
    PageChange,
    PageSnapshot,
    Query,
    Recommendation,
    RecommendationStatus,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    User,
)
from api.page_changes_service import covers, diff, record_crawl
from api.proof_service import intervention_proof, refresh_outcomes

TODAY = date(2026, 10, 4)
SHIP = datetime(2026, 9, 6, tzinfo=UTC)
BEFORE, AFTER = SHIP.date() - timedelta(days=10), SHIP.date() + timedelta(days=10)
CHATGPT, CLAUDE = SurfaceCode.openai_api, SurfaceCode.claude_api


def _tenant(db) -> Tenant:
    t = Tenant(name="Acme", slug="acme", clerk_org_id="org_acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.commit()
    return t


def _run(db, t) -> Run:
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    return run


def _answers(db, t, run, query, day, n, named, *, surface=CHATGPT, rival="", wrong_fact=0,
             cites=()):
    """n answers on one day: the first `named` name the brand (and the rival,
    when given); the first `wrong_fact` carry a finding for fact 3."""
    for i in range(n):
        r = Result(run_id=run.id, tenant_id=t.id, query_text=query, persona_name="generic",
                   surface=surface, variant=ResultVariant.search, status=ResultStatus.ok,
                   created_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC))
        db.add(r)
        db.flush()
        if i < named:
            db.add(Mention(result_id=r.id, tenant_id=t.id, entity_name=rival or "Acme",
                           entity_type="competitor" if rival else "brand", position=0, rank=1))
        if i < wrong_fact:
            db.add(AccuracyFinding(result_id=r.id, tenant_id=t.id, fact_id=3,
                                   subject="starter price", expected="$9", stated="$19"))
        for url in cites:
            domain = url.split("/")[2].removeprefix("www.")
            db.add(Citation(result_id=r.id, tenant_id=t.id, url=url, domain=domain,
                            source_category="brand" if domain == "acme.com" else "other"))
    db.commit()


def _rec(db, t, **kw) -> Recommendation:
    base = {"tenant_id": t.id, "gap_ref": "query:best crm::branch:web_search",
            "branch": "web_search", "title": "Build the page that answers “best crm”",
            "action_text": "x", "priority": 40, "evidence": "strong", "category": "content",
            "control": "own", "query_text": "best crm",
            "impact": {"score": 3.2, "band": "high", "basis": "Touches 10%."},
            "scope": {"questions": ["best crm"], "families": []},
            "targets": [{"kind": "Your page", "label": "acme.com/crm",
                         "url": "https://acme.com/crm"}]}
    rec = Recommendation(**{**base, **kw})
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _member(db, login):
    user = User(email="m@acme.example", clerk_user_id="user_acme")
    db.add(user)
    db.commit()
    db.refresh(user)
    login(user, org_id="org_acme")


# ------------------------------------------------ step 1: logged fixes ----

def test_marking_done_logs_the_fix_as_an_experiment(client, login, db_session):
    t = _tenant(db_session)
    rec = _rec(db_session, t)
    _member(db_session, login)
    resp = client.patch(f"/api/tenant/recommendations/{rec.id}", json={
        "status": "done",
        "fix": {"description": "Added prices and a comparison table", "shipped_at": "2026-09-06"}})
    assert resp.status_code == 200 and resp.json()["status"] == "done"
    [fix] = db_session.exec(select(Intervention)).all()
    assert fix.source == "logged" and fix.created_by == "m@acme.example"
    assert fix.description == "Added prices and a comparison table"
    # Where: the page the recommendation named, when none was given.
    assert fix.url == "https://acme.com/crm" and fix.shipped_at.date() == SHIP.date()
    # What it was, what it is measured on, and what it predicted.
    assert (fix.recommendation_id, fix.gap_ref) == (rec.id, rec.gap_ref)
    assert (fix.play, fix.category, fix.control, fix.evidence) == (
        "web_search", "content", "own", "strong")
    assert fix.query_text == "best crm" and fix.questions == ["best crm"]
    assert fix.predicted["band"] == "high" and fix.predicted["score"] == 3.2
    assert fix.predicted["priority"] == 40

    # The same fix logged again that day corrects the record; it isn't a second one.
    client.patch(f"/api/tenant/recommendations/{rec.id}", json={
        "status": "done", "fix": {"description": "Prices, table and FAQ",
                                  "url": "https://acme.com/crm-software",
                                  "shipped_at": "2026-09-06"}})
    db_session.expire_all()
    [fix] = db_session.exec(select(Intervention)).all()
    assert fix.description == "Prices, table and FAQ" and fix.url.endswith("/crm-software")

    bad = client.patch(f"/api/tenant/recommendations/{rec.id}",
                       json={"status": "done", "fix": {"url": "acme.com/crm"}})
    assert bad.status_code == 422 and "http" in bad.json()["detail"]


def test_done_without_details_still_logs_and_setup_items_do_not(client, login, db_session):
    t = _tenant(db_session)
    rec = _rec(db_session, t)
    setup = _rec(db_session, t, gap_ref="connect_logs", branch="connect_logs",
                 category="setup", title="Connect your server logs", query_text="",
                 impact={}, scope={}, targets=[])
    _member(db_session, login)
    assert client.patch(f"/api/tenant/recommendations/{setup.id}",
                        json={"status": "done"}).json()["status"] == "done"
    assert db_session.exec(select(Intervention)).all() == []
    client.patch(f"/api/tenant/recommendations/{rec.id}", json={"status": "done"})
    [fix] = db_session.exec(select(Intervention)).all()
    assert fix.description == rec.title and fix.url == "https://acme.com/crm"


def test_mark_shipped_on_a_question_closes_its_page_play(client, login, db_session):
    t = _tenant(db_session)
    rec = _rec(db_session, t)
    _member(db_session, login)
    resp = client.post("/api/tenant/interventions",
                       json={"query_text": "best crm", "url": "https://acme.com/crm"})
    assert resp.status_code == 201 and resp.json()["play"] == "web_search"
    db_session.expire_all()
    assert db_session.get(Recommendation, rec.id).status == RecommendationStatus.done
    # A question with no open play is still logged, on its own question.
    other = client.post("/api/tenant/interventions", json={"query_text": "crm pricing"}).json()
    assert other["play"] == "" and other["questions"] == ["crm pricing"]

    # Removing a fix removes its stored outcome too.
    refresh_outcomes(db_session, t.id)
    db_session.commit()
    assert len(db_session.exec(select(FixOutcome)).all()) == 2
    assert client.delete(f"/api/tenant/interventions/{other['id']}").status_code == 204
    assert [o.intervention_id for o in db_session.exec(select(FixOutcome)).all()] == [
        resp.json()["id"]]


def test_recommendations_record_what_a_fix_is_measured_on(db_session):
    from api.impact import Universe
    from api.recommendations_service import Play, _rank

    t = _tenant(db_session)
    run = _run(db_session, t)
    today = datetime.now(UTC).date()
    for q in ("best crm", "crm pricing"):
        _answers(db_session, t, run, q, today, 2, 0)
        _answers(db_session, t, run, q, today, 2, 0, surface=CLAUDE)
    uni = Universe(db_session, t.id)

    def play() -> Play:
        return Play("x", "web_search", "t", "a", 0, "strong", "why", control="own")

    one_question = _rank(play(), uni, uni.for_query("best crm"))
    assert one_question.scope == {"questions": ["best crm"], "families": []}
    one_engine = _rank(play(), uni, uni.for_families(("chatgpt",)))
    assert one_engine.scope == {"questions": [], "families": ["chatgpt"]}
    assert _rank(play(), None, floor=0.5).scope == {}  # nothing measured: site-wide


# ----------------------------------------------- step 2: page changes ----

BASE = {"has_price": False, "has_updated_date": True, "updated_on": "2026-03-01",
        "latest_year": 2026, "has_rating": False, "statistic_count": 6, "word_count": 600,
        "headings": ["Pricing"], "noindex": False, "fact_conflicts": [],
        "brand_found": False, "competitors_found": ["Globex"]}


def _kinds(old, new, **kw):
    return [c["kind"] for c in diff(old, new, **{"owner": "brand", **kw})]


def test_diff_names_what_changed_and_ignores_wobble():
    assert diff(BASE, dict(BASE), owner="brand") == []
    assert _kinds(BASE, {**BASE, "has_price": True}) == ["price_added"]
    # A rolling "updated" date moves a day at a time: not a refresh.
    assert _kinds(BASE, {**BASE, "updated_on": "2026-03-02"}) == []
    [refreshed] = diff(BASE, {**BASE, "updated_on": "2026-10-03"}, owner="brand")
    assert refreshed["kind"] == "date_refreshed" and refreshed["material"]
    assert refreshed["summary"] == "“Updated” date moved from 2026-03-01 to 2026-10-03"
    # A few words either way is noise; a quarter more is a rewrite.
    assert _kinds(BASE, {**BASE, "word_count": 640}) == []
    assert _kinds(BASE, {**BASE, "word_count": 900}) == ["content_expanded"]
    assert _kinds(BASE, {**BASE, "statistic_count": 14}) == ["data_added"]
    assert _kinds(BASE, {**BASE, "noindex": True}) == ["noindex_added"]
    assert _kinds({**BASE, "fact_conflicts": [{"fact_id": 1}]}, BASE) == ["fact_conflict_fixed"]
    # A check the old version predates is never a change.
    old = {k: v for k, v in BASE.items() if k not in ("headings", "updated_on")}
    assert _kinds(old, {**BASE, "headings": ["Pricing", "FAQ"]}) == []


def test_new_sections_are_matched_to_open_sub_questions():
    new = {**BASE, "headings": ["Pricing", "CRM pricing in 2026: what each plan costs"]}
    [covered] = diff(BASE, new, owner="brand", subquestions=["crm pricing 2026"])
    assert covered["kind"] == "subquestion_covered"
    assert covered["summary"] == "Now has a section for “crm pricing 2026”"
    [added] = diff(BASE, new, owner="brand", subquestions=["free crm for nonprofits"])
    assert added["kind"] == "sections_added" and "CRM pricing in 2026" in added["summary"]
    assert covers("How much does a CRM cost per user?", "crm cost per user")
    assert not covers("Our story", "crm cost per user")


def test_third_party_pages_report_who_appears_on_them():
    kinds = [c["kind"] for c in diff(BASE, {**BASE, "brand_found": True}, owner="other")]
    assert kinds == ["brand_added"]
    [rival] = diff(BASE, {**BASE, "competitors_found": ["Globex", "Initech"]}, owner="other")
    assert rival["kind"] == "rival_added" and rival["detail"]["added"] == ["Initech"]
    assert rival["summary"] == "Initech now appears on this page"
    # On the brand's own page, who else is named isn't the story.
    assert diff(BASE, {**BASE, "competitors_found": ["Globex", "Initech"]}, owner="brand") == []


def _page(url, owner, features, **kw):
    return {"url": url, "owner": owner, "status": "ok", "features": features, **kw}


OWN = "https://acme.com/crm"
FEATURES = {k: v for k, v in BASE.items() if k not in ("brand_found", "competitors_found")}


def test_crawls_version_pages_only_when_they_change(db_session):
    t = _tenant(db_session)
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    first = record_crawl(db_session, t.id, [_page(OWN, "brand", FEATURES)], now=t0)
    assert first == {"versions": 1, "changes": 0, "experiments": 0}  # the baseline
    # Unchanged a week later: the same version, seen again. A blocked fetch
    # is not a version at all.
    same = record_crawl(db_session, t.id, [
        _page(OWN, "brand", {**FEATURES, "word_count": 610}),
        {"url": "https://acme.com/down", "owner": "brand", "status": "error"},
    ], now=t0 + timedelta(days=7))
    assert same["versions"] == 0 and same["changes"] == 0
    [snap] = db_session.exec(select(PageSnapshot)).all()
    assert (snap.last_seen_at - snap.first_seen_at).days == 7
    changed = record_crawl(db_session, t.id, [
        _page(OWN, "brand", {**FEATURES, "has_price": True, "word_count": 1200})],
        now=t0 + timedelta(days=14))
    assert changed["versions"] == 1 and changed["changes"] == 2
    kinds = {c.kind: c for c in db_session.exec(select(PageChange)).all()}
    assert set(kinds) == {"price_added", "content_expanded"}
    # Dated to the gap between the two crawls it happened in.
    ch = kinds["price_added"]
    assert (ch.changed_after.day, ch.detected_at.day) == (8, 15)
    assert len(db_session.exec(select(PageSnapshot)).all()) == 2


def test_a_change_attaches_to_the_logged_fix_for_that_page(db_session):
    from api import fixes_service

    t = _tenant(db_session)
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    record_crawl(db_session, t.id, [_page(OWN, "brand", FEATURES)], now=t0)
    fix = fixes_service.log_fix(db_session, t.id, description="Added prices", url=OWN,
                                shipped_at=t0 + timedelta(days=5), query_text="best crm")
    db_session.commit()
    out = record_crawl(db_session, t.id, [_page(OWN, "brand", {**FEATURES, "has_price": True})],
                       now=t0 + timedelta(days=7))
    assert out["experiments"] == 0  # someone already logged it
    [ch] = db_session.exec(select(PageChange)).all()
    assert ch.intervention_id == fix.id
    [item] = intervention_proof(db_session, t.id, today=TODAY)["items"]
    assert [c["summary"] for c in item["changes"]] == ["Prices are now stated on the page"]


def test_an_unlogged_change_opens_a_detected_fix_and_logging_claims_it(db_session):
    from api import fixes_service

    t = _tenant(db_session)
    rec = _rec(db_session, t)  # names https://acme.com/crm as "Your page"
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    record_crawl(db_session, t.id, [_page(OWN, "brand", FEATURES)], now=t0)
    out = record_crawl(db_session, t.id, [_page(OWN, "brand", {**FEATURES, "has_price": True})],
                       now=t0 + timedelta(days=8))
    assert out["experiments"] == 1
    [detected] = db_session.exec(select(Intervention)).all()
    assert detected.source == "detected" and detected.created_by == "crawl"
    assert detected.description == "Prices are now stated on the page"
    # Dated halfway between the crawls, and tied to the play it answers,
    # which stays open: the client hasn't said it is done.
    assert detected.shipped_at.date() == date(2026, 9, 5)
    assert detected.recommendation_id == rec.id and detected.questions == ["best crm"]
    db_session.refresh(rec)
    assert rec.status == RecommendationStatus.open

    # When the client then marks it done, the detected fix folds into theirs.
    logged = fixes_service.mark_done(db_session, rec, description="New pricing section",
                                     shipped_at=t0 + timedelta(days=4))
    db_session.commit()
    assert [(i.source, i.description) for i in db_session.exec(select(Intervention)).all()] == [
        ("logged", "New pricing section")]
    [ch] = db_session.exec(select(PageChange)).all()
    assert logged is not None and ch.intervention_id == logged.id


def test_a_rivals_page_change_is_measured_on_the_rival(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t)
    rival_page = "https://globex.com/pricing"
    t0 = datetime(SHIP.year, SHIP.month, SHIP.day, tzinfo=UTC) - timedelta(days=4)
    db_session.add_all([Query(tenant_id=t.id, text="best crm"),
                        Query(tenant_id=t.id, text="crm for startups")])
    # Globex is named in 20% of answers before its page changed and 70% after;
    # on the question that page isn't cited for, it stays flat.
    _answers(db_session, t, run, "best crm", BEFORE, 30, 6, rival="Globex", cites=[rival_page])
    _answers(db_session, t, run, "best crm", AFTER, 30, 21, rival="Globex", cites=[rival_page])
    _answers(db_session, t, run, "crm for startups", BEFORE, 30, 9, rival="Globex")
    _answers(db_session, t, run, "crm for startups", AFTER, 30, 9, rival="Globex")
    theirs = {"url": rival_page, "owner": "competitor", "owner_name": "Globex", "status": "ok"}
    record_crawl(db_session, t.id, [{**theirs, "features": FEATURES}], now=t0)
    out = record_crawl(db_session, t.id, [
        {**theirs, "features": {**FEATURES, "has_price": True, "updated_on": "2026-09-05"}}],
        now=t0 + timedelta(days=8))
    assert out["experiments"] == 1
    [fix] = db_session.exec(select(Intervention)).all()
    assert (fix.source, fix.subject, fix.questions) == ("detected", "Globex", ["best crm"])

    proof = intervention_proof(db_session, t.id, today=TODAY)
    assert proof["items"] == [] and proof["summary"] is None  # not the brand's fix
    [it] = proof["rival_items"]
    assert it["status"] == "proven" and it["subject"] == "Globex"
    assert it["signals"][0]["label"] == "Globex named in answers"
    assert (it["signals"][0]["before"], it["signals"][0]["after"]) == (20.0, 70.0)
    assert it["signals"][0]["control_delta_pts"] == 0.0
    assert it["headline"].startswith("Globex's mention rate on this question is up 50.0 points "
                                     "since the change")


def test_a_change_nothing_can_be_measured_on_opens_no_fix(db_session):
    t = _tenant(db_session)
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    listed = "https://reviews.example/best-crm"
    record_crawl(db_session, t.id, [_page(listed, "other", FEATURES)], now=t0)
    out = record_crawl(db_session, t.id, [_page(listed, "other", FEATURES, brand_found=True)],
                       now=t0 + timedelta(days=7))
    # The change is recorded; with no answers citing the page there is no
    # experiment to run.
    assert out == {"versions": 1, "changes": 1, "experiments": 0}
    assert db_session.exec(select(Intervention)).all() == []


# ------------------------------------------------- step 3: one scoring ----

def test_a_fix_for_several_questions_is_judged_on_all_of_them(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t)
    for q in ("best crm", "crm pricing"):   # 20% -> 60% on both
        _answers(db_session, t, run, q, BEFORE, 20, 4)
        _answers(db_session, t, run, q, AFTER, 20, 12)
        _answers(db_session, t, run, q, AFTER, 10, 2, surface=CLAUDE)
        _answers(db_session, t, run, q, BEFORE, 10, 2, surface=CLAUDE)
    _answers(db_session, t, run, "untouched", BEFORE, 30, 9)
    _answers(db_session, t, run, "untouched", AFTER, 30, 9)
    db_session.add(Intervention(
        tenant_id=t.id, query_text="", questions=["best crm", "crm pricing"],
        description="Got onto the G2 category page", shipped_at=SHIP, play="reviews",
        category="reviews", control="influence",
        predicted={"band": "medium", "score": 1.4, "basis": "Touches 12%."}))
    db_session.commit()
    [it] = intervention_proof(db_session, t.id, today=TODAY)["items"]
    s = it["signals"][0]
    assert it["status"] == "proven" and (s["before_n"], s["after_n"]) == (60, 60)
    assert s["note"] == "answers to 2 questions vs all untouched questions"
    assert it["headline"].startswith("Mention rate on these 2 questions is up")
    assert it["predicted"] == {"band": "medium", "score": 1.4, "basis": "Touches 12%."}
    assert (it["play"], it["category"], it["source"]) == ("reviews", "reviews", "logged")
    # Per engine: the lift is ChatGPT's; Claude didn't move.
    engines = {e["family"]: e for e in it["by_engine"]}
    assert (engines["chatgpt"]["before"], engines["chatgpt"]["after"]) == (20.0, 60.0)
    assert engines["chatgpt"]["verdict"] == "up" and engines["claude"]["delta_pts"] == 0.0
    # It was there in the first week measured.
    assert it["days_to_effect"] in (14, 21)


def test_an_engine_wide_fix_is_controlled_by_the_other_engines(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t)
    _answers(db_session, t, run, "best crm", BEFORE, 40, 4)                  # ChatGPT 10%
    _answers(db_session, t, run, "best crm", AFTER, 40, 20)                  # ChatGPT 50%
    _answers(db_session, t, run, "best crm", BEFORE, 40, 12, surface=CLAUDE)  # Claude flat
    _answers(db_session, t, run, "best crm", AFTER, 40, 12, surface=CLAUDE)
    db_session.add(Intervention(tenant_id=t.id, query_text="", families=["chatgpt"],
                                description="Unblocked OAI-SearchBot", shipped_at=SHIP,
                                play="crawler_access", category="structure"))
    db_session.commit()
    [it] = intervention_proof(db_session, t.id, today=TODAY)["items"]
    s = it["signals"][0]
    assert it["status"] == "proven" and (s["before"], s["after"]) == (10.0, 50.0)
    assert s["control_delta_pts"] == 0.0 and s["note"] == "answers on ChatGPT vs the other engines"
    assert it["headline"].startswith("Mention rate on ChatGPT is up 40.0 points")


def test_a_wrong_fact_is_judged_on_how_often_it_is_still_said(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t)
    db_session.add(Query(tenant_id=t.id, text="acme price", branded=True))
    _answers(db_session, t, run, "acme price", BEFORE, 40, 40, wrong_fact=24)  # 60% wrong
    _answers(db_session, t, run, "acme price", AFTER, 40, 40, wrong_fact=4)    # 10% wrong
    db_session.add(Intervention(tenant_id=t.id, query_text="", questions=["acme price"],
                                description="Fix a wrong fact: starter price", shipped_at=SHIP,
                                play="accuracy", gap_ref="accuracy:3", category="accuracy"))
    db_session.commit()
    [it] = intervention_proof(db_session, t.id, today=TODAY)["items"]
    s = it["signals"][0]
    assert it["metric"] == "wrong_fact" and s["lower_is_better"] is True
    assert (s["label"], s["before"], s["after"]) == ("Stated wrong in answers", 60.0, 10.0)
    # Fewer wrong answers is the win.
    assert it["status"] == "proven"
    assert it["headline"] == "Answers stating this wrong fell from 60.0% to 10.0% since the fix."


def test_a_page_fix_is_judged_on_the_page_being_cited(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t)
    page = "https://acme.com/pricing"
    _answers(db_session, t, run, "crm pricing", BEFORE, 40, 10)
    _answers(db_session, t, run, "crm pricing", AFTER, 20, 6)
    _answers(db_session, t, run, "crm pricing", AFTER, 20, 6, cites=[page])  # cited again
    db_session.add(Intervention(tenant_id=t.id, query_text="", questions=["crm pricing"],
                                url=page, description="Refreshed the pricing page",
                                shipped_at=SHIP, play="refresh", category="content"))
    db_session.commit()
    [it] = intervention_proof(db_session, t.id, today=TODAY)["items"]
    assert it["metric"] == "page_cited" and it["status"] == "proven"
    assert [s["key"] for s in it["signals"][:2]] == ["page_cited", "mentions"]
    assert (it["signals"][0]["before"], it["signals"][0]["after"]) == (0.0, 50.0)
    assert it["headline"].startswith("Answers citing this page rose from 0.0% to 50.0%")


def test_outcomes_are_stored_and_frozen_once_the_window_is_full(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t)
    _answers(db_session, t, run, "best crm", BEFORE, 30, 6)
    _answers(db_session, t, run, "best crm", AFTER, 30, 18)
    _answers(db_session, t, run, "untouched", BEFORE, 30, 9)
    _answers(db_session, t, run, "untouched", AFTER, 30, 9)
    db_session.add(Intervention(tenant_id=t.id, query_text="best crm", shipped_at=SHIP,
                                description="New page", play="web_search"))
    db_session.commit()

    # Two weeks in: measured, not final.
    assert refresh_outcomes(db_session, t.id, today=SHIP.date() + timedelta(days=14)) == 1
    db_session.commit()
    [row] = db_session.exec(select(FixOutcome)).all()
    assert row.status == "proven" and row.final is False and row.window_days == 14
    assert (row.before_rate, row.after_rate, row.n_before, row.n_after) == (20.0, 60.0, 30, 30)
    assert row.delta_pts == 40.0 and row.control_delta_pts == 0.0 and row.net_pts == 40.0
    assert row.verdict == "up" and row.metric == "mentions" and row.days_to_effect == 14
    assert row.by_engine[0]["family"] == "chatgpt" and row.signals[0]["key"] == "mentions"

    # A full window later it is final, and a later run doesn't rewrite it.
    refresh_outcomes(db_session, t.id, today=TODAY)
    db_session.commit()
    db_session.refresh(row)
    assert row.final is True and row.window_days == 28
    measured = row.measured_at
    _answers(db_session, t, run, "best crm", AFTER, 60, 0)  # history changes afterwards
    assert refresh_outcomes(db_session, t.id, today=TODAY + timedelta(days=30)) == 0
    db_session.refresh(row)
    assert row.after_rate == 60.0 and row.measured_at == measured


def test_page_features_carry_the_date_and_headings():
    from engine.audit.presence import extract_features, parse_date

    html = ("<html><body><h1>CRM pricing</h1><p>Updated on Oct 3rd, 2026. From $12 a month.</p>"
            "<h2>How much does it cost?</h2><p>x</p><h2>How much does it cost?</h2>"
            "<script>var h = '<h2>Not a heading</h2>';</script></body></html>")
    f = extract_features(html)
    assert f["updated_on"] == "2026-10-03"
    assert f["headings"] == ["CRM pricing", "How much does it cost?"]
    assert parse_date("Last updated: 3 October 2026") == "2026-10-03"
    assert parse_date("Reviewed 31/12/2025") == "2025-12-31"
    assert parse_date("Updated November 2026") == "2026-11-01"
    assert parse_date("updated marketing 2026") == "" and parse_date("updated 2000 records") == ""
