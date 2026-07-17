# NC–SC–VA Commercial Insurance Lead Intelligence Workbench

A local, single-user research system for discovering and reviewing independently controlled, 2–5-location commercial P&C prospects. The system keeps every material claim tied to evidence, separates qualification from ranking, and produces reviewed XLSX/CSV evidence packs instead of automating outreach.

**New user?** Start with the [Workbench User Guide](docs/USER_GUIDE.md). It explains every tab and includes a complete prospecting example from discovery through export.

## What is implemented

- Docker Compose services for FastAPI, Celery worker/scheduler, PostGIS/PostgreSQL, Redis, and the React workbench.
- Append-only field assertions with source, record ID/URL, retrieval time, authority, confidence, parser version, hash, retention class, excerpt, and conflict state.
- One account lifecycle from prospect through active/former client, with relationship profiles, interaction cards, linked follow-ups, meetings, and append-only policy snapshots.
- Versioned research assessments, readiness decisions, research batches, crawl-page freshness/errors, and bounded automatic free-research scheduling.
- Overture GeoParquet, recursive/conditional robots-aware first-party crawling, SAM.gov, USAspending, SEC EDGAR, GLEIF, Google Places IDs-only, and opt-in Hunter/domain-email verification connectors.
- Generic CSV/XLSX ingestion for official NC, SC, VA, OSHA, FMCSA, EPA, and TTB snapshots.
- Exact-key ingestion and reviewable fuzzy entity links; account groups count premises across brands and states.
- Qualification gates and a versioned, fully reconciled 0–100 `rules-v2` score.
- Gap-driven free-public and paid-AI research with independent identity/footprint, ownership/control, operations/exposures, and people/events passes; hard batch/per-lead ceilings; complete source capture; and attempt-based completeness.
- Exact-category vertical exclusion, protected classification repair, structured services/exposures/ownership/events, and an accepted-website follow-up crawl.
- Google Calendar OAuth with encrypted refresh tokens, deterministic event IDs, readiness gating, five-minute incremental synchronization, etag conflict handling, and strict private-note separation.
- Local authentication, source/run health, lead and match review, suppression, manual coverage evidence, outcomes, and evidence-pack APIs.
- A responsive React workbench for the complete review workflow.
- Synthetic NC, SC, and VA examples plus automated edge-case tests. No sample is a real lead.

## Start locally

