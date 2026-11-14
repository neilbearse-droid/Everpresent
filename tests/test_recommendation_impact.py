"""Recommendations are ranked by projected impact (reach x gap x odds), sorted
into areas of work, and third-party sources only become plays when a route
onto them is realistic."""

from datetime import timedelta

from sqlmodel import col, select

from api.impact import (
    CATEGORIES,
    Reach,
    Universe,
    assign_bands,
    impact,
    priority_of,
)
from api.models import (
    BrandProfile,
    Citation,
    FanoutShard,
    Mention,
    PagePresence,
    Query,
    QueryClassification,
    Recommendation,
    RecommendationStatus,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    utcnow,
)
from api.recommendations_service import (
    _query_plays,
    _source_plays,
    _subquery_plays,
    generate_recommendations,
)
from api.source_routes import route_for, source_kind

CHATGPT, PERPLEXITY, CLAUDE, GEMINI = (SurfaceCode.openai_api, SurfaceCode.perplexity_api,
                                       SurfaceCode.claude_api, SurfaceCode.gemini_api)


def _tenant(db) -> Tenant:
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.commit()
    return t


def _run(db, tid) -> Run:
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    return run


def _answer(db, t, run, query, surface, *, named=False, rivals=(), cites=()) -> Result:
    """One measured answer: who it names and which URLs it cites."""
    r = Result(run_id=run.id, tenant_id=t.id, query_text=query, persona_name="p",
               surface=surface, variant=ResultVariant.search, status=ResultStatus.ok)
    db.add(r)
    db.commit()
    if named:
        db.add(Mention(result_id=r.id, tenant_id=t.id, entity_type="brand",
                       entity_name="Acme", position=0, rank=1))
    for name in rivals:
        db.add(Mention(result_id=r.id, tenant_id=t.id, entity_type="competitor",
                       entity_name=name, position=1, rank=2))
    for url in cites:
        domain = url.split("/")[2].removeprefix("www.")
        category = "brand" if domain == "acme.com" else "other"
        db.add(Citation(result_id=r.id, tenant_id=t.id, url=url, domain=domain,
                        source_category=category))
    db.commit()
    return r


# ------------------------------------------------------------ the model ----

def test_reach_is_weighted_by_engine_audience(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t.id)
    for _ in range(2):
        _answer(db_session, t, run, "best crm", CHATGPT)
    for _ in range(8):
        _answer(db_session, t, run, "best crm", PERPLEXITY, named=True)
    uni = Universe(db_session, t.id)
    assert len(uni) == 10
    # ChatGPT (weight 40) and Perplexity (weight 3) share the whole audience.
    chatgpt = uni.reach(uni.for_families(("chatgpt",)))
    perplexity = uni.reach(uni.for_families(("perplexity",)))
    assert round(chatgpt.share, 3) == round(40 / 43, 3)
    assert round(chatgpt.share + perplexity.share, 6) == 1.0
    # Two unnamed ChatGPT answers outweigh eight named Perplexity ones.
    everything = uni.reach()
    assert everything.answers == 10 and everything.missing == 2
    assert round(everything.gap, 3) == round(40 / 43, 3)


def test_branded_and_paused_questions_stay_out_of_the_reach(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t.id)
    db_session.add(Query(tenant_id=t.id, text="is acme good", branded=True))
    db_session.add(Query(tenant_id=t.id, text="old question", active=False))
    db_session.commit()
    _answer(db_session, t, run, "best crm", CHATGPT)
    _answer(db_session, t, run, "is acme good", CHATGPT, named=True)
    _answer(db_session, t, run, "old question", CHATGPT)
    old = _answer(db_session, t, run, "best crm", CHATGPT)
    old.created_at = utcnow() - timedelta(days=40)  # outside the 28-day window
    db_session.add(old)
    db_session.commit()
    assert {a.query_text for a in Universe(db_session, t.id).answers.values()} == {"best crm"}
    assert len(Universe(db_session, t.id, scope="all")) == 3
    assert len(Universe(db_session, t.id, scope="branded")) == 1


