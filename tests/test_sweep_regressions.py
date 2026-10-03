"""Regression tests for the October 2026 sweep: hostile log input, upload
streaming limits, token storage, report normalization, playbook stability
and crawler feature robustness. Each test names the failure it pins."""

import asyncio
import gzip
import hashlib
import time
from datetime import timedelta

from sqlmodel import select

import api.agent_analytics as aa
from api.agent_analytics import UploadError, agent_analytics, ingest_lines, ingest_stream
from api.models import (
    AccuracyFinding,
    AgentTrafficDaily,
    BrandProfile,
    Citation,
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
    utcnow,
)
from engine.agents.logparse import LogParser, _parse_ts
from engine.agents.verify import ip_in, parse_ranges

TS = utcnow().strftime("%d/%b/%Y:%H:%M:%S +0000")
GPT = "GPTBot/1.2"
SEARCH = "OAI-SearchBot/1.0"


def line(path: str, status: int = 200, ua: str = GPT) -> str:
    return f'1.1.1.1 - - [{TS}] "GET {path} HTTP/1.1" {status} 1 "-" "{ua}"'


def _tenant(db) -> Tenant:
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.commit()
    return t


def _stream(data: bytes, size: int = 65536):
    async def gen():
        for i in range(0, len(data), size):
            yield data[i:i + size]
    return gen()


def _ingest(db, tid, data: bytes, size: int = 65536) -> dict:
    out = asyncio.run(ingest_stream(db, tid, _stream(data, size)))
    db.commit()
    return out


# --- hostile log input ----------------------------------------------------

def test_nul_and_control_chars_never_reach_the_database(db_session):
    t = _tenant(db_session)
    ingest_lines(db_session, t.id, [line("/x%00y%0a%1bz")], verify=False)
    db_session.commit()
    [row] = db_session.exec(select(AgentTrafficDaily)).all()
    assert row.path == "/xyz"


def test_bad_timestamps_and_statuses_are_skipped_not_fatal():
    for v in (float("nan"), float("inf"), 1e30, True, -5, "abc"):
        assert _parse_ts(v) is None
    assert _parse_ts("1790900000000").year == 2026  # string epoch (ms)
    p = LogParser()
    hit = p.parse('{"ClientRequestUserAgent":"GPTBot","ClientRequestPath":"/a",'
                  '"EdgeStartTimestamp":1790900000,"EdgeResponseStatus":99999999999}')
    assert hit is not None and hit.status == 0
    assert p.parse('{"a":' * 5000 + "1" + "}" * 5000) is None  # no RecursionError
    assert p.parse("﻿" + line("/bom")) is not None


def test_json_array_body_yields_every_hit():
    body = ('[{"proxy":{"userAgent":"GPTBot","path":"/a","timestamp":1790900000000,'
            '"statusCode":200}},{"proxy":{"userAgent":"ClaudeBot","path":"/b",'
            '"timestamp":1790900000000,"statusCode":404}}]')
    hits = LogParser().parse_all(body)
    assert [h.path for h in hits] == ["/a", "/b"]


def test_malformed_long_request_line_is_fast():
    p = LogParser()
    hostile = '1.1.1.1 - - [03/Oct/2026:10:00:00 +0000] "GET /' + "a " * 8000
    start = time.time()
    for _ in range(20):
        p.parse(hostile)
    assert time.time() - start < 1.0


def test_ipv4_mapped_ipv6_is_verified():
    nets = parse_ranges({"prefixes": [{"ipv4Prefix": "66.249.0.0/16"}]})
    assert ip_in("::ffff:66.249.0.5", nets) and ip_in("[66.249.1.1]", nets)


def test_failed_range_fetch_is_retried_soon(monkeypatch):
    import engine.agents.verify as v

    v._cache.clear()
    calls = []

    def boom(url):
        calls.append(url)
        raise RuntimeError("down")

    assert v.ranges_for("https://x.test/r.json", boom) == []
    expires, _ = v._cache["https://x.test/r.json"]
    assert expires - time.time() <= v._FAIL_TTL_S + 1
    v._cache.clear()


# --- upload streaming ------------------------------------------------------

def test_no_newline_upload_is_linear_and_skipped(db_session):
    t = _tenant(db_session)
    start = time.time()
    out = _ingest(db_session, t.id, b"x" * (20 << 20) + b"\n" + line("/ok").encode())
    assert time.time() - start < 5
    assert out["ai_hits"] == 1 and out["unrecognized_lines"] >= 1


def test_gzip_edge_cases(db_session):
    t = _tenant(db_session)
    two = gzip.compress(line("/a").encode() + b"\n") + gzip.compress(line("/b").encode())
    assert _ingest(db_session, t.id, two, size=1)["ai_hits"] == 2  # 1-byte chunks, 2 members
    try:
        _ingest(db_session, t.id, b"\x1f\x8b" + b"garbage" * 10)
        raise AssertionError("corrupt gzip accepted")
    except UploadError as exc:
        assert exc.status == 400