1. Create the local environment file and replace every `CHANGE-ME` value (admin login, `JWT_SECRET`, `POLICY_HMAC_SECRET`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` — the same password must appear inside `REDIS_URL`):

   ```powershell
   Copy-Item .env.example .env
   ```

   Generate strong secrets with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

2. Start the stack:

   ```powershell
   docker compose up --build -d
   ```

3. Optionally load synthetic examples:

   ```powershell
   docker compose exec api python -m app.seed
   ```

4. Open `http://localhost:8080` and use the `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`.

Only `127.0.0.1:8000` and `127.0.0.1:8080` are published. PostgreSQL and Redis remain internal to Compose, and Redis requires `REDIS_PASSWORD`.

### Optional research automation and Google Calendar

Keep `AUTO_RESEARCH_ENABLED=false` until enabled source policies have been reviewed. When enabled, the scheduler selects at most `AUTO_RESEARCH_BATCH_SIZE` new/stale active accounts every 15 minutes and uses only approved free/open sources. `FREE_API_RESEARCH_ENABLED` separately enables SAM.gov, USAspending, SEC EDGAR, and GLEIF attempts; configure `SAM_GOV_API_KEY` and a descriptive `SEC_USER_AGENT` where required. Paid sources still require explicit API authorization and hard ceilings.

Calendar uses this application's Google OAuth web-server credentials. Configure an OAuth redirect for `http://localhost:8000/api/integrations/google-calendar/callback`, generate a dedicated `GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY`, set the remaining `GOOGLE_CALENDAR_*` values, and only then set `CALENDAR_ENABLED=true`. Startup fails closed if the flag is enabled with incomplete credentials. The app requests calendar-list read access and owned-event read/write access; it never copies private preparation, policy, or relationship notes into Google.

**Upgrading an existing install:** containers now run as a non-root user. If your `lead_data` volume was created before this change, fix its ownership once:

```powershell
docker compose run --rm -u root api chown -R 10001:10001 /data
```

## Deploy publicly (HTTPS)

Never expose the plain-HTTP ports to the internet. Use the production overlay, which puts Caddy (automatic Let's Encrypt TLS) in front and hardens the API:

1. In `.env` set `ENVIRONMENT=production`, `DOMAIN=leads.example.com`, `ACME_EMAIL=you@example.com`, and `CORS_ORIGINS=https://leads.example.com`.
2. Point the domain's DNS at the host; open ports 80 and 443.
3. Start: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d`

In production the API marks session cookies `Secure` and disables `/docs`, `/redoc`, and `/openapi.json`. Login is rate limited (8 failures per 15 minutes per IP). Browser sessions use an HttpOnly `SameSite=Strict` cookie; programmatic clients may still send `Authorization: Bearer <token>` from `POST /api/auth/login`.

## Core workflow

1. Configure an Overture release or local GeoParquet URI, then start a small NC discovery run. Overture is discovery evidence only and cannot verify owner-controlled location totals by itself.
2. Import acquired official snapshots from **Runs & imports**. Uploaded bytes are stored once by SHA-256 hash.
3. Work the **Research queue**. New/stale active leads can receive bounded approved free research automatically when `AUTO_RESEARCH_ENABLED=true`; paid APIs are never included.
4. Run a paid AI batch only after selecting leads, approving `openai_web_research`, and setting both per-lead and total hard ceilings. Review every proposed finding and readiness blocker.
5. Resolve proposed matches; exact domains, phones, authoritative entity IDs, and known permit IDs link deterministically.
6. Complete the generated manual SOS and workers' compensation tasks where protected portals require human lookup.
7. Use **Interactions**, **Policies**, and **Meetings** on the same account. Scheduling requires a current contact-ready assessment or a reasoned audited override.

8. Connect Google Calendar from **Calendar** only after configuring application OAuth. Attendee-visible fields never receive research, policy, relationship, or preparation notes.
9. Export approved A–C leads. The ZIP contains XLSX, equivalent UTF-8 CSVs, and a manifest fingerprint.

### Understanding Source Health

The **Source health** page is an operational and policy dashboard:

- **Healthy:** enabled, policy-approved, free of a current error, and successfully used within its freshness window.
- **Stale:** approved and enabled, but never successfully used or older than its configured freshness window. A new installation normally starts with many stale sources.
- **Manual only:** intentionally requires a person to perform the lookup or import; it should not be made automatic merely to obtain a green status.
- **Pending:** terms, licensing, or the permitted acquisition method still require human review.
- **Disabled:** the source switch is off. **Error** means its latest attempt failed. **Blocked** means policy review prohibits its use.

The switch changes only whether the source is available for new work. It does not approve terms, add credentials, start a run, authorize paid usage, or erase previously collected evidence. To make an approved automated source healthy, configure any required credentials, enable its feature flag, restart the services, and complete one successful research or import attempt. You should not expect every source to become healthy: manual-only and protected-portal sources deliberately remain human-operated.

The application still runs when no source is healthy, and stale status alone does not block an approved source from running. However, automated discovery and enrichment will be limited, research will contain more unresolved dimensions, and fewer leads will pass the contact-readiness gate. If the first-party website source is disabled or unapproved, automatic free-research queueing is also disabled. See [Source health in the user guide](docs/USER_GUIDE.md#source-health) for the complete operational reference.

The Google connector stores only Place IDs. A user-confirmed live validation returns a transient attributed view that is not written to the lead graph. Hunter remains disabled per run until commercial use and a hard budget are explicitly supplied.

## Commands

```powershell
# Backend tests
python -m pip install -e "backend[test]"
python -m pytest backend/tests

# Frontend production build
Set-Location frontend
npm.cmd install
npm.cmd test
npm.cmd run build

# Compose configuration
docker compose config --quiet

# Create a compressed PostgreSQL backup in the named backup volume
docker compose --profile maintenance run --rm backup

# Preview the idempotent NC Overture geography repair
docker compose exec api python -m app.repair_overture --states NC

# Apply it after reviewing the preview and taking a backup
docker compose exec api python -m app.repair_overture --states NC --apply

# Preview the exact-category/franchise classification repair
docker compose exec api python -m app.repair_classification

# Apply only after reviewing the preview
docker compose exec api python -m app.repair_classification --apply
```

To inspect or copy backup files:

```powershell
docker compose run --rm --entrypoint sh backup -c "ls -lh /backups"
docker compose run --rm --entrypoint sh backup -c "cat /backups/NAME.dump" > NAME.dump
```

Test a restore into a disposable database before relying on a backup. Stop writers during a production restore.

## Public local API

All protected endpoints accept the browser session cookie or `Authorization: Bearer <local JWT>`.

- `POST /api/auth/login` / `POST /api/auth/logout`
- `GET /api/system/health` (authenticated dependency status)
- `POST /api/runs`
- `GET /api/leads`
- `GET /api/leads/{id}`
- `POST /api/leads/{id}/enrich`
- `POST /api/leads/{id}/research-runs`
- `POST /api/leads/{id}/ai-analysis-runs`
- `POST /api/leads/{id}/website-candidates`
- `GET /api/leads/{id}/research-runs`
- `GET /api/research-runs/{id}`
- `POST /api/research-findings/{id}/decision`
- `POST /api/research-runs/{id}/approve-paid`
- `POST /api/research-runs/{id}/steps/{step}/retry`
- `GET /api/research/queue`
- `GET/POST /api/research/batches`
- `GET /api/leads/{id}/research-assessment`
- `POST /api/leads/{id}/readiness-override`
- `PATCH /api/leads/{id}/sales-stage`
- `PATCH /api/leads/{id}/profile`
- `POST /api/leads/{id}/people` / `PATCH /api/people/{id}`
- `GET/POST /api/leads/{id}/activities`
- `PATCH /api/activities/{id}`
- `GET/POST /api/leads/{id}/tasks`
- `PATCH /api/tasks/{id}`
- `POST /api/leads/{id}/coverage`
- `POST /api/leads/{id}/policies` / `POST /api/policies/{id}/supersede`
- `GET/POST /api/leads/{id}/meetings`
- `PATCH /api/meetings/{id}` / `POST /api/meetings/{id}/sync` / `POST /api/meetings/{id}/cancel`
- `GET /api/integrations/google-calendar/status`
- `POST /api/integrations/google-calendar/connect` / `GET /api/integrations/google-calendar/callback`
- `POST /api/integrations/google-calendar/sync` / `DELETE /api/integrations/google-calendar`
- `POST /api/leads/{id}/google-validation`
- `POST /api/leads/{id}/review`
- `POST /api/leads/{id}/outcomes`
- `POST /api/matches/{id}/decision`
- `POST /api/exports`
- `GET /api/sources/health`
- `PATCH /api/sources/{id}/policy`
- `POST /api/admin/classification-repair`
- `GET /api/model-readiness`
- `POST /api/suppressions`

Interactive OpenAPI documentation is available at `http://localhost:8000/docs` in local development only; it is disabled when `ENVIRONMENT=production`.

## Production boundary

This is a research and review workbench, not legal advice and not an outreach engine. Before real use, a human must review current source terms, bulk-data permissions, licensing obligations, retention rights, CAN-SPAM procedures, and applicable privacy rules. Never bypass authentication, CAPTCHAs, access controls, or a site's robots rules. Do not scrape LinkedIn or the NC SOS interactive UI.

See the [Workbench User Guide](docs/USER_GUIDE.md), [source acquisition](docs/SOURCE_ACQUISITION.md), [scoring and review](docs/SCORING_AND_REVIEW.md), and [data model](docs/DATA_MODEL.md).
