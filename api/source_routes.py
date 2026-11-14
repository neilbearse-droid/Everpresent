"""What kind of third-party page a citation points at, and the realistic
route onto it.

"Get listed on the sites AI cites" is only advice when a route exists. A
review profile can be claimed. A thread can be answered. A ranked list takes
additions through the writer, a form or a programme. A published article is
not edited to add a brand, and nobody gets into someone else's video. Every
place the product names a third-party source says which of these it is."""

import re
from urllib.parse import urlsplit

_MARKETPLACES = (
    "amazon.com", "amazon.ca", "amazon.co.uk", "walmart.com", "target.com", "sephora.com",
    "ulta.com", "bestbuy.com", "etsy.com", "ebay.com", "apps.apple.com",
    "play.google.com", "chromewebstore.google.com", "apps.shopify.com", "wordpress.org",
    "marketplace.visualstudio.com",
)
# A URL that reads like a ranked list or comparison, as opposed to an article.
_LIST_PAGE_RE = re.compile(
    r"(?:^|[/\-_])(?:best|top|vs|versus|alternatives?|compared?|comparison|ranked|"
    r"rankings?|roundup|reviews?|buyers?-guide|buying-guide)(?:[/\-_.]|$)",
    re.IGNORECASE,
)


def is_list_page(url: str) -> bool:
    return bool(_LIST_PAGE_RE.search(urlsplit(url or "").path))


def source_kind(domain: str, url: str = "") -> str:
    """review | list | article | community | video | reference | listing |
    research. A publisher is a "list" when the cited URL reads like a ranked
    list or comparison, else an "article"; with no URL it stays "publisher"."""
    from engine.processing.citations import classify_source_type

    d = (domain or "").lower().removeprefix("www.")
    if any(d == m or d.endswith("." + m) for m in _MARKETPLACES):
        return "listing"
    kind = classify_source_type(d)
    kind = {"encyclopedia": "reference", "social": "community"}.get(kind, kind)
    if kind == "publisher" and url:
        return "list" if is_list_page(url) else "article"
    return kind


# kind -> (label, who has to act, the realistic route in one line)
ROUTES: dict[str, tuple[str, str, str]] = {
    "review": ("Review site", "influence",
               "Claim your profile, get into the cited category, ask customers for reviews"),
    "list": ("Ranked list", "earn",
             "Find how products get on it (testing, a form, a programme) and use that route"),
    "article": ("Article", "earn",
                "It won't be edited to add you: pitch the outlet your next news or data"),
    "publisher": ("Publisher", "earn",
                  "Check whether the cited page is a list that takes additions"),
    "community": ("Community", "influence",
                  "Answer open threads as a disclosed company account"),
    "video": ("Video", "own",
              "You can't join someone else's video: publish your own for the question"),
    "reference": ("Reference", "influence",
                  "Needs independent coverage first; then propose sourced fixes"),
    "listing": ("Store listing", "own", "Create or correct your listing"),
    "research": ("Primary source", "earn",
                 "Cite it on your pages, or publish your own data"),
}


def route_for(domain: str, url: str = "") -> dict[str, str]:
    kind = source_kind(domain, url)
    label, control, route = ROUTES.get(kind, ROUTES["publisher"])
    return {"kind": kind, "kind_label": label, "control": control, "route": route}
