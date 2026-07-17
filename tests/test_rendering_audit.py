"""CSR-dependency verdict (§AEO-plan M3): does the raw HTML carry the content,
or is it a JS-only shell invisible to non-rendering AI crawlers?"""

from engine.audit.rendering import render_verdict

_REAL_CONTENT = (
    "<html><head><title>Smith School of Business</title></head><body>"
    + "<h1>MBA Programs</h1>"
    + "<p>" + " ".join(["Smith is a leading business school in Canada."] * 60) + "</p>"
    + "</body></html>"
)

_SPA_SHELL = (
    "<html><head><title>App</title>"
    '<script src="/static/js/main.abc123.js"></script>'
    '<script src="/static/js/vendor.def456.js"></script>'
    '<script src="/static/js/runtime.789.js"></script></head>'
    '<body><div id="__next"></div>'
    "<noscript>You need to enable JavaScript to run this app.</noscript>"
    "</body></html>"
)

_THIN = "<html><body><h1>Welcome</h1><p>Coming soon.</p></body></html>"


def test_server_rendered_content_passes():
    v = render_verdict(_REAL_CONTENT)
    assert v["verdict"] == "pass"
    assert v["word_count"] >= 250


def test_spa_shell_fails():
    v = render_verdict(_SPA_SHELL)
    assert v["verdict"] == "fail"
    assert v["signals"]["mount_node"] is True
    assert v["signals"]["noscript_warning"] is True
    assert "JavaScript" in v["reason"]


def test_thin_page_warns():
    v = render_verdict(_THIN)
    assert v["verdict"] == "warn"


def test_ssr_react_app_still_passes():
    # A React root id is present, but the content is server-rendered → readable.
    html = (
        '<html><body><div id="root"><h1>Pricing</h1>'
        + "<p>" + " ".join(["Our plans start at forty nine dollars per month."] * 50) + "</p>"
        + "</div></body></html>"
    )
    assert render_verdict(html)["verdict"] == "pass"
