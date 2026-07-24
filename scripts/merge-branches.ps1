# =============================================================================
# merge-branches.ps1 -- integrate the per-developer branches, land them on main,
#                       and DEPLOY Sentinel to Cloud Run. One command.
#
#   Sentinel is a SINGLE Cloud Run service (sentinel, asia-southeast1). Unlike the
#   other repos this script does NOT deploy with a raw `gcloud run deploy --source`:
#   it calls the repo's own deploy\deploy.ps1, which builds the image via Cloud
#   Build and then `gcloud run deploy --image` AS the operator (info@) -- the only
#   pattern that keeps the portal SSO env (PLATFORM_SSO_SECRET / PORTAL_LOGIN_URL /
#   GOOGLE_REDIRECT_URI) intact on every deploy (a bare redeploy that omits the
#   --set-* flags silently wipes them and breaks the ag_sso handoff). Deploy runs as
#   info@agoradatadriven.com -- a laptop deploy as ian@ is rejected by org policy.
#
# == AGENT RUNBOOK ====================================================================
#   1. Run it:   .\scripts\merge-branches.ps1   (or -DryRun first to preview)
#   2. MERGE CONFLICT -> resolved in the tree, script STOPS. Resolve semantically, then:
#          git add -A; git commit --no-edit
#          .\scripts\merge-branches.ps1 -Resume
#   3. GATE failure (conflict markers / py_compile error) -> fix on the integrated
#      tree, commit, re-run with -Resume. Never land + deploy a red tree.
#   4. On success: landed on main + deployed. Report the service URL.
#
# FLAGS: -DryRun · -NoPush (integrate+gate, don't land) · -NoDeploy (land, don't deploy)
#        -Exclude a,b · -Resume · -DeleteMerged (standalone prune) · -DemoSqlite (pass
#        through to deploy.ps1 for a throwaway SQLite deploy instead of prod Cloud SQL)
#        -AllowReverts (bypass the SECONDARY reversion net only -- after confirming a mass deletion
#        is intentional. It does NOT bypass the staleness gate: a stale branch is fixed by syncing.)
#
# GUARDS (fail-safe, never silent):
#   * STALENESS (PRIMARY, hard gate, no bypass) -- a dev branch that does NOT contain origin/main was
#                   built on old main and could revert newer work. This is an EXACT ancestry fact, so
#                   it is the load-bearing guard: the run STOPS before integrating any such branch. The
#                   fix is always to sync the branch onto origin/main (push-branch.ps1 auto-merges it
#                   in) -- there is deliberately no flag to force a stale branch through.
#   * REVERSION (SECONDARY net, -AllowReverts) -- catches the one case staleness can't see: main WAS
#                   merged in, but newer work got discarded during manual conflict resolution. If the
#                   integrated tree deletes files present on main or is heavily net-negative, the land
#                   STOPS unless -AllowReverts confirms the removal is intentional.
#
# USAGE
#   .\scripts\merge-branches.ps1            # integrate -> gate -> land -> deploy (prod)
#   .\scripts\merge-branches.ps1 -DryRun    # preview, change nothing
#   .\scripts\merge-branches.ps1 -NoDeploy  # land only
# =============================================================================

param(
    [string]$Exclude = "",
    [switch]$DeleteMerged,
    [switch]$NoPush,
    [switch]$NoDeploy,
    [switch]$DryRun,
    [switch]$Resume,
    [switch]$DemoSqlite,
    [switch]$AllowReverts   # bypass the SECONDARY reversion net only (deletes files on main / large
                            # net-negative). Does NOT bypass the staleness gate -- sync the branch instead.
)

$ErrorActionPreference = "Continue"
function Die([string]$m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }
function Must([string]$w) { if ($LASTEXITCODE -ne 0) { Die "$w (exit $LASTEXITCODE)" } }

$PROJECT = "agora-data-driven"
$REGION  = "asia-southeast1"
$SERVICE = "sentinel"
$ACCOUNT = "info@agoradatadriven.com"   # deploys MUST run as the operator (org policy + SSO env)

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path   # scripts/ -> repo root
Set-Location $repo

$origBranch = (git rev-parse --abbrev-ref HEAD 2>$null)

git rev-parse -q --verify MERGE_HEAD *>$null
if ($LASTEXITCODE -eq 0 -and -not $Resume) {
    Die "a merge is in progress (unresolved conflict). Resolve it then 'git add -A; git commit --no-edit' and re-run with -Resume, or 'git merge --abort' to discard it."
}
if ($DryRun -and -not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
    Die "-DryRun needs a clean working tree. Commit/stash first, or run without -DryRun."
}

