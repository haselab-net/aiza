# aiza-keepawake.ps1 -- keeps a Windows ssh machine of aiza from its idle sleep
# while it is in use from aiza (the deployment notes). Windows counts only the local
# keyboard and mouse as use, so a Claude working in an aiza session would
# otherwise be put to sleep in the middle of its work.
#
# C:\ProgramData\aiza\keepawake.ps1, started as SYSTEM by the Scheduled Task
# "aiza-keepawake" (at startup and every 5 minutes; a run while one is still
# going is skipped, so this is also its watchdog). SYSTEM because the aiza
# users are Microsoft accounts on some machines, and a task cannot run as one
# without its password. It runs for good and checks once a minute. In use =
#   - a Claude Code conversation file (C:\Users\*\.claude\projects\**\*.jsonl)
#     written in the last $Window seconds,
#   - a claude.exe that used more than $ClaudeCpu CPU seconds per minute in
#     the last minute (a working Claude redraws its spinner all the time, also
#     while a tool runs; an idle one at its prompt uses 0.3-0.5 s a minute),
#   - GPU >= 20 %, or total CPU >= 25 % averaged over the last minute (a long
#     job printing nothing; one formatted-counter sample jumps around).
#   - a connection from another machine to $ServicePorts (bm's transcription
#     gpuwhisper 8192 and its mode switch control_api 8100) seen in the last
#     $Window seconds: in a meeting the GPU stays under 20 % between
#     utterances. Nothing polls these ports outside meetings (the speech server's
#     log of 2026-11-10), so an idle machine still sleeps.
#   - an ssh session (sshd running as the user) of one of the accounts in
#     C:\ProgramData\aiops\gs-accounts.json seen in the last $Window seconds:
#     on a machine whose Office the containers use over ssh as those accounts,
#     with no Claude and little CPU on the machine.
#     Their desktop sessions stay logged on, so only ssh counts, not the
#     processes. Machines without that file skip this.
# While in use it holds SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED)
# (seen in `powercfg /requests` as this powershell.exe), and lets go when not.
# A one-off call without ES_CONTINUOUS does not hold off the idle sleep
# (tried 2026-11-10: slept 5 s after one). The last decision is in
# C:\ProgramData\aiza\keepawake.last.
param([int]$Window = 900, [double]$ClaudeCpu = 1.5, [int]$Interval = 60, [int[]]$ServicePorts = @(8100, 8192))
$ErrorActionPreference = 'SilentlyContinue'
$dir = 'C:\ProgramData\aiza'
New-Item -ItemType Directory -Force $dir | Out-Null
Add-Type -Name P -Namespace AizaKeepAwake -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
$ES_CONTINUOUS = [uint32]2147483648; $ES_SYSTEM_REQUIRED = [uint32]1
$prev = @{}
$prevCpu = $null
$svcSeen = $null; $svcWhat = $null
$gsSeen = $null

function Get-Busy {
  $now = Get-Date
  $why = $null
  $cur = @{}
  foreach ($p in Get-Process claude -ErrorAction SilentlyContinue) {
    $key = "$($p.Id)-$($p.StartTime.Ticks)"
    $cpu = $p.TotalProcessorTime.TotalSeconds
    $cur[$key] = @($cpu, $now)
    $old = $script:prev[$key]
    if ($old -and -not $why) {
      $mins = ($now - $old[1]).TotalMinutes
      if ($mins -gt 0.5 -and (($cpu - $old[0]) / $mins) -gt $ClaudeCpu) {
        $why = 'claude-cpu:{0:N1}s/min' -f (($cpu - $old[0]) / $mins)
      }
    }
  }
  $script:prev = $cur
  if (-not $why) {
    $since = $now.AddSeconds(-$Window)
    foreach ($u in Get-ChildItem C:\Users -Directory) {
      $proj = Join-Path $u.FullName '.claude\projects'
      if (-not (Test-Path $proj)) { continue }
      $f = Get-ChildItem $proj -Recurse -Filter *.jsonl -File | ? LastWriteTime -gt $since | select -First 1
      if ($f) { $why = "claude-log:$($f.FullName.Substring(9))"; break }
    }
  }
  # Remote connections to the GPU services, any state but listening (a short
  # HTTP request stays in TIME_WAIT for about 2 minutes, so a check once a
  # minute sees each one). Recorded every check, also when already busy.
  $svc = Get-NetTCPConnection -LocalPort $ServicePorts -ErrorAction SilentlyContinue |
    ? { $_.State -ne 'Listen' -and $_.State -ne 'Bound' -and $_.RemoteAddress -notmatch '^(127\.|::1$|0\.0\.0\.0$|::$)' } |
    select -First 1
  if ($svc) { $script:svcSeen = $now; $script:svcWhat = "$($svc.LocalPort)" }
  if (-not $why -and $script:svcSeen -and ($now - $script:svcSeen).TotalSeconds -lt $Window) {
    $why = 'gpu-service:{0}@{1}' -f $script:svcWhat, $script:svcSeen.ToString('HH:mm')
  }
  $gsFile = 'C:\ProgramData\aiops\gs-accounts.json'
  if (Test-Path $gsFile) {
    $names = @((Get-Content $gsFile -Raw | ConvertFrom-Json).PSObject.Properties | % { "$($_.Value)" } | ? { $_ })
    if ($names.Count -and (Get-Process sshd -IncludeUserName -ErrorAction SilentlyContinue |
        ? { $_.UserName -and $names -contains ($_.UserName -split '\\')[-1] } | select -First 1)) {
      $script:gsSeen = $now
    }
  }
  if (-not $why -and $script:gsSeen -and ($now - $script:gsSeen).TotalSeconds -lt $Window) {
    $why = 'gs-ssh@{0}' -f $script:gsSeen.ToString('HH:mm')
  }
  if (-not $why -and (Test-Path C:\Windows\System32\nvidia-smi.exe)) {
    foreach ($g in (& C:\Windows\System32\nvidia-smi.exe --query-gpu=utilization.gpu --format=csv,noheader,nounits)) {
      if ([int]"$g".Trim() -ge 20) { $why = "gpu:$("$g".Trim())%"; break }
    }
  }
  # Total CPU over the time since the last check, from the raw counter
  # (idle time per 100 ns); the first check after a start has no average yet.
  $raw = Get-CimInstance Win32_PerfRawData_PerfOS_Processor -Filter "Name='_Total'"
  if ($raw) {
    if ($script:prevCpu -and -not $why) {
      $dt = [double]($raw.Timestamp_Sys100NS - $script:prevCpu.Timestamp_Sys100NS)
      if ($dt -gt 0) {
        $c = [int](100 * (1 - ([double]($raw.PercentProcessorTime - $script:prevCpu.PercentProcessorTime) / $dt)))
        if ($c -ge 25) { $why = "cpu:$c%" }
      }
    }
    $script:prevCpu = $raw
  }
  return $why
}

while ($true) {
  $why = Get-Busy
  $t = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  if ($why) {
    [void][AizaKeepAwake.P]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
    "$t awake ($why)" | Set-Content -Encoding utf8 "$dir\keepawake.last"
  } else {
    [void][AizaKeepAwake.P]::SetThreadExecutionState($ES_CONTINUOUS)
    "$t idle" | Set-Content -Encoding utf8 "$dir\keepawake.last"
  }
  Start-Sleep -Seconds $Interval
}
