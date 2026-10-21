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


# Primary sources: research and official data. Engines increasingly cite the
# original source of a fact over pages that summarize it.
_RESEARCH_DOMAINS = (
    "nih.gov", "pubmed.gov", "europepmc.org", "doi.org", "arxiv.org", "biorxiv.org",
    "medrxiv.org", "ssrn.com", "researchgate.net", "scholar.google.com",
    "nature.com", "science.org", "sciencedirect.com", "cell.com", "springer.com",
    "wiley.com", "tandfonline.com", "sagepub.com", "oup.com", "cambridge.org",
    "jamanetwork.com", "thelancet.com", "nejm.org", "bmj.com", "mdpi.com",
    "frontiersin.org", "plos.org", "cochranelibrary.com", "who.int", "oecd.org",
    "worldbank.org", "imf.org", "europa.eu", "gov.uk",
)
# Government and academic suffixes (official statistics, regulators, universities).
_RESEARCH_SUFFIXES = (".gov", ".mil", ".edu", ".ac.uk", ".gov.uk", ".gov.au", ".gc.ca",
                      ".gouv.fr", ".bund.de", ".edu.au")


def classify_source_type(domain: str) -> str:
    """The kind of source a domain is — research / encyclopedia / community /
    video / review / social / publisher. Pattern-based; the long tail is
    'publisher'."""
    d = domain.lower().removeprefix("www.")
    if any(d == p or d.endswith("." + p) for p in _RESEARCH_DOMAINS) or d.endswith(
        _RESEARCH_SUFFIXES
    ):
        return "research"
    for label, patterns in _SOURCE_TYPE_PATTERNS:
        if any(d == p or d.endswith("." + p) for p in patterns):
            return label
    return "publisher"
