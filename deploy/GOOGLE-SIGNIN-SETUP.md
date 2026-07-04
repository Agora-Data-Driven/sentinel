# Enabling "Sign in with Google" for Sentinel

Password login already works. This adds the **Continue with Google** button so your team can sign in
with their Agora Google accounts. ~10 minutes, one time.

> Only people who've been **added in Manage → Employees** (matched by their email) can get in —
> Google sign-in verifies identity, it does not grant access by itself.

## 1. OAuth consent screen (once)
GCP Console → **APIs & Services → OAuth consent screen** (project `agora-data-driven`):
- User type: **Internal** (so only `@agoradatadriven.com` Workspace accounts can use it). If your
  employees use a different Google domain, choose **External** and add them as test users, or publish.
- App name: `Sentinel`, support email: your email → Save.

## 2. Create the OAuth client
APIs & Services → **Credentials → Create credentials → OAuth client ID**:
- Application type: **Web application**
- Name: `Sentinel Web`
- **Authorized redirect URIs** → add exactly:
  ```
  https://sentinel-585951669065.asia-southeast1.run.app/api/auth/google/callback
  ```
- Create → copy the **Client ID** and **Client secret**.

## 3. Give them to Sentinel + redeploy
Either send me the Client ID + secret and I'll wire it, or run this (from `sentinel/`):

```powershell
# store the secret
"PASTE_CLIENT_SECRET" | gcloud secrets create sentinel-google-client-secret --data-file=- `
  --project agora-data-driven
# let the runtime SA read it
gcloud secrets add-iam-policy-binding sentinel-google-client-secret `
  --member="serviceAccount:sentinel-run@agora-data-driven.iam.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor" --project agora-data-driven

# wire the client id + prod redirect URI (env) and the secret (Secret Manager) onto the
# running service — no rebuild needed, this just updates the current revision's config.
gcloud run services update sentinel --project agora-data-driven --region asia-southeast1 `
  --update-env-vars "GOOGLE_CLIENT_ID=PASTE_CLIENT_ID,GOOGLE_REDIRECT_URI=https://sentinel-585951669065.asia-southeast1.run.app/api/auth/google/callback" `
  --update-secrets "GOOGLE_CLIENT_SECRET=sentinel-google-client-secret:latest"
```

> ⚠️ `GOOGLE_REDIRECT_URI` **must** be set (as above) and match the redirect URI you added in step 2
> exactly — it defaults to `localhost` for local dev, so without this the prod flow would fail.

That's it — the login page then shows **Continue with Google** automatically.

## How your team signs in
1. You add each person in **Manage → Employees** (name, email, role, department). Their email must
   match the Google account they'll use.
2. They open the site → **Continue with Google** → done. (Or use the password you set for them.)
