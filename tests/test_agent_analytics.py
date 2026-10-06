"""Agent Analytics: parse real-world log formats, keep only AI bots, verify
by IP, aggregate, and join crawl data to citations."""

import gzip
import json
from datetime import timedelta

import pytest
from sqlmodel import select

from api.agent_analytics import agent_analytics, ingest_lines
from api.models import (
    AgentTrafficDaily,
    BrandProfile,
    Citation,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunMode,
    SurfaceCode,
    Tenant,
    utcnow,
)
from engine.agents.bots import classify_user_agent
from engine.agents.logparse import LogParser
from engine.agents.verify import ip_in, parse_ranges

TODAY = utcnow().strftime("%d/%b/%Y:%H:%M:%S +0000")
UA_GPT = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.2; +https://openai.com/gptbot"
UA_USER = "Mozilla/5.0 AppleWebKit/537.36; compatible; ChatGPT-User/1.0; +https://openai.com/bot"
UA_SEARCH = "Mozilla/5.0; compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot"
UA_HUMAN = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/605.1.15"


def combined(ip, path, status, ua):
    return f'{ip} - - [{TODAY}] "GET {path} HTTP/1.1" {status} 1234 "-" "{ua}"'


def test_robots_tokens_in_a_user_agent_are_spoofs():
    assert classify_user_agent("Mozilla/5.0 (compatible; Google-Extended)") is None
    assert classify_user_agent("Applebot-Extended/1.0") is None
    assert classify_user_agent("Mozilla/5.0 (compatible; Google-Agent)").purpose == "agent"


def test_classifier_picks_the_specific_bot():
    assert classify_user_agent(UA_SEARCH).name == "OAI-SearchBot"
    assert classify_user_agent(UA_USER).purpose == "user"
    assert classify_user_agent("Mozilla/5.0 ... Claude-SearchBot/1.0").purpose == "search"
    assert classify_user_agent("meta-externalagent/1.1").company == "Meta"
    assert classify_user_agent(UA_HUMAN) is None


def test_parser_handles_combined_cloudflare_vercel_and_cloudfront():
    p = LogParser()
    hit = p.parse(combined("20.1.2.3", "/pricing?utm=x", 200, UA_GPT))
    assert hit and hit.path == "/pricing" and hit.status == 200 and "GPTBot" in hit.user_agent
    cf = json.dumps({"ClientIP": "1.1.1.1", "ClientRequestPath": "/a",
                     "EdgeResponseStatus": 404, "ClientRequestUserAgent": UA_SEARCH,
                     "EdgeStartTimestamp": 1790900000000000000})
    hit = p.parse(cf)
    assert hit and hit.status == 404 and hit.ts.year == 2026
    vercel = json.dumps({"timestamp": 1790900000000, "proxy": {
        "path": "/b", "statusCode": 200, "userAgent": [UA_USER], "clientIp": "2.2.2.2"}})
    assert p.parse(vercel).path == "/b"
    p2 = LogParser()
    assert p2.parse("#Version: 1.0") is None
    p2.parse("#Fields: date time c-ip cs-method cs-uri-stem sc-status cs(User-Agent)")
    hit = p2.parse("2026-10-01\t12:00:00\t3.3.3.3\tGET\t/c\t200\tGPTBot/1.2")
    assert hit and hit.path == "/c" and hit.ip == "3.3.3.3"
    assert p.parse("garbage line") is None


