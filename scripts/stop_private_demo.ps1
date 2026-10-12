$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pidFile = Join-Path $repo 'runtime/private-demo-pids.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'No saved private demo processes.'; exit }
$saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
$all = @(Get-CimInstance Win32_Process)
$owned = [System.Collections.Generic.HashSet[int]]::new()
foreach ($entry in @(@{id=$saved.gateway;pattern='uvicorn private_demo:app --host 127.0.0.1 --port 8767'}, @{id=$saved.tunnel;pattern='tunnel --no-autoupdate --url http://127.0.0.1:8767'})) {
    $process = $all | Where-Object { $_.ProcessId -eq $entry.id }
    if ($process -and $process.CommandLine.Contains($entry.pattern)) { [void]$owned.Add([int]$process.ProcessId) }
    elseif ($process) { throw 'Saved PID now belongs to a different process. Nothing will be stopped.' }
}
do {
    $added = $false
    foreach ($process in $all) {
        if ($owned.Contains([int]$process.ParentProcessId) -and $owned.Add([int]$process.ProcessId)) { $added = $true }
    }
} while ($added)
foreach ($processId in $owned) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }
Write-Output 'Stopped the private gateway and HTTPS tunnel. Local app and voice worker remain available.'
