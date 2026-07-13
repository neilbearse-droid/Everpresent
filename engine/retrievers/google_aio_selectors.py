"""Every DOM selector/marker the google_aio adapter touches (§6.2/§6.3
five-minute-fix contract)."""

SEARCH_URL = "https://www.google.com/search"

# Google's AI Overview container. Google churns these attributes constantly;
# the adapter tries them in order.
AIO_BLOCK_CANDIDATES = [
    '[data-mcp="ai-overview"]',
    "#m-x-content",
    'div[jsname][data-rl]',
    'div:has(> div[aria-label="AI Overview"])',
]
# Text heading fallback when no structural selector matches.
AIO_HEADING_TEXT = "AI Overview"

SHOW_MORE_BUTTON = 'div[role="button"]:has-text("Show more")'

# Organic results (first h3 anchors under the results column).
ORGANIC_RESULT = "#search h3"

CONSENT_DISMISS_CANDIDATES = [
    'button:has-text("Reject all")',
    'button:has-text("Accept all")',
    'button[aria-label="Reject all"]',
]