def test_parser_handles_azure_front_door_json_and_log_analytics_csv():
    afd = json.dumps({
        "time": "2026-10-05T14:02:11.0000000Z", "category": "FrontDoorAccessLog",
        "operationName": "Microsoft.Cdn/Profiles/AccessLog/Write",
        "properties": {"trackingReference": "x", "httpMethod": "GET", "httpVersion": "2.0",
                       "requestUri": "https://www.example.com:443/pricing?ref=1",
                       "userAgent": UA_GPT, "clientIp": "20.1.2.3", "clientPort": "443",
                       "httpStatusCode": "403", "cacheStatus": "MISS"}})
    hit = LogParser().parse(afd)
    assert hit and hit.path == "/pricing" and hit.status == 403 and hit.ip == "20.1.2.3"
    assert hit.ts.day == 5 and "GPTBot" in hit.user_agent

    p = LogParser()
    assert p.parse('TimeGenerated [UTC],Category,httpMethod_s,requestUri_s,'
                   'httpStatusCode_s,clientIp_s,userAgent_s') is None
    hit = p.parse(f'"10/5/2026, 9:15:02.123 PM",FrontDoorAccessLog,GET,'
                  f'https://www.example.com/help/plans,200,4.4.4.4,"{UA_SEARCH}, extra"')
    assert hit and hit.path == "/help/plans" and hit.status == 200 and hit.ts.hour == 21
    assert hit.user_agent.endswith(", extra")  # quoted commas stay inside the field
    # A numeric status column from Log Analytics ("200.0") still reads as 200.
    p.parse("TimeGenerated,requestUri_s,httpStatusCode_d,userAgent_s")
    assert p.parse(f"2026-10-05T10:00:00Z,/a,404.0,{UA_GPT}").status == 404
    # A CSV row before any header is ignored, never misread.
    assert LogParser().parse(f"2026-10-05T10:00:00Z,/a,404,{UA_GPT}") is None


def test_ip_verification():
    nets = parse_ranges({"prefixes": [{"ipv4Prefix": "20.0.0.0/8"},
                                      {"ipv6Prefix": "2001:db8::/32"}]})
    assert ip_in("20.1.2.3", nets) and ip_in("2001:db8::1", nets)
    assert not ip_in("9.9.9.9", nets) and not ip_in("not-an-ip", nets)


def _tenant(db):
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.commit()
    return t


def test_ingest_keeps_only_ai_bots_and_verifies(db_session):
    t = _tenant(db_session)
    lines = [
        combined("20.1.2.3", "/pricing", 200, UA_GPT),     # verified (in range)
        combined("9.9.9.9", "/pricing", 200, UA_GPT),      # spoofed UA
        combined("8.8.8.8", "/pricing", 200, UA_HUMAN),    # human: dropped
        combined("20.1.2.4", "/docs", 404, UA_USER),
    ]
    ranges = lambda url: parse_ranges({"prefixes": [{"ipv4Prefix": "20.0.0.0/8"}]})  # noqa: E731
    out = ingest_lines(db_session, t.id, lines, ranges=ranges)
    db_session.commit()
    assert out["lines"] == 4 and out["ai_hits"] == 3
    rows = db_session.exec(select(AgentTrafficDaily)).all()
    gpt = next(r for r in rows if r.bot == "GPTBot")
    assert gpt.hits == 2 and gpt.verified == 1
    assert all("8.8.8.8" not in str(r) for r in rows)  # no human data stored
    # Re-ingesting the same day adds, it doesn't duplicate rows.
    ingest_lines(db_session, t.id, lines[:1], ranges=ranges)
    db_session.commit()
    gpt = db_session.exec(select(AgentTrafficDaily).where(AgentTrafficDaily.bot == "GPTBot")).one()
    assert gpt.hits == 3


def test_summarized_csv_counts_every_request(db_session):
    """A huge log (tens of GB) is summarized in Log Analytics first: one row
    per day/IP/bot/page/status with a hits column."""
    t = _tenant(db_session)
    lines = [
        "day,clientIp_s,userAgent_s,requestUri_s,httpStatusCode_s,hits",
        f'2026-10-01,20.1.2.3,"{UA_GPT}",https://www.example.com/pricing,200,250',
        f'2026-10-01,9.9.9.9,"{UA_GPT}",https://www.example.com/pricing,200,50',
        f'2026-10-01,8.8.8.8,"{UA_HUMAN}",https://www.example.com/pricing,200,9000',
        f'2026-10-01,20.1.2.3,"{UA_GPT}",https://www.example.com/x,200,-4',  # junk count
    ]
    ranges = lambda url: parse_ranges({"prefixes": [{"ipv4Prefix": "20.0.0.0/8"}]})  # noqa: E731
    out = ingest_lines(db_session, t.id, lines, ranges=ranges)
    db_session.commit()
    assert out["ai_hits"] == 300
    gpt = db_session.exec(select(AgentTrafficDaily).where(AgentTrafficDaily.bot == "GPTBot")).one()
    assert gpt.hits == 300 and gpt.verified == 250 and gpt.date == "2026-10-01"


