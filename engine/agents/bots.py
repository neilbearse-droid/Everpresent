"""AI crawler / agent taxonomy for log classification (Agent Analytics).

Identification is by User-Agent token first (case-insensitive substring match,
longest token wins so "OAI-SearchBot" beats "SearchBot"-style overlaps). A UA
can be spoofed, so a hit is only "verified" when its IP also falls inside the
operator's published ranges (see verify.py); otherwise it is "claimed".

Purpose matters more than the bot name:
  training — collecting data to train future models (no visibility payoff)
  search   — indexing for the engine's own answers/citations (visibility!)
  user     — fetched live because a person asked about this page right now
             (the closest signal of real answer usage)
  agent    — an agentic browser acting for a user
Pure data + functions; no I/O.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Bot:
    token: str      # UA substring that identifies it
    name: str       # display name
    company: str
    purpose: str    # training | search | user | agent
    ip_list_url: str = ""  # operator's published IP ranges (JSON), if any


BOTS: tuple[Bot, ...] = (
    # OpenAI
    Bot("GPTBot", "GPTBot", "OpenAI", "training", "https://openai.com/gptbot.json"),
    Bot("OAI-SearchBot", "OAI-SearchBot", "OpenAI", "search",
        "https://openai.com/searchbot.json"),
    Bot("ChatGPT-User", "ChatGPT-User", "OpenAI", "user",
        "https://openai.com/chatgpt-user.json"),
    Bot("OAI-Operator", "ChatGPT agent", "OpenAI", "agent"),
    # Anthropic
    # One published list covers all three Anthropic bots (read 2026-10-02).
    Bot("ClaudeBot", "ClaudeBot", "Anthropic", "training", "https://claude.com/crawling/bots.json"),
    Bot("Claude-SearchBot", "Claude-SearchBot", "Anthropic", "search", "https://claude.com/crawling/bots.json"),
    Bot("Claude-User", "Claude-User", "Anthropic", "user", "https://claude.com/crawling/bots.json"),
    Bot("anthropic-ai", "anthropic-ai (legacy)", "Anthropic", "training"),
    Bot("Claude-Web", "Claude-Web (legacy)", "Anthropic", "user"),
    # Perplexity
    Bot("PerplexityBot", "PerplexityBot", "Perplexity", "search",
        "https://www.perplexity.com/perplexitybot.json"),
    Bot("Perplexity-User", "Perplexity-User", "Perplexity", "user",
        "https://www.perplexity.com/perplexity-user.json"),
    # Google (Googlebot feeds Search incl. AI Overviews / AI Mode)
    Bot("Googlebot", "Googlebot", "Google", "search",
        "https://developers.google.com/static/search/apis/ipranges/googlebot.json"),
    Bot("Google-Agent", "Google-Agent", "Google", "agent"),
    Bot("Gemini-Deep-Research", "Gemini Deep Research", "Google", "user"),
    Bot("Google-CloudVertexBot", "Google-CloudVertexBot", "Google", "user"),
    Bot("GoogleOther", "GoogleOther", "Google", "training"),
    # Microsoft (Bing index feeds Copilot and ChatGPT search)
    Bot("bingbot", "Bingbot", "Microsoft", "search"),
    # Apple
    Bot("Applebot", "Applebot", "Apple", "search"),
    # Meta
    Bot("meta-externalagent", "Meta-ExternalAgent", "Meta", "training"),
    Bot("meta-externalfetcher", "Meta-ExternalFetcher", "Meta", "user"),
    Bot("FacebookBot", "FacebookBot", "Meta", "training"),
    # Others
    Bot("Amazonbot", "Amazonbot", "Amazon", "search"),
    Bot("Bytespider", "Bytespider", "ByteDance", "training"),
    Bot("CCBot", "CCBot", "Common Crawl", "training"),
    Bot("MistralAI-User", "MistralAI-User", "Mistral", "user"),
    Bot("DuckAssistBot", "DuckAssistBot", "DuckDuckGo", "user"),
    Bot("cohere-ai", "cohere-ai", "Cohere", "training"),
    Bot("YouBot", "YouBot", "You.com", "search"),
    Bot("Diffbot", "Diffbot", "Diffbot", "training"),
    Bot("xAI-Bot", "xAI-Bot", "xAI", "search"),
    Bot("Grok", "Grok", "xAI", "user"),
    Bot("DeepSeekBot", "DeepSeekBot", "DeepSeek", "search"),
)

# robots.txt opt-out tokens, NOT crawlers: they never appear in a real
# request's User-Agent, so a request claiming one is spoofed (dropped).
SPOOF_ONLY_TOKENS = ("google-extended", "applebot-extended")

# Longest token first so specific tokens win over generic ones.
_BY_LENGTH = sorted(BOTS, key=lambda b: -len(b.token))

PURPOSES = ("search", "user", "agent", "training")


def classify_user_agent(user_agent: str) -> Bot | None:
    """The AI bot this UA claims to be, or None for everything else (humans,
    ordinary crawlers). Case-insensitive substring match."""
    if not user_agent:
        return None
    ua = user_agent.lower()
    if any(t in ua for t in SPOOF_ONLY_TOKENS):
        return None
    for bot in _BY_LENGTH:
        if bot.token.lower() in ua:
            return bot
    return None
