"""SSRF guard for fetching URLs we don't control (pages the AI engines cited,
domains typed into an audit). Only http(s) to public addresses: loopback,
private, link-local (cloud metadata at 169.254.169.254), reserved and
multicast targets are refused, on the first request AND every redirect hop.

Use as an httpx request event hook:
    httpx.Client(event_hooks={"request": [guard_public_request]}, ...)
httpx runs request hooks for each redirect hop, so a public page that 302s to
an internal address is stopped before the internal request is sent."""

import ipaddress
import socket

import httpx


class BlockedAddressError(httpx.RequestError):
    """The URL points at a non-public address."""


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def check_public_url(url: httpx.URL) -> None:
    if url.scheme not in ("http", "https"):
        raise BlockedAddressError(f"blocked scheme: {url.scheme}")
    host = url.host
    if not host:
        raise BlockedAddressError("blocked: no host")
    try:
        infos = socket.getaddrinfo(host, url.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedAddressError(f"blocked: cannot resolve {host}") from exc
    for info in infos:
        ip = str(info[4][0])
        if not _is_public(ip):
            raise BlockedAddressError(f"blocked non-public address for {host}: {ip}")


def guard_public_request(request: httpx.Request) -> None:
    check_public_url(request.url)