# A Python interpreter for the syntax gate: prefer this repo's venv, then the shared Agora venv,
# then whatever's on PATH. Returns "" when none is found (the gate then warns + skips, never blocks).
function Find-Python([string]$RepoRoot) {
    $c = @(
        (Join-Path $RepoRoot ".venv\Scripts\python.exe"),
        (Join-Path $RepoRoot "..\.venv\Scripts\python.exe")
    )
    foreach ($p in $c) { if (Test-Path $p) { return (Resolve-Path $p).Path } }
    foreach ($n in @('python', 'py')) {
        $cmd = Get-Command $n -ErrorAction SilentlyContinue | Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1
        if ($cmd) { return $cmd.Source }
    }
    return ""
}

# ---- SANITY GATE: conflict markers + Python py_compile on changed .py ---------
function Invoke-SanityGate {
    param([string[]]$Changed, [string]$RepoRoot)
    $ok = $true
    $present = $Changed | Where-Object { $_ -and (Test-Path (Join-Path $RepoRoot $_)) }

    $conflicted = @()
    foreach ($rel in $present) {
        if (Select-String -Path (Join-Path $RepoRoot $rel) -Pattern '^(<{7}|>{7}) ' -List -ErrorAction SilentlyContinue) { $conflicted += $rel }
    }
    if ($conflicted.Count -gt 0) {
        Write-Host "    [FAIL] leftover merge-conflict markers in:" -ForegroundColor Red
        $conflicted | ForEach-Object { Write-Host "           $_" -ForegroundColor Red }
        $ok = $false
    }

    $pyFiles = @($present | Where-Object { $_ -match '\.py$' })
    if ($pyFiles.Count -gt 0) {
        $py = Find-Python $RepoRoot
        if (-not $py) {
            Write-Host "    [warn] no Python found -- skipping the py_compile gate" -ForegroundColor Yellow
        } else {
            foreach ($rel in $pyFiles) {
                & $py -m py_compile (Join-Path $RepoRoot $rel) 2>&1 | ForEach-Object { Write-Host "           $_" -ForegroundColor Red }
                if ($LASTEXITCODE -ne 0) { Write-Host "    [FAIL] Python syntax error in $rel" -ForegroundColor Red; $ok = $false }
            }
        }
    }
    return $ok
}

# ---- REVERSION NET (SECONDARY): does the integrated tree REMOVE work that's on origin/main? ------
# The staleness gate above already makes it impossible to integrate a branch that doesn't contain
# origin/main, so the classic stale-revert can no longer reach here. This is the backstop for what
# ancestry CAN'T see: main WAS merged in, but newer work got discarded during manual conflict
# resolution. It's a heuristic (files deleted vs main + a large net-negative delta), so unlike the
# staleness gate it CAN false-positive on an intentional big cleanup -- hence the -AllowReverts escape.
function Test-ReversionRisk([string]$mainRef, [string]$intgRef) {
    $deleted = @(git diff --diff-filter=D --name-only $mainRef $intgRef |
        ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $short = (git diff --shortstat $mainRef $intgRef 2>$null)
    $ins = 0; $del = 0
    if ($short -match '(\d+) insertion')  { $ins = [int]$Matches[1] }
    if ($short -match '(\d+) deletion')   { $del = [int]$Matches[1] }
    return [pscustomobject]@{ Deleted = $deleted; Insertions = $ins; Deletions = $del; NetRemoved = ($del - $ins) }
}

function Get-MergedDevBranches([string[]]$Skip) {
    git branch -r --merged origin/main --format='%(refname:short)' |
        Where-Object { $_ -and $_ -like 'origin/*' -and $_ -ne 'origin/HEAD' -and $_ -ne 'origin/main' -and $_ -notlike '*->*' } |
        ForEach-Object { ($_ -replace '^origin/', '').Trim() } |
        Where-Object { $_ -and ($Skip -notcontains $_) -and ($_ -notlike 'integration/*') }
}
function Remove-RemoteBranches([string[]]$Branches) {
    foreach ($b in $Branches) {
        git -c http.version=HTTP/1.1 push origin --delete $b 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "    deleted origin/$b" -ForegroundColor Yellow }
        else { Write-Host "    [warn] could not delete origin/$b (already gone?)" -ForegroundColor Yellow }
    }
}
function Sync-LocalMain {
    Write-Host "[..] Aligning local main with origin/main" -ForegroundColor Cyan
    git -c http.version=HTTP/1.1 fetch origin *>$null
    git switch main 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "    [warn] could not switch to local main -- skipping" -ForegroundColor Yellow; return }
    git merge --ff-only origin/main 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "[OK] local main aligned ($(git rev-parse --short HEAD))" -ForegroundColor Green }
    else { Write-Host "    [warn] local main diverged -- NOT fast-forwarding" -ForegroundColor Yellow }
}

