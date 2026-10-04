"""Answer shape: how an answer presents its sources (m33). Pure functions.

Since May 2026 ChatGPT shows clickable brand-name links inside the answer
text instead of footnote chips, and trackers that count every link as a
"citation" misread that as a change in citing. We keep the two apart:
  inline — a link on words in the answer ("…try GoDaddy…")
  source — a footnote, numbered marker or source chip ("[1]", "godaddy.com")
"""

import re
from urllib.parse import urlsplit

_MARKER = re.compile(r"^[\[\(]?\+?\d{1,3}[\]\)]?$")  # "1", "[2]", "(3)", "+4"


def link_kind(anchor_text: str, url: str) -> str:
    """'source' when the anchor looks like a citation marker or a site label,
    else 'inline'. Only meaningful for captured web UIs, where the anchor
    text is what the user saw."""
    text = (anchor_text or "").strip()
    if not text or _MARKER.match(text):
        return "source"
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    low = text.lower().removeprefix("www.")
    # ChatGPT's inline brand links (May 2026) put the brand's name on a link
    # to its homepage; a source chip labelled with the site points at the
    # specific page it quoted.
    if (parts.path or "/") == "/" and "." not in low:
        return "inline"
    if host and (low == host or low == host.split(".")[0]):
        return "source"
    # A bare domain or site label ("techradar.com", "reddit") as the anchor.
    if " " not in low and ("." in low or len(low) <= 3):
        return "source"
    return "inline"
