<#
  deploy.ps1 - build + deploy Sentinel to Google Cloud Run.

  Mirrors Agora Atrium's pattern: build the image with Cloud Build, then `gcloud run deploy`
  with --no-invoker-iam-check (org policy rejects --allow-unauthenticated; Sentinel does its own
  JWT auth in-process). Run from the sentinel/ root, e.g.:

    # Production (Cloud SQL Postgres) - see DEPLOY.md for one-time setup of the DB + secrets:
    .\deploy\deploy.ps1 -CloudSqlInstance "agora-data-driven:asia-southeast1:sentinel-db"

    # Quick demo (ephemeral SQLite, single instance - data resets on restart):
    .\deploy\deploy.ps1 -DemoSqlite

  Prereqs: gcloud installed + `gcloud auth login`, and the one-time setup in DEPLOY.md
  (APIs enabled, Artifact Registry repo, secrets, and - for prod - the Cloud SQL instance).
#>
param(
  [string]$Project          = "agora-data-driven",
  [string]$Region           = "asia-southeast1",
  [string]$Repo             = "agora",
  [string]$Service          = "sentinel",
  [string]$CloudSqlInstance = "agora-data-driven:asia-southeast1:sentinel-db",  # PROJECT:REGION:INSTANCE
  [switch]$DemoSqlite,
  [string]$ServiceAccount   = "sentinel-run@agora-data-driven.iam.gserviceaccount.com",
  [string]$JwtSecretName    = "sentinel-jwt-secret",    # Secret Manager secret name
  [string]$DbUrlSecretName  = "sentinel-database-url",  # Secret Manager secret name (prod)
  # Portal SSO + cross-app links. These MUST be set on every deploy: `gcloud run deploy
  # --set-*` replaces each category wholesale, so leaving them out silently wipes them and
  # breaks "sign in via the portal" (the ag_sso handoff) until someone re-adds them by hand.
  [string]$SsoSecretName    = "platform-sso-key",       # Secret Manager secret (portal ag_sso HMAC key)
  [string]$PortalLoginUrl   = "https://portal.agoradatadriven.com/login",
  [string]$SkillMasteryUrl  = "https://mastery.agoradatadriven.com",
  # 🔴 THE HOST SENTINEL IS MEANT TO BE REACHED ON. Both hosts serve this service, and they behave
  # DIFFERENTLY: `ag_sso` is scoped to `.agoradatadriven.com`, so on the raw *.run.app URL the portal
  # cookie is never sent, SSO is silently inert (`auth._sso_reachable`) and the password form is the
  # only door — while on the custom domain the portal IS the front door. So which URL somebody
  # happened to bookmark decided whether single sign-on worked for them at all, and an SSO-only
  # account (no password_hash) reaching the run.app host had NO way in. `config.canonical_host` was
  # written for exactly this and this script never passed it, so it has been empty in production the
  # whole time. The redirect is narrow by construction — GET + Accept: text/html + a *.run.app host
  # only, so APIs, probes and the run.app fallback are untouched (main._canonical_host_redirect).
  [string]$CanonicalHost    = "sentinel.agoradatadriven.com",
  # Must match a redirect URI registered on the OAuth client. Points at the canonical host because a
  # browser hitting the run.app callback is now redirected there, and `g_oauth_state` was set on
  # whichever host started the flow — split them and every Google sign-in fails its state check.
  # (Google is unconfigured in production today: GOOGLE_CLIENT_ID is not set, so the button is hidden.)
  [string]$GoogleRedirectUri = "https://sentinel.agoradatadriven.com/api/auth/google/callback",
  # The portal origin the ATRIUM TASK BRIDGE calls (services/atrium_tasks.py). Atrium owns the
  # client-facing tasks; the board reads them over HMAC so a card typed into a client's Atrium
  # shows up here. Omit it and the bridge falls back to PORTAL_LOGIN_URL's origin; if neither
  # resolves the board simply shows Sentinel's own rows.
  [string]$AtriumApiUrl     = "https://portal.agoradatadriven.com",
  # 🔴 CRON_KEY had existed as a SECRET since 2026-07-04 and was never passed to the service, so
  # `cron._authorize`'s header branch could never match and NOTHING could drive /api/cron/* — the
  # whole daily pass was reachable only by a Super Admin clicking a button. A Cloud Scheduler job
  # without this gets a silent 403 forever, so the two must ship together.
  [string]$CronKeySecretName = "sentinel-cron-key",
  # The daily personal context report (services/personal_report -> report_doc). Blank doc id or
  # email = the feature stays off. 🔴 The Doc is REPLACED WHOLESALE on every run.
  [string]$ReportDocId      = "1XCNoSOeD9iFWBYvKrkUsAJjjf032newyeRVPxlDJNBU",
  [string]$ReportUserEmail  = "ianfernandezctm@gmail.com",
  # 🔴 Required for the Drive write. The metadata server issues this service a `cloud-platform`
  # token and the Drive API refuses it, so report_doc exchanges it for a Drive-scoped one by having
  # the account impersonate ITSELF (needs roles/iam.serviceAccountTokenCreator on itself, granted
  # 2026-08-09). Leaving this blank produces a 403/404 that looks exactly like the document never
  # having been shared.
  [string]$ReportImpersonateSa = "sentinel-run@agora-data-driven.iam.gserviceaccount.com",
  # 🔴 ONE WARM INSTANCE. Sentinel had no --min-instances, so it scaled to zero and the first person
  # to open it after any quiet spell paid a full cold start: pull the image, `alembic upgrade head`
  # (entrypoint.sh), then create_all + _ensure_columns' per-table inspect() + three seed/backfill
  # passes. That is the "the morning's first click takes forever" complaint, and it recurred on every
  # scale-up all day. This is a real (small) standing cost — pass `-MinInstances 0` to trade it back
  # for cold starts.
  [int]$MinInstances        = 1,
  # AI task drafting (2026-09-02). See the Vertex block below.
  [bool]$VertexEnabled      = $true,
  [string]$VertexLocation   = "global",          # `global` serves flash AND pro; asia-southeast1 404s on pro
  [string]$VertexModel      = "gemini-2.5-flash",
  # 🔴 Cloud Run's default cap is 100 and Sentinel had no cap at all. Every instance opens its OWN
  # connection pool (app/config.py: 5 held + 15 burst), and `db-f1-micro` allows only ~25 connections
  # for the whole estate — so this number and the pool are ONE decision: worst case is
  # (pool_size + max_overflow) x MaxInstances = 60 here. Raise them together or neither.
  # 3 x the default concurrency of 80 is ~240 in-flight requests, and note that every open browser
  # tab permanently holds one of those slots with its SSE stream (routers/stream.py).
  [int]$MaxInstances        = 3
)
$ErrorActionPreference = "Stop"

