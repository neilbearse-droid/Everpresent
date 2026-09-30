# EverPresent — GoDaddy Demo Readiness

Every engine wired, verified, and collecting before the demo. Work top to
bottom. The admin page's **Engine readiness** panel (`/admin/godaddy`) is the
proof: when every engine says **READY**, you're done.

Start collection as early as possible: trend lines can't be backfilled, and
fan-out trends need about a week of runs.

---

## 1. Get the keys (about an hour, mostly signup screens)

| Engine(s) | Where | What you copy |
|---|---|---|
| ChatGPT (API) | platform.openai.com → Billing (add credit) → API keys | `sk-...` → `OPENAI_API_KEY` |
| Claude (API) + Claude features | console.anthropic.com → Billing (add credit) → API keys | `sk-ant-...` → `ANTHROPIC_API_KEY` |
| Gemini (API) | aistudio.google.com → Get API key → Create key (turn on billing for its Cloud project; free-tier search grounding is rate-limited) | `AIza...` → `GEMINI_API_KEY` |
| Perplexity (API) | perplexity.ai → Settings → API → add credit → Generate key | `pplx-...` → `PERPLEXITY_API_KEY` |
| Google AI Overviews | serpapi.com → Register → Dashboard → Private API Key. Plan: ~10 searches per run, so ~300/month for daily runs plus testing | key → `SERPAPI_KEY` |
| Copilot, ChatGPT (web), Perplexity (web) | A residential proxy (Bright Data, Oxylabs, Decodo/Smartproxy…) → create a residential zone, country **US** | `http://USER:PASS@HOST:PORT` → `SCRAPE_PROXY_URL` |

## 2. Put them in Render (15 minutes)

Engine calls run on the **worker**, so that's where the engine keys go.

- [ ] **everpresent-worker** → Environment: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `PERPLEXITY_API_KEY`, `SERPAPI_KEY`, `SCRAPE_PROXY_URL`. Confirm `GOOGLE_AIO_PROVIDER` = `serpapi`. **Save** (it redeploys).
- [ ] **everpresent-api** → Environment: `ANTHROPIC_API_KEY` (the corrective-content button runs here). **Save**.
- [ ] Each service's **Events** shows the latest commit **Live**. The API deploy runs the database migration itself.

## 3. Configure GoDaddy in the admin panel (10 minutes)

At `/admin/godaddy`:

- [ ] **Plan**: Command or Custom (lower plans drop engines).
- [ ] **Governance → Approve AI processing**.
- [ ] **Governance → Search country: United States (US)**. The GoDaddy tenant was created with the Canada default.
- [ ] **Engine readiness → switch On** all eight: ChatGPT (API), Claude (API), Gemini (API), Perplexity (API), ChatGPT (web), Perplexity (web), Microsoft Copilot, Google AI Overviews. (Gemini web shows n/a: not built.)
- [ ] **Governance → Turn on Claude features** (Whitespace page + corrective-content and brief buttons).
- [ ] **Governance → Monthly spend cap**: at least **$300** for demo week. Too low and calls come back WITHHELD.
- [ ] **Governance → Fan-out re-probe: on**.
- [ ] **Run schedule**: `0 12 * * *` (daily, 12:00 UTC ≈ 8am ET), enabled.
- [ ] **Brand fact sheet**: confirm the domain-privacy fact matches GoDaddy's real policy (it's a placeholder).

## 4. First verification run (20 minutes)

- [ ] **Runs → Trigger run**. Wait for it to finish (browser engines take the longest).
- [ ] Back on `/admin/godaddy`, **Engine readiness**: every switched-on engine should say **READY**. If not:

| Status | Meaning | Fix |
|---|---|---|
| MISSING KEY | The worker has no key for that engine | Add it on **everpresent-worker**, save, re-run |
| BLOCKED | Anti-bot wall | Check `SCRAPE_PROXY_URL` format and that the zone is **residential**, country US |
| ERROR | Calls failed | Click the run number; the result error names the cause (bad key, no billing) |
| WITHHELD | Spend cap hit | Raise the cap, re-run |
| OUTSIDE PLAN | Plan's engine limit | Plan → Command or Custom |
| NOT RUN YET | Switched on after the last run | Trigger a run |

- [ ] **Copilot check** (its page changes often): Render → everpresent-worker → **Shell**:
  `python scripts/smoke_copilot.py --query "What's the best AI website builder?"`
  Exit `0` = good · `3` = blocked (proxy) · `4`/`5` = page changed (screenshots show it; fix in `engine/retrievers/copilot_web_selectors.py`).
- [ ] The four readiness checks at the top of the panel all say **Done**.

## 5. Every day until the demo (2 minutes)

- [ ] Open `/admin/godaddy` → Engine readiness still all **READY** after the overnight run.
- [ ] Anything else: use the table above the same day. A missed day is a gap in the trend.

## 6. Day before the demo

- [ ] Click through: Overview → Engines → Fan-out → Citations → Scorecard → Whitespace → Action Plan.
- [ ] Scorecard → **Generate corrective content** on the accuracy card returns a draft.
- [ ] Fan-out → **Generate corrective brief** on a HIGH row returns a draft.
- [ ] Hard refresh (Cmd/Ctrl+Shift+R) on the demo machine.

## What's covered, and what isn't

Measured: ChatGPT (API and web), Claude, Gemini (API), Perplexity (API and web),
Microsoft Copilot, Google AI Overviews. **Not built:** Gemini web app, Google AI
Mode, Grok, Meta AI. Each is a new adapter, not a setting.
