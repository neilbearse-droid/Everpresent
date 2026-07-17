"""Citation source categorization (§5.1 citations.source_category)."""


def _domain_matches(domain: str, owned: str) -> bool:
    domain, owned = domain.lower().removeprefix("www."), owned.lower().removeprefix("www.")
    return domain == owned or domain.endswith("." + owned)


def domain_is_owned(domain: str, owned_domains: list[str]) -> bool:
    return any(_domain_matches(domain, d) for d in owned_domains)


def categorize_domain(
    domain: str, brand_domains: list[str], competitor_domains: list[str]
) -> str:
    if any(_domain_matches(domain, d) for d in brand_domains):
        return "brand"
    if any(_domain_matches(domain, d) for d in competitor_domains):
        return "competitor"
    return "other"


# Source-TYPE patterns (§AEO-plan m4). Orthogonal to owned/rival: the *kind* of
# page, which diverges sharply by engine (ChatGPT leans encyclopedia/publisher,
# Perplexity leans community/Reddit, AI Overviews lean community + professional).
# Knowing an engine's mix tells you where to earn presence for THAT engine.
_SOURCE_TYPE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("encyclopedia", ("wikipedia.org", "wikidata.org", "britannica.com")),
    ("community", ("reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com",
                   "ycombinator.com", "medium.com")),
    ("video", ("youtube.com", "youtu.be", "vimeo.com", "tiktok.com")),
    ("review", ("g2.com", "capterra.com", "trustpilot.com", "yelp.com", "glassdoor.com",
                "trustradius.com")),
    ("social", ("linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com")),
)


def classify_source_type(domain: str) -> str:
    """The kind of source a domain is — encyclopedia / community / video /
    review / social / publisher. Pattern-based; the long tail is 'publisher'."""
    d = domain.lower().removeprefix("www.")
    for label, patterns in _SOURCE_TYPE_PATTERNS:
        if any(d == p or d.endswith("." + p) for p in patterns):
            return label
    return "publisher"
