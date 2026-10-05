# Guild auto run for Windows. Placed in <vault>/_guild/auto/ by /guild:auto and started by Task Scheduler.
# It runs "/guild:quest auto" only when there is something to do.
$ErrorActionPreference = "Continue"
$auto  = Split-Path -Parent $PSCommandPath
$guild = Split-Path -Parent $auto
$vault = Split-Path -Parent $guild
$logs  = Join-Path $guild "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$lock   = Join-Path $auto "run.lock"
$resume = Join-Path $auto "resume"
$now = Get-Date
function Write-Last($ok, $skipped) {
  $o = [ordered]@{ time = $now.ToString("yyyy-MM-dd HH:mm"); ok = $ok; skipped = $skipped }
  [IO.File]::WriteAllText((Join-Path $logs "last.json"), ($o | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
}
# Another run (auto or by hand) is still going. A lock older than 3 hours is left over from a stopped run.
if (Test-Path $lock) {
  if ((Get-Item $lock).LastWriteTime -gt $now.AddHours(-3)) { exit 0 }
  Remove-Item $lock -Force
}
# Nothing new (requests, answers, feedback) and no unfinished run: do nothing.
$new = @("requests", "answers", "feedback") | ForEach-Object {
  Get-ChildItem -Path (Join-Path $guild $_) -Filter *.json -File -ErrorAction SilentlyContinue
}
if (@($new).Count -eq 0 -and -not (Test-Path $resume)) { Write-Last $true $true; exit 0 }
New-Item -ItemType File -Force -Path $lock | Out-Null
New-Item -ItemType File -Force -Path $resume | Out-Null
$allow = (Get-Content (Join-Path $auto "allow.txt") -Encoding UTF8 | Where-Object { $_.Trim() -and -not $_.StartsWith("#") } | ForEach-Object { $_.Trim() }) -join ","
$claude = "claude"
$cfile = Join-Path $auto "claude.txt"
if (Test-Path $cfile) { $claude = (Get-Content $cfile -Encoding UTF8 | Select-Object -First 1).Trim() }
$log = Join-Path $logs ("run-" + $now.ToString("yyyyMMdd-HHmm") + ".log")
Set-Location $vault
& $claude -p "/guild:quest auto" --permission-mode acceptEdits --allowedTools $allow *> $log
$ok = ($LASTEXITCODE -eq 0)
if ($ok) { Remove-Item $resume -Force -ErrorAction SilentlyContinue }
Write-Last $ok $false
Remove-Item $lock -Force -ErrorAction SilentlyContinue
# Keep the newest 30 logs.
Get-ChildItem $logs -Filter "run-*.log" | Sort-Object Name -Descending | Select-Object -Skip 30 | Remove-Item -Force
