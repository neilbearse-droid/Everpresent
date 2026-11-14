"""Week-one tactics fixes from the October 2026 best-practice sweep: the
access audit grades per bot, the orphaned controlled-study WHY is wired in,
play priorities follow the access → facts → earned → formatting order, and the
dated or over-stated copy strings are gone. Pure functions where possible;
the play sources that need data get a monkeypatched analytics dict."""

from api.dashboards.action_plan import _brief_outline, _citability_diff, _spam_risk
from api.models import (
    BrandProfile,
    FanoutShard,
    PagePresence,
    Query,
    QueryClassification,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)
from api.recommendations_service import (
    _KEY_BOTS,
    _RECRAWL,
    WHY,
    WHY_SUBQUERY_FACTS,
    _agent_plays,
    _KeepExisting,
    _query_plays,
    _strategy_play,
    _subquery_plays,
)
from engine.audit.access import UA_PROBES, evaluate_robots, summarize, ua_verdicts
from engine.content.draft import DRAFT_SYSTEM


def _tenant(db) -> int:
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    assert t.id is not None
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.commit()
    return t.id


# ---------------------------------------------------------------- access audit (B4, B5, row 21)


def test_access_audit_probes_the_search_crawlers_and_keeps_gptbot_as_training():
    kinds = {agent: kind for agent, _ua, kind in UA_PROBES}
    assert {a for a, k in kinds.items() if k == "search_index"} == {
        "OAI-SearchBot", "PerplexityBot", "Claude-SearchBot", "bingbot"}
    assert kinds["GPTBot"] == "training"
    # One homepage fetch per probe keeps the request budget small.
    assert len(UA_PROBES) == 5


def test_search_refusal_fails_and_training_refusal_warns():
    ok = {agent: 200 for agent, _ua, _kind in UA_PROBES}
    agents = evaluate_robots("")
    # Browser 200, GPTBot 403, every search bot 200: the post-September-2026
    # Cloudflare default. A warn, worded as training-only.
    grade, issues = summarize(agents, ua_probes=ua_verdicts(200, {**ok, "GPTBot": 403}),
                              has_llms_txt=True, has_json_ld=True, robots_status=200)
    assert grade == "warn" and "training-only" in issues[0]
    # One search bot refused: fail, and the issue says what the cause usually is.
    grade, issues = summarize(agents, ua_probes=ua_verdicts(200, {**ok, "bingbot": 403}),
                              has_llms_txt=True, has_json_ld=True, robots_status=200)
    assert grade == "fail"
    assert "bingbot (403)" in issues[0] and "September 2026 defaults allow search" in issues[0]


def test_disallow_googlebot_is_a_live_block():
    agents = evaluate_robots("User-agent: Googlebot\nDisallow: /\n")
    grade, issues = summarize(agents, has_llms_txt=True, has_json_ld=True, robots_status=200)
    assert grade == "fail" and any("AI Overviews" in i for i in issues)


def test_json_ld_absence_never_moves_the_grade():
    grade, issues = summarize(evaluate_robots(""), has_llms_txt=True, has_json_ld=False,
                              robots_status=200)
    assert grade == "pass"
    assert issues == ["No JSON-LD on the homepage. It may help Google identify the brand as "
                      "an entity; studies in 2026 found no effect on AI citations."]


# ---------------------------------------------------------------- WHY wiring (B6), grades (row 38)


def test_sub_search_plays_cite_the_controlled_study(db_session):
    assert "2605.25517" in WHY["facts"] and "2605.25517" not in WHY["subquery"]
    assert "correlational" in WHY["subquery"]
    assert WHY_SUBQUERY_FACTS.startswith(WHY["subquery"]) and WHY["facts"] in WHY_SUBQUERY_FACTS

    tid = _tenant(db_session)
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    db_session.add(FanoutShard(tenant_id=tid, run_id=run.id, parent_query_text="best crm",
                               shard_text="crm pricing 2026", shard_norm="crm pricing 2026",
                               reach=2, brand_present=False, winners=["Globex"],
                               source="reprobed"))
    db_session.commit()
    [p] = _subquery_plays(db_session, tid)
    assert p.evidence == "strong" and p.why == WHY_SUBQUERY_FACTS


