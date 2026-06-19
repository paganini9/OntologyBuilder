# Daily 07:00 job (registered with Windows Task Scheduler).
# Runs Claude Code headless to search for new ontology-construction methods and,
# per the user-approved policy, auto-implement MOCK-feasible ones, then notify.
$ErrorActionPreference = "Continue"
$impl = Split-Path -Parent $PSScriptRoot      # ...\OntologyResearch\implementation
$projectRoot = Split-Path -Parent $impl       # ...\OntologyResearch  (holds .claude/commands)

# IMPORTANT: run Claude from the PROJECT ROOT so it can resolve the project
# slash command /impl-daily-check (defined in OntologyResearch\.claude\commands).
# `implementation\` is its own git repo, so cwd'ing there makes Claude treat it as
# the project root and the command is not found ("Unknown command").
Set-Location $projectRoot

$log = Join-Path $impl "registry\daily-run.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $log -Value "[$stamp] daily-check start (cwd=$projectRoot)"

# Requires the Claude Code CLI on PATH. Headless print mode runs the slash command.
$claude = (Get-Command claude -ErrorAction SilentlyContinue)
if ($null -eq $claude) {
  Add-Content -Path $log -Value "[$stamp] ERROR: 'claude' CLI not found on PATH"
  exit 1
}

try {
  # --dangerously-skip-permissions lets the unattended run edit files / git push.
  claude -p "/impl-daily-check" --permission-mode bypassPermissions 2>&1 | Add-Content -Path $log
  Add-Content -Path $log -Value "[$stamp] daily-check done"
} catch {
  Add-Content -Path $log -Value "[$stamp] ERROR: $_"
}