$skip = @("main", "HEAD") + (($Exclude -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })

if ($DeleteMerged) {
    git -c http.version=HTTP/1.1 fetch origin --prune; Must "git fetch"
    $m = @(Get-MergedDevBranches $skip)
    if (-not $m) { Write-Host "    (nothing fully merged into main to delete)" -ForegroundColor Yellow; exit 0 }
    Remove-RemoteBranches $m; Write-Host "[OK] pruned: $($m -join ', ')" -ForegroundColor Green; exit 0
}

# ---- 0. Commit + push local WIP first (skipped under -DryRun) ----------------
if ($DryRun) {
    if (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) { Write-Host "[dry-run] you have uncommitted changes; commit/push them to see them in the plan." -ForegroundColor Yellow }
} elseif (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
    Write-Host "[..] Local changes -- committing + pushing them to your branch first" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "push-branch.ps1"); Must "push-branch"
}

# ---- 1-3. Build the integration branch, merge each dev branch ----------------
$intg = "integration/merge"
if ($Resume) {
    $cur = "$(git rev-parse --abbrev-ref HEAD 2>$null)".Trim()
    if ($cur -ne $intg) { Die "-Resume expects to be on '$intg' but HEAD is '$cur'. Re-run WITHOUT -Resume." }
    if (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) { Die "-Resume needs a clean tree. Finish: git add -A; git commit --no-edit" }
    git -c http.version=HTTP/1.1 fetch origin --prune; Must "git fetch"
    $baseMain = "$(git merge-base origin/main $intg 2>$null)".Trim()
    if (-not $baseMain) { Die "could not find the base of $intg -- re-run WITHOUT -Resume." }
} else {
    git -c http.version=HTTP/1.1 fetch origin --prune; Must "git fetch"
    $baseMain = "$(git rev-parse origin/main)".Trim(); Must "resolve origin/main"
}

$branches = git branch -r --format='%(refname:short)' |
    ForEach-Object { $_.Trim() } | Where-Object { $_ -like 'origin/*' } |
    ForEach-Object { $_ -replace '^origin/', '' } |
    Where-Object { $_ -and ($skip -notcontains $_) -and ($_ -notlike 'integration/*') -and ($_ -ne 'HEAD') }

if (-not $branches) {
    Write-Host "[OK] no dev branches to merge -- origin/main is already current." -ForegroundColor Green
    Sync-LocalMain; exit 0
}
Write-Host "[OK] branches to integrate: $($branches -join ', ')"

# ---- PRIMARY GATE: staleness (each branch MUST contain origin/main) ---------
# The load-bearing guard. A dev branch that does not contain origin/main was built on an OLD main;
# integrating it can silently revert newer work. This is an EXACT ancestry fact (not the heuristic the
# reversion net uses), so a clean branch here means a stale revert is structurally impossible -- not
# merely unlikely. The fix is ALWAYS to sync the branch onto origin/main (push-branch.ps1 auto-merges
# it in), so there is deliberately no bypass flag. Skipped on -Resume (the prior run already gated).
if (-not $Resume) {
    $stale = @()
    foreach ($b in $branches) {
        git merge-base --is-ancestor origin/main "origin/$b" 2>$null
        if ($LASTEXITCODE -ne 0) {
            $bBehind = "$(git rev-list --count origin/$b..origin/main 2>$null)".Trim()
            $stale += [pscustomobject]@{ Branch = $b; Behind = $bBehind }
        }
    }
    if ($stale.Count -gt 0) {
        Write-Host "[STALENESS GATE] these branches do NOT contain origin/main (built on stale main):" -ForegroundColor Red
        $stale | ForEach-Object { Write-Host "      origin/$($_.Branch) -- $($_.Behind) commit(s) behind origin/main" -ForegroundColor Yellow }
        Write-Host "    Landing them could revert newer work already on main. Sync each stale branch FIRST:" -ForegroundColor Yellow
        Write-Host "      git switch <branch>; git merge --no-edit origin/main   (or just re-run its push-branch.ps1)" -ForegroundColor Yellow
        Write-Host "      resolve any conflicts keeping BOTH sides, push, then re-run this script." -ForegroundColor Yellow
        Die "staleness gate tripped -- NOT integrating a stale branch. Syncing is the fix; there is no bypass."
    }
    Write-Host "[OK] staleness gate passed -- every branch contains origin/main." -ForegroundColor Green
}