def test_too_large_is_413(db_session, monkeypatch):
    t = _tenant(db_session)
    monkeypatch.setattr(aa, "MAX_UPLOAD_BYTES", 1000)
    try:
        _ingest(db_session, t.id, b"\n".join([line("/a").encode()] * 50))
        raise AssertionError("oversized upload accepted")
    except UploadError as exc:
        assert exc.status == 413


def test_cloudfront_header_and_path_cap_span_batches(db_session, monkeypatch):
    t = _tenant(db_session)
    monkeypatch.setattr(aa, "_CHUNK_LINES", 10)
    monkeypatch.setattr(aa, "MAX_PATHS", 5)
    rows = ["#Version: 1.0", "#Fields: date time c-ip cs-method cs-uri-stem sc-status "
            "cs(User-Agent)"]
    day = utcnow().strftime("%Y-%m-%d")
    rows += [f"{day}\t10:00:00\t1.1.1.1\tGET\t/p{i}\t200\tGPTBot/1.2" for i in range(40)]
    out = _ingest(db_session, t.id, "\n".join(rows).encode())
    assert out["ai_hits"] == 40
    paths = {r.path for r in db_session.exec(select(AgentTrafficDaily)).all()}
    assert len(paths) == 6 and aa.OTHER_PATH in paths  # 5 kept + the fold bucket


def test_reupload_adds_and_reports_overlap(db_session):
    t = _tenant(db_session)
    first = _ingest(db_session, t.id, line("/a").encode())
    second = _ingest(db_session, t.id, line("/a").encode())
    assert first["overlap_days"] == [] and second["overlap_days"] == first["days"]
    [row] = db_session.exec(select(AgentTrafficDaily)).all()
    assert row.hits == 2  # upsert adds, one row


# --- token storage ---------------------------------------------------------

def test_push_token_is_stored_hashed(client, login, db_session):
    t = Tenant(name="Acme", slug="acme")
    admin = User(email="a@x.test", clerk_user_id="u_a", is_superadmin=True)
    db_session.add_all([t, admin])
    db_session.commit()
    login(admin)
    tok = client.post("/api/admin/tenants/acme/agent-log-token").json()["token"]
    db_session.refresh(t)
    assert t.agent_log_token == hashlib.sha256(tok.encode()).hexdigest() != tok
    res = client.post("/api/ingest/agent-logs", content=line("/a").encode(),
                      headers={"Authorization": f"bearer {tok}"})  # scheme is case-insensitive
    assert res.status_code == 200 and res.json()["ai_hits"] == 1
    bad = client.post("/api/ingest/agent-logs", content=b"x",
                      headers={"Authorization": f"Bearer {t.agent_log_token}"})
    assert bad.status_code == 401  # the stored digest is not a credential


# --- report normalization --------------------------------------------------

def _cite(db, tid, url):
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    r = Result(run_id=run.id, tenant_id=tid, query_text="q", persona_name="p",
               surface=SurfaceCode.openai_api, variant=ResultVariant.search,
               status=ResultStatus.ok, created_at=utcnow() - timedelta(days=1))
    db.add(r)
    db.commit()
    db.add(Citation(result_id=r.id, tenant_id=tid, url=url, domain="acme.com"))
    db.commit()
    return r


def test_encoded_and_trailing_slash_paths_are_one_page(db_session):
    t = _tenant(db_session)
    _cite(db_session, t.id, "https://acme.com/caf%C3%A9-guide/")
    lines = [line("/caf%C3%A9-guide", ua=SEARCH)] * 3 + [line("/pricing")] * 100
    lines += [line("/pricing/", 404)]
    ingest_lines(db_session, t.id, lines, verify=False)
    db_session.commit()
    rep = agent_analytics(db_session, t.id)
    assert "/café-guide" not in [p["path"] for p in rep["read_not_cited"]]
    assert not rep["cited_at_risk"]
    assert next(p for p in rep["top_pages"] if p["path"] == "/pricing")["hits"] == 101


def test_404s_are_not_reported_as_the_bot_being_blocked(db_session):
    from api.recommendations_service import _agent_plays

    t = _tenant(db_session)
    lines = [line("/", 200, "Googlebot/2.1")] * 170 + [line("/old", 404, "Googlebot/2.1")] * 60
    lines += [line("/", 200, b) for b in ("OAI-SearchBot/1.0", "bingbot/2.0",
                                           "PerplexityBot/1.0", "Claude-SearchBot/1.0")]
    ingest_lines(db_session, t.id, lines, verify=False)
    db_session.commit()
    refs = {p.gap_ref for p in _agent_plays(db_session, t.id)}
    assert "crawler:Googlebot:errors" not in refs and "broken_pages" in refs


def test_page_url_collapses_www_and_scheme():
    from api.dashboards_service import _page_url

    a = _page_url("http://www.acme.com/pricing/?utm_source=chatgpt.com", ["acme.com"])
    assert a == _page_url("https://acme.com/pricing", ["acme.com"]) == "https://acme.com/pricing"
    assert _page_url("https://vertexaisearch.cloud.google.com/x", ["acme.com"]) is None


