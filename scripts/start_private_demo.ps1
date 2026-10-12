param([Parameter(Mandatory=$true)][string]$Python, [Parameter(Mandatory=$true)][string]$Cloudflared)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$tunnelPath = (Resolve-Path -LiteralPath $Cloudflared).Path
$runtimePath = Join-Path $repo 'runtime'
if (Get-NetTCPConnection -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue) { throw 'Private demo port is already in use.' }
$env:PYTHONUTF8='1'
$gateway = Start-Process -FilePath $pythonPath -ArgumentList '-m uvicorn private_demo:app --host 127.0.0.1 --port 8767 --no-proxy-headers --no-access-log' -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput "$runtimePath/private-gateway.out.log" -RedirectStandardError "$runtimePath/private-gateway.err.log" -PassThru
$tunnel = Start-Process -FilePath $tunnelPath -ArgumentList 'tunnel --no-autoupdate --url http://127.0.0.1:8767' -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput "$runtimePath/private-tunnel.out.log" -RedirectStandardError "$runtimePath/private-tunnel.err.log" -PassThru
@{ gateway=$gateway.Id; tunnel=$tunnel.Id } | ConvertTo-Json | Set-Content -LiteralPath "$runtimePath/private-demo-pids.json"
Write-Output 'Started private gateway and HTTPS tunnel. Gateway denies all traffic until configured with its exact hostname.'