# Resolve to the repo root (parent of this script's folder) so the build context is correct.
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Image = "$Region-docker.pkg.dev/$Project/$Repo/${Service}:latest"

Write-Host "Building image via Cloud Build: $Image" -ForegroundColor Cyan
gcloud builds submit --project $Project --tag $Image .
if ($LASTEXITCODE -ne 0) { throw "Cloud Build failed." }

# Assemble deploy args.
$deployArgs = @(
  "run", "deploy", $Service,
  "--project", $Project,
  "--region", $Region,
  "--image", $Image,
  "--platform", "managed",
  "--no-invoker-iam-check",           # org policy: no --allow-unauthenticated; app does its own auth
  "--port", "8080",
  "--memory", "512Mi",
  "--service-account", $ServiceAccount,
  "--set-secrets", "JWT_SECRET=${JwtSecretName}:latest",
  "--set-secrets", "PLATFORM_SSO_SECRET=${SsoSecretName}:latest",  # portal SSO handoff — see note above
  "--set-secrets", "CRON_KEY=${CronKeySecretName}:latest"          # lets Cloud Scheduler drive /api/cron/*
)

# Production posture: passwordless DEV_LOGIN is OFF. Sign in with the bootstrap admin
# (melo@agora.ph — change the password immediately) or wire Google OAuth (see
# GOOGLE-SIGNIN-SETUP.md). If you MUST keep the dev-login dropdown temporarily, append
# ",ALLOW_DEV_LOGIN_IN_PROD=true" below — the app will boot with a loud SECURITY warning.
$envVars = "ENVIRONMENT=production,SECURE_COOKIES=true,DEV_LOGIN_ENABLED=false,TIMEZONE=Asia/Manila,PORTAL_LOGIN_URL=$PortalLoginUrl,CANONICAL_HOST=$CanonicalHost,SKILL_MASTERY_URL=$SkillMasteryUrl,GOOGLE_REDIRECT_URI=$GoogleRedirectUri,ATRIUM_API_URL=$AtriumApiUrl,REPORT_DOC_ID=$ReportDocId,REPORT_USER_EMAIL=$ReportUserEmail,REPORT_IMPERSONATE_SA=$ReportImpersonateSa"