if (-not $Resume) { Write-Host "[..] Creating $intg off origin/main" -ForegroundColor Cyan; git switch -C $intg origin/main; Must "create $intg" }

$merged = @()
foreach ($b in $branches) {
    git merge-base --is-ancestor "origin/$b" HEAD 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "    [skip] $b already integrated" -ForegroundColor DarkGray; $merged += $b; continue }
    # STALENESS echo: the pre-flight staleness gate above already blocks stale branches on a fresh run.
    # This only fires under -Resume (which skips the pre-flight) if a branch went stale between runs --
    # warn loudly; the reversion net below is the backstop.
    git merge-base --is-ancestor origin/main "origin/$b" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $bBehind = "$(git rev-list --count origin/$b..origin/main 2>$null)".Trim()
        Write-Host "    [STALE] origin/$b is $bBehind commit(s) behind origin/main -- built on stale main; watch for reverts." -ForegroundColor Yellow
    }
    Write-Host "[..] Merging $b" -ForegroundColor Cyan
    git merge --no-ff -m "Merge $b into $intg" "origin/$b"
    if ($LASTEXITCODE -ne 0) {
        if ($DryRun) {
            git merge --abort *>$null
            Write-Host "[dry-run] $b conflicts with the integration -- can't preview past it." -ForegroundColor Yellow
            if ($origBranch -and $origBranch -ne 'HEAD' -and $origBranch -ne $intg) { git switch $origBranch *>$null } else { git switch main *>$null }
            git branch -D $intg *>$null; exit 1
        }
        $unmerged = @(git diff --name-only --diff-filter=U | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        Write-Host "`n[CONFLICT] $b does not merge cleanly -- left in the tree for you to resolve." -ForegroundColor Red
        $unmerged | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
        Write-Host "  AGENT: resolve each file preserving BOTH devs' intent -- BUT if '$b' is [STALE]" -ForegroundColor Yellow
        Write-Host "         (built on old main) and a hunk REVERTS newer work (deletes files/features that" -ForegroundColor Yellow
        Write-Host "         are on main), keep the up-to-date side; never reintroduce a revert. Then:" -ForegroundColor Yellow
        Write-Host "         git add -A; git commit --no-edit" -ForegroundColor Yellow
        Write-Host "         .\scripts\merge-branches.ps1 -Resume   (the reversion guard runs before landing)" -ForegroundColor Yellow
        exit 1
    }
    $merged += $b
}
Write-Host "[OK] all branches integrated: $($merged -join ', ')" -ForegroundColor Green

# ---- 4. gate ---------------------------------------------------------------
$changed = git diff --name-only $baseMain $intg | ForEach-Object { $_.Trim() } | Where-Object { $_ }
Write-Host "[..] Sanity gate (conflict markers + py_compile)" -ForegroundColor Cyan
if (-not (Invoke-SanityGate -Changed $changed -RepoRoot $repo)) { Die "sanity gate FAILED -- do NOT land. Fix on $intg, then re-run with -Resume." }
Write-Host "[OK] sanity gate passed" -ForegroundColor Green

# ---- 4b. reversion net (secondary backstop) --------------------------------
Write-Host "[..] Reversion net (did manual conflict resolution discard newer work?)" -ForegroundColor Cyan
$rev = Test-ReversionRisk origin/main $intg
$NET_REMOVE_LIMIT = 300
if (($rev.Deleted.Count -gt 0 -or $rev.NetRemoved -ge $NET_REMOVE_LIMIT) -and -not $AllowReverts) {
    Write-Host "[REVERSION GUARD] the integrated tree removes work that exists on origin/main:" -ForegroundColor Red
    if ($rev.Deleted.Count -gt 0) {
        Write-Host "    deletes $($rev.Deleted.Count) file(s) present on main:" -ForegroundColor Red
        $rev.Deleted | Select-Object -First 25 | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
        if ($rev.Deleted.Count -gt 25) { Write-Host "      ... and $($rev.Deleted.Count - 25) more" -ForegroundColor Yellow }
    }
    Write-Host "    net lines: +$($rev.Insertions) / -$($rev.Deletions)  (net $($rev.NetRemoved) removed)" -ForegroundColor Red
    Write-Host "    A branch built on STALE main reverts newer work like this. Confirm it's intentional." -ForegroundColor Yellow
    Write-Host "    If a stale branch is the cause: rebase it onto origin/main and re-push, then re-run." -ForegroundColor Yellow
    Write-Host "    If the removal is genuinely intended: re-run with -AllowReverts." -ForegroundColor Yellow
    Die "reversion guard tripped -- NOT landing."
}
Write-Host "[OK] reversion guard passed (+$($rev.Insertions) / -$($rev.Deletions))" -ForegroundColor Green

