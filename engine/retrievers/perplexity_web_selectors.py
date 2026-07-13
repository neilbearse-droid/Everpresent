"""Every DOM selector the perplexity_web adapter touches, in one file (§6.2)
— the five-minute-fix contract, same as chatgpt_web_selectors."""

URL = "https://www.perplexity.ai/"

# The ask box (contenteditable in current builds; textarea in older ones).
PROMPT_INPUT = 'textarea[placeholder*="Ask"], [contenteditable="true"][data-lexical-editor]'
SUBMIT_BUTTON = 'button[aria-label="Submit"]'

# The streamed answer body; the last one on the page is our answer.
ANSWER_CONTAINER = '[class*="prose"]'
# Present while streaming.
STOP_BUTTON = 'button[aria-label="Stop generating"]'

DISMISS_CANDIDATES = [
    'button[aria-label="Close"]',
    'button:has-text("Not now")',
]