def test_odds_order_plays_with_the_same_reach():
    reach = Reach(answers=50, missing=40, share=0.10, gap=0.08, families=["chatgpt"])
    own = impact(reach, control="own", evidence="strong")
    ask = impact(reach, control="influence", evidence="strong")
    earn = impact(reach, control="earn", evidence="strong")
    assert own["score"] > ask["score"] > earn["score"]
    assert own["score"] == 6.4  # 100 x 0.08 gap x (1.0 x 0.8)
    assert impact(reach, control="own", evidence="emerging")["score"] < own["score"]
    assert own["named"] == 10 and "you're named in 10 of them" in own["basis"]
    # A problem every touched answer carries doesn't talk about "named in".
    assert "named" not in impact(reach, control="own", evidence="strong", at_stake=True)
    # With nothing measured the floor stands in, and the record says so.
    floored = impact(None, control="own", evidence="official", floor=0.8)
    assert floored["score"] == 0.8 and floored["measured"] is False
    assert priority_of(30) > priority_of(15) > priority_of(1) > priority_of(0.1) >= 1


def test_bands_are_relative_to_the_list_and_floors_are_never_high():
    scores = [{"score": 50.0, "measured": True}, {"score": 20.0, "measured": True},
              {"score": 15.0, "measured": True}, {"score": 10.0, "measured": True},
              {"score": 5.0, "measured": True}]
    assign_bands(scores)
    # The plays that open the first half of the projected impact are high, the
    # ones that open the next 35% medium, the tail low.
    assert [s["band"] for s in scores] == ["high", "medium", "medium", "low", "low"]
    lone_floor = [{"score": 0.8, "measured": False}]
    assign_bands(lone_floor)
    assert lone_floor[0]["band"] == "medium"
    assert set(CATEGORIES) >= {"structure", "content", "accuracy", "third_party", "reviews",
                               "community", "platforms", "setup"}


# ------------------------------------------------- third-party sources ----

G2 = "https://www.g2.com/categories/crm"
LIST = "https://techradar.com/best/best-crm-software"
NEWS = "https://newsroom.example/2026/globex-raises-funding"
THREAD = "https://www.reddit.com/r/sales/comments/abc/which_crm"
VIDEO = "https://www.youtube.com/watch?v=abc"
PCMAG = "https://pcmag.com/picks/the-best-crm"


def _cited_world(db, t):
    """Three runs. g2, a TechRadar list, a news article, a Reddit thread and a
    YouTube video are each cited in every run alongside rivals; pcmag names
    Acme as often as rivals; a one-off blog is cited in a single run."""
    for i in range(3):
        run = _run(db, t.id)
        for surface in (CHATGPT, PERPLEXITY):
            _answer(db, t, run, "best crm", surface, rivals=["Globex", "Initech"],
                    cites=[G2, LIST, NEWS, THREAD, VIDEO])
            _answer(db, t, run, "crm for startups", surface, named=True, rivals=["Globex"],
                    cites=[PCMAG])
        if i == 0:
            for _ in range(4):
                _answer(db, t, run, "best crm", CHATGPT, rivals=["Globex"],
                        cites=["https://oneoff.example/best-crm-list"])
        # A rival's own site is "competitor", never a third-party target.
        r = _answer(db, t, run, "best crm", CLAUDE, rivals=["Globex"])
        db.add(Citation(result_id=r.id, tenant_id=t.id, url="https://globex.com/crm",
                        domain="globex.com", source_category="competitor"))
        db.commit()


