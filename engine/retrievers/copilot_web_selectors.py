"""Every DOM selector the copilot_web adapter touches, in one file (§6.2).

Microsoft Copilot is the most redesign-prone of the measured surfaces (it has
shipped several composer rewrites), so each role is a LIST of candidates and
the adapter takes the first that matches. When Copilot ships a redesign, fixing
capture should be adding a string here — never a code change in the adapter.

These are best-effort against copilot.microsoft.com as of this writing and MUST
be re-verified against a live session before the demo; the adapter logic
(fresh-session → submit → settle → extract) is the durable part."""

URL = "https://copilot.microsoft.com/"

# The composer. Copilot has used a contenteditable div and, in other builds, a
# plain textarea; try both plus stable testids/aria labels.
PROMPT_INPUT_CANDIDATES = [
    'textarea[data-testid="composer-input"]',
    'textarea#userInput',
    'div[contenteditable="true"][data-testid="composer-input"]',
    'div[contenteditable="true"][role="textbox"]',
    'textarea[aria-label*="Message"]',
    'textarea',
]

# Submit control. When none matches, the adapter falls back to pressing Enter.
SUBMIT_BUTTON_CANDIDATES = [
    'button[data-testid="submit-button"]',
    'button[aria-label="Submit"]',
    'button[aria-label*="Send"]',
    'button[title*="Submit"]',
]

# One node per assistant turn; the last is the answer to our query.
ANSWER_CONTAINER_CANDIDATES = [
    '[data-testid="ai-message"]',
    '[data-content="ai-message"]',
    '[data-author="bot"]',
    'div[class*="response"]',
]

# Present while the answer streams; its disappearance (plus a stable DOM) is the
# completion signal. Absent in some builds — the adapter treats a missing stop
# button as "not streaming" and relies on DOM stability alone.
STOP_BUTTON_CANDIDATES = [
    'button[data-testid="stop-button"]',
    'button[aria-label*="Stop"]',
]

# Cookie banners / sign-in nudges / region interstitials, best-effort dismissed.
DISMISS_CANDIDATES = [
    'button[data-testid="close-button"]',
    'button[aria-label="Close"]',
    'button:has-text("Accept")',
    'button:has-text("Got it")',
    'button:has-text("No thanks")',
    'button:has-text("Stay signed out")',
]
