"""Every DOM selector the chatgpt_web adapter touches, in one file (§6.2):
they WILL break when OpenAI ships a redesign, and fixing them should take
five minutes of updating strings here — never a code change in the adapter."""

URL = "https://chatgpt.com/"

# The composer. chatgpt.com renders a contenteditable div with this id for
# both logged-in and logged-out sessions.
PROMPT_INPUT = "#prompt-textarea"
SEND_BUTTON = '[data-testid="send-button"]'

# Present while the answer is streaming; its disappearance (plus stable DOM)
# is the completion signal.
STOP_BUTTON = '[data-testid="stop-button"]'

# One node per assistant turn; the last one is the answer to our query.
ASSISTANT_MESSAGE = '[data-message-author-role="assistant"]'

# Logged-out interstitials, best-effort dismissed if present.
DISMISS_CANDIDATES = [
    '[data-testid="close-button"]',
    'button:has-text("Stay logged out")',
    'a:has-text("Stay logged out")',
]
