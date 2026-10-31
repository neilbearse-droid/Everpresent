"""AI-crawler access audit: pure robots evaluation + grading. No network —
the fetch layer is thin and exercised in production only."""

from engine.audit.access import UA_PROBES, entity_signals, evaluate_robots, summarize, ua_verdicts

BLOCKING_ROBOTS = """
User-agent: GPTBot
Disallow: /

User-agent: PerplexityBot
Disallow: /

User-agent: *
Allow: /
"""


def _by_agent(agents):
    return {a["agent"]: a for a in agents}


def _probes(**refused):
    """UA A/B results: the browser got a 200; the named bots got the given
    status (None = no response), every other probe a 200."""
    statuses = {agent: 200 for agent, _ua, _kind in UA_PROBES}
    statuses.update(refused)
    return ua_verdicts(200, statuses)


def test_evaluate_robots_flags_blocked_agents():
    agents = _by_agent(evaluate_robots(BLOCKING_ROBOTS))
    assert agents["GPTBot"]["allowed"] is False and agents["GPTBot"]["mentioned"] is True
    assert agents["PerplexityBot"]["allowed"] is False
    # Unmentioned agents fall through to the * group (allowed).
    assert agents["ClaudeBot"]["allowed"] is True and agents["ClaudeBot"]["mentioned"] is False
    assert agents["Bingbot"]["allowed"] is True


def test_googlebot_and_meta_fetcher_rows_are_graded():
    # A Googlebot block is the one Google block that matters (AI Overviews and
    # AI Mode ride on the Search index); Google-Extended is training only.
    agents = _by_agent(evaluate_robots("User-agent: Googlebot\nDisallow: /\n"))
    assert agents["Googlebot"]["kind"] == "search_index" and agents["Googlebot"]["allowed"] is False
    assert agents["Google-Extended"]["allowed"] is True
    grade, issues = summarize(list(agents.values()), ua_probes=_probes(), has_llms_txt=True,
                              has_json_ld=True, robots_status=200)
    assert grade == "fail" and any("Googlebot" in i for i in issues)
    # Meta-ExternalFetcher (live fetch) is distinct from Meta-ExternalAgent (training).
    agents = _by_agent(evaluate_robots("User-agent: Meta-ExternalAgent\nDisallow: /\n"))
    assert agents["Meta-ExternalFetcher"]["kind"] == "user_fetch"
    assert agents["Meta-ExternalFetcher"]["allowed"] is True
    assert agents["Meta-ExternalAgent"]["allowed"] is False
    assert agents["meta-webindexer"]["kind"] == "search_index"


def test_empty_robots_allows_everyone():
    agents = evaluate_robots("")
    assert all(a["allowed"] for a in agents)


def test_grade_fails_on_retrieval_block_or_cdn_challenge():
    agents = evaluate_robots(BLOCKING_ROBOTS)
    # PerplexityBot is a retrieval agent -> fail, with an explanatory issue.
    grade, issues = summarize(agents, ua_probes=_probes(), has_llms_txt=True,
                              has_json_ld=True, robots_status=200)
    assert grade == "fail"
    assert any("PerplexityBot" in i for i in issues)

    # Clean robots but the CDN refuses a SEARCH crawler's UA -> still fail,
    # and the issue names the bot, its status and the usual cause.
    clean = evaluate_robots("")
    grade, issues = summarize(clean, ua_probes=_probes(**{"OAI-SearchBot": 403}),
                              has_llms_txt=True, has_json_ld=True, robots_status=200)
    assert grade == "fail"
    [issue] = [i for i in issues if "by user agent" in i]
    assert "OAI-SearchBot (403)" in issue and "WAF rule" in issue
    assert "GPTBot" not in issue


def test_ua_verdicts_are_per_bot():
    probes = {p["agent"]: p for p in _probes(bingbot=None, GPTBot=403)}
    assert probes["bingbot"]["blocked"] is True and probes["bingbot"]["status"] is None
    assert probes["GPTBot"]["blocked"] is True and probes["GPTBot"]["kind"] == "training"
    assert probes["OAI-SearchBot"]["blocked"] is False
    # No browser 200 to compare against: nothing can be called blocked.
    assert not any(p["blocked"] for p in ua_verdicts(503, {a: 403 for a, _u, _k in UA_PROBES}))
    # Several search bots refused: all named, "no response" spelled out.
    _grade, issues = summarize(evaluate_robots(""), ua_probes=_probes(bingbot=None,
                                                                     PerplexityBot=429),
                               has_llms_txt=True, has_json_ld=True, robots_status=200)
    [issue] = [i for i in issues if "by user agent" in i]
    assert "PerplexityBot (429)" in issue and "bingbot (no response)" in issue


