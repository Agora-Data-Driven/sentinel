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
  [string]$GoogleRedirectUri = "https://sentinel-585951669065.asia-southeast1.run.app/api/auth/google/callback"
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
  "--set-secrets", "PLATFORM_SSO_SECRET=${SsoSecretName}:latest"   # portal SSO handoff — see note above
)

# Production posture: passwordless DEV_LOGIN is OFF. Sign in with the bootstrap admin
# (melo@agora.ph — change the password immediately) or wire Google OAuth (see
# GOOGLE-SIGNIN-SETUP.md). If you MUST keep the dev-login dropdown temporarily, append
# ",ALLOW_DEV_LOGIN_IN_PROD=true" below — the app will boot with a loud SECURITY warning.
$envVars = "ENVIRONMENT=production,SECURE_COOKIES=true,DEV_LOGIN_ENABLED=false,TIMEZONE=Asia/Manila,PORTAL_LOGIN_URL=$PortalLoginUrl,SKILL_MASTERY_URL=$SkillMasteryUrl,GOOGLE_REDIRECT_URI=$GoogleRedirectUri"

if ($DemoSqlite) {
  Write-Host "DEMO mode: ephemeral SQLite, single instance (data resets on restart)." -ForegroundColor Yellow
  $envVars += ",DATABASE_URL=sqlite:////app/sentinel.db"
  $deployArgs += @("--min-instances", "1", "--max-instances", "1", "--set-env-vars", $envVars)
}
elseif ($CloudSqlInstance -ne "") {
  Write-Host "PROD mode: Cloud SQL $CloudSqlInstance" -ForegroundColor Cyan
  $deployArgs += @(
    "--add-cloudsql-instances", $CloudSqlInstance,
    "--set-secrets", "DATABASE_URL=${DbUrlSecretName}:latest",
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
