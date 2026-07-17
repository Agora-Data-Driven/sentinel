# =============================================================================
# push-branch.ps1 -- commit ALL your local work and push it to THIS machine's
#                    own branch, so it can be integrated by merge-branches.ps1.
#
# Each machine gets its own branch so two developers never push to the same one.
# The branch name defaults to this machine's name; override it once (it sticks)
# so the branch reads like "alex/work" instead of "DESKTOP-AB12/work".
#
#   First time, set your name (writes a gitignored scripts/.devname):
#     .\scripts\push-branch.ps1 -Dev alex
#   After that:
#     .\scripts\push-branch.ps1                       # -> alex/work
#     .\scripts\push-branch.ps1 -Desc sso-fix         # -> alex/sso-fix
#     .\scripts\push-branch.ps1 -Message "WIP sso"    # custom commit message
#
# Then integrate + deploy with:  .\scripts\merge-branches.ps1
# =============================================================================

param(
    [string]$Dev = "",
    [string]$Desc = "",
    [string]$Message = ""
)

# git writes progress to stderr, which "Stop" would treat as fatal even on success.
$ErrorActionPreference = "Continue"
function Die([string]$m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }
function Must([string]$w) { if ($LASTEXITCODE -ne 0) { Die "$w (exit $LASTEXITCODE)" } }

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path   # scripts/ -> repo root
Set-Location $repo

# 1. Owner name: -Dev (remembered) > scripts/.devname > this machine's name.
$devFile = Join-Path $PSScriptRoot ".devname"
if (-not [string]::IsNullOrWhiteSpace($Dev)) {
    Set-Content -Path $devFile -Value $Dev.Trim() -Encoding ascii
} elseif (Test-Path $devFile) {
    $Dev = (Get-Content $devFile -Raw).Trim()
}
if ([string]::IsNullOrWhiteSpace($Dev)) { $Dev = $env:COMPUTERNAME }

function Slug([string]$s) { return (($s.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')) }
$name = Slug $Dev
if ([string]::IsNullOrWhiteSpace($name)) { Die "could not derive a branch name from '$Dev'" }
$slug = Slug $Desc
if ([string]::IsNullOrWhiteSpace($slug)) { $slug = "work" }
$branch = "$name/$slug"

Write-Host "[push-branch] target branch: $branch" -ForegroundColor Cyan

# 2. Snapshot current working state onto the branch (create-or-reset to HEAD).
git switch -C $branch
Must "create/switch to $branch"

# 3. Stage everything (new + modified + deleted), including untracked files.
git add -A
Must "git add -A"

# 4. Secret guard (defense in depth -- these are gitignored, but never push them anyway).
$staged = (git diff --cached --name-only) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$danger = $staged | Where-Object { $_ -match '(\.env$)|(\.env\.)|(\.p8$)|(\.pem$)|(\.key$)|(credentials.*\.json$)|(service-account.*\.json$)' -and $_ -notmatch '\.env\.(example|sample|template)$' }  # allow placeholder templates (.env.example/.sample/.template), which are meant to be committed
if ($danger) {
    git restore --staged $danger 2>$null
    Die "refusing to commit secret-looking files: $($danger -join ', '). They have been unstaged -- gitignore them."
}

# 5. Commit (skip cleanly if nothing to commit; the branch still gets pushed).
if (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
    if ([string]::IsNullOrWhiteSpace($Message)) { $Message = "WIP from $name" }
    git commit -m $Message
    Must "commit"
} else {
    Write-Host "[push-branch] nothing new to commit -- pushing the branch as-is." -ForegroundColor Yellow
}

# 6. Prune stale remote-tracking refs (a merged+deleted branch leaves a ghost
#    origin/<branch> that makes --force-with-lease reject with "stale info").
git -c http.version=HTTP/1.1 fetch --prune origin 2>$null

# 7. Push over HTTP/1.1 (pushes to these repos HANG over HTTP/2 -- documented gotcha).
#    --force-with-lease so re-running updates YOUR branch safely, never clobbering others.
git -c http.version=HTTP/1.1 push -u origin $branch --force-with-lease
Must "push $branch"

Write-Host ""
Write-Host "[OK] pushed $branch" -ForegroundColor Green
Write-Host "     Integrate + deploy with:  .\scripts\merge-branches.ps1   (or open a PR to main)."
