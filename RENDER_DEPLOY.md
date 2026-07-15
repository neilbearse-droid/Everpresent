# Deploying EverPresent on Render

This is the no-prior-experience guide. Render hosts the whole app for you —
no server to manage, no SSH, no Linux. You connect this GitHub repo, Render
reads `render.yaml`, and builds everything. Budget ~30 minutes, most of it
waiting for builds.

You'll need three accounts, all free to start: **GitHub** (you have it —
that's where this code lives), **Clerk** (logins), and **Render** (hosting).
Plus an **OpenAI** API key for the actual measurement.

---

## Step 1 — Get your Clerk keys (logins)

See **CLERK_SETUP.md** for the click-by-click. You come out of it with three
values:

- `CLERK_PUBLISHABLE_KEY` (starts `pk_`)
- `CLERK_SECRET_KEY` (starts `sk_`)
- `CLERK_JWKS_URL` (ends `/.well-known/jwks.json`)

Keep them in a note for Step 4. Starting with Clerk's **Development** instance
is fine.

## Step 2 — Get an OpenAI API key

- Go to **platform.openai.com**, sign in, → **API keys** → **Create new
  secret key**. Copy it (starts `sk-`). That's `OPENAI_API_KEY`.
- Add a little credit under **Billing** (even $5 lasts a long time — runs are
  capped per tenant so you can't overspend).

## Step 3 — Create the Render Blueprint

1. Go to **render.com**, sign up, and connect your **GitHub** account when it
   asks (authorize Render to see the `Everpresent` repo).
2. In the Render dashboard: **New +** → **Blueprint**.
3. Pick the **`Everpresent`** repository. Render finds `render.yaml`
   automatically and shows the services it will create: `everpresent-api`,
   `everpresent-web`, `everpresent-worker`, a Postgres database, and Redis.
4. Click **Apply**. Render starts creating everything. The first build takes
   several minutes (the worker downloads a browser for scraping — that one is
   slowest).

## Step 4 — Fill in the secrets

Render will prompt you for the values marked "not synced" (the ones we keep
out of the code). If it doesn't prompt during Apply, open each service →
**Environment** and add them there. Set these:

On **everpresent-api**:

| Key | Value |
|---|---|
| `SUPERADMIN_EMAIL` | your email (`neil.bearse@gmail.com`) — this becomes the admin login |
| `CLERK_SECRET_KEY` | from Step 1 |
| `CLERK_PUBLISHABLE_KEY` | from Step 1 |
| `CLERK_JWKS_URL` | from Step 1 |
| `OPENAI_API_KEY` | from Step 2 |

On **everpresent-web**:

| Key | Value |
|---|---|
| `CLERK_SECRET_KEY` | same as above |
| `CLERK_PUBLISHABLE_KEY` | same as above |

On **everpresent-worker**:

| Key | Value |
|---|---|
| `OPENAI_API_KEY` | same as above |

(The database URL, Redis URL, and everything else wire themselves up
automatically — you only touch the secrets.)

Leave the `SMTP_*` and BigQuery fields blank for now — email reports and the
warehouse mirror are optional and switch on later (see the main README).

Click **Save** on each; Render redeploys the changed services.

## Step 5 — (Development instance: nothing to do)

If you're using a Clerk **Development** instance (the `pk_test_…` key), it
accepts logins from any URL — including your `onrender.com` one — so there is
**nothing to configure here**. Clerk's Domains page even says the allowlist
"is not available on development instances." Skip straight to Step 6.

(Only when you later create a **Production** instance for a custom domain do
you configure the Primary domain there. Not needed to log in now.)

## Step 6 — Create your admin user and log in

The app is invite-only (public sign-ups are off), so you create the first
admin directly in Clerk rather than self-registering:

1. Clerk dashboard → **Users** → **+ Create user**.
2. Use the **same email** you set as `SUPERADMIN_EMAIL`, and set a password.
3. On your `onrender.com` site → **Sign in** (not sign up) with those
   credentials.

Because the email matches `SUPERADMIN_EMAIL`, the app links you to the seeded
superadmin account on first login. You're in, as the admin. 🎉

(This is also how you add client users later: create/invite them in Clerk,
and they sign in.)

That's the deploy done. From here, follow the "Activate Smith" steps in
`LAUNCH.md` (create the Clerk organization, approve the tenant, trigger a
run).

---

## What this costs

Render bills per service, monthly:

| Service | Plan | ~Cost |
|---|---|---|
| Web (frontend) | Starter | ~$7 |
| API | Starter | ~$7 |
| Worker (has the browser) | Standard | ~$25 |
| Postgres | Basic | ~$7 |
| Redis (Key Value) | Starter | ~$10 |
| **Total** | | **~$55/mo** |

Plus OpenAI usage (~$5–10/mo for weekly runs, hard-capped per tenant).

**Cheaper options:**
- Switch the model to `gpt-4o-mini` (`OPENAI_MODEL` on api + worker) — cuts AI
  cost ~10×.
- The worker is the pricey service because it runs a browser for the
  ChatGPT/Perplexity/Google scraping. If you only need the API-based
  measurement (OpenAI) at first, you can put the worker on a smaller plan —
  ask and I'll adjust `render.yaml`.

## If something goes wrong

- **A service shows "Deploy failed":** open it → **Logs**. The usual cause is
  a missing secret from Step 4.
- **Login redirects somewhere broken:** you probably skipped Step 5 (telling
  Clerk about your live URL).
- **"Free" Postgres note:** Render's cheapest Postgres is a paid Basic plan;
  the free database tier expires after 90 days, so the blueprint uses Basic to
  avoid a surprise outage.

Bring me any log message and I'll tell you exactly what to change.
