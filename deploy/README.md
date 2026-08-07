# deploy/ — shipping Sentinel to Cloud Run

The deploy scripts and guides. One rule above all (from [../AGENTS.md](../AGENTS.md) §1): **always
`.\deploy\deploy.ps1` from the sentinel/ root, never a raw `gcloud run deploy`** — the script bakes
in the env/secrets that a hand deploy silently wipes. Full first-time setup: [DEPLOY.md](DEPLOY.md).

## File map

| Entry | What it is |
|---|---|
| `deploy.ps1` | Cloud Build the image, then `gcloud run deploy` with everything baked in: params block `:17-39` (project/region/service + `$SsoSecretName`, `$PortalLoginUrl`, `$SkillMasteryUrl`, `$GoogleRedirectUri`, `$AtriumApiUrl`), `--set-secrets` JWT + `PLATFORM_SSO_SECRET` `:63-64`, the **`$envVars` line `:71`** (ENVIRONMENT/SECURE_COOKIES/DEV_LOGIN_ENABLED/TIMEZONE/PORTAL_LOGIN_URL/SKILL_MASTERY_URL/GOOGLE_REDIRECT_URI/ATRIUM_API_URL), `-DemoSqlite` vs `-CloudSqlInstance` branch `:73-88` |
| `seed-job.ps1` | One-off Cloud Run job that runs `seed.py` against Cloud SQL (demo data) |
| `fix-github-oidc.ps1` | Repairs the GitHub-Actions Workload Identity trust (dry-run by default, `-Apply` to fix) |
| `DEPLOY.md` | One-time infra setup (APIs, Cloud SQL, secrets), bootstrap users, backups gap, troubleshooting |
| `GOOGLE-SIGNIN-SETUP.md` | Wiring `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (the code path is complete — `backend/app/routers/auth.py:163-221`) |

## Config contract (what deploy.ps1 bakes → who consumes it)

| Env / secret | Set at (deploy.ps1) | Consumed by | Breaks when missing |
|---|---|---|---|
| `JWT_SECRET` (secret `sentinel-jwt-secret`) | `:63` | `backend/app/security.py` | every session |
| `PLATFORM_SSO_SECRET` (secret `platform-sso-key`) | `:64` | `security.user_from_sso` / `sso.py`, `routers/internal.py` HMAC, atrium bridges | portal sign-in + every service-to-service call |
| `DATABASE_URL` (secret `sentinel-database-url`) | `:82` | `backend/app/database.py` | boot (prod) |
| `PORTAL_LOGIN_URL` | `$envVars :71` | login bounce, atrium bridge origin fallback | portal handoff |
| `SKILL_MASTERY_URL` | `$envVars :71` | iframe src + `middleware._permissions_policy` | Academy tabs + **microphone** |
| `GOOGLE_REDIRECT_URI` | `$envVars :71` | `routers/auth.py` OAuth flow | Google sign-in (redirect_uri mismatch) |
| `ATRIUM_API_URL` | `$envVars :71` | `services/atrium_tasks.py` / watcher bridge | Atrium cards vanish from the board (fail-soft) |

### Scaling flags (added 2026-08-07 — these are latency, not cosmetics)

| Flag | Value | Why |
|---|---|---|
| `--min-instances` | `1` (param `-MinInstances`) | Sentinel had none, so it scaled to **zero** and the first click after any quiet spell paid a full cold start: image pull → `alembic upgrade head` → `create_all` + `_ensure_columns`' per-table `inspect()` + three seed/backfill passes. That is the "the morning's first click takes forever" complaint, and it recurred on every scale-up all day. Real (small) standing cost — `-MinInstances 0` trades it back |
| `--cpu-boost` | on | Full CPU during boot, which is exactly the window Cloud Run otherwise throttles. Free when there is no cold start |
| `--max-instances` | `3` (param `-MaxInstances`) | Cloud Run's default is **100** and Sentinel had no cap. Each instance opens its own DB pool (`app/config.py`: 5 held + 15 burst) and `db-f1-micro` allows only ~25 connections for the whole estate — so worst case is `(5+15) × 3 = 60`. **This number and the pool are one decision**: raise them together or neither. 3 × the default concurrency of 80 is ~240 in-flight requests, and every open browser tab permanently holds one slot with its SSE stream |

`_mirror_clients` also came **off** the startup path the same day (`main._startup` runs it on a daemon
thread): startup handlers complete before uvicorn accepts a connection, so its 10s Atrium call was
being added to every cold start for a refresh its own docstring calls non-urgent.

🔴 **`--min-instances 1` has a non-obvious consequence: the service no longer restarts on its own.**
Anything that only ran at boot now effectively runs *once*. That bit the client mirror the same
afternoon — a client created in Atrium stayed unpickable in Sentinel for hours, with a healthy boot
log and no error. Fixed by giving it two more triggers (the daily pass and a **Sync now** button — see
[AGENTS.md](../AGENTS.md) §2). **Before adding boot-only work, ask what refreshes it now that nothing
restarts.**

## Cookbook

1. **Standard prod deploy** — from `sentinel/`: `.\deploy\deploy.ps1` (defaults already target
   `agora-data-driven` / `asia-southeast1` / Cloud SQL `sentinel-db`). Then verify (below).
2. **Add an env var** — add it to the `$envVars` string at `deploy.ps1:71` (and a param if it
   should be overridable). NEVER `gcloud run services update --set-env-vars` by hand — it replaces
   the whole category.
3. **Add a secret** — create it in Secret Manager, add a `--set-secrets` pair beside `:63-64`,
   grant the runtime SA (`sentinel-run@…`) accessor on it.
4. **Seed / reseed demo data** — `.\deploy\seed-job.ps1 -CloudSqlInstance "agora-data-driven:asia-southeast1:sentinel-db"`.
5. **Check what is actually serving** (read the WHOLE traffic array — `traffic[0]` can be a
   tagged old revision):
   ```powershell
   gcloud run services describe sentinel --project agora-data-driven --region asia-southeast1 `
     --format="yaml(status.traffic)"
   curl.exe -s https://sentinel-585951669065.asia-southeast1.run.app/api/health
   ```
