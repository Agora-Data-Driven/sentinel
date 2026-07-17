<#
  fix-github-oidc.ps1 - repair the GitHub Actions -> Google Cloud keyless auth (Workload Identity
  Federation) that the "Deploy Sentinel to Cloud Run" workflow uses.

  WHY: the auto-deploy failed with
      unauthorized_client ... "The given credential is rejected by the attribute condition."
  That means the Workload Identity *provider* condition doesn't allow THIS repo's OIDC token. The
  repo is Agora-Data-Driven/sentinel, but the pool was set up for a different owner/repo
  (the upstream Agoradatadriven/Sentinel). This script points it at the right repo and binds the
  deploy service account to it.

  SAFE BY DEFAULT: with no switches it only INSPECTS and prints the exact commands it *would* run.
  Add -Apply to actually change anything.

  Prereqs: `gcloud auth login` as an account with IAM admin on the project (e.g. info@agoradatadriven.com).
  Run from anywhere:  .\deploy\fix-github-oidc.ps1            # dry run (inspect + show plan)
                      .\deploy\fix-github-oidc.ps1 -Apply     # actually apply
#>
param(
  [string]$Project        = "agora-data-driven",
  [string]$ProjectNumber  = "585951669065",                 # from the workflow's provider path
  [string]$Pool           = "github-pool",
  [string]$Provider       = "github",
  [string]$Repo           = "Agora-Data-Driven/sentinel",   # owner/name that runs the workflow
  [string]$ServiceAccount = "sentinel-deploy@agora-data-driven.iam.gserviceaccount.com",
  [switch]$KeepUpstream,                                     # also allow Agoradatadriven/Sentinel
  [string]$UpstreamRepo   = "Agoradatadriven/Sentinel",
  [switch]$Apply
)
$ErrorActionPreference = "Stop"

# Scope to the exact repository, never the whole org: an org-wide condition would let ANY repo in
# the org impersonate the deploy service account.
if ($KeepUpstream) {
  $condition = "assertion.repository in ['$Repo', '$UpstreamRepo']"
} else {
  $condition = "assertion.repository == '$Repo'"
}
$member = "principalSet://iam.googleapis.com/projects/$ProjectNumber/locations/global/workloadIdentityPools/$Pool/attribute.repository/$Repo"

Write-Host "== Current provider configuration ==" -ForegroundColor Cyan
gcloud iam workload-identity-pools providers describe $Provider `
  --project=$Project --location=global --workload-identity-pool=$Pool `
  --format="yaml(displayName, attributeCondition, attributeMapping)"

Write-Host ""
Write-Host "== Planned changes ==" -ForegroundColor Cyan
Write-Host "1) Set provider attribute condition to:" -ForegroundColor Yellow
Write-Host "     $condition"
Write-Host "   (NOTE: this REPLACES the existing condition. If the current one above must keep" -ForegroundColor DarkYellow
Write-Host "    other repos, re-run with -KeepUpstream or edit `$condition first.)" -ForegroundColor DarkYellow
Write-Host "2) Grant the deploy SA's workloadIdentityUser to:" -ForegroundColor Yellow
Write-Host "     $member"

if (-not $Apply) {
  Write-Host ""
  Write-Host "Dry run only. Re-run with -Apply to make these changes." -ForegroundColor Green
  return
}

Write-Host ""
Write-Host "Applying (1/2): updating provider attribute condition..." -ForegroundColor Cyan
gcloud iam workload-identity-pools providers update-oidc $Provider `
  --project=$Project --location=global --workload-identity-pool=$Pool `
  --attribute-condition=$condition
if ($LASTEXITCODE -ne 0) { throw "Failed to update provider attribute condition." }

Write-Host "Applying (2/2): binding the deploy service account..." -ForegroundColor Cyan
gcloud iam service-accounts add-iam-policy-binding $ServiceAccount `
  --project=$Project --role="roles/iam.workloadIdentityUser" --member=$member
if ($LASTEXITCODE -ne 0) { throw "Failed to add the service account IAM binding." }

Write-Host ""
Write-Host "Done. Re-run the deploy: GitHub -> Actions -> 'Deploy Sentinel to Cloud Run' -> Run workflow" -ForegroundColor Green
Write-Host "(or push to main). It should now authenticate successfully." -ForegroundColor Green
