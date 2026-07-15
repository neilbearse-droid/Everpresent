# Launch checklist

Everything left to go from "deployed" to "clients seeing dashboards." The app
code is built and tested; this is the human setup.

## 0. Deploy

- [ ] **Clerk** account + keys — see `CLERK_SETUP.md`
- [ ] **OpenAI** API key + a little billing credit
- [ ] **Render** blueprint deployed, secrets filled — see `RENDER_DEPLOY.md`
- [ ] Log in at your `…onrender.com` URL with your `SUPERADMIN_EMAIL` account

That's the "clickable, deployed app" milestone. Everything below activates a
client.

## 1. Activate Smith (unblocked launch tenant)

- [ ] In **Clerk** → Organizations: create the Smith organization, invite its
      members by email.
- [ ] In the app at **/admin/smith**:
  - [ ] Paste the Clerk org id (`org_…`) into "Clerk organization"
  - [ ] **Approve AI processing** (governance gate)
  - [ ] Enable the surfaces you want (`openai_api` for API measurement;
        `chatgpt_web` / `perplexity_web` / `google_aio` for scraped surfaces)
  - [ ] Set the monthly spend cap and notification emails
  - [ ] *(recommended)* Import the real Smith config YAML (the seeded corpus
        is a placeholder)
- [ ] Hit **Trigger run**, wait for it to complete, and confirm the Overview /
      Personas / Queries / Citations dashboards populate.
- [ ] Set the weekly schedule.

## 2. Activate Greenshield (after paperwork)

- [ ] Sign the third-party processing terms (spec §12.2). Their governance
      gate stays closed until then — Smith is unaffected.
- [ ] Then repeat Step 1 for `greenshield`.

## 3. Optional integrations (switch on anytime)

- [ ] **Email reports:** set `SMTP_*` env vars on the api + worker services.
- [ ] **BigQuery mirror:** set `BIGQUERY_PROJECT`, `BIGQUERY_DATASET`, and
      mount the service-account JSON; the nightly mirror starts on its own.
- [ ] **Google AIO accuracy:** label your 40 seed queries into
      `seeds/aio_labels.yaml` (template: `seeds/aio_labels.example.yaml`),
      then reprocess. Until then the AIO classifier uses provisional
      thresholds (see `DECISIONS.md` M6.1).

## Cost control

- Per-tenant monthly spend caps are enforced before every API call — you can't
  get a surprise bill.
- Switch `OPENAI_MODEL` to `gpt-4o-mini` (api + worker) to cut AI cost ~10×.