def test_source_plays_name_pages_and_what_is_realistic(db_session):
    t = _tenant(db_session)
    _cited_world(db_session, t)
    db_session.add(PagePresence(tenant_id=t.id, url=G2, domain="g2.com", brand_found=False,
                                competitors_found=["Globex", "Initech"]))
    db_session.commit()
    plays = {p.gap_ref: p for p in _source_plays(db_session, t.id)}
    # A one-off citation, a rival's own site and a page that names the brand
    # as often as its rivals are not targets.
    assert set(plays) == {"source:g2.com", "source:techradar.com", "source:newsroom.example",
                          "source:reddit.com", "source:youtube.com"}

    g2 = plays["source:g2.com"]
    assert (g2.branch, g2.category, g2.control) == ("reviews", "reviews", "influence")
    assert "in 3 of your last 3 runs" in g2.action_text and "Globex" in g2.action_text
    assert "The page cited most doesn't mention you." in g2.action_text
    assert g2.targets[0]["url"] == G2 and g2.targets[0]["detail"] == "cited in 6 answers"
    assert g2.targets[0]["note"] == "doesn't mention you; names Globex and Initech"

    listed = plays["source:techradar.com"]
    assert (listed.branch, listed.category, listed.control) == ("earned", "third_party", "earn")
    assert listed.targets[0]["kind"] == "List"
    assert any("If there is no route in, drop it" in s for s in listed.steps)

    news = plays["source:newsroom.example"]
    assert news.branch == "press" and "won't be edited to add you" in news.action_text
    assert news.steps[0].startswith("Don't ask to be added to a published article")

    thread = plays["source:reddit.com"]
    assert thread.category == "community" and thread.control == "influence"
    assert any("archived or locked, skip it" in s for s in thread.steps)
    video = plays["source:youtube.com"]
    assert video.control == "own" and "can't get into someone else's video" in video.steps[0]

    # Same reach on all five: what's in reach of the brand ranks first, a
    # list it has to be chosen for next, an article that won't change last.
    assert g2.impact["score"] > listed.impact["score"] > news.impact["score"]
    assert g2.impact["answers"] == 6 and g2.impact["named"] == 0


def test_a_page_that_already_names_the_brand_changes_the_ask(db_session):
    t = _tenant(db_session)
    _cited_world(db_session, t)
    db_session.add(PagePresence(tenant_id=t.id, url=LIST, domain="techradar.com",
                                brand_found=True, competitors_found=["Globex"]))
    db_session.commit()
    listed = {p.gap_ref: p for p in _source_plays(db_session, t.id)}["source:techradar.com"]
    assert "already mentions you" in listed.action_text
    assert listed.steps[0].startswith("You're already on the page cited most")


def test_source_kinds_and_routes():
    assert source_kind("g2.com") == "review"
    assert source_kind("techradar.com", LIST) == "list"
    assert source_kind("newsroom.example", NEWS) == "article"
    assert source_kind("www.amazon.com") == "listing"
    assert source_kind("en.wikipedia.org") == "reference"
    assert route_for("youtube.com")["control"] == "own"
    assert route_for("newsroom.example", NEWS)["route"].startswith("It won't be edited")


# ------------------------------------------------------ question plays ----

def _gap_question(db, t, run, text, *, aio=False, named_on=()):
    db.add(Query(tenant_id=t.id, text=text))
    db.add(QueryClassification(
        tenant_id=t.id, query_text=text, surface=SurfaceCode.openai_api,
        web_search_likelihood="likely",
        google_aio_source_type="aio_dominant" if aio else "",
        google_aio_signals={"cited_domains": ["g2.com"]} if aio else {}))
    for surface in (CHATGPT, PERPLEXITY, CLAUDE, GEMINI):
        _answer(db, t, run, text, surface, named=surface in named_on, rivals=["Globex"])
    db.commit()


def test_search_and_overview_gaps_on_one_question_are_one_page_play(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t.id)
    _gap_question(db_session, t, run, "best crm", aio=True)
    db_session.add(FanoutShard(tenant_id=t.id, run_id=run.id, parent_query_text="best crm",
                               shard_text="crm pricing 2026", shard_norm="crm pricing 2026",
                               reach=3, brand_present=False, winners=["Globex"],
                               source="reprobed"))
    db_session.commit()
    [p] = _query_plays(db_session, t.id, {})
    assert p.gap_ref == "query:best crm::branch:web_search" and p.category == "content"
    assert p.title == "Build the page that answers “best crm”"
    assert "Google's AI Overview answers it without citing you." in p.action_text
    assert any("crm pricing 2026" in s for s in p.steps)
    assert any(s.startswith("For Google's AI answer") for s in p.steps)
    assert {"kind": "Sub-question", "label": "crm pricing 2026",
            "note": "you're absent from its results"} in p.targets
    # Its sub-questions ride on the page play, not on a second one.
    assert _subquery_plays(db_session, t.id, covered=frozenset({"best crm"})) == []
    assert len(_subquery_plays(db_session, t.id)) == 1


