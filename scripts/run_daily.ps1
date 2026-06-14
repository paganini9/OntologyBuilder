# Daily 07:00 job (registered with Windows Task Scheduler).
# Runs Claude Code headless to search for new ontology-construction methods and
# notify the user. It does NOT implement anything (that needs user approval).
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot   # implementation/
Set-Location $root

$log = Join-Path $root "registry\daily-run.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $log -Value "[$stamp] daily-check start"

# Requires the Claude Code CLI on PATH. Headless print mode runs the slash command.
$claude = (Get-Command claude -ErrorAction SilentlyContinue)
if ($null -eq $claude) {
  Add-Content -Path $log -Value "[$stamp] ERROR: 'claude' CLI not found on PATH"
  exit 1
}

try {
  claude -p "/impl-daily-check" 2>&1 | Add-Content -Path $log
  Add-Content -Path $log -Value "[$stamp] daily-check done"
} catch {
  Add-Content -Path $log -Value "[$stamp] ERROR: $_"
}
