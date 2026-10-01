"""SSRF guard: cited/audited URLs may only reach public http(s) addresses, on
every redirect hop, and oversized bodies are cut off while streaming."""

import httpx
import pytest

from engine.audit.presence import MAX_HTML_BYTES, crawl_page
from engine.netguard import BlockedAddressError, check_public_url, guard_public_request


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/iam",
    "http://127.0.0.1:8000/api/admin/tenants",
    "http://localhost/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/",
    "file:///etc/passwd",
    "gopher://example.com/",
])
def test_internal_and_odd_targets_are_refused(url):
    with pytest.raises(BlockedAddressError):
        check_public_url(httpx.URL(url))


def test_public_ip_literal_is_allowed():
    check_public_url(httpx.URL("https://93.184.216.34/"))


def test_redirect_to_metadata_is_stopped_before_it_is_sent(monkeypatch):
    """The auditor's proof: a public page 302s to the cloud metadata service."""
    sent: list[str] = []
    monkeypatch.setattr(
        "engine.netguard.socket.getaddrinfo",
        lambda host, *a, **k: [
            (0, 0, 0, "", ("93.184.216.34" if host == "evil.test" else host, 0))
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        if request.url.host == "evil.test":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/iam"})
        return httpx.Response(200, text="SECRET")

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True,
                      event_hooks={"request": [guard_public_request]}) as client:
        out = crawl_page(client, "http://evil.test/article")
    assert "error" in out and "blocked" in out["error"]
    assert sent == ["http://evil.test/article"]  # the internal hop never went out


def test_huge_body_is_capped_while_streaming(monkeypatch):
    monkeypatch.setattr("engine.netguard.socket.getaddrinfo",
                        lambda *a, **k: [(0, 0, 0, "", ("93.184.216.34", 0))])
    big = b"<p>" + b"a" * (MAX_HTML_BYTES * 3)

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=big)),
                      event_hooks={"request": [guard_public_request]}) as client:
        out = crawl_page(client, "http://big.test/")
    assert out["http_status"] == 200 and len(out["html"]) <= MAX_HTML_BYTES
