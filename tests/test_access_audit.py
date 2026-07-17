"""AI-crawler access audit: pure robots evaluation + grading. No network —
the fetch layer is thin and exercised in production only."""

from engine.audit.access import evaluate_robots, summarize

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


def test_evaluate_robots_flags_blocked_agents():
    agents = _by_agent(evaluate_robots(BLOCKING_ROBOTS))
    assert agents["GPTBot"]["allowed"] is False and agents["GPTBot"]["mentioned"] is True
    assert agents["PerplexityBot"]["allowed"] is False
    # Unmentioned agents fall through to the * group (allowed).
    assert agents["ClaudeBot"]["allowed"] is True and agents["ClaudeBot"]["mentioned"] is False
    assert agents["Bingbot"]["allowed"] is True


def test_empty_robots_allows_everyone():
    agents = evaluate_robots("")
    assert all(a["allowed"] for a in agents)


def test_grade_fails_on_retrieval_block_or_cdn_challenge():
    agents = evaluate_robots(BLOCKING_ROBOTS)
    # PerplexityBot is a retrieval agent -> fail, with an explanatory issue.
    grade, issues = summarize(agents, ua_blocked=False, has_llms_txt=True,
                              has_json_ld=True, robots_status=200)
    assert grade == "fail"
    assert any("PerplexityBot" in i for i in issues)

    # Clean robots but the CDN rejects the bot UA -> still fail.
    clean = evaluate_robots("")
    grade, issues = summarize(clean, ua_blocked=True, has_llms_txt=True,
                              has_json_ld=True, robots_status=200)
    assert grade == "fail"
    assert any("bot protection" in i for i in issues)


def test_grade_warns_on_training_blocks_and_missing_best_practices():
    training_only = evaluate_robots("User-agent: GPTBot\nDisallow: /\n")
    grade, issues = summarize(training_only, ua_blocked=False, has_llms_txt=True,
                              has_json_ld=True, robots_status=200)
    assert grade == "warn"
    assert any("GPTBot" in i and "training" in i for i in issues)

    clean = evaluate_robots("")
    grade, issues = summarize(clean, ua_blocked=False, has_llms_txt=False,
                              has_json_ld=False, robots_status=200)
    assert grade == "warn"
    assert any("llms.txt" in i for i in issues)
    assert any("JSON-LD" in i for i in issues)


def test_grade_passes_when_everything_is_open_and_present():
    grade, issues = summarize(evaluate_robots(""), ua_blocked=False, has_llms_txt=True,
                              has_json_ld=True, robots_status=200)
    assert grade == "pass" and issues == []
