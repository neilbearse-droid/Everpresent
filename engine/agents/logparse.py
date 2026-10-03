"""Access-log parsing for Agent Analytics. Auto-detects, per line:

- Apache/Nginx "combined" format
- JSON lines from Cloudflare Logpush (ClientRequestUserAgent, ClientIP,
  ClientRequestPath/URI, EdgeResponseStatus, EdgeStartTimestamp), Vercel log
  drains (proxy.userAgent/path/statusCode/clientIp), Fastly/generic JSON with
  common field names
- AWS CloudFront standard logs (tab-separated, with a #Fields header)

Returns a normalized LogHit or None. Pure; no I/O. Lines that aren't AI bots
are dropped by the caller before anything is stored, so human traffic and
human IPs never leave the parser.
"""

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit


@dataclass
class LogHit:
    ts: datetime
    ip: str
    method: str
    path: str
    status: int
    user_agent: str


# Real access-log lines are a few hundred bytes; anything far longer is junk
# or hostile and is skipped before any pattern runs on it.
MAX_LINE_CHARS = 16_384

# Bounded and non-overlapping (target can't contain a quote), so a malformed
# request line can't backtrack.
_COMBINED = re.compile(
    r'^(?P<ip>[^\s]{1,64}) [^\s]{1,256} [^\s]{1,256} \[(?P<ts>[^\]]{1,64})\] '
    r'"(?P<method>[A-Z]{1,16}) (?P<target>[^\s"]{1,8192})[^"]{0,64}" '
    r'(?P<status>\d{3}) [^\s]{1,32}(?: "[^"]{0,8192}" "(?P<ua>[^"]{0,4096})")?'
)
# NUL and other C0 control characters: Postgres text can't hold NUL, and none
# belong in a URL path.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _http_status(code: int) -> int:
    """A real HTTP status or 0 (unknown); keeps junk out of an int column."""
    return code if 100 <= code <= 599 else 0


def _clean_path(target: str) -> str:
    target = target.strip()
    if "://" in target:
        target = urlsplit(target).path or "/"
    path = target.split("?", 1)[0].split("#", 1)[0] or "/"
    return _CONTROL.sub("", unquote(path))[:500] or "/"


def _parse_ts(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        if not math.isfinite(n) or n <= 0:
            return None
        # Cloudflare uses ns, ms or s epochs depending on the timestamp format.
        if n > 1e17:
            n /= 1e9
        elif n > 1e14:
            n /= 1e6
        elif n > 1e11:
            n /= 1e3
        try:
            return datetime.fromtimestamp(n, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if s.isdigit():  # an epoch sent as a string
        return _parse_ts(int(s)) if len(s) <= 20 else None
    for fmt in ("%d/%b/%Y:%H:%M:%S %z",):
        try:
            return datetime.strptime(s, fmt).astimezone(UTC)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _first(d: dict, *keys: str) -> object:
    for k in keys:
        cur: object = d
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if cur not in (None, ""):
            return cur
    return None


def _parse_json(line: str) -> list[LogHit]:
    """One JSON object per line, or a JSON array of them (Vercel's "json"
    drain format sends an array per request body)."""
    try:
        d = json.loads(line)
    except (ValueError, RecursionError):
        return []
    items = d if isinstance(d, list) else [d]
    return [h for h in (_hit_from_dict(x) for x in items[:100_000] if isinstance(x, dict)) if h]


def _hit_from_dict(d: dict) -> LogHit | None:
    ua = _first(d, "ClientRequestUserAgent", "proxy.userAgent", "user_agent", "userAgent",
                "request_user_agent", "http.user_agent", "ua", "request.headers.user-agent")
    target = _first(d, "ClientRequestPath", "ClientRequestURI", "proxy.path", "path", "url",
                    "request_uri", "uri", "http.url", "request.url")
    status = _first(d, "EdgeResponseStatus", "OriginResponseStatus", "proxy.statusCode",
                    "status", "statusCode", "status_code", "http.status_code",
                    "response.status")
    ts = _parse_ts(_first(d, "EdgeStartTimestamp", "timestamp", "time", "ts", "date",
                          "@timestamp", "proxy.timestamp"))
    ip = _first(d, "ClientIP", "proxy.clientIp", "client_ip", "clientIp", "ip",
                "remote_addr", "http.client_ip")
    method = _first(d, "ClientRequestMethod", "proxy.method", "method", "request_method",
                    "http.method")
    if not ua or not target or ts is None:
        return None
    try:
        code = int(str(status)) if status is not None else 0
    except ValueError:
        code = 0
    code = _http_status(code)
    return LogHit(ts=ts, ip=str(ip or ""), method=str(method or "GET").upper(),
                  path=_clean_path(str(target)), status=code, user_agent=str(ua))


class LogParser:
    """Stateful only for CloudFront's #Fields header; otherwise per line."""

    def __init__(self) -> None:
        self._cf_fields: list[str] | None = None

    def parse(self, line: str) -> LogHit | None:
        """The single hit on this line, or None."""
        hits = self.parse_all(line)
        return hits[0] if hits else None

    def parse_all(self, line: str) -> list[LogHit]:
        """Every hit on this line: one for text formats, possibly many for a
        JSON array body."""
        stripped = line.lstrip("\ufeff").lstrip()  # BOM on a file's first line
        if stripped.startswith("["):
            # A JSON array body can be large; it's bounded by the upload cap.
            return _parse_json(stripped)
        if len(line) > MAX_LINE_CHARS:
            return []
        hit = self._parse_line(line.rstrip("\r\n").lstrip("\ufeff"))
        return [hit] if hit else []

    def _parse_line(self, line: str) -> LogHit | None:
        if not line.strip():
            return None
        if line.startswith("#Fields:"):
            self._cf_fields = line[len("#Fields:"):].split()
            return None
        if line.startswith("#"):
            return None
        if line.lstrip().startswith("{"):
            hits = _parse_json(line)
            return hits[0] if hits else None
        if self._cf_fields and "\t" in line:
            return self._parse_cloudfront(line)
        m = _COMBINED.match(line)
        if not m:
            return None
        ts = _parse_ts(m.group("ts"))
        if ts is None:
            return None
        return LogHit(ts=ts, ip=m.group("ip"), method=m.group("method"),
                      path=_clean_path(m.group("target")), status=int(m.group("status")),
                      user_agent=m.group("ua") or "")

    def _parse_cloudfront(self, line: str) -> LogHit | None:
        assert self._cf_fields is not None
        row = dict(zip(self._cf_fields, line.split("\t"), strict=False))
        ts = _parse_ts(f"{row.get('date', '')}T{row.get('time', '')}+00:00")
        ua = unquote(unquote(row.get("cs(User-Agent)", "")))
        if ts is None or not ua:
            return None
        try:
            status = _http_status(int(row.get("sc-status", "0")))
        except ValueError:
            status = 0
        return LogHit(ts=ts, ip=row.get("c-ip", ""), method=row.get("cs-method", "GET"),
                      path=_clean_path(row.get("cs-uri-stem", "/")), status=status,
                      user_agent=ua)
