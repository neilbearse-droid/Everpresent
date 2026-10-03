"""Verify a claimed AI bot by IP: the hit's IP must fall inside the operator's
published ranges (e.g. https://openai.com/gptbot.json). Anyone can send
"GPTBot" as a User-Agent; only OpenAI can send it from OpenAI's addresses.

Range lists are fetched lazily, cached for a day, and any fetch failure just
means "can't verify" (the hit stays 'claimed'), never an ingest error.
"""

import ipaddress
import time
from collections.abc import Callable
from typing import Any

import httpx

_TTL_S = 24 * 3600
_FAIL_TTL_S = 600  # retry a failed fetch soon: a hit stays unverified for good
_Network = ipaddress.IPv4Network | ipaddress.IPv6Network
_cache: dict[str, tuple[float, list[_Network]]] = {}


def parse_ranges(payload: Any) -> list[_Network]:
    """Google/OpenAI/Perplexity publish {"prefixes": [{"ipv4Prefix": ...} |
    {"ipv6Prefix": ...}]}; also accept a bare list of CIDR strings."""
    items: list[str] = []
    if isinstance(payload, dict):
        for p in payload.get("prefixes") or []:
            if isinstance(p, dict):
                items += [v for k, v in p.items() if k in ("ipv4Prefix", "ipv6Prefix")]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, str)]
    nets: list[_Network] = []
    for cidr in items:
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    return nets


def _fetch(url: str) -> list[_Network]:
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return parse_ranges(resp.json())


def ranges_for(url: str, fetch: Callable[[str], list[_Network]] = _fetch) -> list[_Network]:
    now = time.time()
    hit = _cache.get(url)
    if hit and now < hit[0]:
        return hit[1]
    try:
        nets = fetch(url)
        expires = now + _TTL_S
    except Exception:  # noqa: BLE001 — unverifiable, not an error
        nets = []
        expires = now + _FAIL_TTL_S
    _cache[url] = (expires, nets)
    return nets


def ip_in(ip: str, nets: list[_Network]) -> bool:
    try:
        addr = ipaddress.ip_address(ip.strip().strip("[]"))
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped  # "::ffff:66.249.0.5" is an IPv4 client
    return any(addr.version == n.version and addr in n for n in nets)