# --- playbook stability ----------------------------------------------------

def test_one_accuracy_play_per_fact(db_session):
    from api.recommendations_service import _accuracy_plays

    t = _tenant(db_session)
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    for sc, stated in ((SurfaceCode.openai_api, "$19.99"), (SurfaceCode.claude_api, "$20"),
                       (SurfaceCode.gemini_api, "$19.99/mo")):
        r = Result(run_id=run.id, tenant_id=t.id, query_text="price", persona_name="p",
                   surface=sc, variant=ResultVariant.search, status=ResultStatus.ok)
        db_session.add(r)
        db_session.commit()
        db_session.add(AccuracyFinding(result_id=r.id, tenant_id=t.id, fact_id=3,
                                       subject="starter price", expected="$9.99", stated=stated))
    db_session.commit()
    [p] = _accuracy_plays(db_session, t.id)
    assert p.gap_ref == "accuracy:3" and p.priority == 98
    assert "$19.99 / $20 / $19.99/mo" in p.action_text


def test_failing_source_keeps_its_plays_and_statuses(db_session, monkeypatch):
    import api.recommendations_service as rs

    t = _tenant(db_session)
    ingest_lines(db_session, t.id, [line("/", 200, SEARCH)] * 250, verify=False)
    db_session.commit()
    rs.generate_recommendations(db_session, t)
    rec = db_session.exec(select(Recommendation).where(
        Recommendation.gap_ref == "crawler:PerplexityBot:absent")).one()
    rec.status = RecommendationStatus.in_progress
    db_session.add(rec)
    db_session.commit()

    def boom(*_a, **_k):
        raise RuntimeError("agent analytics down")

    monkeypatch.setattr(rs, "_agent_plays", boom)
    rs.generate_recommendations(db_session, t)
    monkeypatch.undo()
    rs.generate_recommendations(db_session, t)
    db_session.expire_all()
    rec = db_session.exec(select(Recommendation).where(
        Recommendation.gap_ref == "crawler:PerplexityBot:absent")).one()
    assert rec.status == RecommendationStatus.in_progress


def test_stale_logs_keep_bot_plays_and_ask_for_fresh_logs(db_session):
    import api.recommendations_service as rs

    t = _tenant(db_session)
    ingest_lines(db_session, t.id, [line("/", 200, SEARCH)] * 250, verify=False)
    db_session.commit()
    rs.generate_recommendations(db_session, t)
    old = (utcnow() - timedelta(days=45)).date().isoformat()
    for row in db_session.exec(select(AgentTrafficDaily)).all():
        row.date = old
        db_session.add(row)
    db_session.commit()
    rs.generate_recommendations(db_session, t)
    db_session.expire_all()
    recs = {r.gap_ref: r for r in db_session.exec(select(Recommendation)).all()}
    assert recs["crawler:PerplexityBot:absent"].status == RecommendationStatus.open
    assert recs["connect_logs"].title == "Upload recent server logs"


def test_lost_citation_play_stays_open_until_won_back(db_session, monkeypatch):
    import api.recommendations_service as rs

    t = _tenant(db_session)
    url = "https://acme.com/pricing"
    plans = [
        {"protect": {"ready": True, "lost": [{"url": url, "queries": ["q"]}],
                     "latest_cited": []}},
        {"protect": {"ready": True, "lost": [], "latest_cited": []}},  # still not cited
        {"protect": {"ready": True, "lost": [], "latest_cited": [url]}},  # won back
    ]
    import api.dashboards_service as ds

    states = []
    for plan in plans:
        monkeypatch.setattr(ds, "action_plan", lambda *_a, plan=plan: plan)
        rs.generate_recommendations(db_session, t)
        db_session.expire_all()
        rec = db_session.exec(select(Recommendation).where(
            Recommendation.gap_ref == f"refresh:{url}")).one()
        states.append(rec.status)
    assert states == [RecommendationStatus.open, RecommendationStatus.open,
                      RecommendationStatus.resolved]


# --- crawler features --------------------------------------------------------

def test_features_ignore_scripts_and_styles():
    from engine.audit.presence import extract_features

    f = extract_features('<script>s.replace(/a/,"$1,")</script>'
                         "<style>.a{grid-column:1/5;aspect-ratio:4/5}</style><p>Hi</p>")
    assert not f["has_price"] and not f["has_rating"]
    g = extract_features("<p>Updated on October 3rd, 2026. Rated 4.6 out of 5.</p>")
    assert g["has_updated_date"] and g["has_rating"]
    assert not extract_features("<p>We updated 2000 records</p>")["has_updated_date"]


def test_hostile_pages_are_linear():
    from engine.audit.presence import extract_features

    n = 200_000
    for page in ("<time " * (n // 6), "<h2>" * (n // 4), "1," * (n // 2),
                 "updated" + " " * n, "<script>" * (n // 8), "<" * n):
        start = time.time()
        extract_features(page)
        assert time.time() - start < 3, page[:20]