def test_aio_play_ranks_with_the_access_gate_and_web_search_cites_facts(db_session):
    tid = _tenant(db_session)
    db_session.add(Query(tenant_id=tid, text="best crm"))
    db_session.add(QueryClassification(
        tenant_id=tid, query_text="best crm", surface=SurfaceCode.google_aio,
        web_search_likelihood="", google_aio_source_type="aio_dominant",
        google_aio_signals={"cited_domains": ["g2.com"]}))
    db_session.commit()
    [aio] = _query_plays(db_session, tid, {})
    assert aio.branch == "aio" and aio.evidence == "official"
    # A page job on the brand's own site; with no measured Google answer its
    # rank stands on the Overview's audience share, and says so.
    assert aio.category == "content" and aio.control == "own"
    assert not aio.impact["measured"] and "cites none of your pages" in aio.impact["basis"]
    # The web_search play carries the controlled study alongside the
    # sub-search mechanism.
    assert WHY_SUBQUERY_FACTS.endswith(WHY["facts"])


def _analytics(**overrides):
    base = {"has_data": True, "days": 30, "total_hits": 500, "by_bot": [],
            "cited_at_risk": [], "broken_pages": [], "read_not_cited": []}
    base.update(overrides)
    return base


def test_agent_play_priorities_and_grades(db_session, monkeypatch):
    import api.agent_analytics as aa

    tid = _tenant(db_session)
    # No logs at all: the gate every access play depends on, product rationale.
    monkeypatch.setattr(aa, "agent_analytics",
                        lambda *_a, **_k: {"has_data": False, "days": 30, "stale": False})
    [gate] = _agent_plays(db_session, tid)
    assert gate.gap_ref == "connect_logs" and gate.evidence == "moderate"
    # Setup: it changes what can be measured, so it carries no projected impact.
    assert gate.category == "setup" and not gate.impact
    # Stale logs: same grade, and the existing bot plays are kept.
    monkeypatch.setattr(aa, "agent_analytics",
                        lambda *_a, **_k: {"has_data": False, "days": 30, "stale": True})
    try:
        _agent_plays(db_session, tid)
    except _KeepExisting as keep:
        [stale] = keep.plays
        assert stale.category == "setup" and stale.evidence == "moderate"
    else:
        raise AssertionError("stale logs must freeze the existing plays")

    # Enough hits, one search bot present: every other key bot is absent (a
    # structure fix in the brand's control, official evidence), a
    # read-but-never-cited page is a content fix, and the broken-page plays
    # carry product rationale (moderate) and rank under a blocked crawler.
    monkeypatch.setattr(aa, "agent_analytics", lambda *_a, **_k: _analytics(
        by_bot=[{"bot": "OAI-SearchBot", "hits": 500, "blocked": 0}],
        read_not_cited=[{"path": "/pricing", "search": 40, "user": 2}],
        broken_pages=[{"path": "/old", "errors": 30}],
        cited_at_risk=[{"path": "/guide", "cited": 3, "reason": "HTTP 500 errors"}]))
    by_ref = {p.gap_ref: p for p in _agent_plays(db_session, tid)}
    absent = [p for r, p in by_ref.items() if r.endswith(":absent")]
    assert {p.gap_ref.split(":")[1] for p in absent} == set(_KEY_BOTS) - {"OAI-SearchBot"}
    assert all(p.category == "structure" and p.control == "own" and p.evidence == "official"
               for p in absent)
    assert any("September 2026 defaults allow search crawlers" in s for s in absent[0].steps)
    assert not any("AI-bot blocking" in s for s in absent[0].steps)
    assert by_ref["read_not_cited"].category == "content"
    assert "fetched these pages 42 times" in by_ref["read_not_cited"].impact["basis"]
    assert by_ref["broken_pages"].evidence == "moderate"
    assert all(p.priority > by_ref["broken_pages"].priority for p in absent)
    assert by_ref["at_risk:/guide"].evidence == "moderate"
    # Row 19: Bingbot's engine string in the official play no longer states
    # ChatGPT's use of Bing's index as fact.
    assert _KEY_BOTS["Bingbot"] == "Copilot (official) and, by most accounts, ChatGPT search"
    assert "by most accounts, ChatGPT search" in by_ref["crawler:Bingbot:absent"].action_text