# ---- -NoPush / -DryRun: stop -----------------------------------------------
if ($NoPush -or $DryRun) {
    $tag = if ($DryRun) { "[dry-run]" } else { "[no-push]" }
    Write-Host "`n$tag $intg is clean + gated. NOT landed or deployed." -ForegroundColor Green
    Write-Host "$tag would LAND:   git switch main; git merge --ff-only $intg; git -c http.version=HTTP/1.1 push origin main"
    Write-Host "$tag would DEPLOY: .\deploy\deploy.ps1  (Cloud Build image -> gcloud run deploy $SERVICE as $ACCOUNT)"
    if ($DryRun) {
        if ($origBranch -and $origBranch -ne 'HEAD' -and $origBranch -ne $intg) { git switch $origBranch *>$null } else { git switch main *>$null }
        git branch -D $intg *>$null
    }
    exit 0
}

# ---- 5. LAND ----------------------------------------------------------------
Write-Host "[..] Landing $intg into main" -ForegroundColor Cyan
git switch main;                 Must "switch to main"
git merge --ff-only origin/main; Must "sync local main to origin/main"
git merge --ff-only $intg;       Must "fast-forward main to $intg"
git -c http.version=HTTP/1.1 push origin main; Must "push origin main"
Write-Host "[OK] landed -- main is now $(git rev-parse --short HEAD)" -ForegroundColor Green

# ---- 6. DEPLOY (via the repo's own deploy.ps1, as info@) --------------------
$deployScript = Join-Path $repo "deploy\deploy.ps1"
if ($NoDeploy) {
    Write-Host "[OK] -NoDeploy: skipping deploy. Deploy later with:" -ForegroundColor Yellow
    Write-Host "     .\deploy\deploy.ps1   (as $ACCOUNT)" -ForegroundColor Yellow
} elseif (-not (Test-Path $deployScript)) {
    Write-Host "[ERROR] deploy\deploy.ps1 not found -- main is landed; deploy Sentinel by hand." -ForegroundColor Red
    exit 1
} else {
    # Force the operator account for the deploy (a laptop deploy as ian@ is org-policy rejected),
    # and fail fast if it isn't authenticated (an expired token only fails deep in the build).
    $prevAccount = $env:CLOUDSDK_CORE_ACCOUNT
    $env:CLOUDSDK_CORE_ACCOUNT = $ACCOUNT
    $null = gcloud auth print-access-token --account $ACCOUNT 2>$null
    if ($LASTEXITCODE -ne 0) {
        $env:CLOUDSDK_CORE_ACCOUNT = $prevAccount
        Write-Host "[ERROR] gcloud not authenticated as $ACCOUNT. main is landed; nothing deployed yet." -ForegroundColor Red
        Write-Host "        Run 'gcloud auth login $ACCOUNT', then:  .\deploy\deploy.ps1" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[..] Deploying $SERVICE to Cloud Run ($REGION) as $ACCOUNT via deploy\deploy.ps1" -ForegroundColor Cyan
    $deployOk = $true
    try {
        if ($DemoSqlite) { & $deployScript -DemoSqlite } else { & $deployScript }
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { $deployOk = $false }
    } catch {
        $deployOk = $false
        Write-Host "[ERROR] deploy threw: $($_.Exception.Message)" -ForegroundColor Red
    } finally {
        $env:CLOUDSDK_CORE_ACCOUNT = $prevAccount
    }
    if (-not $deployOk) {
        Write-Host "[ERROR] deploy failed. main is already landed; fix the cause and re-run directly:" -ForegroundColor Red
        Write-Host "        .\deploy\deploy.ps1   (as $ACCOUNT)" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[OK] deployed $SERVICE." -ForegroundColor Green
}

# ---- 7. prune ---------------------------------------------------------------
git -c http.version=HTTP/1.1 fetch origin --prune *>$null
$m = @(Get-MergedDevBranches $skip)
if ($m.Count -gt 0) { Write-Host "[..] Pruning merged dev branches: $($m -join ', ')" -ForegroundColor Cyan; Remove-RemoteBranches $m }

Write-Host "`n[OK] DONE -- integrated, landed on main, deployed to Cloud Run." -ForegroundColor Green
