# Setting up Clerk (logins)

Clerk is a hosted login service. You click through their dashboard — no code.
The whole job is to come away with **three values** and **two settings**
flipped on.

## What you're collecting

| `.env` / Render variable | What it is |
|---|---|
| `CLERK_PUBLISHABLE_KEY` | starts `pk_` — the public front-end key |
| `CLERK_SECRET_KEY` | starts `sk_` — the private back-end key (never share) |
| `CLERK_JWKS_URL` | a URL ending `/.well-known/jwks.json` — how the API verifies logins |

## Steps

**1. Make an account & application**
- Go to **dashboard.clerk.com**, sign up (free tier is fine).
- **Create application**. Name it `EverPresent`.
- Tick **Email** (and optionally **Google**) as sign-in methods → **Create**.

**2. Grab the two keys**
- Left sidebar → **API keys** (sometimes **Configure → API keys**).
- Copy the **Publishable key** (`pk_…`) → `CLERK_PUBLISHABLE_KEY`.
- Copy the **Secret key** (`sk_…`, click reveal) → `CLERK_SECRET_KEY`.

**3. Build the JWKS URL**
- On the same page find the **Frontend API URL** (may be under a "Show"/
  "Advanced" section). Looks like `https://something.clerk.accounts.dev`.
- Your `CLERK_JWKS_URL` is that URL + `/.well-known/jwks.json`, e.g.
  `https://something.clerk.accounts.dev/.well-known/jwks.json`

**4. Turn on Organizations** (each client = one organization = one tenant)
- Left sidebar → **Organizations** → toggle **Enable organizations** on.

**5. Make it invite-only** (no public signups, per the product spec)
- Left sidebar → **User & authentication → Restrictions** → turn **off**
  public sign-ups (or set sign-up mode to restricted). Only people you invite
  can get in.

## Dev vs. Production

Clerk gives you a **Development** instance immediately (`pk_test_`/`sk_test_`
keys) — perfect to get logging in. When you launch on your own domain, create
a **Production** instance in Clerk for `pk_live_` keys and a custom auth
domain, and swap those values in Render. Start with Development.

## After deploying

On a **Development** instance, logins work on any URL (including your
`onrender.com` site) with no domain configuration — Clerk's Domains allowlist
is disabled for dev instances, and that's fine. You only configure a Primary
domain later, when you create a **Production** instance for a custom domain.

> Menu labels drift over time — Clerk reshuffles their dashboard. The concepts
> (API keys, Organizations, Restrictions) are stable; use the dashboard search
> box if a label doesn't match.
