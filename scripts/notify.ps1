# Notify the user about newly found implementable methods.
# Usage:  powershell -File scripts/notify.ps1 "<message>"
# Always logs; additionally shows a Windows toast if BurntToast is installed.
param(
  [Parameter(Mandatory = $true)][string]$Message
)
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "registry\daily-notify.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $log -Value "[$stamp] $Message"

try {
  if (Get-Module -ListAvailable -Name BurntToast) {
    Import-Module BurntToast -ErrorAction Stop
    New-BurntToastNotification -Text "온톨로지 방법 — 신규 후보", $Message
  } else {
    # fallback: tray balloon via Windows Forms
    Add-Type -AssemblyName System.Windows.Forms
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon = [System.Drawing.SystemIcons]::Information
    $n.Visible = $true
    $n.ShowBalloonTip(8000, "온톨로지 방법 — 신규 후보", $Message, "Info")
    Start-Sleep -Seconds 9
    $n.Dispose()
  }
} catch {
  Add-Content -Path $log -Value "[$stamp] (toast 실패, 로그만 기록): $_"
}