6. **Roll back** — `gcloud run services update-traffic sentinel --project agora-data-driven
   --region asia-southeast1 --to-revisions <rev>=100` (or redeploy a good commit via `deploy.ps1`).
7. **GitHub auto-deploy 401s (`unauthorized_client`)** — `.\deploy\fix-github-oidc.ps1` (dry run),
   then `-Apply`; deploy by hand with `deploy.ps1` until fixed.

## Gotchas / DO NOT TOUCH

- **The env baking in `deploy.ps1` is the fix for a real outage** — a raw deploy once wiped
  `PLATFORM_SSO_SECRET` + the URLs and broke portal sign-in and the Academy mic. Every var stays
  on every deploy.
- **Don't wrap `deploy.ps1` in `2>&1`** — PowerShell 5.1 turns gcloud's stderr progress into
  ErrorRecords and the script dies mid-deploy. Run it bare.
- **Region is `asia-southeast1`**; deploy as `info@agoradatadriven.com` (verify the window's
  gcloud pin — see DEPLOY.md §0; never `gcloud config set`).
- **Last-deploy-wins** — another machine's `/go` can replace your revision; check the serving
  revision, not `git status`, before concluding anything (AGENTS.md §5).
- **Backups are NOT configured** on `sentinel-db` — open ops task; see DEPLOY.md "Backups".
- Migrations run at boot (`entrypoint.sh` → `migrate.py`); nothing to run by hand on deploy.

## Status (volatile)

- Live: `https://sentinel-585951669065.asia-southeast1.run.app` — serving revision
  **`sentinel-00112-mpl`** (verified 2026-07-29).
- Cloud SQL: `agora-data-driven:asia-southeast1:sentinel-db` (Postgres 16, ENTERPRISE,
  db-f1-micro). Secrets in use: `sentinel-jwt-secret`, `sentinel-database-url`, `platform-sso-key`.
- Runtime SA: `sentinel-run@agora-data-driven.iam.gserviceaccount.com`.