# AI task drafting (services/ai_draft.py, 2026-09-02) — Vertex AI Gemini through the runtime SA, GCP-billed,
# no API key: the same pattern Atrium's deploy_dash_platform.ps1 uses. The SA needs roles/aiplatform.user
# or every call answers 403 — granted here idempotently (a repeat binding is a no-op), and the API is
# enabled the same way. Set -VertexEnabled:$false to ship with the Draft-with-AI button saying "unavailable".
if ($VertexEnabled) {
  gcloud services enable aiplatform.googleapis.com --project $Project *> $null
  gcloud projects add-iam-policy-binding $Project --member "serviceAccount:$ServiceAccount" --role "roles/aiplatform.user" --condition None *> $null
  $envVars += ",VERTEX_GEMINI_ENABLED=true,VERTEX_PROJECT=$Project,VERTEX_LOCATION=$VertexLocation,VERTEX_MODEL=$VertexModel"
}

if ($DemoSqlite) {
  Write-Host "DEMO mode: ephemeral SQLite, single instance (data resets on restart)." -ForegroundColor Yellow
  $envVars += ",DATABASE_URL=sqlite:////app/sentinel.db"
  $deployArgs += @("--min-instances", "1", "--max-instances", "1", "--set-env-vars", $envVars)
}
elseif ($CloudSqlInstance -ne "") {
  Write-Host "PROD mode: Cloud SQL $CloudSqlInstance" -ForegroundColor Cyan
  Write-Host "  min-instances=$MinInstances (0 = cold starts), max-instances=$MaxInstances" -ForegroundColor DarkGray
  $deployArgs += @(
    "--add-cloudsql-instances", $CloudSqlInstance,
    "--set-secrets", "DATABASE_URL=${DbUrlSecretName}:latest",
    "--min-instances", "$MinInstances",
    "--max-instances", "$MaxInstances",
    # Full CPU while the container boots (migrations + the seed/backfill passes), which is exactly
    # the window Cloud Run otherwise throttles. Costs nothing when there is no cold start to speed up.
    "--cpu-boost",
    "--set-env-vars", $envVars
  )
}
else {
  throw "Choose a database: pass -CloudSqlInstance <PROJECT:REGION:INSTANCE> (prod) or -DemoSqlite."
}

Write-Host "Deploying to Cloud Run..." -ForegroundColor Cyan
gcloud @deployArgs
if ($LASTEXITCODE -ne 0) { throw "Cloud Run deploy failed." }

$url = gcloud run services describe $Service --project $Project --region $Region --format "value(status.url)"
Write-Host ""
Write-Host "Deployed: $url" -ForegroundColor Green
Write-Host "Next: seed the database -> .\deploy\seed-job.ps1  (see DEPLOY.md)" -ForegroundColor Green
