# Commit (and push, if a remote exists) after a method is implemented.
# Usage:  powershell -File scripts/git_push_method.ps1 <method-id>
param(
  [Parameter(Mandatory = $true)][string]$MethodId
)
# Continue (not Stop): git writes harmless warnings (e.g. LF->CRLF) to stderr,
# which would otherwise abort the script under Stop.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot   # implementation/

if (-not (Test-Path (Join-Path $root ".git"))) {
  Write-Host "git repo가 없습니다. 먼저 init 합니다."
  git -C $root init | Out-Null
}

git -C $root add -A
# nothing staged? bail gracefully
$staged = git -C $root diff --cached --name-only
if (-not $staged) { Write-Host "변경 없음 — 커밋 생략"; exit 0 }

$subject = "feat($MethodId): implement ontology construction method"
$body = "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git -C $root commit -m $subject -m $body | Out-Null
Write-Host "committed: $subject"

# push only if an 'origin' remote is configured
$remote = git -C $root remote
if ($remote -contains "origin") {
  $branch = git -C $root rev-parse --abbrev-ref HEAD
  git -C $root push -u origin $branch
  Write-Host "pushed to origin/$branch"
} else {
  Write-Host "원격(origin) 없음 — 로컬 커밋만 완료. GitHub 연결 후 push 하세요:"
  Write-Host "  git -C `"$root`" remote add origin <REPO_URL>"
  Write-Host "  git -C `"$root`" push -u origin main"
}
