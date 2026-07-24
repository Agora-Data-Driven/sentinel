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
#     .\scripts\push-branch.ps1 -Force                # push even if behind main (skip the sync)
#
# STAYS CURRENT WITH MAIN: it commits your work first, fetches, then MERGES origin/main into your
# branch (your commits are preserved) so you never publish a stale branch that would revert newer
# work. A genuine conflict stops the push with clear guidance -- your work is always safe.
#
# Then integrate + deploy with:  .\scripts\merge-branches.ps1
# =============================================================================

param(
    [string]$Dev = "",
    [string]$Desc = "",
    [string]$Message = "",
    [switch]$Force   # override the "behind origin/main" staleness guard (use only when intentional)
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

# 6b. SYNC WITH MAIN (safe reconcile) -- never publish a branch built on STALE main; integrating one
#     later can silently REVERT newer work that already landed. Your work is already COMMITTED above,
#     so this is non-destructive: we MERGE origin/main INTO your branch (your commits are kept, your
#     files are never overwritten). A real conflict STOPS the push with guidance -- nothing is lost.
git rev-parse -q --verify origin/main *>$null
if ($LASTEXITCODE -eq 0) {
    git merge-base --is-ancestor origin/main HEAD 2>$null
    if ($LASTEXITCODE -ne 0) {
        $behind = "$(git rev-list --count HEAD..origin/main 2>$null)".Trim()
        if ($Force) {
            Write-Host "[push-branch] WARNING: -Force -- publishing '$branch' $behind commit(s) behind origin/main WITHOUT merging. It may revert newer work when integrated." -ForegroundColor Yellow
        } else {
            Write-Host "[push-branch] '$branch' is $behind commit(s) behind origin/main -- merging main in first (your committed work is preserved)..." -ForegroundColor Cyan
            git merge --no-edit origin/main
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[push-branch] merged origin/main into '$branch' cleanly (+$behind). Your work is intact; pushing the reconciled branch." -ForegroundColor Green
            } else {
                $conf = @(git diff --name-only --diff-filter=U | ForEach-Object { $_.Trim() } | Where-Object { $_ })
                Write-Host ""
                Write-Host "[push-branch] STOP: your branch is OUTDATED and merging the latest main hit conflicts." -ForegroundColor Red
                Write-Host "   Your work is SAFE -- it's already committed on '$branch'; only these files overlap main's newer changes:" -ForegroundColor Yellow
                $conf | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
                Write-Host "   Fix each file (keep BOTH your change AND main's), then re-run to push:" -ForegroundColor Yellow
                Write-Host "      git add -A; git commit --no-edit" -ForegroundColor Yellow
                Write-Host "      .\scripts\push-branch.ps1" -ForegroundColor Yellow
                Write-Host "   Not ready? Back out the merge (keeps all your work) and do it later:  git merge --abort" -ForegroundColor DarkGray
                exit 1
            }
        }
    }
}

# 7. Push over HTTP/1.1 (pushes to these repos HANG over HTTP/2 -- documented gotcha).
#    --force-with-lease so re-running updates YOUR branch safely, never clobbering others.
git -c http.version=HTTP/1.1 push -u origin $branch --force-with-lease
Must "push $branch"

Write-Host ""
Write-Host "[OK] pushed $branch" -ForegroundColor Green
Write-Host "     Integrate + deploy with:  .\scripts\merge-branches.ps1   (or open a PR to main)."