def test_a_cited_page_of_your_own_makes_it_an_upgrade(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t.id)
    _gap_question(db_session, t, run, "best crm")
    plan = {"briefs": [{
        "query": "best crm", "query_id": 7, "competitors_winning": ["Globex"],
        "contestability": {"label": "winnable now"},
        "citability": {"ready": True, "winners": ["https://g2.com/categories/crm"],
                       "your_page": {"url": "https://acme.com/crm"},
                       "gaps": ["Winning pages state prices outright; yours doesn't."]}}]}
    [p] = _query_plays(db_session, t.id, plan)
    assert p.title == "Upgrade acme.com/crm to win “best crm”"
    assert p.link == "/dashboard/action-plan#brief-7"
    assert "Winning pages state prices outright; yours doesn't." in p.steps
    assert p.targets[0] == {"kind": "Your page", "label": "acme.com/crm",
                            "url": "https://acme.com/crm",
                            "note": "already cited for this question"}
    # A settled answer is harder to enter than one still being decided.
    plan["briefs"][0]["contestability"] = {"label": "locked in"}
    [locked] = _query_plays(db_session, t.id, plan)
    assert locked.impact["score"] < p.impact["score"]


def test_memory_questions_are_one_long_term_play(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t.id)
    for text in ("what is a crm", "who invented the crm"):
        db_session.add(Query(tenant_id=t.id, text=text))
        db_session.add(QueryClassification(tenant_id=t.id, query_text=text,
                                           surface=SurfaceCode.openai_api,
                                           web_search_likelihood="unlikely"))
        for surface in (CHATGPT, PERPLEXITY, CLAUDE):
            _answer(db_session, t, run, text, surface, rivals=["Globex"])
    db_session.commit()
    [p] = _query_plays(db_session, t.id, {})
    assert p.gap_ref == "training:memory" and p.category == "third_party"
    assert (p.control, p.speed) == ("earn", "model")
    assert [x["label"] for x in p.targets] == ["what is a crm", "who invented the crm"]


# ------------------------------------------------------ the whole list ----

def test_generated_rows_carry_area_rank_and_band(db_session):
    t = _tenant(db_session)
    run = _run(db_session, t.id)
    _gap_question(db_session, t, run, "best crm")
    # The second question is partly won (ChatGPT names the brand): still a
    # gap on three engines of four, but the biggest audience is already in.
    _gap_question(db_session, t, run, "crm for startups", named_on=(CHATGPT,))
    generate_recommendations(db_session, t)
    rows = db_session.exec(
        select(Recommendation).where(Recommendation.category == "content")
        .order_by(col(Recommendation.priority).desc())).all()
    assert [r.query_text for r in rows] == ["best crm", "crm for startups"]
    top, second = rows
    assert top.impact["band"] == "high" and top.impact["score"] > second.impact["score"]
    assert (top.control, top.effort, top.speed) == ("own", "days", "weeks")
    assert top.impact["basis"].startswith("Touches ")
    setup = db_session.exec(
        select(Recommendation).where(Recommendation.gap_ref == "connect_logs")).one()
    assert setup.category == "setup" and setup.impact == {} and setup.priority < second.priority

    # A play a person dismissed stops taking a share of the bands.
    top.status = RecommendationStatus.dismissed
    db_session.add(top)
    db_session.commit()
    generate_recommendations(db_session, t)
    db_session.expire_all()
    second = db_session.exec(select(Recommendation).where(
        Recommendation.query_text == "crm for startups")).one()
    assert second.impact["band"] == "high"