def test_strategy_steps_run_access_then_own_pages_then_third_parties(db_session, monkeypatch):
    import api.dashboards_service as ds

    monkeypatch.setattr(ds, "mention_rates",
                        lambda *_a, **_k: {"overall": {"answers": 40, "rate": 12.5}})
    [play] = _strategy_play(db_session, 1)
    assert play.title == "Focus: get found at all"
    first, second, third = play.steps
    assert "AI search bot can reach" in first
    assert "sub-questions" in second and "own pages" in second and "prices" in second
    assert third.startswith("Then get onto the third-party")


# ---------------------------------------------------------------- action plan copy (gap 17)


def test_word_count_gap_fires_only_under_the_floor():
    win = {"word_count": 2000, "statistic_count": 0}
    winners = [PagePresence(tenant_id=1, url=f"https://w{i}.example", features=dict(win))
               for i in range(2)]
    long_enough = PagePresence(tenant_id=1, url="https://acme.com/a",
                               features={"word_count": 400})
    gaps = _citability_diff(winners, long_enough)["gaps"]
    assert not any("words" in g for g in gaps)
    short = PagePresence(tenant_id=1, url="https://acme.com/b", features={"word_count": 120})
    [gap] = [g for g in _citability_diff(winners, short)["gaps"] if "words" in g]
    assert gap.startswith("This page is under 250 words") and gap.endswith("Cover them, don't pad")


def test_answer_capsule_gap_is_labelled_practitioner_evidence():
    win = {"has_answer_capsule": True, "word_count": 800}
    winners = [PagePresence(tenant_id=1, url=f"https://w{i}.example", features=dict(win))
               for i in range(2)]
    mine = PagePresence(tenant_id=1, url="https://acme.com/p",
                        features={"has_answer_capsule": False, "word_count": 800})
    [gap] = [g for g in _citability_diff(winners, mine)["gaps"] if "answer capsule" in g]
    assert "under the first heading" in gap and "Practitioner evidence" in gap
    assert "question heading" not in gap


def test_spam_risk_is_for_self_ranked_lists_not_comparisons():
    for q in ("best crm 2026", "top 10 crms for startups", "cheapest domain registrar",
              "HubSpot alternatives", "5 best website builders"):
        assert _spam_risk(q) is not None, q
    for q in ("HubSpot vs Salesforce", "compare HubSpot and Salesforce",
              "HubSpot versus Salesforce comparison", "which is better, Wix or Squarespace?"):
        assert _spam_risk(q) is None, q
    risk = _spam_risk("best crm")
    assert risk is not None
    note = risk["note"]
    assert "May 15, 2026" in note and "June and August 2026 spam updates" in note
    assert "self-ranked 'best of' lists" in note and "scaled 'alternatives' pages" in note
    assert "September 2026 spam" not in note


def test_recrawl_copy_does_not_state_chatgpt_uses_bing_as_fact():
    assert "by most accounts, ChatGPT search" in _RECRAWL
    # Claude's search runs on Brave, which takes URL submissions (M67).
    assert "ChatGPT and Perplexity have no recrawl request" in _RECRAWL
    assert "Brave's submit-a-URL form" in _RECRAWL
    assert "which feeds Copilot and ChatGPT)" not in _RECRAWL
    outline = _brief_outline("best crm", "Acme", ["Globex"], ["crm pricing"])
    assert "Bing/Copilot/ChatGPT" not in outline[-1]
    assert "by most accounts, ChatGPT search" in outline[-1]
    assert "no recrawl request" in outline[-1]
    # The brief still prescribes the comparison table the spam filter must not punish.
    assert any("Honest comparison table" in line for line in outline)


# ---------------------------------------------------------------- dated copy (rows 9, 16)


def test_muse_markets_are_dated():
    assert "US since Sept 8, 2026, Singapore since Oct 28" in WHY["muse"]
    assert "not in Canada as of Oct 31, 2026" in WHY["muse"]
    assert "US and Canada" not in WHY["muse"]


def test_drafter_writes_for_a_reader_and_dates_the_spam_policy():
    assert "write for a reader who wants the facts" in DRAFT_SYSTEM
    assert "designed to be cited" not in DRAFT_SYSTEM
    assert "May 15, 2026" in DRAFT_SYSTEM and "June and August 2026 spam updates" in DRAFT_SYSTEM
    assert "2026 spam policy targets both" not in DRAFT_SYSTEM
