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
