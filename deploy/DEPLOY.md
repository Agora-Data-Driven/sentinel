# Deploying Sentinel to Google Cloud Run

Sentinel deploys the same way as Agora **Atrium** — a container on **Cloud Run**, built by
**Cloud Build**, deployed with `--no-invoker-iam-check` (the org's Domain-Restricted-Sharing policy
rejects `--allow-unauthenticated`; Sentinel does its own JWT auth in-process).

> **Important:** Cloud Run is **stateless** — the container filesystem is wiped on every restart or
> scale event. So **production needs Cloud SQL (Postgres)**, not SQLite. A single-instance SQLite
> "demo" mode exists for a quick look, but its data is ephemeral.

Defaults match Agora's infra: project `agora-data-driven`, region `asia-southeast1`, Artifact
Registry repo `agora`. Override any of them with the script params.

---

## 0. One-time prerequisites

```powershell
gcloud auth login
gcloud config set project agora-data-driven

# Enable the APIs Sentinel uses
gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
  artifactregistry.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com

# Artifact Registry repo (skip if the shared 'agora' repo already exists)
gcloud artifacts repositories create agora --repository-format=docker --location=asia-southeast1 2>$null
```

Create the **JWT secret** (used in every mode):
```powershell
# Generate a strong random secret and store it
python -c "import secrets; print(secrets.token_urlsafe(48))" | `
  gcloud secrets create sentinel-jwt-secret --data-file=-
```

---

## Option A — Production (Cloud SQL Postgres)  ✅ recommended

### 1. Create the database
```powershell
# NOTE: agora-data-driven defaults to the ENTERPRISE_PLUS edition, which rejects the shared-core
# db-f1-micro tier. Pass --edition=ENTERPRISE to use the small/cheap tier.
gcloud sql instances create sentinel-db `
  --database-version=POSTGRES_16 --edition=ENTERPRISE --tier=db-f1-micro --region=asia-southeast1
gcloud sql databases create sentinel --instance=sentinel-db
gcloud sql users create sentinel --instance=sentinel-db --password="CHOOSE-A-STRONG-PASSWORD"
```
Find the **instance connection name** (`PROJECT:REGION:INSTANCE`):
```powershell
gcloud sql instances describe sentinel-db --format="value(connectionName)"
# → agora-data-driven:asia-southeast1:sentinel-db
```

### 2. Store the DATABASE_URL secret
Cloud Run reaches Cloud SQL over a unix socket at `/cloudsql/<connectionName>`:
```powershell
$conn = "agora-data-driven:asia-southeast1:sentinel-db"
"postgresql+psycopg2://sentinel:CHOOSE-A-STRONG-PASSWORD@/sentinel?host=/cloudsql/$conn" | `
  gcloud secrets create sentinel-database-url --data-file=-
```

### 3. Deploy
```powershell
.\deploy\deploy.ps1 -CloudSqlInstance "agora-data-driven:asia-southeast1:sentinel-db"
```

### 4. Seed the demo data (optional) or start empty
- **Start empty (real launch):** do nothing — the app auto-creates empty tables on first boot.
  Then add your first Super Admin (see "Bootstrapping real users" below).
- **Load the demo dataset:**
  ```powershell
  .\deploy\seed-job.ps1 -CloudSqlInstance "agora-data-driven:asia-southeast1:sentinel-db"
  ```

---

## Option B — Quick demo (ephemeral SQLite)

One command, no database to set up. **Data resets on every restart** — for a look-around only:
```powershell
.\deploy\deploy.ps1 -DemoSqlite
```
This pins the service to a single instance and leaves DEV_LOGIN on. To seed it, the simplest path is
to redeploy from an image that seeds on boot — but since the data is throwaway anyway, most people
just click through the empty app. Prefer Option A for anything real.

---

## Bootstrapping real users (empty production start)

With `DEV_LOGIN_ENABLED=false` there's no dropdown login. Two ways to get your first admin in:

1. **Wire Google OAuth** (recommended): set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (as secrets),
   then complete the OAuth callback wiring in `app/routers/auth.py` (stubbed in this MVP).
2. **Seed a minimal admin** via the seed job, then edit/disable the rest in the People page.

---

## Updating after a code change

Just re-run the deploy — Cloud Build rebuilds the image and Cloud Run rolls out a new revision:
```powershell
.\deploy\deploy.ps1 -CloudSqlInstance "agora-data-driven:asia-southeast1:sentinel-db"
```

## Custom domain (like atrium.agoradatadriven.com)

```powershell
gcloud run domain-mappings create --service sentinel `
  --domain sentinel.agoradatadriven.com --region asia-southeast1
```
Then add the shown DNS records at your registrar. Cloud Run provisions the TLS cert automatically.

---

## Cost note
`db-f1-micro` Cloud SQL + a scale-to-zero Cloud Run service is a few dollars/month at low traffic.
Cloud SQL bills while the instance exists (it doesn't scale to zero) — stop it when unused:
`gcloud sql instances patch sentinel-db --activation-policy=NEVER`.

## Troubleshooting
- **403 on the URL:** expected if you open it before logging in — the app gates everything behind
  auth. Hit `/login` (demo) or your OAuth flow.
- **Build fails:** check `gcloud builds list` / the build log link it prints.
- **DB connection errors:** confirm `--add-cloudsql-instances` matches the secret's `host=/cloudsql/…`
  connection name exactly, and that the runtime service account has `roles/cloudsql.client`.
- **GitHub auto-deploy fails with `unauthorized_client … rejected by the attribute condition`:**
  the Workload Identity provider doesn't trust this repo's OIDC token (it was set up for a
  different repo/org). Fix it once, logged in as an IAM admin:
  ```powershell
  .\deploy\fix-github-oidc.ps1            # dry run: shows the current config + planned changes
  .\deploy\fix-github-oidc.ps1 -Apply     # apply (scopes trust to Agora-Data-Driven/sentinel)
  ```
  Then re-run **Actions → "Deploy Sentinel to Cloud Run" → Run workflow**. Until it's fixed, deploy
  manually with `deploy.ps1` above (that uses your own `gcloud auth login`, not the GitHub identity).

## Applying database migrations
The container runs `alembic`-based migrations at startup via `backend/entrypoint.sh` →
`backend/migrate.py`, which is safe on any DB state: it runs `alembic upgrade head` on a fresh or
already-stamped database, and `alembic stamp head` to adopt an existing schema that was originally
built by `create_all` (no data touched). Nothing extra to run by hand.
