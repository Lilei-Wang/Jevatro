# Kill Edge, relaunch dashboard app window with proxy bypass
Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
$prof = Join-Path $env:TEMP "edgeprof_dashboard"
Start-Process msedge -ArgumentList @(
  "--user-data-dir=$prof",
  "--no-proxy-server",
  "--app=http://127.0.0.1:8765/?fresh=2",
  "--window-position=900,30",
  "--window-size=1650,1030",
  "--no-first-run"
)
Write-Output "relaunched with --no-proxy-server"