def test_report_joins_crawls_to_citations(db_session):
    t = _tenant(db_session)
    lines = (
        [combined("1.1.1.1", "/guide", 200, UA_SEARCH)] * 5      # read, never cited
        + [combined("1.1.1.1", "/pricing", 500, UA_USER)] * 2    # cited but erroring
        + [combined("1.1.1.1", "/old", 200, UA_GPT)]
        + [combined("1.1.1.1", "/dead", 404, UA_SEARCH)] * 3    # broken, not "losing"
    )
    ingest_lines(db_session, t.id, lines, verify=False)
    run = Run(tenant_id=t.id)
    db_session.add(run)
    db_session.commit()
    r = Result(run_id=run.id, tenant_id=t.id, query_text="q", persona_name="p",
               persona_segment="all", surface=SurfaceCode.openai_api, mode=RunMode.A,
               variant=ResultVariant.search, status=ResultStatus.ok,
               created_at=utcnow() - timedelta(days=1))
    db_session.add(r)
    db_session.commit()
    for url in ("https://www.acme.com/pricing", "https://acme.com/about", "https://rival.com/x"):
        db_session.add(Citation(result_id=r.id, tenant_id=t.id, url=url,
                                domain=url.split("/")[2].removeprefix("www.")))
    # Gemini grounding redirect labelled with the brand's domain: not a brand page.
    db_session.add(Citation(
        result_id=r.id, tenant_id=t.id, domain="acme.com",
        url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/AbC"))
    db_session.commit()

    rep = agent_analytics(db_session, t.id)
    assert rep["has_data"] and rep["total_hits"] == 11
    assert rep["by_purpose"]["search"] == 8 and rep["by_purpose"]["user"] == 2
    assert [p["path"] for p in rep["read_not_cited"]] == ["/guide"]
    risk = {x["path"]: x["reason"] for x in rep["cited_at_risk"]}
    assert "error" in risk["/pricing"] and "not fetched" in risk["/about"]
    assert not any("grounding" in path for path in risk)
    assert {p["path"] for p in rep["broken_pages"]} == {"/dead", "/pricing"}
    assert rep["user_fetch_pages"][0]["path"] == "/pricing"


def test_upload_and_push_endpoints(client, login, db_session):
    from api.models import User

    t = Tenant(name="Acme", slug="acme", clerk_org_id="org_a")
    u = User(email="m@x.test", clerk_user_id="u_m")
    admin = User(email="a@x.test", clerk_user_id="u_a", is_superadmin=True)
    db_session.add_all([t, u, admin])
    db_session.commit()
    login(u, org_id="org_a", org_role="org:admin")
    body = gzip.compress("\n".join([combined("1.1.1.1", "/a", 200, UA_SEARCH)] * 3).encode())
    res = client.post("/api/tenant/agent-logs", content=body,
                      headers={"Content-Type": "application/octet-stream"})
    assert res.status_code == 200 and res.json()["ai_hits"] == 3
    assert client.get("/api/tenant/agent-analytics").json()["total_hits"] == 3

    assert client.post("/api/ingest/agent-logs", content=b"x",
                       headers={"Authorization": "Bearer nope"}).status_code == 401
    login(admin)
    tok = client.post("/api/admin/tenants/acme/agent-log-token").json()["token"]
    assert "agent_log_token" not in client.get("/api/admin/tenants/acme").json()["tenant"]
    res = client.post("/api/ingest/agent-logs",
                      content=combined("1.1.1.1", "/b", 200, UA_USER).encode(),
                      headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200 and res.json()["ai_hits"] == 1


@pytest.mark.parametrize("ua,purpose", [(UA_GPT, "training"), (UA_SEARCH, "search")])
def test_purposes(ua, purpose):
    assert classify_user_agent(ua).purpose == purpose
