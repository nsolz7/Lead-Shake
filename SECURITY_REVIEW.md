# Security Review — Lead Intelligence Workbench

## Remediation status (updated 2026-07-16, same day)

All findings below have been remediated in code except the four external actions only the operator can perform:

| # | Finding | Status |
|---|---------|--------|
| C1 | PII dump in repo root | **Fixed** — moved to gitignored `data/backups/`; `*.dump` ignored. *Still yours: move it off this machine to encrypted storage.* |
| C2 | Live secrets in `.env` | **Partly fixed** — `JWT_SECRET` rotated, `REDIS_PASSWORD` added. *Still yours: rotate Google/Hunter/OpenAI keys at the provider and `POSTGRES_PASSWORD` via `ALTER USER` (steps in `.env` comments). `POLICY_HMAC_SECRET` deliberately kept (rotation breaks dedup of imported policy records).* |
| C3 | No TLS | **Fixed** — `docker-compose.prod.yml` + `Caddyfile`: automatic Let's Encrypt TLS. |
| H1 | No login rate limiting | **Fixed** — 8 failures / 15 min per IP (Redis-backed, in-memory fallback, direct-peer backstop). Verified by test. |
| H2 | Missing security headers | **Fixed** — HSTS, CSP, X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy in nginx; `server_tokens off`; 260 MB body limit on `/api/` (imports previously broke at nginx's 1 MB default). |
| H3 | JWT in localStorage | **Fixed** — HttpOnly `SameSite=Strict` cookie (Secure in production); localStorage use removed; `POST /api/auth/logout` added; bearer tokens still accepted for API clients. Verified by test. |
| H4 | /docs exposed | **Fixed** — docs/redoc/openapi disabled when `ENVIRONMENT=production`. |
| M1 | Root containers | **Fixed** — backend runs as `appuser` (uid 10001); frontend on `nginx-unprivileged` (port 8080). *One-time for existing installs: `docker compose run --rm -u root api chown -R 10001:10001 /data`.* |
| M2 | /health detail public | **Fixed** — public `/health` returns bare ok; detail moved to authenticated `GET /api/system/health`. |
| M3 | Unvalidated link hrefs | **Fixed** — `safeHref()` allows only http/https before rendering external links. |
| M4 | Verbose errors | **Fixed** — Google validation transport errors now return a generic 503 (provider URLs/keys never surface). Remaining `str(exc)` cases are the app's own controlled validation messages. |
| M5 | Broad CORS | **Fixed** — methods pinned to GET/POST/PATCH/DELETE/OPTIONS; headers to Authorization + Content-Type. |
| L1 | Unpinned Python deps | **Mitigated** — `pip-audit` in CI + weekly Dependabot (pip, npm, actions, docker). Full lockfile still recommended. |
| L2 | Redis unauthenticated | **Fixed** — `requirepass` enforced; password required in `.env`. |
| L3 | No CI security scanning | **Fixed** — CI now runs pip-audit, `npm audit --audit-level=high`, gitleaks, and validates the prod overlay. |

Verification performed: auth/rate-limit/cookie/logout flow tested green against the real modules; frontend production build passes; all compose/CI YAML parses. Run `python -m pytest backend/tests` and `docker compose up --build` locally to confirm end-to-end.

---

# Original review

**Date:** 2026-07-16
**Reviewed build:** FastAPI + Celery/Redis + PostGIS backend, React/Vite + nginx frontend, Docker Compose
**Context:** App stores customer PII (names, phones, emails, addresses). Currently bound to `127.0.0.1`; owner intends to host publicly soon.

## Verdict

**Do not expose this build to the public internet as-is.** The application logic is reasonably clean — no SQL injection (SQLAlchemy ORM throughout), safe file-upload handling (SHA-256 paths, not filename), robots-aware scraping, and every endpoint requires auth. The gaps are in **secrets hygiene, transport security, and deployment hardening** — exactly the layers that matter most once this leaves localhost. Several are quick fixes.

The single most urgent item is the **plaintext database dump full of PII sitting in the repo root**, which was *not* covered by `.gitignore`. I fixed the ignore rules and added the missing `.env.example` (see "Changes I made" below), but the live secrets and the dump still need manual remediation.

---

## Findings by severity

### CRITICAL

**C1 — Unprotected PostgreSQL dump containing customer PII in repo root**
`leadintel-20260716T065438Z.dump` (2.2 MB, PostgreSQL custom-format) sits at the project root and was **not matched by `.gitignore`** — one `git add .` away from being committed and, if the repo is ever pushed, permanently exposed in history. It contains live lead data (contacts, phones, emails, addresses).
*Fix:* I added `*.dump` to `.gitignore`. You must still **move this file out of the repo tree** to an encrypted, access-controlled backup location. If it was ever committed, purge it from history (`git filter-repo`) and rotate anything derived from it. Store backups encrypted at rest.

**C2 — Live secrets present in `.env`, no rotation before going public**
`.env` contains real-looking production credentials: `JWT_SECRET`, `POLICY_HMAC_SECRET`, the Postgres password, and third-party API keys (`GOOGLE_MAPS_API_KEY` starting `AIza...`, `HUNTER_API_KEY`, `OPENAI_API_KEY` starting `sk-proj...`). `.env` is correctly gitignored, but the file exists on disk with real values and the admin password is stored/compared in plaintext.
*Fix:* Before public launch, **rotate every one of these secrets** (they've now been read during this review). Generate fresh high-entropy values: `python -c "import secrets; print(secrets.token_urlsafe(48))"` for `JWT_SECRET` and `POLICY_HMAC_SECRET`. Move production secrets into your host's secret manager (Docker secrets, AWS SSM/Secrets Manager, etc.) rather than a plaintext `.env` on the server.

**C3 — No TLS / HTTPS**
nginx listens on plain HTTP port 80 with no TLS. Publicly, that means the admin password, the JWT bearer token, and all customer PII travel in cleartext and are trivially interceptable.
*Fix:* Terminate TLS before this is reachable publicly — a reverse proxy (Caddy, Traefik, or nginx with certbot/Let's Encrypt) in front of the frontend container. Redirect all HTTP→HTTPS. Do not publish port 80 for app traffic once HTTPS is in place.

### HIGH

**H1 — No rate limiting or lockout on `/api/auth/login`**
Authentication is a single static admin username + password. There is no rate limit, no lockout, no CAPTCHA, so the one credential is open to unlimited online brute-force / credential-stuffing once public.
*Fix:* Add rate limiting (e.g. `slowapi` on the login route, or limit at the nginx/reverse-proxy layer). Consider a strong generated admin password and, ideally, a second factor given this guards customer PII.

**H2 — Missing HTTP security headers**
`nginx.conf` sets no security headers. Publicly this leaves you exposed to clickjacking, MIME sniffing, and downgrade attacks, and there is no Content-Security-Policy.
*Fix:* Add to the nginx server block: `Strict-Transport-Security` (after TLS), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a restrictive `Content-Security-Policy`. A starter config is in the appendix.

**H3 — JWT in `localStorage` + long-lived, non-revocable tokens**
The frontend stores the bearer token in `localStorage` (`frontend/src/api.ts`), which is readable by any injected script (XSS-exfiltratable). Tokens are HS256, valid 720 minutes (12 h), with no revocation list and no rotation.
*Fix:* Prefer an `HttpOnly`, `Secure`, `SameSite=Strict` cookie for the token so JS can't read it (pairs with a CSRF token). At minimum, shorten expiry, add refresh/rotation, and pair with the CSP in H2 to reduce XSS blast radius.

**H4 — Interactive API docs and OpenAPI schema exposed**
`/docs`, `/redoc`, and `/openapi.json` are served (FastAPI defaults, not disabled in `main.py`). Publicly this hands an attacker a complete, browsable map of every endpoint and schema.
*Fix:* Disable in production (`FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`) or gate them behind auth/allowlist.

### MEDIUM

**M1 — Containers run as root.** Neither `backend/Dockerfile` nor `frontend/Dockerfile` sets a `USER`; both run as root, so a container-escape or RCE starts with root. *Fix:* add a non-root `USER` and run the app as an unprivileged user.

**M2 — Unauthenticated `/health` dependency disclosure.** `/health` returns DB/Redis up/down status without auth — minor recon aid. *Fix:* return a bare `200` publicly and keep detail on an internal-only route.

**M3 — Attacker-influenced link `href`s.** In `App.tsx`, scraped `finding.source_url` / Google URIs are rendered directly into `<a href>`. React won't block a `javascript:` scheme, so a malicious scraped URL could yield script execution on click. *Fix:* validate scheme is `http(s)` before rendering; reject others.

**M4 — Verbose error details returned to clients.** Some handlers return `str(exc)` (e.g. the 503 path in enrich/validation), which can leak internal detail. *Fix:* return generic client messages; log specifics server-side (the request-ID logging is already in place — good).

**M5 — CORS allows all methods and headers.** `allow_methods=["*"], allow_headers=["*"]` with `allow_credentials=True`. Origins are explicitly listed (good), but widen only what you need. *Fix:* pin methods/headers to the actual set used.

### LOW

**L1 — Python dependencies are range-pinned, not locked.** `pyproject.toml` uses `>=,<` ranges with no lockfile/hashes, so builds aren't reproducible and a bad transitive release can slip in. *Fix:* add a hashed lockfile (`pip-tools`/`uv`) and enable Dependabot. *(Note: `npm audit` on the frontend returned **0 vulnerabilities** — that side is clean today.)*

**L2 — Redis has no auth.** Fine while internal to Compose, but never publish its port; add `requirepass` if it ever leaves the private network.

**L3 — No automated security scanning in CI.** `.github/workflows/ci.yml` runs tests/build only. *Fix:* add `pip-audit`, `npm audit`, and secret-scanning (e.g. gitleaks) to the pipeline.

---

## Priority checklist before going public

1. Move the `.dump` out of the repo; verify it was never committed. **(C1)**
2. Rotate JWT, HMAC, DB password, and all API keys; move to a secret manager. **(C2)**
3. Put TLS in front of everything; force HTTPS. **(C3)**
4. Rate-limit login + strong admin password / MFA. **(H1)**
5. Add nginx security headers + CSP. **(H2)**
6. Disable `/docs`, `/redoc`, `/openapi.json`. **(H4)**
7. Move token to HttpOnly cookie (or shorten + rotate). **(H3)**
8. Non-root containers. **(M1)**

## What's already solid

No raw SQL / no SQL-injection surface (ORM used throughout); file uploads stored by content hash with a fixed suffix (no path traversal) and size-capped; every business endpoint enforces `require_user`; robots-aware, rate-limited scraping; structured request-ID logging; secrets read from env, not hardcoded in source; paid connectors disabled by default with budget ceilings.

## Changes I made in this review

- **`.gitignore`** — added `*.dump`, `*.sql.gz`, and `.env.*` (keeping `!.env.example`) so backups and env files can't be committed.
- **`.env.example`** — created the template the README references but that was missing, with all keys blanked and a secret-generation hint. (Verify no real values before committing.)

*No application code was modified.* All fixes above are recommendations for you to apply.

---

### Appendix — starter nginx security headers

```nginx
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer" always;
add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'" always;
```