def test_gptbot_only_refusal_is_a_training_warn():
    # Cloudflare's September 2026 default: training crawlers refused, search
    # crawlers allowed. A GPTBot 403 next to a browser 200 says nothing about
    # live answers, so it is a warn worded as training-only, never a fail.
    grade, issues = summarize(evaluate_robots(""), ua_probes=_probes(GPTBot=403),
                              has_llms_txt=True, has_json_ld=True, robots_status=200)
    assert grade == "warn"
    [issue] = issues
    assert "GPTBot (403)" in issue and "training-only" in issue
    assert "can't read the site" not in issue
    # When a search bot is refused too, the search issue carries the fail and
    # the training note is not repeated.
    grade, issues = summarize(evaluate_robots(""),
                              ua_probes=_probes(GPTBot=403, **{"Claude-SearchBot": 403}),
                              has_llms_txt=True, has_json_ld=True, robots_status=200)
    assert grade == "fail" and len(issues) == 1 and "Claude-SearchBot (403)" in issues[0]


def test_grade_warns_on_training_blocks_only():
    training_only = evaluate_robots("User-agent: GPTBot\nDisallow: /\n")
    grade, issues = summarize(training_only, ua_probes=_probes(), has_llms_txt=True,
                              has_json_ld=True, robots_status=200)
    assert grade == "warn"
    assert any("GPTBot" in i and "training" in i for i in issues)


def test_missing_json_ld_is_advisory_only():
    # Ahrefs' May 2026 quasi-experiment found no citation effect from schema,
    # so a missing JSON-LD block is noted but never lowers the grade.
    clean = evaluate_robots("")
    grade, issues = summarize(clean, ua_probes=_probes(), has_llms_txt=False,
                              has_json_ld=False, robots_status=200)
    assert grade == "pass"
    # llms.txt is unproven (zero observed crawler consumption) — its absence is
    # NOT a graded defect anymore (§AEO-plan m1).
    assert not any("llms.txt" in i for i in issues)
    [issue] = [i for i in issues if "JSON-LD" in i]
    assert "found no effect on AI citations" in issue
    assert "lean on schema" not in issue


def test_missing_llms_txt_alone_does_not_lower_grade():
    # Everything open + JSON-LD present, only llms.txt missing → still pass.
    grade, issues = summarize(evaluate_robots(""), ua_probes=_probes(), has_llms_txt=False,
                              has_json_ld=True, robots_status=200)
    assert grade == "pass" and issues == []


def test_grade_fails_on_csr_shell():
    # A JS-only homepage is as invisible as a hard block (§AEO-plan M3).
    grade, issues = summarize(evaluate_robots(""), ua_probes=_probes(), has_llms_txt=True,
                              has_json_ld=True, robots_status=200,
                              render_verdict="fail", render_reason="JS-only shell.")
    assert grade == "fail"
    assert any("JS-only shell." in i for i in issues)


def test_grade_passes_when_everything_is_open_and_present():
    grade, issues = summarize(evaluate_robots(""), ua_probes=_probes(), has_llms_txt=True,
                              has_json_ld=True, robots_status=200)
    assert grade == "pass" and issues == []


def test_entity_signals_detection():
    rich = (
        '<script type="application/ld+json">{"@type":"Organization",'
        '"sameAs":["https://en.wikipedia.org/wiki/Smith","https://www.wikidata.org/wiki/Q1"]}'
        "</script>"
    )
    e = entity_signals(rich)
    assert e["has_sameas"] and e["has_org_schema"]
    assert e["links_wikipedia"] and e["links_wikidata"]

    bare = entity_signals("<html><body>Welcome</body></html>")
    assert not any(bare.values())


def test_missing_entity_signals_is_advisory_only():
    # No entity signals → an advisory issue, but not a graded failure.
    grade, issues = summarize(evaluate_robots(""), ua_probes=_probes(), has_llms_txt=True,
                              has_json_ld=True, robots_status=200,
                              entity={"has_sameas": False, "links_wikipedia": False})
    assert grade == "pass"
    assert any("entity-authority" in i for i in issues)
